"""Kesinti günü: bir DMA'da planlı su kesintisi ve su geri geldiğindeki dolum.

Şebeke saat saat, basınca bağlı talep (PDD) ile çözülür: basınç 15 m'nin altına düşen düğüm istediği
suyun yalnızca bir kısmını alabilir. Depolar her saatin sonunda gerçekte aldıkları suyla güncellenir.

- Şamandıralı vana (yapay zekâ kapalı): su gelince her depo boşalan kısmını en hızlı şekilde doldurmaya
  çalışır. Herkes aynı anda çektiği için basınç çöker; yüksekteki ve deposuz binalar susuz kalır.
- Orkestratör (yapay zekâ açık): kesintiyi önceden bildiği için depoları gece saatlerinde doldurur.
  Su gelince her saat dolumu önce simüle eder ve DMA'daki en düşük basınç 15 m'nin altına inmeyecek
  kadar su bırakır; deposuz binalar her zaman önceliklidir.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
from wntr.network import LinkStatus

from .config import (
    MIN_SERVICE_PRESSURE_M, OUTAGE_END_HOUR, OUTAGE_START_HOUR, PDD_MINIMUM_PRESSURE_M,
    PDD_REQUIRED_PRESSURE_M, PREFILL_HOURS, TANK_INLET_M3H,
)
from .network import Twin, set_feed_setting, simulate
from .orchestrator import Plan
from .tanks import NodeStorage, rate_profile

# Kesinti günü her zaman saatlik çözülür; ince adımlı modelin dizileri saatlik ortalamaya indirilir
HOURS = 24
# Kesinti sonrası dolum: depo açığının bu oranları sırayla denenir, basıncı koruyan ilki seçilir
REFILL_STEPS = (1.0, 0.6, 0.35, 0.2, 0.1, 0.0)


def to_hourly(arr: np.ndarray, axis: int = 0) -> np.ndarray:
    """Adım başına diziyi (24·k uzunluğunda) saatlik ortalamaya indirir."""
    arr = np.asarray(arr, dtype=float)
    k = arr.shape[axis] // HOURS
    if k <= 1:
        return arr
    shape = list(arr.shape)
    shape[axis:axis + 1] = [HOURS, k]
    return arr.reshape(shape).mean(axis=axis + 1)


@dataclass
class OutageRun:
    key: str
    label: str
    junctions: list[str]
    hourly: dict
    daily: dict
    node_pressure: np.ndarray        # [24, n] DMA düğümleri (saatlik)
    node_fill: dict[str, np.ndarray] # düğüm -> [24] depo doluluğu (%)


def pick_dma(twin: Twin, buildings: pd.DataFrame) -> str:
    """Kesinti için en kalabalık DMA."""
    persons = buildings.groupby("junction")["persons"].sum()
    return max(twin.dmas, key=lambda d: float(persons.reindex(d.junctions).fillna(0).sum())).name


@dataclass
class _Group:
    volume: np.ndarray       # [n]
    cons: np.ndarray         # [n, 24] m³/sa
    persons: np.ndarray      # [n]
    cap: np.ndarray          # [n] giriş kapasitesi m³/sa


def _group(b: pd.DataFrame, mask: pd.Series, junctions: list[str], pattern: list[float]) -> _Group:
    sub = b[mask]
    g = sub.groupby("junction").agg(volume=("tank_m3", "sum"), daily=("q_m3d", "sum"),
                                    persons=("persons", "sum"), n=("tank_m3", "size"))
    g = g.reindex(junctions).fillna(0.0)
    return _Group(volume=g["volume"].to_numpy(), cons=rate_profile(g["daily"].to_numpy(), pattern),
                  persons=g["persons"].to_numpy(), cap=g["n"].to_numpy() * TANK_INLET_M3H)


def simulate_outage(twin: Twin, buildings: pd.DataFrame, storage: NodeStorage, plan: Plan, base_demand: np.ndarray,
                    settings: dict[str, float], dma_name: str, mode: str, normal_peak_m3h: float,
                    start: int = OUTAGE_START_HOUR, end: int = OUTAGE_END_HOUR) -> OutageRun:
    """mode: "off" (şamandıra) ya da "on" (orkestratör). base_demand: senaryonun [T, N] talebi (m³/s)."""
    tw = copy.deepcopy(twin)
    wn = tw.wn
    wn.options.time.duration = 0
    wn.options.hydraulic.demand_model = "PDD"
    wn.options.hydraulic.required_pressure = PDD_REQUIRED_PRESSURE_M
    wn.options.hydraulic.minimum_pressure = PDD_MINIMUM_PRESSURE_M
    if "sabit" not in wn.pattern_name_list:
        wn.add_pattern("sabit", [1.0])
    for d in tw.dmas:
        if d.name in settings:
            set_feed_setting(tw, d, settings[d.name])
    base_demand = to_hourly(base_demand)
    pattern = list(to_hourly(np.asarray(tw.pattern)))

    dma = next(d for d in tw.dmas if d.name == dma_name)
    J = dma.junctions
    col = {j: i for i, j in enumerate(tw.junctions)}
    b = buildings[buildings["junction"].isin(J)]
    smart_mask = (b["tank_m3"] > 0) & b["smart"] & (mode == "on")
    dumb_mask = (b["tank_m3"] > 0) & ~smart_mask
    direct_mask = b["tank_m3"] <= 0
    S = _group(b, smart_mask, J, pattern)
    Dm = _group(b, dumb_mask, J, pattern)
    X = _group(b, direct_mask, J, pattern)

    # Başlangıç doluluğu: şamandıralı depolar dolu, akıllı depolar orkestratörün planındaki seviyede
    sidx = storage.index()
    plan_inflow = to_hourly(plan.inflow, axis=1)
    LS = np.zeros(len(J))
    plan_in = np.zeros((len(J), HOURS))
    for k, j in enumerate(J):
        if j in sidx and S.volume[k] > 0:
            i = sidx[j]
            frac = plan.level[i, 0] / max(storage.volume[i], 1e-9)
            LS[k] = frac * S.volume[k]
            plan_in[k] = plan_inflow[i] * (S.cons[k].sum() / max(plan_inflow[i].sum(), 1e-9))
    LD = Dm.volume.copy()

    leak_coef = np.array([tw.leak_coef.get(j, 0.0) for j in J])
    n_exp = float(wn.options.hydraulic.emitter_exponent)
    inlet = wn.get_link(dma.feed)

    rec = {k: np.zeros(HOURS) for k in ("inflow_m3h", "p_min", "p_mean", "low_nodes", "stored_m3", "unserved_ph")}
    node_p = np.zeros((HOURS, len(J)))
    fill = np.zeros((HOURS, len(J)))
    tank_vol = S.volume + Dm.volume
    def solve(requested: np.ndarray, is_open: bool):
        for k, j in enumerate(J):
            wn.get_node(j).demand_timeseries_list[0].base_value = float(requested[k] / 3600.0)
        inlet.initial_status = LinkStatus.Open if is_open else LinkStatus.Closed
        return simulate(tw)

    prefill_from = max(0, start - PREFILL_HOURS)
    for t in range(HOURS):
        # Diğer DMA'lar normal gününde
        for j in tw.junctions:
            ts = wn.get_node(j).demand_timeseries_list[0]
            ts.pattern_name = "sabit"
            ts.base_value = float(base_demand[t, col[j]])

        is_open = not (start <= t < end)
        cs, cd, cx = S.cons[:, t], Dm.cons[:, t], X.cons[:, t]
        zeros = np.zeros(len(J))
        req_x = cx.copy() if is_open else zeros
        req_d = np.minimum(Dm.cap, np.clip(Dm.volume - LD + cd, 0, None)) if is_open else zeros
        if not is_open or mode != "on":
            req_s = zeros
            res = solve(req_s + req_d + req_x, is_open)
        elif prefill_from <= t < start or t >= end:
            # Ön-dolum ya da kesinti sonrası: önce simüle et, basınç yetmiyorsa daha az su bırak
            hours_left = (start - t) if t < start else 1
            extra = np.minimum(np.clip(S.volume - LS, 0, None) / hours_left, np.clip(S.cap - cs, 0, None))
            for step in REFILL_STEPS:
                req_s = cs + step * extra
                res = solve(req_s + req_d + req_x, is_open)
                if res.node["pressure"][J].to_numpy()[0].min() >= MIN_SERVICE_PRESSURE_M:
                    break
        else:
            req_s = plan_in[:, t].copy()
            res = solve(req_s + req_d + req_x, is_open)
        requested = req_s + req_d + req_x

        p = res.node["pressure"][J].to_numpy()[0]
        if not is_open:
            p = np.zeros_like(p)  # kaynağı kesilmiş bölgede su yok
        got = res.node["demand"][J].to_numpy()[0] * 3600.0
        leak = leak_coef * np.clip(p, 0, None) ** n_exp * 3600.0
        delivered = np.clip(got - leak, 0, None)
        f = np.where(requested > 1e-9, np.minimum(1.0, delivered / np.maximum(requested, 1e-9)), 1.0)

        LS = LS + f * req_s - cs
        LD = LD + f * req_d - cd
        short_s = np.clip(-LS, 0, None)
        short_d = np.clip(-LD, 0, None)
        LS = np.clip(LS, 0, S.volume)
        LD = np.clip(LD, 0, Dm.volume)
        short_x = cx - f * req_x
        with np.errstate(divide="ignore", invalid="ignore"):
            ph = (np.nan_to_num(X.persons * short_x / cx) + np.nan_to_num(S.persons * short_s / cs)
                  + np.nan_to_num(Dm.persons * short_d / cd))

        if dma.reservoir:
            rec["inflow_m3h"][t] = -res.node["demand"][dma.reservoir].to_numpy()[0] * 3600.0
        else:
            rec["inflow_m3h"][t] = res.link["flowrate"][dma.feed].to_numpy()[0] * 3600.0
        rec["p_min"][t] = p.min()
        rec["p_mean"][t] = p.mean()
        rec["low_nodes"][t] = int((p < MIN_SERVICE_PRESSURE_M).sum())
        rec["stored_m3"][t] = LS.sum() + LD.sum()
        rec["unserved_ph"][t] = ph.sum()
        node_p[t] = p
        with np.errstate(divide="ignore", invalid="ignore"):
            fill[t] = np.where(tank_vol > 0, 100.0 * (LS + LD) / tank_vol, np.nan)

    after = slice(end, HOURS)
    ok_after = [t for t in range(end, HOURS) if rec["low_nodes"][t] == 0]
    pre = rec["stored_m3"][start - 1] if start > 0 else tank_vol.sum()
    full_after = [t for t in range(end, HOURS) if rec["stored_m3"][t] >= 0.95 * pre]
    daily = {
        "refill_peak_m3h": float(rec["inflow_m3h"][after].max()),
        "normal_peak_m3h": float(normal_peak_m3h),
        "min_pressure_after": float(rec["p_min"][after].min()),
        "low_node_hours_after": float(rec["low_nodes"][after].sum()),
        "unserved_person_hours": float(rec["unserved_ph"].sum()),
        "unserved_during_ph": float(rec["unserved_ph"][start:end].sum()),
        "unserved_after_ph": float(rec["unserved_ph"][after].sum()),
        "pressure_ok_hour": float(ok_after[0]) if ok_after else -1.0,
        "tanks_full_hour": float(full_after[0]) if full_after else -1.0,
        "stored_at_start_m3": float(rec["stored_m3"][start - 1]) if start > 0 else float(tank_vol.sum()),
    }
    label = "Orkestratör" if mode == "on" else "Şamandıralı vana"
    node_fill = {j: fill[:, k] for k, j in enumerate(J) if tank_vol[k] > 0}
    return OutageRun(mode, label, J, rec, daily, node_p, node_fill)
