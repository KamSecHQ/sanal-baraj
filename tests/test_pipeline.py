"""İnternetsiz uçtan uca test: sentetik bir ızgara şebekeyi kurar, boyutlandırır, simüle eder ve dışa aktarır."""
import json

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from twin.config import (
    DIURNAL_PATTERN, MAX_DMA_ELEV_SPREAD_M, MIN_SERVICE_PRESSURE_M, RESERVE_FRACTION, WATER_VALUE_TL_M3,
)
from twin.export import export, slugify
from twin.network import build_model, finalize, partition_dmas
from twin.pipeline import compare
from twin.pressure import zones_feasible
from twin.quake import QuakeAreas


def synthetic_grid(n=12, spacing=100.0):
    """n x n sokak ızgarası; batıdan doğuya 0'dan ~55 m'ye yükselen arazi."""
    grid = nx.grid_2d_graph(n, n)
    ids = {node: k + 1 for k, node in enumerate(grid.nodes)}
    lonlat, xy, z = {}, {}, {}
    for (i, j), k in ids.items():
        x, y = i * spacing, j * spacing
        xy[k] = np.array([x, y])
        z[k] = 0.05 * x
        lonlat[k] = (28.70 + x / 84000.0, 41.00 + y / 111000.0)
    H = nx.Graph()
    for a, b in grid.edges:
        u, v = ids[a], ids[b]
        H.add_edge(u, v, length=spacing, highway="residential", geometry=LineString([lonlat[u], lonlat[v]]))
    return H, lonlat, xy, z


@pytest.fixture(scope="module", params=[60, 15], ids=["60dk", "15dk"])
def synthetic(request):
    H, lonlat, xy, z = synthetic_grid()
    consumer = {n: 0.0005 for n in H.nodes}  # düğüm başı 0,5 L/s
    twin = build_model(H, lonlat, xy, z, consumer, DIURNAL_PATTERN, nodes_per_dma=60, step_minutes=request.param)
    res = finalize(twin, leak_share=0.12, log=lambda *_: None)
    # Her düğümde tek bina: tüketimi düğüm talebine eşit, katlar 3 ile 7 arasında
    junction_of = {osm: j for j, osm in twin.osm_id.items()}
    floors = [3 + (n % 5) for n in H.nodes]
    buildings = gpd.GeoDataFrame({
        "junction": [junction_of[n] for n in H.nodes],
        "floors": floors,
        "height": [3.0 * f for f in floors],
        "q_m3d": [0.0005 * 86400] * H.number_of_nodes(),
        "persons": [30.0] * H.number_of_nodes(),
        "btype": ["yes"] * H.number_of_nodes(),
        "dma": [twin.dma_of[junction_of[n]] + 1 for n in H.nodes],
    }, geometry=[Point(lonlat[n]).buffer(0.00005) for n in H.nodes], crs=4326)
    # Deprem günü: mahalle eşlemesi yok, 5 hasar ızgaranın borularına dağıtılır (1 kırık, 4 sızıntı)
    cmp = compare(twin, buildings, np.random.default_rng(1), quake_areas=QuakeAreas("dma", {}, pool=5),
                  log=lambda *_: None)
    return twin, res, cmp


def test_partition_is_connected_and_respects_elevation_spread():
    H, _, xy, z = synthetic_grid()
    nodes = list(H.nodes)
    labels = partition_dmas(H, nodes, np.array([xy[n] for n in nodes]), np.array([z[n] for n in nodes]),
                            nodes_per_dma=200)
    assert len(set(labels)) > 1
    for c in set(labels):
        members = [n for n, lab in zip(nodes, labels) if lab == c]
        assert nx.is_connected(H.subgraph(members))
        assert np.ptp([z[n] for n in members]) <= MAX_DMA_ELEV_SPREAD_M


def test_baseline_meets_service_pressure(synthetic):
    twin, res, _ = synthetic
    p_peak = res.node["pressure"].loc[twin.peak_time_s][twin.junctions]
    assert p_peak.min() >= MIN_SERVICE_PRESSURE_M - 0.5


