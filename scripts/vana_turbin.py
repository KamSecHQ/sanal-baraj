"""Yerçekimi enerjisi: basınç pilotunun vanalarında yok edilen hidrolik gücü hesaplar (mikro türbin potansiyeli).

    .venv/bin/python scripts/vana_turbin.py Bayrampaşa
"""
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import numpy as np
from twin.build import parse_args, build_twin
from twin.pipeline import compare
for ilce in sys.argv[1:]:
    built = build_twin(parse_args([ilce, "--no-quake"]), log=lambda *_: None)
    cmp = compare(built.twin, built.buildings, built.rng, with_outage=False, with_leak=False, log=lambda *_: None)
    tw = cmp.pilot_twin; res = cmp.scenarios["pilot"].res
    T = tw.steps; step_h = 24 / T
    rows = []
    for d in tw.dmas:
        if not d.parent: continue
        link = tw.wn.get_link(d.feed)
        q = res.link["flowrate"][d.feed].to_numpy()[:T]            # m³/s
        dh = (res.node["head"][link.start_node_name] - res.node["head"][link.end_node_name]).to_numpy()[:T]
        p_kw = 9.81 * np.clip(q, 0, None) * np.clip(dh, 0, None)    # hidrolik güç
        rows.append((d.name, float(q.mean()*1000), float(dh.mean()), float(p_kw.mean()), float((p_kw*step_h).sum())))
    rows.sort(key=lambda r: -r[4])
    tot = sum(r[4] for r in rows)
    pump = cmp.metrics["pilot"]["daily"]["pump_kwh"]
    print(ilce, "vana", len(rows), "hidrolik kWh/gün", round(tot,1), "pompalama kWh/gün", round(pump), "oran", round(100*tot/pump,2))
    for r in rows[:8]: print("  ", r[0], "Q L/s %.1f" % r[1], "dH m %.1f" % r[2], "kW %.2f" % r[3], "kWh/g %.1f" % r[4])
    json.dump({"ilce": ilce, "rows": rows, "pump_kwh": pump}, open(f"turbin-{ilce}.json", "w"))
