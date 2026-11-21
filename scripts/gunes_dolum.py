"""Güneşle dolum: orkestratörü gerçek saatlik elektrik piyasa fiyatıyla (EPİAŞ Gün Öncesi Piyasası) çalıştırır.

Gün öncesi fiyatı bir gün önceden yayımlanır; orkestratör ertesi günün dolum planını bu fiyatla yapabilir.
Beş gerçek gün denenir (mevsimler farklı). Her gün için: kapalı, bugünkü üç zamanlı tarifeyle optimize edilen
akıllı depo, güneş odaklı (fiyat ağırlığı 1,0) ve dengeli (0,3) planın piyasa maliyeti, 09–16 arası pompalama
payı ve tepe debisi. Fiyatlar EPİAŞ günlük bültenlerinin "Gün Öncesi Piyasası" sayfasından (TL/MWh).

    .venv/bin/python scripts/gunes_dolum.py Bayrampaşa
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from twin.build import build_twin, parse_args  # noqa: E402
from twin.orchestrator import float_valve_plan, orchestrate  # noqa: E402
from twin.pipeline import uncontrolled_flows  # noqa: E402
from twin.scenario import metrics, run, set_settings, step_prices  # noqa: E402
from twin.tanks import aggregate, assign_tanks, booster_power_kw  # noqa: E402

DAYS = {
    "11.05.2025 (ilkbahar, pazar)": [2997.79, 2951.56, 2950.00, 2620.00, 2910.11, 2598.39, 2154.56, 799.99, 200.00,
                                      149.67, 120.00, 100.01, 101.00, 120.00, 120.00, 129.00, 144.97, 999.99, 3050.00,
                                      3399.00, 3400.00, 3400.00, 3399.00, 3264.07],
    "17.07.2025 (yaz, sıcak)": [3399.46, 3338.38, 3300.00, 3300.00, 3295.39, 3338.38, 3246.04, 2950.00, 3356.08,
                                3355.01, 3202.97, 3068.00, 2900.00, 3144.25, 3200.00, 3200.01, 3359.99, 3400.00, 3400.00,
                                3400.00, 3400.00, 3400.00, 3400.00, 3400.00],
    "25.08.2026 (yaz)": [3697.00, 3300.00, 3300.00, 2900.00, 2900.01, 3187.32, 2904.99, 1499.98, 2875.00, 2330.01,
                         2154.99, 2319.99, 1499.97, 2949.01, 2949.01, 2800.00, 3277.24, 3594.47, 3323.70, 4183.43,
                         4295.00, 3827.01, 3473.00, 3400.00],
    "26.10.2025 (sonbahar, pazar)": [3350.00, 3250.01, 3200.01, 3334.43, 3349.70, 3155.00, 3391.32, 2936.00, 1606.97,
                                     850.00, 128.28, 10.01, 1.00, 1.01, 80.00, 395.10, 3233.07, 3400.00, 3400.00,
                                     3400.00, 3400.00, 3400.00, 2807.77, 1606.98],
    "14.12.2025 (kış, pazar)": [2210.11, 2125.00, 1999.99, 2257.00, 2156.00, 2884.42, 3299.00, 3299.00, 3300.07,
                                2699.99, 1599.98, 1599.98, 1327.40, 1740.11, 1719.99, 2605.00, 3389.99, 3400.00,
                                3400.00, 3390.00, 3099.97, 3246.00, 2499.01, 2542.04],
}


def main(ilce: str) -> dict:
    built = build_twin(parse_args([ilce, "--no-quake"]), log=lambda *_: None)
    twin, rng = built.twin, built.rng
    b = assign_tanks(built.buildings, rng)
    storage = aggregate(b, "junction", twin.junctions, twin.pattern)
    bk = booster_power_kw(b, twin.pattern)
    tanked = b["tank_m3"] > 0
    fx = float(b.loc[tanked & ~b["smart"], "tank_m3"].sum())
    use = float(b.loc[tanked, "q_m3d"].sum() / 24.0)
    k = twin.steps // 24
    dt = 24 / twin.steps
    sun = (np.arange(twin.steps) * dt >= 9) & (np.arange(twin.steps) * dt < 16)
    dmas = {d.name: d.junctions for d in twin.dmas}

    off = run(twin, storage, float_valve_plan(storage), "off", "kapali", retune=True)
    unc = uncontrolled_flows(twin, storage, off)
    tariff = step_prices(twin.steps)
    set_settings(twin, off.settings)
    on = run(twin, storage, orchestrate(storage, dmas, unc, tariff / tariff.mean(), log=lambda *_: None),
             "on", "tarife", retune=True)
    kw = {"kapali": metrics(twin, storage, off, bk, fx, use), "tarife": metrics(twin, storage, on, bk, fx, use)}

    out = {}
    for day, prices in DAYS.items():
        ptf = np.repeat(np.asarray(prices), k)
        m = dict(kw)
        for w in (1.0, 0.3):
            set_settings(twin, off.settings)
            plan = orchestrate(storage, dmas, unc, ptf / ptf.mean(), price_weight=w, log=lambda *_: None)
            m[f"gunes_{w}"] = metrics(twin, storage, run(twin, storage, plan, "solar", "gunes", retune=True), bk, fx, use)
        row = {}
        for name, mm in m.items():
            p = np.asarray(mm["hourly"]["pump_kw"])
            row[name] = {"ptf_tl": round(float((p * ptf / 1000).sum() * dt)),
                         "gunes_payi": round(100 * float(p[sun].sum() / p.sum()), 1),
                         "tepe_m3h": round(float(np.max(mm["hourly"]["inflow_m3h"])))}
        base = row["kapali"]["ptf_tl"]
        print(f"\n{day}: öğle (10–14) ortalama fiyat {np.mean(prices[10:15]):,.0f} TL/MWh, gün {np.mean(prices):,.0f}")
        for name, r in row.items():
            print(f"  {name:10s} piyasa maliyeti {r['ptf_tl']:>8,} TL/gün ({100 * (r['ptf_tl'] - base) / base:+5.1f}%)"
                  f"  güneş saatlerinde %{r['gunes_payi']:4.1f}  tepe {r['tepe_m3h']:,} m³/sa")
        out[day] = row
    Path(f"gunes-{ilce}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Bayrampaşa")
