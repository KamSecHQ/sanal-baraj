"""Copernicus GLO-30 sayısal yükseklik modelinden düğüm kotlarını okur.

GLO-30 bir yüzey modelidir (binalar ve ağaçlar dahil). Yol ekseninde ölçülen değerin
bina çatılarına karışmaması için 3x3 pencerede minimum alınır.
"""
from __future__ import annotations

import math
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.ndimage import minimum_filter

from .config import CACHE_DIR

TILE_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"


def _tile_name(lat_floor: int, lon_floor: int) -> str:
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def _tile_path(name: str, cache_dir: Path) -> Path:
    path = cache_dir / f"{name}.tif"
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        req = urllib.request.Request(TILE_URL.format(name=name), headers={"User-Agent": "sanal-baraj/0.1"})
        with urllib.request.urlopen(req, timeout=300) as r, tmp.open("wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(path)
    return path


def sample_elevations(lons, lats, cache_dir: Path | None = None) -> np.ndarray:
    """Her (lon, lat) noktası için kot (m). Okunamayan noktalar komşu ortalamasıyla doldurulur."""
    cache_dir = cache_dir or CACHE_DIR / "dem"
    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    out = np.full(len(lons), np.nan)

    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (lo, la) in enumerate(zip(lons, lats)):
        groups[(math.floor(la), math.floor(lo))].append(i)

    for (lat_f, lon_f), idx in groups.items():
        path = _tile_path(_tile_name(lat_f, lon_f), cache_dir)
        with rasterio.open(path) as src:
            rows, cols = rasterio.transform.rowcol(src.transform, lons[idx], lats[idx])
            rows, cols = np.asarray(rows), np.asarray(cols)
            r0, r1 = max(rows.min() - 2, 0), min(rows.max() + 3, src.height)
            c0, c1 = max(cols.min() - 2, 0), min(cols.max() + 3, src.width)
            arr = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(float)
            if src.nodata is not None:
                arr[arr == src.nodata] = np.nan
            arr = minimum_filter(np.nan_to_num(arr, nan=np.nanmax(arr)), size=3)
            rr = np.clip(rows - r0, 0, arr.shape[0] - 1)
            cc = np.clip(cols - c0, 0, arr.shape[1] - 1)
            out[idx] = arr[rr, cc]

    if np.isnan(out).any():
        out[np.isnan(out)] = np.nanmean(out) if not np.isnan(out).all() else 0.0
    # Deniz kıyısındaki negatif değerleri sıfıra çek
    return np.maximum(out, 0.0)


def despike_on_graph(graph, nodes: list, z: np.ndarray, max_slope: float = 0.15,
                     tolerance_m: float = 5.0, rounds: int = 3) -> tuple[np.ndarray, int]:
    """Komşularından sokak eğimiyle açıklanamayacak kadar farklı kotları komşu medyanıyla değiştirir.

    Yükseklik modelindeki dere yatağı, köprü ve çatı sapmalarını temizler. (yeni kotlar, düzeltilen düğüm sayısı)
    """
    z = np.asarray(z, dtype=float).copy()
    pos = {n: i for i, n in enumerate(nodes)}
    fixed: set[int] = set()
    for _ in range(rounds):
        changed = 0
        new = z.copy()
        for n in nodes:
            nbrs = list(graph.neighbors(n))
            if not nbrs:
                continue
            zn = np.array([z[pos[m]] for m in nbrs])
            dist = np.array([graph[n][m]["length"] for m in nbrs])
            med = float(np.median(zn))
            allowed = tolerance_m + max_slope * float(np.median(dist))
            i = pos[n]
            # Tek komşulu uç düğümlerde de, çok komşulu düğümlerde de aynı ölçüt
            if abs(z[i] - med) > allowed and (len(nbrs) == 1 or np.all(np.sign(zn - z[i]) == np.sign(med - z[i]))):
                new[i] = med
                fixed.add(i)
                changed += 1
        z = new
        if changed == 0:
            break
    return z, len(fixed)
