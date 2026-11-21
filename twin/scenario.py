"""Senaryolar: "yapay zekâ kapalı" (şamandıralı vana), "akıllı depo" (orkestratör), basınç pilotu.

Senaryolar aynı fiziksel şebekeyi (aynı çaplar, aynı kaçak katsayıları) paylaşır. Fark depoların şebekeden
ne zaman su çektiği ve buna göre ayarlanan bölge beslemeleridir. Bütün diziler adım başınadır; debiler m³/sa.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import (
    MIN_SERVICE_PRESSURE_M, TARIFF_PERIOD, TARIFF_TL_PER_KWH, UTILITY_PUMP_EFFICIENCY,
)
from .network import Twin, get_feed_setting, set_feed_setting, simulate, tune_heads
from .orchestrator import Plan
from .tanks import NodeStorage


def step_prices(steps: int) -> np.ndarray:
    """Adım başına elektrik fiyatı (TL/kWh), üç zamanlı tarifeden."""
    hours = (np.arange(steps) * 24 / steps).astype(int)
    return np.array([TARIFF_TL_PER_KWH[TARIFF_PERIOD[h]] for h in hours])


def puant_mask(steps: int) -> np.ndarray:
    hours = (np.arange(steps) * 24 / steps).astype(int)
    return np.array([TARIFF_PERIOD[h] == "puant" for h in hours])


@dataclass
class Scenario:
    key: str                     # "off", "on" ya da "pilot"
    label: str
    plan: Plan
    applied: np.ndarray          # [T, N] düğümlere uygulanan talep (m³/s), kaçak hariç
    res: object
    settings: dict[str, float]   # bölge adı -> besleme ayarı (rezervuar kotu ya da PRV çıkış basıncı, m)


def node_demands(twin: Twin, storage: NodeStorage, plan: Plan) -> np.ndarray:
    """Düğüm talep matrisi [T, N] (m³/s): kontrol edilemeyen talep + akıllı depo dolumları."""
    col = {j: i for i, j in enumerate(twin.junctions)}
    D = np.zeros((twin.steps, len(twin.junctions)))
    for j, q in storage.fixed.items():
        D[:, col[j]] += q
    for i, j in enumerate(storage.junctions):
        D[:, col[j]] += plan.inflow[i]
    return D / 3600.0


def apply_demands(twin: Twin, D: np.ndarray) -> None:
    """Her düğüme kendi günlük talep örüntüsünü yazar."""
    wn = twin.wn
    for i, j in enumerate(twin.junctions):
        q = D[:, i]
        ts = wn.get_node(j).demand_timeseries_list[0]
        mean = float(q.mean())
        if mean <= 0:
            ts.base_value = 0.0
            continue
        name = f"d_{j}"
        mult = list(q / mean)
        if name in wn.pattern_name_list:
            wn.get_pattern(name).multipliers = mult
        else:
            wn.add_pattern(name, mult)
        ts.base_value = mean
        ts.pattern_name = name


def set_settings(twin: Twin, settings: dict[str, float]) -> None:
    for d in twin.dmas:
        if d.name in settings:
            set_feed_setting(twin, d, settings[d.name])


def current_settings(twin: Twin) -> dict[str, float]:
    return {d.name: get_feed_setting(twin, d) for d in twin.dmas}


def run(twin: Twin, storage: NodeStorage, plan: Plan, key: str, label: str, retune: bool) -> Scenario:
    D = node_demands(twin, storage, plan)
    apply_demands(twin, D)
    if twin.supply is not None:
        twin.supply.apply_operation(twin, key, D)
    res = simulate(twin)
    if retune:
        for _ in range(3):
            if tune_heads(twin, res) < 0.2:
                break
            res = simulate(twin)
    return Scenario(key=key, label=label, plan=plan, applied=D, res=res, settings=current_settings(twin))


def activate(twin: Twin, sc: Scenario) -> None:
    """Modeli bu senaryonun taleplerine ve beslemelerine geri getirir (INP yazmadan önce)."""
    apply_demands(twin, sc.applied)
    set_settings(twin, sc.settings)
    if twin.supply is not None:
        twin.supply.apply_operation(twin, sc.key, sc.applied)


def zone_inflow(twin: Twin, res, d) -> np.ndarray:
    """Bölgeye giren debi (m³/s, adım başına)."""
    T = twin.steps
    if d.reservoir:
        return -res.node["demand"][d.reservoir].to_numpy()[:T]
    return res.link["flowrate"][d.feed].to_numpy()[:T]


def metrics(twin: Twin, storage: NodeStorage, sc: Scenario, booster_kw: np.ndarray,
            fixed_tank_m3: float, tank_use_m3h: float) -> dict:
    """Adım başına ve günlük göstergeler. Debiler m³/sa, güç kW, maliyet TL.

    fixed_tank_m3: kit takılmamış (hep dolu) depoların toplam hacmi; tank_use_m3h: tüm depolu
    binaların ortalama saatlik tüketimi ("kaç saat yeter" hesabı için). Basınç pilotunun alt bölgeleri
    ana DMA'nın içinden beslendiği için debileri ana DMA'nın girişinde zaten sayılır.
    """
    T, dt = twin.steps, twin.step_h
    J = twin.junctions
    P = sc.res.node["pressure"][J].to_numpy()[:T]
    demand = sc.res.node["demand"][J].to_numpy()[:T]
    leak = np.clip(demand - sc.applied, 0.0, None) * 3600.0
    delivered = sc.applied.sum(axis=1) * 3600.0
    prices = step_prices(T)

    inflow = np.zeros(T)
    zone_kw = np.zeros(T)
    dma_inflow: dict[str, np.ndarray] = {}
    for d in twin.dmas:
        if d.parent:
            continue
        q = zone_inflow(twin, sc.res, d)
        dma_inflow[d.name] = q * 3600.0
        inflow += q * 3600.0
        if d.reservoir:
            zone_kw += 9.81 * q * sc.settings[d.name] / UTILITY_PUMP_EFFICIENCY
    extra = {}
    if twin.supply is not None:
        pump_kw, extra = twin.supply.metrics(twin, sc.res)
    else:
        pump_kw = zone_kw

    smart_use = storage.consumption.sum(axis=0).mean()
    stored = sc.plan.level[:, :T].sum(axis=0) + fixed_tank_m3
    # Akıllı depolardaki suyun ortalama bekleme süresi = ortalama hacim / ortalama çekiş
    water_age_h = float(sc.plan.level[:, :T].sum(axis=0).mean() / smart_use) if smart_use > 0 else 0.0

    series = {
        "inflow_m3h": inflow, "delivered_m3h": delivered, "leak_m3h": leak.sum(axis=1),
        "p_mean": P.mean(axis=1), "p_min": P.min(axis=1), "p_max": P.max(axis=1),
        "low_nodes": (P < MIN_SERVICE_PRESSURE_M).sum(axis=1),
        "pump_kw": pump_kw, "pump_tl": pump_kw * prices,
        "booster_kw": booster_kw, "stored_m3": stored,
        "stored_hours": stored / max(tank_use_m3h, 1e-9),
        **extra,
    }
    puant = puant_mask(T)
    daily = {
        "inflow_m3": float(inflow.sum() * dt), "leak_m3": float(leak.sum() * dt),
        "leak_share": float(leak.sum() / inflow.sum()),
        "peak_inflow_m3h": float(inflow.max()), "peak_to_mean": float(inflow.max() / inflow.mean()),
        "p_mean": float(P.mean()), "p_max": float(P.max()),
        "pump_kwh": float(pump_kw.sum() * dt), "pump_tl": float((pump_kw * prices).sum() * dt),
        "booster_kwh": float(booster_kw.sum() * dt),
        "puant_share": float(inflow[puant].sum() / inflow.sum()),
        "min_reserve_hours": float(series["stored_hours"].min()),
        "water_age_h": water_age_h,
        "mean_head_m": float(np.mean([sc.settings[d.name] for d in twin.dmas if not d.parent])),
    }
    return {"hourly": series, "daily": daily, "dma_inflow": dma_inflow, "pressure": P}
