"""Basınçtan enerji: şebekenin binaya getirdiği basınç depo girişinde nereye gidiyor?

Su bodrum deposuna şebeke basıncıyla (Bayrampaşa'da ortalama ~35 m) gelir; şamandıra ya da motorlu vana bu basıncı
sıfırlar, enerji ısıya döner. Sonra hidrofor aynı suyu elektrikle yeniden dairelere basar. Modül bina başına
ölçer:

- Girişte boşa giden hidrolik güç: ρ·g·Q·p, Q depoya giren debi (senaryonun dolum planı), p düğüm basıncı.
- Mikro türbinle geri kazanılabilecek elektrik ve bunun kitin kendi ihtiyacını karşılayıp karşılamadığı
  (kendi enerjisini üreten kit: pil ve elektrik bağlantısı gerekmez).
- Şebeke basıncının gün boyu yettiği katlar (hidrofora gerek kalmadan beslenebilir) ve bunun bedeli: o katların
  talebi depodan çıkarsa sanal barajdan da çıkar, şebekenin tepe saatine geri döner.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    BOOSTER_EFFICIENCY, BOOSTER_TOP_PRESSURE_M, FLOOR_HEIGHT_M, KIT_POWER_W, TURBINE_EFFICIENCY,
    TURBINE_RESIDUAL_M,
)
from .network import Twin
from .tanks import NodeStorage


@dataclass
class EnergyStudy:
    inlet_w: np.ndarray          # [bina] girişte boşa giden ortalama hidrolik güç (W); depo yoksa 0
    turbine_w: np.ndarray        # [bina] mikro türbinle geri kazanılabilecek ortalama elektrik (W)
    direct_floors: np.ndarray    # [bina] şebeke basıncının gün boyu yettiği kat sayısı
    booster_kwh_d: np.ndarray    # [bina] hidrofor elektriği (kWh/gün)
    summary: dict


def study(twin: Twin, b: pd.DataFrame, storage: NodeStorage, scenario) -> EnergyStudy:
    """b: depo atanmış bina tablosu; scenario: dolum planı ve basınçları kullanılacak senaryo (akıllı depo)."""
    T = twin.steps
    dt = 24.0 / T
    n = len(b)
    col = {j: i for i, j in enumerate(twin.junctions)}
    P = np.clip(scenario.res.node["pressure"][twin.junctions].to_numpy()[:T], 0, None)   # [T, N] m
    sidx = storage.index()
    q = b["q_m3d"].to_numpy(dtype=float)
    tank = b["tank_m3"].to_numpy(dtype=float) > 0
    smart = b["smart"].to_numpy(dtype=bool) & tank
    jcol = b["junction"].map(col).to_numpy()

    inlet_w = np.zeros(n)
    turbine_w = np.zeros(n)
    q_smart = pd.Series(np.where(smart, q, 0.0)).groupby(b["junction"].to_numpy()).transform("sum").to_numpy()
    pattern = np.asarray(twin.pattern, dtype=float)
    for k in np.where(tank)[0]:
        j = b["junction"].iat[k]
        if smart[k] and j in sidx:
            inflow = scenario.plan.inflow[sidx[j]] * q[k] / max(q_smart[k], 1e-12)       # m³/sa [T]
        else:
            inflow = q[k] / 24.0 * pattern                                                # şamandıra: tüketim kadar
        p = P[:, jcol[k]]
        inlet_w[k] = float((9.81 * inflow / 3.6 * p).mean())                              # W
        turbine_w[k] = float((9.81 * inflow / 3.6 * np.clip(p - TURBINE_RESIDUAL_M, 0, None)).mean()) * TURBINE_EFFICIENCY

    floors = b["floors"].to_numpy(dtype=float)
    p_min = P[:, jcol].min(axis=0)
    direct = np.clip(np.floor((p_min - BOOSTER_TOP_PRESSURE_M) / FLOOR_HEIGHT_M) + 1, 0, floors)
    direct = np.where(tank, direct, 0.0)
    head = b["booster_head_m"].to_numpy(dtype=float)
    booster_kwh = np.where(tank, 9.81 * q / 86400.0 * head / BOOSTER_EFFICIENCY * 24.0, 0.0)
    frac = np.where(tank, direct / np.maximum(floors, 1), 0.0)

    nt = int(tank.sum())
    summary = {
        "tank_buildings": nt,
        "inlet_kwh_d": float(inlet_w.sum() * 24 / 1000),
        "inlet_w_mean": float(inlet_w[tank].mean()) if nt else 0.0,
        "inlet_w_median": float(np.median(inlet_w[tank])) if nt else 0.0,
        "inlet_p_mean": float((P[:, jcol[tank]].mean())) if nt else 0.0,
        "turbine_kwh_d": float(turbine_w.sum() * 24 / 1000),
        "self_powered_share": float((turbine_w[tank] >= KIT_POWER_W).mean()) if nt else 0.0,
        "booster_kwh_d": float(booster_kwh.sum()),
        "direct_saving_kwh_d": float((booster_kwh * frac).sum()),
        "direct_demand_share": float((q * frac).sum() / max(q[tank].sum(), 1e-9)),
        "kit_w": KIT_POWER_W, "turbine_efficiency": TURBINE_EFFICIENCY,
    }
    return EnergyStudy(inlet_w, turbine_w, direct, booster_kwh, summary)
