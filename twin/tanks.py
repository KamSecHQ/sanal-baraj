"""Bina depoları ve hidroforlar: hangi binada depo var, hacmi ne, düğüm başına toplamı ve hidrofor gücü.

Debiler m³/sa cinsinden ve örüntünün her adımı için verilir (60 dk'da 24, 15 dk'da 96 adım).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import (
    BOOSTER_EFFICIENCY, BOOSTER_TOP_PRESSURE_M, FLOOR_HEIGHT_M, PARTICIPATION,
    TANK_DAYS, TANK_INLET_M3H, TANK_MAX_M3, TANK_MIN_M3, TANK_SHARE_HIGH_RISE, TANK_SHARE_LOW_RISE,
)


def assign_tanks(b: pd.DataFrame, rng: np.random.Generator, participation: float = PARTICIPATION) -> pd.DataFrame:
    """Binalara depo, akıllı kit ve hidrofor basma yüksekliği atar.

    Eklenen sütunlar: tank_m3 (0 = depo yok), smart (kit takılı mı), booster_head_m.
    """
    b = b.copy()
    share = np.where(b["floors"] >= 5, TANK_SHARE_HIGH_RISE, TANK_SHARE_LOW_RISE)
    has_tank = (rng.random(len(b)) < share) & (b["q_m3d"].to_numpy() > 0)
    volume = np.clip(TANK_DAYS * b["q_m3d"].to_numpy(), TANK_MIN_M3, TANK_MAX_M3)
    b["tank_m3"] = np.where(has_tank, volume, 0.0)
    b["smart"] = has_tank & (rng.random(len(b)) < participation)
    b["booster_head_m"] = np.where(has_tank, b["floors"] * FLOOR_HEIGHT_M + BOOSTER_TOP_PRESSURE_M, 0.0)
    return b


@dataclass
class NodeStorage:
    """Düğüm başına toplanmış akıllı depolar ve kontrol edilemeyen talep (m³/sa, adım başına)."""
    junctions: list[str]          # akıllı deposu olan düğümler
    volume: np.ndarray            # [n] m³
    consumption: np.ndarray       # [n, T] akıllı depolardan çekilen tüketim
    inlet_max: np.ndarray         # [n]
    fixed: dict[str, np.ndarray]  # düğüm -> [T] şebekenin doğrudan gördüğü talep (depo yok ya da kit yok)

    def index(self) -> dict[str, int]:
        return {j: i for i, j in enumerate(self.junctions)}


def rate_profile(daily_m3: np.ndarray, pattern: list[float]) -> np.ndarray:
    """Günlük tüketimi (m³) normalize örüntüyle adım başına debiye (m³/sa) çevirir."""
    p = np.asarray(pattern, dtype=float)
    return np.outer(np.asarray(daily_m3, dtype=float) / 24.0, p)


def aggregate(b: pd.DataFrame, junction_col: str, junctions: list[str], pattern: list[float]) -> NodeStorage:
    """Binaları bağlı oldukları düğümde toplar."""
    smart = b[b["smart"]]
    g = smart.groupby(junction_col).agg(volume=("tank_m3", "sum"), daily=("q_m3d", "sum"), n=("tank_m3", "size"))
    g = g[g["daily"] > 0]
    js = list(g.index)
    consumption = rate_profile(g["daily"].to_numpy(), pattern)

    others = b[~b["smart"]].groupby(junction_col)["q_m3d"].sum()
    prof = rate_profile(others.to_numpy(), pattern)
    fixed = {j: np.zeros(len(pattern)) for j in junctions}
    for j, row in zip(others.index, prof):
        fixed[j] = row
    return NodeStorage(junctions=js, volume=g["volume"].to_numpy(), consumption=consumption,
                       inlet_max=g["n"].to_numpy() * TANK_INLET_M3H, fixed=fixed)


def booster_power_kw(b: pd.DataFrame, pattern: list[float]) -> np.ndarray:
    """Depolu binalardaki hidroforların adım başına toplam elektrik gücü (kW).

    Hidrofor bodrumdaki depodan çektiği için gücü şebeke basıncından bağımsızdır;
    bütün senaryolarda aynıdır.
    """
    tanked = b[b["tank_m3"] > 0]
    flow = rate_profile(tanked["q_m3d"].to_numpy(), pattern)  # m³/sa
    head = tanked["booster_head_m"].to_numpy()[:, None]
    return (9.81 * flow / 3600.0 * head / BOOSTER_EFFICIENCY).sum(axis=0)
