"""Komut satırı: ilçe (ve isteğe bağlı mahalle) adından dijital ikiz üretir.

Örnek:
    .venv/bin/python -m twin.build Avcılar
    .venv/bin/python -m twin.build Kadıköy --mahalle Moda
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pyproj import Transformer

from . import osm
from .config import (
    DATA_DIR, DIURNAL_PATTERN, LEAK_SHARE, MAX_DMA_ELEV_SPREAD_M, NETWORK_STATES, NODES_PER_DMA,
    PARTICIPATION, PER_CAPITA_LPD, RESERVE_FRACTION, SUBZONE_ELEV_SPREAD_M,
)
from .dem import despike_on_graph, sample_elevations
from .demand import assign_to_nodes, building_table
from .export import export, slugify, update_index
from .network import Twin, build_model, finalize
from .pipeline import compare
from .quake import QuakeAreas, build_areas
from .ref import district_daily_consumption_m3, floor_bands, floor_sampler


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="İlçe adından su şebekesi dijital ikizi üretir ve 24 saat simüle eder.")
    ap.add_argument("ilce", help="İstanbul ilçesi, ör. Avcılar")
    ap.add_argument("--mahalle", help="Yalnız bu mahalleyi modelle, ör. Moda")
    ap.add_argument("--nodes-per-dma", type=int, default=NODES_PER_DMA)
    ap.add_argument("--max-spread", type=float, default=MAX_DMA_ELEV_SPREAD_M,
                    help="bir DMA içinde izin verilen en büyük kot farkı (m)")
    ap.add_argument("--subzone-spread", type=float, default=SUBZONE_ELEV_SPREAD_M,
                    help="basınç pilotunun önerdiği alt bölgelerde en büyük kot farkı (m)")
    ap.add_argument("--leak-share", type=float, default=LEAK_SHARE, help="fiziksel kaçak payı (0-1)")
    ap.add_argument("--per-capita", type=float, help="L/kişi/gün; verilmezse ilçe tüketimine kalibre edilir")
    ap.add_argument("--participation", type=float, default=PARTICIPATION,
                    help="akıllı kit takılan depoların payı (0-1)")
    ap.add_argument("--network-state", choices=sorted(NETWORK_STATES), default="tasarim",
                    help="tasarim: yeni ve cömert boyutlu şebeke; mevcut: yaşlanmış, daha çok yük kaybı")
    ap.add_argument("--outage-dma", help="kesinti günü senaryosunun DMA'sı, ör. DMA-12 (verilmezse en kalabalık DMA)")
    ap.add_argument("--no-dem", action="store_true", help="yükseklik modelini kullanma (düz arazi)")
    ap.add_argument("--no-quake", action="store_true", help="deprem günü senaryosunu çalıştırma")
    ap.add_argument("--seed", type=int, default=42)
    return ap.parse_args(argv)


@dataclass
class Built:
    twin: Twin
    buildings: pd.DataFrame
    utm: object
    rng: np.random.Generator
    calibration: dict
    quake_areas: QuakeAreas | None = None


def build_twin(args: argparse.Namespace, log=print) -> Built:
    """OSM'den şebekeyi kurar, boyutlandırır ve kaçağı kalibre eder (henüz senaryo yok)."""
    query = osm.place_query(args.ilce, args.mahalle)
    log(f"Alan sınırı: {query}")
    boundary = osm.fetch_boundary(query)
    polygon = boundary.geometry.iloc[0]
    utm = boundary.estimate_utm_crs()

    log("Yol ağı indiriliyor (OSM)")
    pg = osm.roads_to_pipe_graph(osm.fetch_roads(polygon))
    log(f"  {pg.graph.number_of_nodes()} düğüm, {pg.graph.number_of_edges()} boru adayı")

    log("Binalar indiriliyor (OSM)")
    buildings = osm.fetch_buildings(polygon)
    log(f"  {len(buildings)} bina ayak izi")

    nodes = list(pg.graph.nodes)
    lon = np.array([pg.lonlat[n][0] for n in nodes])
    lat = np.array([pg.lonlat[n][1] for n in nodes])
    x, y = Transformer.from_crs(4326, utm, always_xy=True).transform(lon, lat)
    xy_arr = np.column_stack([x, y])

    if args.no_dem:
        z = np.zeros(len(nodes))
    else:
        log("Kotlar okunuyor (Copernicus GLO-30)")
        z = sample_elevations(lon, lat)
        z, n_fixed = despike_on_graph(pg.graph, nodes, z)
        log(f"  kot aralığı {z.min():.0f}–{z.max():.0f} m, {n_fixed} sapmalı kot düzeltildi")

    rng = np.random.default_rng(args.seed)
    bands = floor_bands(args.ilce, args.mahalle)
    btab = building_table(buildings, utm, floor_sampler(bands, rng))
    btab["node"] = assign_to_nodes(btab, nodes, xy_arr)

    official = None if args.mahalle else district_daily_consumption_m3(args.ilce)
    eq_persons = float(btab["demand_persons"].sum())
    if args.per_capita:
        lpcd, source = args.per_capita, "kullanıcı"
    elif official and eq_persons > 0:
        lpcd, source = official * 1000.0 / eq_persons, "İBB 2023 ilçe tüketimi"
    else:
        lpcd, source = PER_CAPITA_LPD, "varsayılan"
    log(f"Talep: {btab['persons'].sum():,.0f} kişi (tahmini), {lpcd:.0f} L/kişi/gün ({source})")
    if source.startswith("İBB") and not 80 <= lpcd <= 300:
        log("  UYARI: kişi başı tüketim olağan aralığın dışında; OSM bina verisi eksik olabilir")
    btab["q_m3d"] = btab["demand_persons"] * lpcd / 1000.0
    consumer = (btab.groupby("node")["q_m3d"].sum() / 86400.0).to_dict()

    state = NETWORK_STATES[args.network_state]
    log(f"Şebeke modeli kuruluyor ({args.network_state})")
    twin = build_model(pg.graph, pg.lonlat, {n: xy_arr[i] for i, n in enumerate(nodes)},
                       {n: float(z[i]) for i, n in enumerate(nodes)}, consumer, DIURNAL_PATTERN,
                       nodes_per_dma=args.nodes_per_dma, max_spread=args.max_spread,
                       roughness=state["roughness"])
    log(f"  {len(twin.dmas)} DMA, {len(twin.boundary_pipes)} sınır vanası (kapalı)")
    finalize(twin, leak_share=args.leak_share, max_velocity=state["max_velocity"],
             max_headloss=state["max_headloss"], log=log)

    junction_of = {osm_id: j for j, osm_id in twin.osm_id.items()}
    btab["junction"] = [junction_of[n] for n in btab["node"]]
    btab["dma"] = [twin.dma_of[j] + 1 for j in btab["junction"]]
    calibration = {"official_daily_m3": official, "per_capita_lpd": round(lpcd, 1), "source": source}

    # Deprem günü: İBB mahalle hasarını borulara bağlamak için OSM mahalle sınırları (yoksa ilçe toplamı)
    hoods = None
    no_quake = getattr(args, "no_quake", False)
    if not args.mahalle and not no_quake:
        try:
            hoods = osm.fetch_neighbourhoods(polygon)
        except Exception as e:   # ağ yoksa ilçe toplamıyla devam
            log(f"  mahalle sınırları alınamadı ({type(e).__name__}); deprem hasarı ilçe geneline dağıtılacak")
    areas = None if no_quake else build_areas(twin, btab, args.ilce, args.mahalle, hoods, polygon, utm, log=log)
    if areas is not None and areas.building_area is not None:
        btab["mahalle"] = areas.building_area
    return Built(twin=twin, buildings=btab, utm=utm, rng=rng, calibration=calibration, quake_areas=areas)


