"""Simülasyon sonuçlarını harita arayüzünün okuduğu GeoJSON/JSON dosyalarına ve EPANET INP'ye yazar.

Normal gün senaryoları aynı dosyalarda tutulur: düğümlerde p{h} (kapalı), pa{h} (akıllı depo), pb{h}
(basınç pilotu), ps{h} (güneşle dolum) basınç; borularda q{h}, qa{h}, qb{h}, qs{h} debi; akıllı depolu binalarda
l{h} ve ls{h} (güneşle dolum) doluluk; depolu binalarda ew/et (girişte boşa giden ve türbinle geri kazanılabilecek
güç, W) ve nd (şebeke basıncının yettiği kat).
Kesinti günü yalnız seçilen DMA'nın öğelerinde: düğümlerde o{h}/oa{h} basınç, binalarda ol{h}/oal{h} doluluk.
Sızıntı avı ayrı bir dosyada (leak.json): DMA düğümleri, sensör düzenleri, her olay için aday olasılıkları.
Deprem günü bütün ilçede: düğümlerde e{h}/ea{h} basınç (şamandıra / kit), binalarda ar (alan sırası), ek/eka
(deposunun kirlenme riskine girdiği saat); hasar noktaları, alanlar ve DMA durumları quake.json'da.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import wntr
from shapely.geometry import MultiPoint, Point, mapping

from .config import (
    MIN_SERVICE_PRESSURE_M, OUTAGE_END_HOUR, OUTAGE_START_HOUR, QUAKE_DRINK_LPCD, QUAKE_REOPEN_AFTER_H,
    QUAKE_SUSPECT_PRESSURE_M, QUAKE_USE_LPCD, TARIFF_PERIOD, TARIFF_TL_PER_KWH, WATER_VALUE_TL_M3,
)
from .network import Twin
from .scenario import activate

HOURS = 24   # harita saatlik gösterir; ince adımlı sonuçlar saatlik özetlenir
_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
SCENARIO_KEYS = ("off", "on", "pilot", "solar")
# Saatlik özette hangi seri nasıl indirgenir (varsayılan: ortalama)
SERIES_REDUCE = {"p_min": "min", "p_max": "max", "low_nodes": "max", "stored_m3": "first", "stored_hours": "first"}
PREFIX_P = {"off": "p", "on": "pa", "pilot": "pb", "solar": "ps"}
PREFIX_Q = {"off": "q", "on": "qa", "pilot": "qb", "solar": "qs"}
OUTAGE_P = {"off": "o", "on": "oa"}
OUTAGE_L = {"off": "ol", "on": "oal"}
QUAKE_P = {"off": "e", "on": "ea"}
QUAKE_RISK = {"off": "ek", "on": "eka"}


def slugify(*parts: str | None) -> str:
    text = "-".join(p for p in parts if p)
    text = text.translate(_TR).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _r(x, nd=1):
    return float(round(float(x), nd))


def _rl(arr, nd=1):
    return [_r(x, nd) for x in arr]


def _write_geojson(path: Path, features: list[dict]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _coords(geom, nd=6):
    """Shapely geometrisini koordinatları yuvarlanmış GeoJSON sözlüğüne çevirir."""
    g = mapping(geom)

    def rnd(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [rnd(x) for x in c]

    return {"type": g["type"], "coordinates": rnd(g["coordinates"])}


def _point(lonlat):
    return {"type": "Point", "coordinates": [round(lonlat[0], 6), round(lonlat[1], 6)]}


def hourly(arr, how: str = "mean") -> np.ndarray:
    """Adım başına diziyi saatliğe indirger (ilk eksen 24·k uzunluğunda)."""
    arr = np.asarray(arr, dtype=float)
    k = arr.shape[0] // HOURS
    if k <= 1:
        return arr
    r = arr.reshape((HOURS, k) + arr.shape[1:])
    return {"mean": r.mean(axis=1), "min": r.min(axis=1), "max": r.max(axis=1), "first": r[:, 0]}[how]


def _block(m: dict) -> dict:
    ratio_keys = ("leak_share", "peak_to_mean", "puant_share")
    series = {}
    for k, v in m["hourly"].items():
        h = hourly(v, SERIES_REDUCE.get(k, "mean"))
        series[k] = [int(x) for x in h] if k == "low_nodes" else _rl(h)
    return {"daily": {k: _r(v, 4 if k in ratio_keys else 1) for k, v in m["daily"].items()}, "hourly": series}


def _pct(new: float, old: float) -> float:
    return _r(100.0 * (new - old) / old, 1) if old else 0.0


def export(twin: Twin, cmp, out_dir: Path, meta: dict, utm_crs) -> dict:
    """cmp: pipeline.Comparison."""
    out_dir.mkdir(parents=True, exist_ok=True)
    J = twin.junctions
    keys = [k for k in SCENARIO_KEYS if k in cmp.scenarios]
    P_full = {k: cmp.metrics[k]["pressure"] for k in keys}
    P = {k: hourly(P_full[k]) for k in keys}
    outage = cmp.outage if cmp.outage_dma else {}
    quake = getattr(cmp, "quake", None)
    energy = getattr(cmp, "energy", None)
    o_col = {}
    if outage:
        o_col = {j: i for i, j in enumerate(next(iter(outage.values())).junctions)}

    # Düğümler
    feats = []
    for i, j in enumerate(J):
        props = {"id": j, "osm": twin.osm_id[j], "dma": twin.dma_of[j] + 1, "z": _r(twin.elevation[j]),
                 "q": _r(twin.consumer_base[j] * 1000, 3)}
        for k in keys:
            props.update({f"{PREFIX_P[k]}{h}": _r(P[k][h, i]) for h in range(HOURS)})
        if j in o_col:
            for k, run in outage.items():
                props.update({f"{OUTAGE_P[k]}{h}": _r(run.node_pressure[h, o_col[j]]) for h in range(HOURS)})
        if quake:
            for k, run in quake.runs.items():
                props.update({f"{QUAKE_P[k]}{h}": _r(run.node_pressure[h, i]) for h in range(HOURS)})
        feats.append({"type": "Feature", "geometry": _point(twin.lonlat[j]), "properties": props})
    _write_geojson(out_dir / "nodes.geojson", feats)

    # Borular (pilotta kapatılan alt bölge sınırları "bp")
    T = twin.steps
    flows = {k: cmp.scenarios[k].res.link["flowrate"].abs().iloc[:T] for k in keys}
    vel = cmp.scenarios["off"].res.link["velocity"].abs()
    pilot_closed = (cmp.pilot_twin.boundary_pipes - twin.boundary_pipes) if cmp.pilot_twin else set()
    feats = []
    for p in twin.wn.pipe_name_list:
        if p not in twin.pipe_geometry:
            continue
        pipe = twin.wn.get_link(p)
        boundary = p in twin.boundary_pipes
        props = {"id": p, "d": int(round(pipe.diameter * 1000)), "L": _r(pipe.length),
                 "dma": 0 if boundary else twin.dma_of[pipe.start_node_name] + 1,
                 "b": int(boundary), "bp": int(p in pilot_closed), "hw": twin.pipe_highway[p],
                 "v": _r(vel[p].max(), 2)}
        for k in keys:
            q = hourly(flows[k][p].to_numpy()) * 1000
            props.update({f"{PREFIX_Q[k]}{h}": _r(q[h], 2) for h in range(HOURS)})
        feats.append({"type": "Feature", "geometry": _coords(twin.pipe_geometry[p]), "properties": props})
    _write_geojson(out_dir / "pipes.geojson", feats)

    # DMA sınırları ve girişler
    pts = gpd.GeoSeries([Point(twin.lonlat[j]) for j in J], crs=4326).to_crs(utm_crs)
    col = {j: i for i, j in enumerate(J)}
    dma_feats, inlet_feats, dma_rows = [], [], []
    outage_bbox = None
    hulls = {}
    for d in twin.dmas:
        members = [col[j] for j in d.junctions]
        hull = MultiPoint(list(pts.iloc[members])).convex_hull.buffer(60)
        hull_ll = gpd.GeoSeries([hull], crs=utm_crs).to_crs(4326).iloc[0]
        hulls[d.name] = hull_ll
        dma_feats.append({"type": "Feature", "geometry": _coords(hull_ll),
                          "properties": {"dma": d.index + 1, "name": d.name, "n": len(members),
                                         "out": int(d.name == cmp.outage_dma)}})
        if d.name == cmp.outage_dma:
            outage_bbox = [round(v, 6) for v in hull_ll.bounds]
        lon, lat = twin.lonlat[d.inlet_junction]
        inlet_feats.append({"type": "Feature", "geometry": _point((lon, lat)),
                            "properties": {"dma": d.index + 1, "name": d.name}})
        row = {"id": d.index + 1, "name": d.name, "junctions": len(members), "inlet": [round(lon, 6), round(lat, 6)]}
        for k in keys:
            row[k] = {"head_m": _r(cmp.scenarios[k].settings[d.name]),
                      "inflow_m3h": _rl(hourly(cmp.metrics[k]["dma_inflow"][d.name])),
                      "p_min": _rl(hourly(P_full[k][:, members].min(axis=1), "min")),
                      "p_max": _rl(hourly(P_full[k][:, members].max(axis=1), "max"))}
        dma_rows.append(row)
    _write_geojson(out_dir / "dmas.geojson", dma_feats)
    _write_geojson(out_dir / "inlets.geojson", inlet_feats)

    # Basınç pilotunun önerdiği vanalar
    _write_geojson(out_dir / "prvs.geojson", [
        {"type": "Feature", "geometry": _point(v.lonlat),
         "properties": {"name": v.name, "parent": v.parent, "rank": v.rank,
                        "save": _r(v.saving_m3d), "excess": _r(v.excess_m),
                        "net": _r(v.net_tl_d), "dtl": _r(v.cost_tl_d), "dh": _r(v.head_m, 2)}}
        for v in cmp.prvs])

    # Binalar
    b = cmp.buildings
    st = cmp.storage
    def fill_of(key):
        if key not in cmp.scenarios:
            return {}
        lv = cmp.scenarios[key].plan.level[:, :T][:, ::max(1, T // HOURS)]   # saat başlarındaki doluluk
        return {j: 100.0 * lv[i, :HOURS] / st.volume[i] for i, j in enumerate(st.junctions) if st.volume[i] > 0}
    fill, fill_s = fill_of("on"), fill_of("solar")
    feats = []
    area_idx = {a: i for i, a in enumerate(quake.area_names)} if quake else {}
    for pos, (_, row) in enumerate(b.iterrows()):
        props = {"h": _r(row["height"]), "fl": int(row["floors"]), "kisi": int(round(row["persons"])),
                 "q": _r(row["q_m3d"], 2), "dma": int(row["dma"]), "t": row["btype"],
                 "tv": _r(row["tank_m3"]), "sm": int(bool(row["smart"])), "hb": _r(row["booster_head_m"])}
        j = row["junction"]
        if props["sm"] and j in fill:
            props.update({f"l{h}": int(round(fill[j][h])) for h in range(HOURS)})
        if props["sm"] and j in fill_s:
            props.update({f"ls{h}": int(round(fill_s[j][h])) for h in range(HOURS)})
        if props["tv"] > 0:
            for k, run in outage.items():
                if j in run.node_fill:
                    props.update({f"{OUTAGE_L[k]}{h}": int(round(run.node_fill[j][h])) for h in range(HOURS)})
        if quake:
            props["ar"] = area_idx[quake.building_area[pos]]
            for k, run in quake.runs.items():
                if run.risk_hour[pos] >= 0:
                    props[QUAKE_RISK[k]] = int(run.risk_hour[pos])
        if energy is not None and props["tv"] > 0:
            props.update({"ew": _r(energy.inlet_w[pos]), "et": _r(energy.turbine_w[pos]), "nd": int(energy.direct_floors[pos])})
        feats.append({"type": "Feature", "geometry": _coords(row.geometry), "properties": props})
    _write_geojson(out_dir / "buildings.geojson", feats)

    # Özet
    lons = [ll[0] for ll in twin.lonlat.values()]
    lats = [ll[1] for ll in twin.lonlat.values()]
    pipe_km = sum(twin.wn.get_link(p).length for p in twin.pipe_geometry) / 1000
    comparison = {}
    if {"off", "on"} <= set(keys):
        a = cmp.metrics["off"]["daily"]
        for k in ("inflow_m3", "leak_m3", "peak_inflow_m3h", "p_mean", "pump_kwh", "pump_tl",
                  "puant_share", "min_reserve_hours", "water_age_h", "mean_head_m"):
            row = {"off": _r(a[k], 3), "on": _r(cmp.metrics["on"]["daily"][k], 3),
                   "pct": _pct(cmp.metrics["on"]["daily"][k], a[k])}
            if "pilot" in keys:
                row["pilot"] = _r(cmp.metrics["pilot"]["daily"][k], 3)
                row["pct_pilot"] = _pct(cmp.metrics["pilot"]["daily"][k], a[k])
            if "solar" in keys:
                row["solar"] = _r(cmp.metrics["solar"]["daily"][k], 3)
                row["pct_solar"] = _pct(cmp.metrics["solar"]["daily"][k], a[k])
            comparison[k] = row
    summary = {
        **meta,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "center": [round(float(np.mean(lons)), 6), round(float(np.mean(lats)), 6)],
        "bbox": [round(min(lons), 6), round(min(lats), 6), round(max(lons), 6), round(max(lats), 6)],
        "counts": {"junctions": len(J), "pipes": len(twin.pipe_geometry), "pipe_km": _r(pipe_km),
                   "dmas": len(twin.dmas), "buildings": len(b), "smart_tanks": int(b["smart"].sum())},
        "population": int(round(float(b["persons"].sum()))),
        "tank_volume_m3": _r(b["tank_m3"].sum()),
        "consumption_m3": _r(sum(twin.consumer_base.values()) * 86400),
        "pattern": _rl(hourly(twin.pattern), 3),
        "step_minutes": twin.step_s // 60,
        "tariff": {"period": TARIFF_PERIOD[:HOURS], "tl_per_kwh": TARIFF_TL_PER_KWH},
        "scenarios": {k: _block(cmp.metrics[k]) for k in keys},
        "comparison": comparison,
        "pilot": {"prvs": len(cmp.prvs), "candidates": cmp.prv_candidates or len(cmp.prv_curve),
                  "accepted": cmp.prv_accepted, "curve_m3d": _rl(cmp.prv_curve), "curve_tl": _rl(cmp.prv_net_curve),
                  "estimated_m3d": _r(sum(v.saving_m3d for v in cmp.prvs)),
                  "net_tl_d": _r(sum(v.net_tl_d for v in cmp.prvs)), "water_value_tl_m3": WATER_VALUE_TL_M3},
        "dmas": dma_rows,
        "min_service_pressure_m": MIN_SERVICE_PRESSURE_M,
    }
    if outage:
        dma_b = b[b["junction"].isin(o_col)]
        summary["outage"] = {
            "dma": cmp.outage_dma, "start": OUTAGE_START_HOUR, "end": OUTAGE_END_HOUR, "bbox": outage_bbox,
            "persons": int(round(float(dma_b["persons"].sum()))),
            "persons_no_tank": int(round(float(dma_b.loc[dma_b["tank_m3"] <= 0, "persons"].sum()))),
            "buildings": int(len(dma_b)), "tank_buildings": int((dma_b["tank_m3"] > 0).sum()),
            "tank_m3": _r(dma_b["tank_m3"].sum()),
            **{k: {"label": run.label,
                   "daily": {x: _r(v) for x, v in run.daily.items()},
                   "hourly": {x: (_rl(v) if x != "low_nodes" else [int(y) for y in v]) for x, v in run.hourly.items()}}
               for k, run in outage.items()},
        }
    if cmp.leak is not None:
        summary["leak"] = export_leak(twin, cmp.leak, summary, out_dir)
    if "solar" in cmp.extra:
        x = cmp.extra["solar"]
        summary["solar"] = {**x, "ptf_tl": {k: _r(v) for k, v in x["ptf_tl"].items()},
                            "solar_share": {k: _r(v, 4) for k, v in x["solar_share"].items()}}
    if energy is not None:
        summary["energy"] = {k: (_r(v, 3) if isinstance(v, float) else v) for k, v in energy.summary.items()}
    if quake:
        summary["quake"] = export_quake(twin, quake, b, hulls, summary, out_dir)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    for k, fname in (("off", "model.inp"), ("on", "model_yapay_zeka.inp"), ("pilot", "model_basinc_pilotu.inp")):
        if k in cmp.scenarios:
            target = cmp.pilot_twin if k == "pilot" else twin
            activate(target, cmp.scenarios[k])
            wntr.network.write_inpfile(target.wn, str(out_dir / fname), units="LPS")
    return summary


def export_leak(twin: Twin, st, summary: dict, out_dir: Path) -> dict:
    """Sızıntı avını leak.json'a yazar (düğümler DMA sırasıyla); özet göstergeleri döndürür."""
    idx = {j: i for i, j in enumerate(st.junctions)}
    dma_row = next(d for d in summary["dmas"] if d["name"] == st.dma)
    base = dma_row["on"]["inflow_m3h"] if "on" in dma_row else dma_row["off"]["inflow_m3h"]
    add = st.leak_lps * 3.6
    metrics = {k: {x: _r(v, 3) for x, v in m.items()} for k, m in st.summary().items()}
    brief = {"dma": st.dma, "hour": st.hour, "leak_lps": st.leak_lps, "events": len(st.events),
             "sigma_m": _r(st.sigma_m, 3), "dma_pipe_m": _r(st.dma_pipe_m, 0),
             "sensors": {k: len(v) for k, v in st.sensors.items()}, "metrics": metrics,
             "quiet": {k: {x: _r(v, 3) for x, v in m.items()} for k, m in st.quiet.items()},
             "excite_fraction": _r(st.excite_fraction, 2), "excite_m3h": _r(st.excite_m3h),
             "quiet_inflow_m3h": _r(st.quiet_inflow_m3h), "demand_noise": st.demand_noise,
             "sensor_noise_m": st.sensor_noise_m, "confidence": st.confidence}
    doc = {
        **brief,
        "nodes": [[round(twin.lonlat[j][0], 6), round(twin.lonlat[j][1], 6)] for j in st.junctions],
        "ids": st.junctions,
        "len_m": _rl(st.node_len_m, 0),
        "sensor_idx": {k: [idx[j] for j in v] for k, v in st.sensors.items()},
        "night_hours": [st.hour],
        "events": [{
            "true": idx[e.true], "drop_m": _r(e.drop_m, 3),
            "post": {k: [round(float(x), 5) for x in p] for k, p in e.posterior.items() if k != "meter"},
            "search_m": {k: _r(v, 0) for k, v in e.search_m.items()},
            "hit": e.hit, "rank": e.rank, "error_m": {k: _r(v, 0) for k, v in e.error_m.items()},
            "inflow_base": base, "inflow_leak": [_r(v + add) for v in base],
        } for e in st.events],
    }
    (out_dir / "leak.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return brief


def export_quake(twin: Twin, q, b, hulls: dict, summary: dict, out_dir: Path) -> dict:
    """Deprem gününü quake.json'a yazar (hasar noktaları, alanlar, DMA durumları); özeti döndürür."""
    persons = b["persons"].to_numpy(dtype=float)
    tank = b["tank_m3"].to_numpy(dtype=float)
    area = q.building_area
    dma_id = {d.name: d.index + 1 for d in twin.dmas}

    def hourly_block(run) -> dict:
        ints = ("low_nodes", "suspect_dmas")
        return {"label": run.label, "daily": {x: _r(v) for x, v in run.daily.items()},
                "hourly": {x: ([int(y) for y in v] if x in ints else _rl(v)) for x, v in run.hourly.items()}}

    areas = []
    for name in q.area_names:
        m = area == name
        n_p = float(persons[m].sum())
        geom = q.areas.geometry.get(name) if q.areas.kind == "mahalle" else None
        geom = geom if geom is not None else hulls.get(name)
        here = [br for br in q.breaks if br.area == name]
        row = {"name": name, "persons": int(round(n_p)), "buildings": int(m.sum()),
               "tank_buildings": int((tank[m] > 0).sum()), "tank_m3": _r(tank[m].sum()),
               "tank_persons": int(round(float(persons[m & (tank > 0)].sum()))),
               "damage": int(q.areas.damage.get(name, 0)) if q.areas.kind == "mahalle" else None,
               "breaks": sum(br.kind == "kirik" for br in here), "leaks": sum(br.kind == "sizinti" for br in here),
               "clean_m3": {k: _rl(run.area_clean_m3[name]) for k, run in q.runs.items()},
               "days": {k: _rl(run.area_clean_m3[name] * 1000.0 / (QUAKE_DRINK_LPCD * n_p) if n_p > 0
                               else np.zeros(HOURS)) for k, run in q.runs.items()},
               "geometry": _coords(geom, 5) if geom is not None else None}
        areas.append(row)

    dmas = {}
    for d in twin.dmas:
        dmas[d.name] = {"id": d.index + 1,
                        "suspect": {k: run.suspect_hour.get(d.name) for k, run in q.runs.items()},
                        "reopen": q.runs["on"].reopen_hour.get(d.name) if "on" in q.runs else None,
                        "damage": sum(br.dma == d.name for br in q.breaks)}
    doc = {
        "hour": q.hour, "kind": q.areas.kind,
        "breaks": [{"ll": [round(br.lonlat[0], 6), round(br.lonlat[1], 6)], "pipe": br.pipe, "kind": br.kind,
                    "d": int(round(br.diameter_mm)), "o": _r(br.opening_mm), "dma": br.dma, "dma_id": dma_id[br.dma],
                    "area": br.area, "lps": {k: _rl(run.break_lps[:, i]) for k, run in q.runs.items()}}
                   for i, br in enumerate(q.breaks)],
        "areas": areas,
        "dmas": dmas,
    }
    (out_dir / "quake.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    off = q.runs["off"]
    sus = [n for n in off.suspect_hour if n in hulls]
    if sus:
        bounds = np.array([hulls[n].bounds for n in sus])
        bbox = [round(float(bounds[:, 0].min()), 6), round(float(bounds[:, 1].min()), 6),
                round(float(bounds[:, 2].max()), 6), round(float(bounds[:, 3].max()), 6)]
    else:
        bbox = summary["bbox"]
    return {
        "hour": q.hour, "kind": q.areas.kind, "source": q.areas.source, "damage_ibb": q.areas.total,
        "areas": len(q.area_names), "bbox": bbox,
        "use_lpcd": QUAKE_USE_LPCD, "drink_lpcd": QUAKE_DRINK_LPCD, "suspect_pressure_m": QUAKE_SUSPECT_PRESSURE_M,
        "reopen_after_h": QUAKE_REOPEN_AFTER_H,
        "population": int(round(float(persons.sum()))),
        "persons_no_tank": int(round(float(persons[tank <= 0].sum()))),
        "tank_m3": _r(tank.sum()), "tank_buildings": int((tank > 0).sum()), "smart_tanks": int(b["smart"].sum()),
        **{k: hourly_block(run) for k, run in q.runs.items()},
    }


def update_index(data_dir: Path, summary: dict) -> None:
    path = data_dir / "index.json"
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    items = [i for i in items if i["slug"] != summary["slug"]]
    items.append({"slug": summary["slug"], "name": summary["name"], "built_at": summary["built_at"]})
    items.sort(key=lambda i: i["name"])
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
