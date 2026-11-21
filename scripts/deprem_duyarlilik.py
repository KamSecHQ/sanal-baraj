"""Deprem günü duyarlılığı: sonucu belirleyen varsayımlar değişince depolardaki temiz su ne olur?

Bir ilçenin normal günü bir kez kurulur (OSM önbellekte), deprem günü şu varyantlarla yeniden çalıştırılır:
- hasar yerleşimi: yayınlanan üretimdeki yerleşim ve beş farklı tohum
- kırık oranı: %20 (HAZUS, yer sarsıntısı) yerine %50
- kaynatma uyarısı: yalnız hasarlı ya da basıncı düşen DMA yerine bütün ilçe
- arz tarafı: sarsıntıdan sonra bütün DMA giriş kotları 10 ya da 20 m düşer (terfi ya da elektrik kesintisi)
Son dört varyant ilk tohumun yerleşimini kullanır; karşılaştırma o satırla yapılır.

Örnek:
    .venv/bin/python scripts/deprem_duyarlilik.py Bayrampaşa
Çıktı: ekrana Markdown tablo, data/<bölge>/deprem_duyarlilik.csv
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from twin.build import build_twin, parse_args  # noqa: E402
from twin.config import DATA_DIR, QUAKE_DRINK_LPCD  # noqa: E402
from twin.export import slugify  # noqa: E402
from twin.pipeline import compare  # noqa: E402
from twin.quake import study  # noqa: E402

SEEDS = (11, 22, 33, 44, 55)
VARIANTS = [
    ("Kırık oranı %50", {"break_share": 0.5}),
    ("Kaynatma uyarısı bütün ilçe", {"suspect_scope": "ilce"}),
    ("Giriş kotu −10 m", {"head_drop_m": 10.0}),
    ("Giriş kotu −20 m", {"head_drop_m": 20.0}),
]


def row(name: str, q, population: float) -> dict:
    off, on = q.runs["off"].daily, q.runs["on"].daily
    days = lambda m3: 1000.0 * m3 / (QUAKE_DRINK_LPCD * population)  # noqa: E731
    return {
        "varyant": name, "kirik": int(off["breaks"]), "sizinti": int(off["leaks"]),
        "supheli_dma": int(off["suspect_dmas"]), "supheli_kisi": round(off["suspect_persons"]),
        "temiz_m3_off": round(off["clean_m3_end"]), "temiz_m3_on": round(on["clean_m3_end"]),
        "gun_off": round(days(off["clean_m3_end"]), 1), "gun_on": round(days(on["clean_m3_end"]), 1),
        "riskli_depo_off": int(off["risk_tanks"]), "riskli_depo_on": int(on["risk_tanks"]),
        "temizsiz_kisi_off": round(off["no_clean_end"]), "temizsiz_kisi_on": round(on["no_clean_end"]),
        "susuz_kisi_saat_off": round(off["dry_ph"]), "susuz_kisi_saat_on": round(on["dry_ph"]),
        "en_dusuk_basinc_m": round(off["p_min_after"], 1), "basinci_dusuk_dugum_saat": round(off["low_node_hours"]),
    }


def main(argv=None) -> list[dict]:
    args = parse_args(argv)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:6.1f} sn] {m}", flush=True)  # noqa: E731
    built = build_twin(args, log=lambda *_: None)
    if built.quake_areas is None:
        raise SystemExit("Bu bölge için İBB deprem hasarı yok")
    cmp = compare(built.twin, built.buildings, built.rng, participation=args.participation,
                  subzone_spread=args.subzone_spread, outage_dma=args.outage_dma, with_leak=True,
                  quake_areas=built.quake_areas, log=lambda *_: None)
    pop = float(cmp.buildings["persons"].sum())
    rows = [row("Yayınlanan yerleşim", cmp.quake, pop)]
    log("yayınlanan yerleşim bitti")
    common = (built.twin, cmp.buildings, cmp.storage, {"off": cmp.scenarios["off"], "on": cmp.scenarios["on"]},
              built.quake_areas)
    for seed in SEEDS:
        q = study(*common, np.random.default_rng(seed), log=lambda *_: None)
        rows.append(row(f"Tohum {seed}", q, pop))
        log(f"tohum {seed} bitti")
    for name, kw in VARIANTS:
        q = study(*common, np.random.default_rng(SEEDS[0]), log=lambda *_: None, **kw)
        rows.append(row(f"{name} (tohum {SEEDS[0]})", q, pop))
        log(f"{name} bitti")

    out = DATA_DIR / slugify(args.ilce, args.mahalle) / "deprem_duyarlilik.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    fmt = lambda v: f"{v:,.0f}".replace(",", ".") if isinstance(v, int) else f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    print(f"\n{args.ilce}: deprem günü duyarlılığı (gün sonu; şamandıra / kit)\n")
    print("| Varyant | Kırık / sızıntı | Şüpheli DMA | Temiz su (m³) | İçme suyu (gün) | Riskli depo | "
          "Temiz suyu olmayan (kişi) | Susuz (kişi-saat) | En düşük basınç (m) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['varyant']} | {r['kirik']} / {r['sizinti']} | {r['supheli_dma']} | "
              f"{fmt(r['temiz_m3_off'])} / {fmt(r['temiz_m3_on'])} | {fmt(r['gun_off'])} / {fmt(r['gun_on'])} | "
              f"{fmt(r['riskli_depo_off'])} / {fmt(r['riskli_depo_on'])} | "
              f"{fmt(r['temizsiz_kisi_off'])} / {fmt(r['temizsiz_kisi_on'])} | "
              f"{fmt(r['susuz_kisi_saat_off'])} / {fmt(r['susuz_kisi_saat_on'])} | {fmt(r['en_dusuk_basinc_m'])} |")
    print(f"\nCSV: {out}")
    return rows


if __name__ == "__main__":
    main()