def test_orchestrator_flattens_and_respects_tanks(synthetic):
    _, _, cmp = synthetic
    off, on = cmp.metrics["off"]["daily"], cmp.metrics["on"]["daily"]
    # Tepe debisi belirgin düşmeli, kimse susuz kalmamalı
    assert on["peak_inflow_m3h"] < 0.9 * off["peak_inflow_m3h"]
    assert cmp.metrics["on"]["hourly"]["low_nodes"].max() == 0
    # Gün boyunca depolara giren su = depolardan çekilen su (döngüsel denge)
    applied_on, applied_off = cmp.scenarios["on"].applied.sum(), cmp.scenarios["off"].applied.sum()
    assert abs(applied_on - applied_off) / applied_off < 0.005
    # Depo seviyeleri yedek ile kapasite arasında
    lv, vol = cmp.scenarios["on"].plan.level, cmp.storage.volume[:, None]
    assert (lv >= RESERVE_FRACTION * vol - 1e-3).all() and (lv <= vol + 1e-6).all()


def test_pressure_pilot_cuts_leakage_without_losing_service(synthetic):
    _, _, cmp = synthetic
    assert cmp.prvs, "dik ızgarada en az bir vana önerilmeli"
    on, pilot = cmp.metrics["on"], cmp.metrics["pilot"]
    assert pilot["daily"]["leak_m3"] < 0.97 * on["daily"]["leak_m3"]
    assert pilot["hourly"]["p_min"].min() >= MIN_SERVICE_PRESSURE_M - 0.5
    # Seçilen her vana net kazançlı; net kazanç eğrisi artan olmalı
    assert all(b > a for a, b in zip(cmp.prv_net_curve, cmp.prv_net_curve[1:]))


def test_pilot_zone_must_touch_main_zone():
    # m - y - x zinciri: x tek başına uygun; y de seçilirse x ana bölgeye değmez, beslenemez (Bayrampaşa hatası)
    G = nx.path_graph(["m0", "m1", "y", "x"])
    members = list(G.nodes)
    assert zones_feasible(G, members, [["x"]])
    assert zones_feasible(G, members, [["y", "x"]])
    assert not zones_feasible(G, members, [["x"], ["y"]])
    assert not zones_feasible(G, members, [["m1"]])   # ana bölgeyi ikiye böler


def test_outage_refill_keeps_pressure(synthetic):
    _, _, cmp = synthetic
    off, on = cmp.outage["off"].daily, cmp.outage["on"].daily
    assert on["refill_peak_m3h"] < off["refill_peak_m3h"]
    assert on["min_pressure_after"] >= MIN_SERVICE_PRESSURE_M - 0.5
    assert on["unserved_after_ph"] <= off["unserved_after_ph"]


def test_export(synthetic, tmp_path):
    twin, _, cmp = synthetic
    summary = export(twin, cmp, tmp_path, {"slug": slugify("Test", "Izgara"), "name": "Test"}, "EPSG:32635")
    assert 0.10 <= summary["scenarios"]["off"]["daily"]["leak_share"] <= 0.14
    assert summary["comparison"]["peak_inflow_m3h"]["pct"] < -10
    assert summary["comparison"]["leak_m3"]["pct_pilot"] < summary["comparison"]["leak_m3"]["pct"]
    # DMA girişlerinin toplamı şebekeye giren suya eşit olmalı (pilotun alt bölgeleri ana DMA'ya eklenir)
    for k in ("off", "on", "pilot"):
        dma_total = sum(sum(d[k]["inflow_m3h"]) for d in summary["dmas"])
        total = summary["scenarios"][k]["daily"]["inflow_m3"]
        assert abs(dma_total - total) / total < 0.01
    assert summary["outage"]["dma"] == cmp.outage_dma

    nodes = json.loads((tmp_path / "nodes.geojson").read_text(encoding="utf-8"))["features"]
    props = nodes[0]["properties"]
    assert all(f"p{h}" in props and f"pa{h}" in props and f"pb{h}" in props for h in range(24))
    assert any("o0" in f["properties"] for f in nodes)
    assert all(f"e{h}" in props and f"ea{h}" in props for h in range(24))
    assert summary["quake"]["off"]["daily"]["risk_tanks"] > 0 == summary["quake"]["on"]["daily"]["risk_tanks"]
    quake = json.loads((tmp_path / "quake.json").read_text(encoding="utf-8"))
    assert len(quake["breaks"]) == 5 and all(a["geometry"] for a in quake["areas"])
    for name in ("model.inp", "model_yapay_zeka.inp", "model_basinc_pilotu.inp", "prvs.geojson", "leak.json"):
        assert (tmp_path / name).exists()
    leak = json.loads((tmp_path / "leak.json").read_text(encoding="utf-8"))
    assert len(leak["nodes"]) == len(leak["len_m"]) and leak["events"]
    assert abs(sum(leak["events"][0]["post"]["dense"]) - 1) < 1e-3