def main(argv=None) -> dict:
    args = parse_args(argv)
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:6.1f} sn] {msg}", flush=True)

    built = build_twin(args, log)
    log("Depolar, orkestratör, basınç pilotu, kesinti günü, sızıntı avı ve deprem günü")
    cmp = compare(built.twin, built.buildings, built.rng, participation=args.participation,
                  subzone_spread=args.subzone_spread, outage_dma=args.outage_dma, quake_areas=built.quake_areas,
                  log=log)

    slug = slugify(args.ilce, args.mahalle)
    name = f"{args.mahalle}, {args.ilce}" if args.mahalle else args.ilce
    meta = {"slug": slug, "name": name, "ilce": args.ilce, "mahalle": args.mahalle,
            "calibration": built.calibration,
            "params": {"leak_share": args.leak_share, "nodes_per_dma": args.nodes_per_dma,
                       "max_spread_m": args.max_spread, "subzone_spread_m": args.subzone_spread,
                       "participation": args.participation, "network_state": args.network_state,
                       "reserve_fraction": RESERVE_FRACTION, "dem": not args.no_dem, "seed": args.seed}}
    out_dir = DATA_DIR / slug
    log(f"Dışa aktarılıyor: {out_dir}")
    summary = export(built.twin, cmp, out_dir, meta, built.utm)
    update_index(DATA_DIR, summary)

    log("Bitti. Yapay zekâ kapalı → akıllı depo → akıllı depo + basınç pilotu:")
    labels = {"inflow_m3": "şebekeye giren su (m³/gün)", "leak_m3": "kaçak (m³/gün)",
              "peak_inflow_m3h": "tepe debisi (m³/sa)", "p_mean": "ortalama basınç (m)",
              "pump_kwh": "basma enerjisi (kWh/gün)", "pump_tl": "enerji maliyeti (TL/gün)",
              "min_reserve_hours": "en düşük depo yedeği (sa)", "water_age_h": "depoda su yaşı (sa)"}
    for k, label in labels.items():
        c = summary["comparison"][k]
        log(f"  {label:30s} {c['off']:>11,.1f} → {c['on']:>11,.1f} ({c['pct']:+5.1f}%) → "
            f"{c['pilot']:>11,.1f} ({c['pct_pilot']:+5.1f}%)")
    if summary.get("outage"):
        o = summary["outage"]
        log(f"Kesinti günü ({o['dma']}, {o['start']:02d}:00–{o['end']:02d}:00):")
        for k in ("off", "on"):
            s = o[k]["daily"]
            log(f"  {o[k]['label']:18s} dönüşte tepe debi {s['refill_peak_m3h']:,.0f} m³/sa, en düşük basınç "
                f"{s['min_pressure_after']:.1f} m, dönüş sonrası susuz kişi-saat {s['unserved_after_ph']:,.0f}")
    if summary.get("quake"):
        qz = summary["quake"]
        log(f"Deprem günü ({qz['hour']:02d}:00, İBB senaryosunda {qz['damage_ibb']} boru hasarı):")
        for k in ("off", "on"):
            s = qz[k]["daily"]
            log(f"  {qz[k]['label']:18s} gün sonunda temiz su {s['clean_m3_end']:,.0f} m³, kirlenme riskinde depo "
                f"{s['risk_tanks']:,.0f}, temiz suyu olmayan {s['no_clean_end']:,.0f} kişi")
    return summary


if __name__ == "__main__":
    main()
