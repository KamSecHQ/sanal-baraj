"""İBB açık verisinden türetilen referans tablolar (data/ref)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import REF_DIR


def tr_upper(s: str) -> str:
    """Türkçe büyük harf: 'Avcılar' -> 'AVCILAR', 'Şişli' -> 'ŞİŞLİ'."""
    return s.replace("i", "İ").replace("ı", "I").upper().strip()


@dataclass
class FloorBands:
    k1_4: int
    k5_9: int
    k9_19: int

    @property
    def total(self) -> int:
        return self.k1_4 + self.k5_9 + self.k9_19


def floor_bands(ilce: str, mahalle: str | None = None) -> FloorBands | None:
    """İlçe (ya da mahalle) için 2017 MAKS kat bandı dağılımı."""
    path = REF_DIR / "mahalle_bina_2017.csv"
    if not path.exists():
        return None
    want_ilce = tr_upper(ilce)
    want_mah = tr_upper(mahalle).replace(" MAHALLESİ", "") if mahalle else None
    acc = FloorBands(0, 0, 0)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if tr_upper(r["ilce"]) != want_ilce:
                continue
            if want_mah and tr_upper(r["mahalle"]) != want_mah:
                continue
            acc.k1_4 += int(float(r["kat_1_4"] or 0))
            acc.k5_9 += int(float(r["kat_5_9"] or 0))
            acc.k9_19 += int(float(r["kat_9_19"] or 0))
    return acc if acc.total > 0 else None


def floor_sampler(bands: FloorBands | None, rng: np.random.Generator) -> Callable[[], int]:
    """Kat sayısı etiketi olmayan binalar için ilçenin kat dağılımından örnekler."""
    if bands is None:
        return lambda: 4
    p = np.array([bands.k1_4, bands.k5_9, bands.k9_19], dtype=float)
    p /= p.sum()
    ranges = [(2, 4), (5, 8), (9, 15)]

    def sample() -> int:
        lo, hi = ranges[rng.choice(3, p=p)]
        return int(rng.integers(lo, hi + 1))

    return sample


def district_daily_consumption_m3(ilce: str) -> float | None:
    """İlçenin 2023 faturalanan günlük ortalama su tüketimi (m³/gün)."""
    path = REF_DIR / "ilce_tuketim_2023.csv"
    if not path.exists():
        return None
    want = tr_upper(ilce)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if tr_upper(r["ilce"]) == want:
                return float(r["gunluk_ort_m3"])
    return None


def mahalle_key(name: str) -> str:
    """Mahalle adlarını eşlemek için boşluksuz anahtar: 'İsmet Paşa Mahallesi', 'İSMET PAŞA' ve 'ORTAMAHALLE'
    ('Orta Mahallesi') aynı anahtara iner."""
    k = tr_upper(name).replace("MAHALLESİ", "")
    k = "".join(ch for ch in k if ch.isalnum())
    return k[:-len("MAHALLE")] if k.endswith("MAHALLE") and len(k) > len("MAHALLE") else k


def quake_pipe_damage(ilce: str) -> dict[str, int]:
    """İBB 2019 deprem senaryosu (7,5 Mw gece): ilçenin mahalle anahtarı -> içme suyu borusu hasarı (adet)."""
    path = REF_DIR / "mahalle_deprem_2019.csv"
    if not path.exists():
        return {}
    want = tr_upper(ilce)
    out: dict[str, int] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if tr_upper(r["ilce"]) == want:
                out[mahalle_key(r["mahalle"])] = int(float(r["icme_suyu_boru_hasari"] or 0))
    return out
