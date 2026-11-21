"""Nereden başlamalı? İstanbul ilçelerini su sorunu ve Sanal Baraj'a uygunluk açısından sıralar.

Çalıştırma:  .venv/bin/python scripts/oncelik.py      (önce scripts/fetch_ibb_ref.py)
Çıktı:       data/ref/ilce_oncelik.csv

Yöntem (ağırlıklar bizim seçimimiz, rapor bunu açıkça söyler):
  Su sorunu  = şu beş göstergenin ilçeler arasındaki yüzdelik sıralarının ortalaması
               1.000 abone başına susuzluk şikâyeti (2023)
               1.000 abone başına su arıza ihbarı (2023)
               1.000 abone başına duyurulu kesinti saati (Şub 2023 – Şub 2024)
               basınç düşüklüğü kaynaklı kesinti sayısı
               1.000 abone başına deprem senaryosunda içme suyu borusu hasarı
  Uygunluk   = 5 ve üzeri katlı bina sayısı ve payının yüzdelik sıralarının ortalaması
               (Sanal Baraj apartman depolarıyla çalışır)
  Öncelik    = iki puanın geometrik ortalaması

Sağlamlık kontrolü: her göstergeyi tek tek çıkarıp sıralamayı yeniden hesaplar ve ilk 5'in ne kadar
değiştiğini yazar.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "ref"
PROBLEM = ["susuzluk_1000", "ariza_1000", "kesinti_saat_1000", "basinc_olay", "deprem_1000"]


def load() -> pd.DataFrame:
    abone = pd.read_csv(REF / "ilce_abone.csv").set_index("ilce")["abone"]
    susuz = pd.read_csv(REF / "mahalle_susuzluk_2023.csv").groupby("ilce")["adet"].sum().rename("susuzluk")
    ariza = pd.read_csv(REF / "mahalle_ariza_2023.csv").groupby("ilce")["adet"].sum().rename("ariza")
    kes = pd.read_csv(REF / "kesintiler_2023_2024.csv")
    kes["basinc"] = kes["sebep"].str.upper().str.contains("BASINÇ")
    kg = kes.groupby("ilce").agg(kesinti=("sebep", "size"), kesinti_saat=("sure_saat", "sum"),
                                 basinc_olay=("basinc", "sum"))
    dep = pd.read_csv(REF / "mahalle_deprem_2019.csv").groupby("ilce").agg(
        deprem_boru=("icme_suyu_boru_hasari", "sum"), barinma=("gecici_barinma", "sum"))
    bina = pd.read_csv(REF / "mahalle_bina_2017.csv")
    bina["ilce"] = bina["ilce"].map(lambda s: str(s).replace("i", "İ").replace("ı", "I").upper().strip())
    bg = bina.groupby("ilce")[["kat_1_4", "kat_5_9", "kat_9_19"]].sum()
    bg["yuksek_bina"] = bg["kat_5_9"] + bg["kat_9_19"]
    bg["yuksek_pay"] = bg["yuksek_bina"] / bg[["kat_1_4", "kat_5_9", "kat_9_19"]].sum(axis=1)

    df = pd.DataFrame({"abone": abone}).join([susuz, ariza, kg, dep, bg[["yuksek_bina", "yuksek_pay"]]]).fillna(0)
    k = df["abone"] / 1000.0
    df["susuzluk_1000"] = df["susuzluk"] / k
    df["ariza_1000"] = df["ariza"] / k
    df["kesinti_saat_1000"] = df["kesinti_saat"] / k
    df["deprem_1000"] = df["deprem_boru"] / k
    return df


def score(df: pd.DataFrame, problem_cols=PROBLEM) -> pd.DataFrame:
    out = df.copy()
    out["sorun"] = out[problem_cols].rank(pct=True).mean(axis=1) * 100
    out["uygunluk"] = out[["yuksek_pay", "yuksek_bina"]].rank(pct=True).mean(axis=1) * 100
    out["oncelik"] = np.sqrt(out["sorun"] * out["uygunluk"])
    return out.sort_values("oncelik", ascending=False)


def robustness(df: pd.DataFrame, top: int = 5) -> list[tuple[str, list[str]]]:
    base = list(score(df).index[:top])
    rows = []
    for c in PROBLEM:
        alt = list(score(df, [x for x in PROBLEM if x != c]).index[:top])
        rows.append((c, [x for x in alt if x not in base]))
    return rows


if __name__ == "__main__":
    df = score(load())
    cols = ["oncelik", "sorun", "uygunluk", "susuzluk_1000", "ariza_1000", "kesinti_saat_1000", "basinc_olay",
            "deprem_boru", "barinma", "yuksek_bina", "yuksek_pay", "abone"]
    df[cols].round(2).to_csv(REF / "ilce_oncelik.csv", index_label="ilce")
    pd.set_option("display.width", 200)
    print(df[cols[:8]].round(1).head(10).to_string())
    print("\nSağlamlık (bir gösterge çıkarılınca ilk 5'e giren yeni ilçeler):")
    for c, new in robustness(load()):
        print(f"  {c:20s} {', '.join(new) if new else 'değişiklik yok'}")
    print(f"\nyazıldı: {REF / 'ilce_oncelik.csv'}")
