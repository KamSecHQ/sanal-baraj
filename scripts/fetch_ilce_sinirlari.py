"""İstanbul'un 39 ilçesinin sınırlarını OSM'den (Nominatim) çeker; haritadaki "Nereden başlamalı" görünümü için.

Çalıştırma:  .venv/bin/python scripts/fetch_ilce_sinirlari.py
Çıktı:       data/ref/ilceler.geojson  (sadeleştirilmiş, ~300 KB; özellik: ilce = İBB tablolarındaki büyük harfli ad)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import osmnx as ox
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin.config import CACHE_DIR  # noqa: E402

REF = ROOT / "data" / "ref"
SIMPLIFY_DEG = 0.0006   # ~50 m; ilçe ölçeğinde görünmez, dosyayı küçültür

ox.settings.use_cache = True
ox.settings.cache_folder = str(CACHE_DIR / "osmnx")
ox.settings.log_console = False


def title_tr(upper: str) -> str:
    """İBB'nin büyük harfli ilçe adını Türkçe başlık biçimine çevirir: 'KÜÇÜKÇEKMECE' -> 'Küçükçekmece'."""
    low = upper.replace("I", "ı").replace("İ", "i").lower()
    return low[0].replace("i", "İ").replace("ı", "I").upper() + low[1:]


def main() -> None:
    ilceler = pd.read_csv(REF / "ilce_oncelik.csv")["ilce"].tolist()
    feats = []
    for ilce in ilceler:
        name = title_tr(ilce)
        gdf = ox.geocode_to_gdf(f"{name}, İstanbul, Türkiye")
        geom = gdf.geometry.iloc[0].simplify(SIMPLIFY_DEG, preserve_topology=True)
        g = json.loads(gpd_to_json(geom))
        feats.append({"type": "Feature", "geometry": g, "properties": {"ilce": ilce, "name": name}})
        print(f"  {name:15s} {geom.geom_type}")
    out = REF / "ilceler.geojson"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False,
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(feats)} ilçe -> {out} ({out.stat().st_size / 1024:.0f} KB)")


def gpd_to_json(geom) -> str:
    """Koordinatları 5 basamağa (~1 m) yuvarlayarak GeoJSON metni üretir."""
    from shapely.geometry import mapping

    def rnd(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], 5), round(c[1], 5)]
        return [rnd(x) for x in c]

    g = mapping(geom)
    return json.dumps({"type": g["type"], "coordinates": rnd(g["coordinates"])})


if __name__ == "__main__":
    main()
