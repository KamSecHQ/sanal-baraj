"""Üretilmiş ilçelerin dört gün sonuçlarını yan yana koyar.

Kullanım: .venv/bin/python scripts/ilce_karsilastir.py [slug ...]
Çıktı: tablo (ekrana) ve data/ilce-karsilastirma.json (site ve sunum bunu okur).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def row(slug: str) -> dict | None:
    p = DATA / slug / "summary.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text())
    off, on = s["scenarios"]["off"]["daily"], s["scenarios"]["on"]["daily"]
    r = {
        "slug": slug, "name": s["name"], "buildings": s["counts"]["buildings"],
        "smart_tanks": s["counts"]["smart_tanks"], "pipe_km": s["counts"]["pipe_km"],
        "population": s.get("population"),
        "peak_off": off["peak_inflow_m3h"], "peak_on": on["peak_inflow_m3h"],
        "peak_pct": 100 * (on["peak_inflow_m3h"] / off["peak_inflow_m3h"] - 1),
        "puant_off": 100 * off["puant_share"], "puant_on": 100 * on["puant_share"],
    }
    o = s.get("outage")
    if o:
        r.update(out_p_off=o["off"]["daily"]["min_pressure_after"], out_p_on=o["on"]["daily"]["min_pressure_after"],
                 out_dry_off=o["off"]["daily"]["unserved_after_ph"], out_dry_on=o["on"]["daily"]["unserved_after_ph"])
    q = s.get("quake")
    if q and q.get("off"):
        d = lambda m3: 1000 * m3 / (q["drink_lpcd"] * q["population"])
        r.update(quake_days_off=d(q["off"]["daily"]["clean_m3_end"]), quake_days_on=d(q["on"]["daily"]["clean_m3_end"]),
                 quake_risk_off=q["off"]["daily"]["risk_tanks"], quake_risk_on=q["on"]["daily"]["risk_tanks"])
    return r


def main() -> None:
    slugs = sys.argv[1:] or [x["slug"] for x in json.loads((DATA / "index.json").read_text())
                             if "-" not in x["slug"]]
    rows = [r for r in (row(s) for s in slugs) if r]
    rows.sort(key=lambda r: r["peak_pct"])
    print(f"{'İlçe':14} {'bina':>7} {'depo':>7} {'tepe':>8} {'puant':>13} {'kesinti p':>13} {'deprem gün':>13}")
    for r in rows:
        kp = f"{r.get('out_p_off', 0):.1f}→{r.get('out_p_on', 0):.1f}" if "out_p_off" in r else "-"
        dq = f"{r.get('quake_days_off', 0):.1f}→{r.get('quake_days_on', 0):.1f}" if "quake_days_off" in r else "-"
        print(f"{r['name']:14} {r['buildings']:>7} {r['smart_tanks']:>7} {r['peak_pct']:>7.1f}% "
              f"{r['puant_off']:>5.1f}→{r['puant_on']:<5.1f} {kp:>13} {dq:>13}")
    (DATA / "ilce-karsilastirma.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
