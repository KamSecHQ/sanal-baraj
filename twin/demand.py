"""Bina ayak izlerinden nüfus ve su talebi tahmini; talebin en yakın şebeke düğümüne atanması."""
from __future__ import annotations

import re
from typing import Callable

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .config import (
    AMENITY_TYPES, FLAT_GROSS_AREA_M2, FLOOR_HEIGHT_M, FUNCTION_TAG_TYPES, LARGE_FOOTPRINT_M2, MIN_FOOTPRINT_M2,
    NET_TO_GROSS, NON_RESIDENTIAL_FACTOR, PERSONS_PER_FLAT, RESIDENTIAL_TYPES, ZERO_DEMAND_TYPES,
)

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _parse_levels(value) -> int | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    m = _NUM.search(str(value))
    if not m:
        return None
    n = int(round(float(m.group().replace(",", "."))))
    return n if 1 <= n <= 60 else None


def building_type(b: pd.DataFrame) -> pd.Series:
    """Talep hesabındaki bina türü: building etiketi; building=yes ise işlev etiketi ya da büyüklük öne geçer."""
    btype = b.get("building", pd.Series("yes", index=b.index)).fillna("yes").astype(str)
    generic = btype == "yes"
    out = btype.copy()
    for tag, kind in FUNCTION_TAG_TYPES.items():
        if tag in b:
            out[generic & b[tag].notna() & (out == "yes")] = kind
    if "amenity" in b:
        am = b["amenity"]
        hit = generic & am.notna() & (out == "yes")
        out[hit] = am[hit].map(lambda a: AMENITY_TYPES.get(str(a), "public"))
    if "area" in b:
        out[generic & (out == "yes") & (b["area"] > LARGE_FOOTPRINT_M2)] = "buyuk_yapi"
    return out


def building_table(buildings: gpd.GeoDataFrame, utm_crs, sample_floors: Callable[[], int]) -> gpd.GeoDataFrame:
    """Her bina için kat, kişi ve konut eşdeğeri talep birimi (kişi) hesaplar.

    Dönen tabloda: floors, height, persons (yalnız konut), demand_persons (talep hesabındaki eşdeğer kişi),
    levels_tagged (kat sayısı OSM'de etiketli mi), cx/cy (UTM merkez).
    """
    b = buildings.copy()
    proj = b.to_crs(utm_crs)
    b["area"] = proj.area.values
    b = b[b["area"] >= MIN_FOOTPRINT_M2].copy()
    proj = proj.loc[b.index]

    btype = building_type(b)
    tagged = b["building:levels"].map(_parse_levels) if "building:levels" in b else None
    floors = []
    for i in range(len(b)):
        lv = tagged.iloc[i] if tagged is not None else None
        floors.append(int(lv) if lv is not None and not pd.isna(lv) else sample_floors())
    b["floors"] = floors
    b["levels_tagged"] = tagged.notna().values if tagged is not None else False
    b["height"] = b["floors"] * FLOOR_HEIGHT_M

    flats = np.maximum(1, np.round(b["area"] * b["floors"] * NET_TO_GROSS / FLAT_GROSS_AREA_M2))
    is_res = btype.isin(RESIDENTIAL_TYPES)
    factor = np.where(
        btype.isin(ZERO_DEMAND_TYPES), 0.0,
        np.where(is_res, 1.0, btype.map(NON_RESIDENTIAL_FACTOR).fillna(0.3)),
    )
    b["btype"] = btype.values
    b["persons"] = np.where(is_res, flats * PERSONS_PER_FLAT, 0.0)
    b["demand_persons"] = flats * PERSONS_PER_FLAT * factor

    centroids = proj.geometry.centroid
    b["cx"] = centroids.x.values
    b["cy"] = centroids.y.values
    return b.reset_index(drop=True)


def assign_to_nodes(b: gpd.GeoDataFrame, node_ids: list, node_xy: np.ndarray) -> np.ndarray:
    """Her binayı en yakın şebeke düğümüne bağlar; düğüm kimliklerini döndürür."""
    tree = cKDTree(node_xy)
    _, idx = tree.query(np.column_stack([b["cx"].values, b["cy"].values]))
    return np.asarray(node_ids, dtype=object)[idx]
