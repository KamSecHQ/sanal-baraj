"""Boyutlandırılmış şebeke üzerinde senaryoları kurar, çalıştırır ve göstergelerini hesaplar.

Normal gün üç senaryo:  off (şamandıralı vana) · on (akıllı depo) · pilot (akıllı depo + basınç pilotu)
Kesinti günü iki mod:   off (şamandıra) · on (orkestratör), seçilen bir DMA'da
Sızıntı avı:            aynı DMA'da gece ölçümüyle sızıntı yeri, üç sensör düzeniyle
Güneşle dolum:          solar (akıllı depo, orkestratör tarife yerine saatlik piyasa fiyatına bakar)
Deprem günü iki mod:    off (şamandıra) · on (kit girişi mühürler), bütün ilçede İBB senaryosunun boru hasarıyla
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import (
    PARTICIPATION, PILOT_MAX_PRVS, SOLAR_HOURS, SOLAR_PRICE_DATE, SOLAR_PRICE_TL_MWH, SOLAR_PRICE_WEIGHT,
    SUBZONE_ELEV_SPREAD_M,
)
from .network import Twin
from .orchestrator import float_valve_plan, orchestrate
from .leak import LeakStudy, study as leak_study
from .outage import OutageRun, pick_dma, simulate_outage
from .pressure import Prv, apply_zones, candidate_zones, evaluate, merge, net_curve, savings_curve
from .quake import QuakeAreas, QuakeStudy, study as quake_study
from .energy import EnergyStudy, study as energy_study
from .scenario import Scenario, activate, metrics, run, set_settings, step_prices
from .tanks import NodeStorage, aggregate, assign_tanks, booster_power_kw


@dataclass
class Comparison:
    buildings: pd.DataFrame
    storage: NodeStorage
    scenarios: dict[str, Scenario]
    metrics: dict[str, dict]
    pilot_twin: Twin | None = None
    prvs: list[Prv] = field(default_factory=list)
    prv_curve: list[float] = field(default_factory=list)       # ilk k vananın kaçak kazancı (m³/gün)
    prv_net_curve: list[float] = field(default_factory=list)   # ilk k vananın net kazancı (TL/gün)
    prv_candidates: int = 0
    prv_accepted: int = 0
    outage: dict[str, OutageRun] = field(default_factory=dict)
    outage_dma: str | None = None
    leak: LeakStudy | None = None
    quake: QuakeStudy | None = None
    energy: EnergyStudy | None = None
    extra: dict = field(default_factory=dict)   # hafta sonu, doğrulama gibi ek sonuçlar


def uncontrolled_flows(twin: Twin, storage: NodeStorage, off: Scenario) -> dict[str, np.ndarray]:
    """Orkestratör için DMA başına kontrol edilemeyen debi: depo dışı talep + kapalı senaryodaki ortalama kaçak."""
    T = twin.steps
    col = {j: i for i, j in enumerate(twin.junctions)}
    demand = off.res.node["demand"][twin.junctions].to_numpy()[:T]
    leak_mean = (np.clip(demand - off.applied, 0.0, None) * 3600.0).mean(axis=0)
    out = {}
    for d in twin.dmas:
        idx = [col[j] for j in d.junctions]
        fixed = sum((storage.fixed[j] for j in d.junctions), np.zeros(T))
        out[d.name] = fixed + float(leak_mean[idx].sum())
    return out


def solar_summary(m: dict, ptf: np.ndarray, steps: int) -> dict:
    """Senaryoların piyasa fiyatıyla basma maliyeti (TL/gün) ve güneş saatlerindeki pompalama payı."""
    dt = 24.0 / steps
    hours = np.arange(steps) * dt
    sun = (hours >= SOLAR_HOURS[0]) & (hours < SOLAR_HOURS[1])
    out = {"date": SOLAR_PRICE_DATE, "price_tl_mwh": list(SOLAR_PRICE_TL_MWH), "hours": list(SOLAR_HOURS),
           "ptf_tl": {}, "solar_share": {}}
    for k in ("off", "on", "solar"):
        kw = np.asarray(m[k]["hourly"]["pump_kw"], dtype=float)
        out["ptf_tl"][k] = float((kw * ptf / 1000.0).sum() * dt)
        out["solar_share"][k] = float(kw[sun].sum() / max(kw.sum(), 1e-9))
    return out


def compare(twin: Twin, buildings: pd.DataFrame, rng: np.random.Generator,
            participation: float = PARTICIPATION, subzone_spread: float = SUBZONE_ELEV_SPREAD_M,
            max_prvs: int = PILOT_MAX_PRVS, outage_dma: str | None = None, with_outage: bool = True,
            with_leak: bool = True, quake_areas: QuakeAreas | None = None, log=print) -> Comparison:
    """buildings: en az floors, q_m3d, persons ve junction sütunları olan bina tablosu.

    quake_areas verilirse deprem günü de çalıştırılır (bina sırası buildings ile aynı olmalı).
    """
    b = assign_tanks(buildings, rng, participation=participation)
    storage = aggregate(b, "junction", twin.junctions, twin.pattern)
    booster_kw = booster_power_kw(b, twin.pattern)
    tanked = b["tank_m3"] > 0
    fixed_tank_m3 = float(b.loc[tanked & ~b["smart"], "tank_m3"].sum())
    tank_use_m3h = float(b.loc[tanked, "q_m3d"].sum() / 24.0)
    log(f"  {int(tanked.sum())} binada depo ({b['tank_m3'].sum():,.0f} m³), {int(b['smart'].sum())} akıllı kit")

    off = run(twin, storage, float_valve_plan(storage), "off", "Yapay zekâ kapalı", retune=True)
    prices = step_prices(twin.steps)
    dmas = {d.name: d.junctions for d in twin.dmas}
    unc = uncontrolled_flows(twin, storage, off)
    plan = orchestrate(storage, dmas, unc, prices / prices.mean(), log=log)

    set_settings(twin, off.settings)
    on = run(twin, storage, plan, "on", "Akıllı depo", retune=True)

    # Basınç pilotu: adaylar akıllı depo senaryosunun basınçlarından çıkar, her biri DMA alt modelinde
    # simüle edilir; net kazancı (kaçak değeri − enerji maliyeti artışı) pozitif olanlardan en iyileri seçilir
    cands = candidate_zones(twin, on.res, max_spread=subzone_spread)
    accepted = evaluate(twin, cands, on.applied, on.settings, log=log)
    chosen = merge(accepted, max_prvs=max_prvs)
    pilot_twin, prvs = apply_zones(twin, chosen)
    pilot = run(pilot_twin, storage, plan, "pilot", "Akıllı depo + basınç pilotu", retune=True)
    n_acc = sum(len(v) for v in accepted.values())
    log(f"  basınç pilotu: {len(cands)} aday, {n_acc} tanesi net kazançlı, en iyi {len(prvs)} tanesi seçildi")

    # Güneşle dolum: aynı orkestratör, tarife yerine saatlik piyasa fiyatıyla (öğlen güneş bolken ucuz)
    ptf = np.repeat(np.asarray(SOLAR_PRICE_TL_MWH, dtype=float), twin.steps // 24)
    plan_s = orchestrate(storage, dmas, unc, ptf / ptf.mean(), price_weight=SOLAR_PRICE_WEIGHT, log=lambda *_: None)
    set_settings(twin, off.settings)
    solar = run(twin, storage, plan_s, "solar", "Güneşle dolum", retune=True)
    activate(twin, on)

    m = {
        "off": metrics(twin, storage, off, booster_kw, fixed_tank_m3, tank_use_m3h),
        "on": metrics(twin, storage, on, booster_kw, fixed_tank_m3, tank_use_m3h),
        "pilot": metrics(pilot_twin, storage, pilot, booster_kw, fixed_tank_m3, tank_use_m3h),
        "solar": metrics(twin, storage, solar, booster_kw, fixed_tank_m3, tank_use_m3h),
    }
    cmp = Comparison(buildings=b, storage=storage, scenarios={"off": off, "on": on, "pilot": pilot, "solar": solar}, metrics=m,
                     pilot_twin=pilot_twin, prvs=prvs, prv_curve=savings_curve(chosen),
                     prv_net_curve=net_curve(chosen), prv_candidates=len(cands), prv_accepted=n_acc)

    cmp.extra["solar"] = solar_summary(m, ptf, twin.steps)
    s = cmp.extra["solar"]
    log(f"  güneşle dolum: piyasa maliyeti {s['ptf_tl']['on']:,.0f} → {s['ptf_tl']['solar']:,.0f} TL/gün, "
        f"güneş saatlerinde pompalama %{100 * s['solar_share']['on']:.1f} → %{100 * s['solar_share']['solar']:.1f}")

    if with_outage:
        name = outage_dma or pick_dma(twin, b)
        normal_peak = float(m["off"]["dma_inflow"][name].max())
        for key, sc in (("off", off), ("on", on)):
            cmp.outage[key] = simulate_outage(twin, b, storage, sc.plan, sc.applied, sc.settings, name, key,
                                              normal_peak_m3h=normal_peak)
        cmp.outage_dma = name
        log(f"  kesinti günü: {name}")
    if with_leak:
        name = cmp.outage_dma or outage_dma or pick_dma(twin, b)
        cmp.leak = leak_study(twin, storage, plan, on.settings, name, np.random.default_rng(int(rng.integers(2**31))), log=log)
    cmp.energy = energy_study(twin, b, storage, on)
    if quake_areas is not None:
        cmp.quake = quake_study(twin, b, storage, {"off": off, "on": on}, quake_areas,
                                np.random.default_rng(int(rng.integers(2**31))), log=log)
    return cmp
