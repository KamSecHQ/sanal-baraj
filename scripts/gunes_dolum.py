"""Güneşle dolum: orkestratörü gerçek saatlik elektrik piyasa fiyatıyla (EPİAŞ GÖP, 26.10.2025) çalıştırır.

Kapalı, bugünkü üç zamanlı tarife ve güneş odaklı (fiyat ağırlığı 0,3 ve 1,0) planları karşılaştırır:
piyasa maliyeti, 09–16 arası pompalama payı, tepe debisi.

    .venv/bin/python scripts/gunes_dolum.py Bayrampaşa
"""
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import numpy as np
from twin.build import parse_args, build_twin
from twin.orchestrator import orchestrate, float_valve_plan
from twin.pipeline import uncontrolled_flows
from twin.scenario import run, metrics, set_settings, step_prices
from twin.tanks import assign_tanks, aggregate, booster_power_kw
# EPİAŞ Gün Öncesi Piyasası, 26.10.2025, saatlik PTF (TL/MWh)
PTF = [3350.00, 3250.01, 3200.01, 3334.43, 3349.70, 3155.00, 3391.32, 2936.00, 1606.97, 850.00, 128.28, 10.01,
       1.00, 1.01, 80.00, 395.10, 3233.07, 3400.00, 3400.00, 3400.00, 3400.00, 3400.00, 2807.77, 1606.98]
ilce = sys.argv[1]
built = build_twin(parse_args([ilce, "--no-quake"]), log=lambda *_: None)
twin, b0, rng = built.twin, built.buildings, built.rng
b = assign_tanks(b0, rng)
storage = aggregate(b, "junction", twin.junctions, twin.pattern)
bk = booster_power_kw(b, twin.pattern)
tanked = b["tank_m3"] > 0
fx = float(b.loc[tanked & ~b["smart"], "tank_m3"].sum()); use = float(b.loc[tanked, "q_m3d"].sum() / 24.0)
k = twin.steps // 24
ptf_step = np.repeat(np.array(PTF), k)
off = run(twin, storage, float_valve_plan(storage), "off", "kapali", retune=True)
unc = uncontrolled_flows(twin, storage, off)
dmas = {d.name: d.junctions for d in twin.dmas}
out = {}
def evaluate(name, sc):
    m = metrics(twin, storage, sc, bk, fx, use)
    kw = np.asarray(m["hourly"]["pump_kw"])
    dt = 24 / len(kw)
    e = kw.sum() * dt
    cost = float((kw * ptf_step[:len(kw)] / 1000.0).sum() * dt)
    solar = float(kw[(np.arange(len(kw)) * dt >= 9) & (np.arange(len(kw)) * dt < 16)].sum() * dt)
    inflow = np.asarray(m["hourly"]["inflow_m3h"])
    out[name] = {"kwh": round(e), "ptf_tl": round(cost), "solar_share": round(100 * solar / e, 1),
                 "peak_m3h": round(float(inflow.max())), "tarife_tl": round(m["daily"]["pump_tl"]),
                 "p_min": round(float(np.min(m["hourly"]["p_min"])), 1), "kw_h": [round(float(x)) for x in kw.reshape(24, -1).mean(axis=1)]}
    print(name, {k: v for k, v in out[name].items() if k != "kw_h"}, flush=True)
    return m
evaluate("kapali", off)
tariff = step_prices(twin.steps)
plan_t = orchestrate(storage, dmas, unc, tariff / tariff.mean(), log=lambda *_: None)
set_settings(twin, off.settings)
on_t = run(twin, storage, plan_t, "on", "tarife", retune=True); evaluate("akilli_tarife", on_t)
for w in (0.3, 1.0):
    plan_s = orchestrate(storage, dmas, unc, ptf_step / ptf_step.mean(), price_weight=w, log=lambda *_: None)
    set_settings(twin, off.settings)
    sc = run(twin, storage, plan_s, "on", "gunes", retune=True); evaluate(f"akilli_gunes_w{w}", sc)
json.dump(out, open(f"gunes-{ilce}.json", "w"), indent=1)