def test_leak_hunt_dense_sensors_narrow_the_search(synthetic):
    _, _, cmp = synthetic
    st = cmp.leak
    assert st is not None and st.events
    m = st.summary()
    # Yalnız sayaçla arama alanı bütün DMA; yoğun sensörle çok daha küçük olmalı ve gerçek yeri çoğunlukla kapsamalı
    assert m["meter"]["search_share"] == pytest.approx(1.0)
    assert m["dense"]["search_m"] < 0.5 * m["meter"]["search_m"]
    assert m["dense"]["search_m"] <= m["sparse"]["search_m"] + 1e-6
    assert m["dense"]["hit_rate"] >= 0.5
    for e in st.events:
        assert abs(e.posterior["dense"].sum() - 1) < 1e-9


def test_pilot_selection_is_simulated_and_pays_off(synthetic):
    # Alt modelde ölçülen marjinal değerlerin toplamı tam şebekedeki farkla tutarlı olmalı (DMA'lar bağımsız),
    # ve seçilen vanalar bir bütün olarak da net kazançlı kalmalı (kaçak değeri > basma maliyeti artışı)
    _, _, cmp = synthetic
    on, pilot = cmp.metrics["on"]["daily"], cmp.metrics["pilot"]["daily"]
    saved_full = on["leak_m3"] - pilot["leak_m3"]
    saved_sub = sum(v.saving_m3d for v in cmp.prvs)
    assert saved_sub == pytest.approx(saved_full, rel=0.05)
    dcost_full = pilot["pump_tl"] - on["pump_tl"]
    assert sum(v.cost_tl_d for v in cmp.prvs) == pytest.approx(dcost_full, rel=0.05, abs=5.0)
    assert saved_full * WATER_VALUE_TL_M3 - dcost_full > 0
    assert all(v.net_tl_d > 0 for v in cmp.prvs)
    assert cmp.prv_accepted >= len(cmp.prvs) and cmp.prv_candidates >= cmp.prv_accepted


def test_quake_kit_keeps_tank_water_clean(synthetic):
    _, _, cmp = synthetic
    q = cmp.quake
    assert q is not None and len(q.breaks) == 5 and sum(br.kind == "kirik" for br in q.breaks) == 1
    off, on = q.runs["off"], q.runs["on"]
    # Hasarlı DMA'da şamandıralı depo şüpheli şebeke suyunu çeker; kit girişi mühürler, depo temiz kalır
    assert off.daily["suspect_dmas"] >= 1 and off.daily["risk_tanks"] > 0
    assert on.daily["risk_tanks"] == 0 and on.daily["sealed_tanks_end"] > 0
    assert on.daily["clean_m3_end"] >= off.daily["clean_m3_end"] + 1.0
    assert off.daily["break_m3"] > 0
    assert on.daily["dry_ph"] <= off.daily["dry_ph"] + 1e-6
    # Şüpheli DMA'larda şamandıralı depolarda temiz su kalmaz; alanların toplamı ilçenin toplamına eşit
    sus = [a for a in q.area_names if a in off.suspect_hour]
    assert sus and all(off.area_clean_m3[a][-1] == 0 for a in sus)
    for run in (off, on):
        assert np.allclose(sum(run.area_clean_m3.values()), run.hourly["clean_m3"])


def test_slugify_turkish():
    assert slugify("Avcılar", "Gümüşpala") == "avcilar-gumuspala"
    assert slugify("Şişli") == "sisli"
