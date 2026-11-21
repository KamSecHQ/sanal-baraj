"""İBB Açık Veri'den referans tabloları indirip data/ref altına UTF-8 CSV olarak yazar.

Çalıştırma:  .venv/bin/python scripts/fetch_ibb_ref.py

Üretilen dosyalar:
  mahalle_bina_2017.csv        mahalle başına bina sayısı (yapım yılı ve kat bandı)
  ilce_tuketim_2023.csv        ilçe başına faturalanan su tüketimi
  ilce_abone.csv               ilçe başına aktif İSKİ abone sayısı
  mahalle_susuzluk_2023.csv    mahalle başına İSKİ'ye gelen susuzluk şikâyeti
  mahalle_ariza_2023.csv       mahalle başına İSKİ'ye gelen su arıza ihbarı
  kesintiler_2023_2024.csv     duyurulu su kesintileri (Şubat 2023 – Şubat 2024), satır satır
  mahalle_deprem_2019.csv      7,5 Mw gece senaryosu, mahalle başına hasar ve barınma
  ilce_nufus.csv               TÜİK belediye nüfusları 2019–2024
"""
from __future__ import annotations

import csv
import http.client
import io
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "ref"
BASE = "https://data.ibb.gov.tr/dataset"

URLS = {
    "bina": f"{BASE}/be3582eb-09d7-42f8-84d3-b3817dc9ab0a/resource/cef193d5-0bd2-4e8d-8a69-275c50288875/download/2017-yl-mahalle-bazl-bina-saylar.csv",
    "tuketim": f"{BASE}/7009ca22-2cda-4b3e-91a6-2c2a36ea1986/resource/23fac2f5-6107-47d1-975b-779dd8a30f59/download/ilce-baznda-su-tuketim-miktar-2023.xlsx",
    "abone": f"{BASE}/ab4a5210-f90d-4f88-84f0-a58929b55f6f/resource/7194f6e4-c287-43c6-bf02-36f9c64865ee/download/ilcelere-gore-aktif-abone-saylar.xlsx",
    "susuzluk": f"{BASE}/f41d89f1-6624-41f7-84cb-ee1baa33ab6a/resource/e1c10e3c-a562-4d8f-8659-9603bf6b3109/download/iski-2023-yl-susuzluk-ikayet-ve-cevap-saylar.xlsx",
    "ariza": f"{BASE}/736cd643-5927-4b50-9d24-9e825ec91ade/resource/6c991cff-7219-44c0-99a0-3566473889e1/download/iski-2023-yl-ilce-ve-mahalle-bazl-gelen-ve-cevaplanan-su-arza-says.xlsx",
    "kesinti": f"{BASE}/9bc78003-8dc8-4772-8f3f-a5ad7b8c8120/resource/ef33872e-b9e4-4b78-baeb-5ddcfe9b47ff/download/istanbulda-meydana-gelen-su-kesintileri-2023-2024.xlsx",
    "deprem": f"{BASE}/c13514d9-86b1-4b83-a9b9-1a15cb5f254c/resource/9c3ac492-de4b-4245-b418-7ad3df67a193/download/deprem-senaryosu-analiz-sonuclar.csv",
    "nufus": f"{BASE}/1fddeb79-a456-485d-a17e-5ef7649e21ce/resource/c6c9b289-2824-41b3-ab3d-4fd655ed4e24/download/2019.2024-yllar-belediye-nufuslar.xlsx",
}

# Kaynak tablolardaki ilçe kısaltmaları
ILCE_KISALTMA = {
    "B.ÇEKMECE": "BÜYÜKÇEKMECE",
    "K.ÇEKMECE": "KÜÇÜKÇEKMECE",
    "G.O.PAŞA": "GAZİOSMANPAŞA",
    "EYÜP": "EYÜPSULTAN",
}


def tr_upper(s) -> str:
    return str(s).replace("i", "İ").replace("ı", "I").upper().strip()


def ilce(s) -> str:
    name = tr_upper(s)
    return ILCE_KISALTMA.get(name, name)


def mahalle(s) -> str:
    name = tr_upper(s)
    for suffix in (" MAHALLESİ", " MAH.", " MAH"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _download(url: str, attempts: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "sanal-baraj/0.1"})
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError):
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("indirilemedi: " + url)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp1254"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _write(name: str, header: list[str], rows) -> Path:
    out = REF / name
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return out


def fetch_bina() -> Path:
    rows = list(csv.DictReader(io.StringIO(_decode(_download(URLS["bina"]))), delimiter=";"))
    return _write("mahalle_bina_2017.csv",
                  ["ilce", "mahalle", "once_1980", "y1980_2000", "sonra_2000", "kat_1_4", "kat_5_9", "kat_9_19"],
                  ([r["ilce_adi"].strip(), r["mahalle_adi"].strip(), r["1980_oncesi"], r["1980-2000_arasi"],
                    r["2000_sonrasi"], r["1-4 kat_arasi"], r["5-9 kat_arasi"], r["9-19 kat_arasi"]] for r in rows))


