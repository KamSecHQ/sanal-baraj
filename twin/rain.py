"""Yağmur deposu ve sel tamponu: çatılardaki yağmur suyu hem ikinci bir kaynak hem selde bir tampon olabilir mi?

Senaryo: her konut binasının çatısına, yönetmeliğin istediği büyüklükte (yıllık toplanabilir suyun %6'sı) bir yağmur
deposu konmuş. Yağmur suyu içme suyu deposuna karışmaz; içme dışı işlerde (tuvalet, temizlik, bahçe) kullanılır.

- Sel tamponu: bir sağanakta çatılardan akan suyun ne kadarı depolarda tutulabilir? Klasik depo yağışlı bir haftada
  zaten büyük ölçüde doludur. Akıllı depo hava tahminini okur, sağanaktan önce kendini boşaltır (sakin saatte,
  kanalizasyon boşken), sağanakta bütün hacmi süngerin çekmesi gibi kullanır.
- İkinci kaynak: aylık ortalama yağışla bir yıllık depo dengesi; içme dışı tüketimin ne kadarını yağmur karşılar,
  şebekeden ne kadar su tasarruf edilir. Gerçek yağış düzensiz olduğu için bu hesap iyimserdir.
"""
from __future__ import annotations

import calendar

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import (
    RAIN_EVENTS_MM, RAIN_MONTHLY_MM, RAIN_NONPOTABLE_SHARE, RAIN_PASSIVE_START, RAIN_RUNOFF_COEF, RAIN_TANK_SHARE,
)


def roof_area(b: pd.DataFrame) -> np.ndarray:
    """Bina taban alanı (m²): bina tablosunun `area` sütunu, yoksa geometriden."""
    if "area" in b:
        return b["area"].to_numpy(dtype=float)
    g = gpd.GeoSeries(b.geometry, crs=getattr(b, "crs", None) or 4326)
    return g.to_crs(g.estimate_utm_crs()).area.to_numpy()


def study(b: pd.DataFrame) -> dict:
    """b: bina tablosu (persons, q_m3d ve geometri ya da area). Yalnız konut binaları (persons > 0) sayılır."""
    res = b["persons"].to_numpy(dtype=float) > 0
    roof = np.where(res, roof_area(b), 0.0)
    annual_mm = float(sum(RAIN_MONTHLY_MM))
    collect = roof * annual_mm / 1000.0 * RAIN_RUNOFF_COEF          # m³/yıl
    tank = RAIN_TANK_SHARE * collect                                  # m³
    demand = np.where(res, b["q_m3d"].to_numpy(dtype=float) * RAIN_NONPOTABLE_SHARE, 0.0)   # m³/gün

    events = []
    for mm in RAIN_EVENTS_MM:
        runoff = roof * mm / 1000.0 * RAIN_RUNOFF_COEF
        smart = np.minimum(tank, runoff).sum()
        passive = np.minimum(tank * (1.0 - RAIN_PASSIVE_START), runoff).sum()
        events.append({"mm": mm, "runoff_m3": float(runoff.sum()), "smart_m3": float(smart),
                       "passive_m3": float(passive), "smart_share": float(smart / max(runoff.sum(), 1e-9)),
                       "passive_share": float(passive / max(runoff.sum(), 1e-9))})

    # Bir yıllık depo dengesi, her ayın ortalama günlük yağışıyla
    level = np.zeros(len(b))
    used = 0.0
    for m, mm in enumerate(RAIN_MONTHLY_MM):
        days = calendar.monthrange(2025, m + 1)[1]
        inflow = roof * (mm / days) / 1000.0 * RAIN_RUNOFF_COEF
        for _ in range(days):
            level = np.minimum(level + inflow, tank)
            take = np.minimum(level, demand)
            level -= take
            used += float(take.sum())
    total_q = float(b["q_m3d"].sum()) * 365.0
    return {
        "buildings": int(res.sum()), "roof_m2": float(roof.sum()), "annual_mm": annual_mm,
        "collectable_m3_y": float(collect.sum()), "tank_m3": float(tank.sum()),
        "events": events, "used_m3_y": used, "used_share_of_consumption": used / max(total_q, 1e-9),
        "nonpotable_share": RAIN_NONPOTABLE_SHARE, "passive_start": RAIN_PASSIVE_START, "tank_share": RAIN_TANK_SHARE,
        "nonpotable_days_from_tanks": float(tank.sum() / max(demand.sum(), 1e-9)),
    }
