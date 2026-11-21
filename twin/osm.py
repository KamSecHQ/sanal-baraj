"""OpenStreetMap'ten sınır, yol ağı ve bina ayak izlerini çeker; yolları boru adayı grafiğine çevirir."""
from __future__ import annotations

import time
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import osmnx as ox
import requests
from shapely.geometry import LineString

from .config import CACHE_DIR, EXCLUDED_HIGHWAYS, HIGHWAY_PRIORITY

ox.settings.use_cache = True
ox.settings.cache_folder = str(CACHE_DIR / "osmnx")
ox.settings.log_console = False
ox.settings.requests_timeout = 300

# Ana Overpass sunucusu zaman zaman bağlantıyı reddediyor; sırayla aynalar denenir
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
    "https://overpass.kumi.systems/api",
]


def _overpass(fn, *args, rounds: int = 3, **kwargs):
    """Overpass isteğini önce ana sunucuda, bağlantı ya da sunucu hatasında (502, 504, kota) aynalarda dener.

    Bütün aynalar başarısızsa artan beklemeyle baştan dener.
    """
    last = None
    for attempt in range(rounds):
        for url in OVERPASS_MIRRORS:
            ox.settings.overpass_url = url
            try:
                return fn(*args, **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    ox._errors.ResponseStatusCodeError) as e:
                last = e
                print(f"  Overpass {url.split('/')[2]} yanıt vermedi ({type(e).__name__}), sıradaki deneniyor",
                      flush=True)
        time.sleep(15 * 2 ** attempt)
    raise last


def place_query(ilce: str, mahalle: str | None = None) -> str:
    if mahalle:
        name = mahalle if "mahalle" in mahalle.lower() else f"{mahalle} Mahallesi"
        return f"{name}, {ilce}, İstanbul, Türkiye"
    return f"{ilce}, İstanbul, Türkiye"


def fetch_boundary(query: str) -> gpd.GeoDataFrame:
    gdf = ox.geocode_to_gdf(query)
    if gdf.empty or gdf.geometry.iloc[0].geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"'{query}' için alan sınırı bulunamadı")
    return gdf


def fetch_roads(polygon) -> nx.MultiDiGraph:
    return _overpass(ox.graph_from_polygon, polygon, network_type="drive", simplify=True,
                     retain_all=False, truncate_by_edge=True)


def fetch_buildings(polygon) -> gpd.GeoDataFrame:
    gdf = _overpass(ox.features_from_polygon, polygon, tags={"building": True})
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    keep = [c for c in ("building", "building:levels", "height", "name", "amenity", "shop", "office", "leisure",
                        "tourism", "healthcare", "geometry") if c in gdf.columns]
    gdf = gdf[keep].reset_index(drop=True)
    return gdf


def fetch_neighbourhoods(polygon) -> gpd.GeoDataFrame:
    """İlçedeki mahalle sınırları (OSM admin_level=8). Sütunlar: mahalle (ham ad), geometry."""
    gdf = _overpass(ox.features_from_polygon, polygon, tags={"boundary": "administrative", "admin_level": "8"})
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    gdf = gdf[gdf.get("admin_level", "8").astype(str) == "8"]
    return gdf[["name", "geometry"]].rename(columns={"name": "mahalle"}).reset_index(drop=True)


def _pick_highway(hw) -> str:
    if isinstance(hw, list):
        ranked = sorted(hw, key=lambda h: HIGHWAY_PRIORITY.index(h) if h in HIGHWAY_PRIORITY else 99)
        return ranked[0]
    return hw or "road"


@dataclass
class PipeGraph:
    """Boru adayı grafiği. Düğümler OSM düğüm kimliği; kenarlarda length (m), highway, geometry (lon/lat)."""
    graph: nx.Graph
    lonlat: dict  # düğüm -> (lon, lat)


def roads_to_pipe_graph(G: nx.MultiDiGraph) -> PipeGraph:
    """Yönlü çoklu yol grafiğini yönsüz, tekil kenarlı boru grafiğine çevirir; en büyük bağlı parçayı tutar."""
    H = nx.Graph()
    for u, v, d in G.edges(data=True):
        if u == v:
            continue
        hw = _pick_highway(d.get("highway"))
        if hw in EXCLUDED_HIGHWAYS:
            continue
        length = float(d.get("length", 0.0))
        if length <= 0.5:
            continue
        if H.has_edge(u, v) and H[u][v]["length"] <= length:
            continue
        geom = d.get("geometry")
        if geom is None:
            geom = LineString([(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])])
        H.add_edge(u, v, length=length, highway=hw, geometry=geom)
    if H.number_of_nodes() == 0:
        raise ValueError("Yol ağı boş: alan çok küçük ya da OSM verisi yok")
    largest = max(nx.connected_components(H), key=len)
    H = H.subgraph(largest).copy()
    lonlat = {n: (G.nodes[n]["x"], G.nodes[n]["y"]) for n in H.nodes}
    return PipeGraph(graph=H, lonlat=lonlat)