def fetch_tuketim() -> Path:
    df = pd.read_excel(io.BytesIO(_download(URLS["tuketim"])))
    name_col = df.columns[0]
    month_cols = [c for c in df.columns if str(c).isdigit()]
    rows = []
    for _, r in df.iterrows():
        name = str(r[name_col]).strip()
        if not name or name == "nan" or name == "GENEL TOPLAM":
            continue
        yearly = float(sum(r[c] for c in month_cols if pd.notna(r[c])))
        rows.append([ilce(name), round(yearly), round(yearly / 365.0)])
    return _write("ilce_tuketim_2023.csv", ["ilce", "yillik_m3", "gunluk_ort_m3"], rows)


def fetch_abone() -> Path:
    df = pd.read_excel(io.BytesIO(_download(URLS["abone"])), header=None).iloc[:, 1:3]
    df.columns = ["ilce", "abone"]
    df["abone"] = pd.to_numeric(df["abone"], errors="coerce")
    df = df.dropna()
    df = df[~df["ilce"].astype(str).str.contains("TOPLAM")]
    return _write("ilce_abone.csv", ["ilce", "abone"], ([ilce(r.ilce), int(r.abone)] for r in df.itertuples()))


def fetch_mahalle_counts(key: str, out: str, cols: tuple[str, str, str]) -> Path:
    df = pd.read_excel(io.BytesIO(_download(URLS[key])))
    c_ilce, c_mah, c_n = cols
    g = df.groupby([df[c_ilce].map(ilce), df[c_mah].map(mahalle)])[c_n].sum()
    return _write(out, ["ilce", "mahalle", "adet"], ([i, m, int(n)] for (i, m), n in g.items()))


def fetch_kesinti() -> Path:
    df = pd.read_excel(io.BytesIO(_download(URLS["kesinti"])))
    rows = []
    for r in df.itertuples(index=False):
        if pd.isna(r[0]):
            continue

        def t(x):
            try:
                return datetime.strptime(str(x).strip(), "%d/%m/%Y %H:%M:%S")
            except ValueError:
                return None

        a, b = t(r[2]), t(r[3])
        hours = round((b - a).total_seconds() / 3600, 2) if a and b and b > a else ""
        rows.append([ilce(r[0]), str(r[5]).strip(), str(r[1]).strip(), a.isoformat() if a else "",
                     b.isoformat() if b else "", hours])
    return _write("kesintiler_2023_2024.csv", ["ilce", "mahalle", "sebep", "baslangic", "bitis", "sure_saat"], rows)


def fetch_nufus() -> Path:
    """TÜİK ADNKS belediye nüfusları (İBB üzerinden), 2019–2024."""
    df = pd.read_excel(io.BytesIO(_download(URLS["nufus"])))
    years = [c for c in df.columns if str(c).isdigit()]
    rows = []
    for _, r in df.iterrows():
        name = str(r[df.columns[0]]).replace("Belediyesi", "").strip()
        if not name or name == "nan":
            continue
        rows.append([ilce(name)] + [int(r[y]) for y in years])
    return _write("ilce_nufus.csv", ["ilce"] + [str(y) for y in years], rows)


def fetch_deprem() -> Path:
    df = pd.read_csv(io.StringIO(_decode(_download(URLS["deprem"]))), sep=";")
    keep = ["icme_suyu_boru_hasari", "atik_su_boru_hasari", "cok_agir_hasarli_bina_sayisi", "agir_hasarli_bina_sayisi",
            "can_kaybi_sayisi", "gecici_barinma"]
    return _write("mahalle_deprem_2019.csv", ["ilce", "mahalle"] + keep,
                  ([ilce(r["ilce_adi"]), mahalle(r["mahalle_adi"])] + [int(r[k]) for k in keep] for _, r in df.iterrows()))


if __name__ == "__main__":
    REF.mkdir(parents=True, exist_ok=True)
    for fn in (fetch_bina, fetch_tuketim, fetch_abone, fetch_kesinti, fetch_deprem, fetch_nufus):
        print("yazıldı:", fn())
    print("yazıldı:", fetch_mahalle_counts("susuzluk", "mahalle_susuzluk_2023.csv", ("ILCE", "MAHALLE_ADI", "GELEN ARIZA")))
    print("yazıldı:", fetch_mahalle_counts("ariza", "mahalle_ariza_2023.csv", ("İlçe", "Mahalle", "Gelen Arıza")))
