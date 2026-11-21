"""Sızıntı avı: yeni bir boru patlağının yerini binalardaki basınç sensörleriyle bulmak.

DMA girişindeki debi sayacı, gece en düşük debide (MNF) sızıntıyı fark eder ama yerini söylemez; arama
alanı bütün DMA'dır. Akıllı kitin giriş basıncı sensörü her binada şebeke basıncını ölçer. Sızıntı,
yakınındaki düğümlerde basıncı biraz daha çok düşürür. Model her aday düğüm için "sızıntı burada olsaydı"
basınç imzasını hesaplar; ölçülen sapmaya en iyi uyan adaylar olasılıkla sıralanır:

    gözlem  r = a · s_c + ε,   a ≥ 0 bilinmeyen sızıntı büyüklüğü,   ε ~ N(0, σ²)
    a*_c    = max(0, s_c·r / s_c·s_c)
    P(c|r)  ∝ exp(−‖r − a*_c s_c‖² / 2σ²)

σ, sızıntısız ama gürültülü denemelerden ölçülür: gece talebi her düğümde rastgele sapar, sensör hata yapar.
Arama alanı, olasılığın %90'ını kapsayan en küçük düğüm kümesine bağlı boru uzunluğudur.

Ölçümü orkestratör düzenler, bu yalnız akıllı kitle mümkündür:
- Sessiz şebeke: akıllı depoların plansız dolumu durur, şebekede yalnız deposuz binaların talebi kalır.
- Kontrollü yükleme: ardından depolar bilinen debiyle (seviye sensörü ölçer) doldurulur. Gece şebeke o kadar
  sakindir ki 2 L/s'lik sızıntı sensörlerde birkaç santimlik iz bırakır; yük kaybı debiyle büyüdüğü için bilinen
  yük bu izi büyütür, gürültüye ise neredeyse hiç eklemez. Sahada "adım testi" denen yöntemin akıllı kitle
  yapılan halidir. Yük, en düşük basıncı hizmet sınırının üstünde tutacak kadar seçilir.

Üç sensör düzeni karşılaştırılır: yalnız DMA sayacı, seyrek (DMA başına birkaç kaydedici), yoğun (akıllı kitli
her bina). Seyrek düzen de aynı sessiz şebekeyle değerlendirilir; fark yalnız sensör sayısından gelir.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import wntr

from .config import (
    LEAK_CONFIDENCE, LEAK_CONTROL_NOISE, LEAK_DEMAND_NOISE, LEAK_DETECT_HOUR, LEAK_EVENT_LPS, LEAK_EVENTS,
    LEAK_EXCITE_MINUTES, LEAK_EXCITE_STEPS, LEAK_NOISE_RUNS, LEAK_SENSOR_NOISE_M, LEAK_SPARSE_SENSORS,
    MIN_SERVICE_PRESSURE_M,
)
from .network import Twin, copy_hydraulic_options, node_leak_lengths
from .orchestrator import Plan
from .tanks import NodeStorage


@dataclass
class LeakEvent:
    true: str                        # sızıntının gerçek düğümü
    posterior: dict[str, np.ndarray] # düzen -> [n] aday olasılıkları (DMA düğüm sırasıyla)
    search_m: dict[str, float]       # düzen -> arama alanındaki boru uzunluğu (m)
    hit: dict[str, bool]             # gerçek düğüm arama alanında mı
    rank: dict[str, int]             # gerçek düğümün olasılık sırası (1 = en olası)
    error_m: dict[str, float]        # en olası aday ile gerçek yer arasındaki kuş uçuşu mesafe
    drop_m: float                    # gerçek sızıntının sensörlerde yarattığı en büyük basınç düşüşü


@dataclass
class LeakStudy:
    dma: str
    hour: int
    leak_lps: float
    junctions: list[str]
    sensors: dict[str, list[str]]
    sigma_m: float
    dma_pipe_m: float
    node_len_m: np.ndarray
    excite_fraction: float = 0.0     # kontrollü yüklemede depo giriş kapasitesinin kullanılan oranı
    excite_m3h: float = 0.0          # yüklemenin DMA'ya eklediği bilinen debi
    quiet_inflow_m3h: float = 0.0    # sessiz şebekede (dolum durmuş) bölgeye giren debi, kaçak dahil
    demand_noise: float = 0.0        # varsayımlar (rapor ve arayüz için)
    sensor_noise_m: float = 0.0
    confidence: float = 0.0
    events: list[LeakEvent] = field(default_factory=list)
    quiet: dict = field(default_factory=dict)   # yüklemesiz (yalnız sessiz şebeke) ölçümün özeti

    def summary(self) -> dict:
        out = {}
        for k in self.sensors:
            ev = self.events
            out[k] = {"search_m": float(np.mean([e.search_m[k] for e in ev])),
                      "search_share": float(np.mean([e.search_m[k] for e in ev]) / self.dma_pipe_m),
                      "hit_rate": float(np.mean([e.hit[k] for e in ev])),
                      "median_rank": float(np.median([e.rank[k] for e in ev])),
                      "error_m": float(np.mean([e.error_m[k] for e in ev]))}
        return out


class _Snap:
    """DMA'nın tek başına modeli: giriş rezervuarı sabit kotlu olduğu için diğer bölgelerden bağımsızdır."""

    def __init__(self, twin: Twin, dma, head_m: float, demand_m3s: dict[str, float]):
        src = twin.wn
        wn = wntr.network.WaterNetworkModel()
        wn.options.time.duration = 0
        copy_hydraulic_options(src, wn)
        members = set(dma.junctions)
        for j in dma.junctions:
            n = src.get_node(j)
            wn.add_junction(j, base_demand=float(demand_m3s.get(j, 0.0)), elevation=n.elevation, coordinates=n.coordinates)
            wn.get_node(j).emitter_coefficient = twin.leak_coef.get(j, 0.0)
        r = src.get_node(dma.reservoir)
        wn.add_reservoir(dma.reservoir, base_head=head_m, coordinates=r.coordinates)
        for p in src.pipe_name_list:
            pipe = src.get_link(p)
            u, v = pipe.start_node_name, pipe.end_node_name
            if p == dma.feed or (u in members and v in members and p not in twin.boundary_pipes):
                wn.add_pipe(p, u, v, length=pipe.length, diameter=pipe.diameter, roughness=pipe.roughness,
                            minor_loss=pipe.minor_loss)
        self.wn = wn
        self.feed = dma.feed
        self.inflow_m3h = 0.0                 # son çözümde bölgeye giren debi
        self.junctions = list(dma.junctions)
        self.base = np.array([float(demand_m3s.get(j, 0.0)) for j in self.junctions])
        self._tmp = tempfile.TemporaryDirectory()

    def pressure(self, demand: np.ndarray) -> np.ndarray:
        for j, q in zip(self.junctions, demand):
            self.wn.get_node(j).demand_timeseries_list[0].base_value = float(q)
        res = wntr.sim.EpanetSimulator(self.wn).run_sim(file_prefix=str(Path(self._tmp.name) / "s"))
        self.inflow_m3h = float(res.link["flowrate"][self.feed].iloc[0]) * 3600.0
        return res.node["pressure"][self.junctions].to_numpy()[0]


def _spread(xy: np.ndarray, k: int, start: int) -> list[int]:
    """En uzak nokta örneklemesi: birbirinden olabildiğince uzak k nokta (geleneksel kaydedici yerleşimi)."""
    chosen = [start]
    d = np.linalg.norm(xy - xy[start], axis=1)
    while len(chosen) < min(k, len(xy)):
        i = int(np.argmax(d))
        chosen.append(i)
        d = np.minimum(d, np.linalg.norm(xy - xy[i], axis=1))
    return chosen


def _posterior(r: np.ndarray, S: np.ndarray, sigma: float) -> np.ndarray:
    """r: [m] gözlenen sapma, S: [n, m] aday imzaları -> [n] olasılık."""
    ss = (S * S).sum(axis=1)
    a = np.clip((S @ r) / np.maximum(ss, 1e-12), 0.0, None)
    sse = ((r[None, :] - a[:, None] * S) ** 2).sum(axis=1)
    logl = -sse / (2.0 * sigma ** 2)
    w = np.exp(logl - logl.max())
    return w / w.sum()


def _search_set(p: np.ndarray, conf: float) -> np.ndarray:
    order = np.argsort(-p)
    k = int(np.searchsorted(np.cumsum(p[order]), conf) + 1)
    return order[:k]


def _hunt(snap: _Snap, fixed: np.ndarray, ctrl: np.ndarray, sensors: dict[str, list[int]], truths: np.ndarray,
          q_leak: float, rng: np.random.Generator, demand_noise: float, control_noise: float, sensor_noise: float,
          noise_runs: int) -> tuple[np.ndarray, dict[str, float], list[np.ndarray], np.ndarray]:
    """Bir ölçüm düzeni için imzalar, gürültü düzeyi ve her olayın gözlemi."""
    n = len(fixed)
    base = fixed + ctrl
    p0 = snap.pressure(base)
    S = np.zeros((n, n))
    for c in range(n):
        d = base.copy()
        d[c] += q_leak
        S[c] = snap.pressure(d) - p0

    def observe(leak_at: int | None) -> np.ndarray:
        d = fixed * np.clip(1.0 + demand_noise * rng.standard_normal(n), 0.0, None) \
            + ctrl * (1.0 + control_noise * rng.standard_normal(n))
        if leak_at is not None:
            d[leak_at] += q_leak
        return snap.pressure(d) - p0 + sensor_noise * rng.standard_normal(n)

    noise = np.array([observe(None) for _ in range(noise_runs)])
    sigma = {k: float(noise[:, s].std()) for k, s in sensors.items()}
    obs = [observe(int(t)) for t in truths]
    return S, sigma, obs, p0


def study(twin: Twin, storage: NodeStorage, plan: Plan, settings: dict[str, float], dma_name: str,
          rng: np.random.Generator, hour: int = LEAK_DETECT_HOUR, leak_lps: float = LEAK_EVENT_LPS,
          n_events: int = LEAK_EVENTS, demand_noise: float = LEAK_DEMAND_NOISE,
          control_noise: float = LEAK_CONTROL_NOISE, sensor_noise: float = LEAK_SENSOR_NOISE_M,
          noise_runs: int = LEAK_NOISE_RUNS, n_sparse: int = LEAK_SPARSE_SENSORS, conf: float = LEAK_CONFIDENCE,
          log=print) -> LeakStudy:
    """settings ve plan: akıllı depo senaryosunun bölge ayarları ve dolum planı."""
    dma = next(d for d in twin.dmas if d.name == dma_name)
    J = dma.junctions
    n = len(J)
    step = int(hour * twin.steps / 24)
    q_leak = leak_lps / 1000.0
    # Kontrol edilemeyen talep (deposuz ya da kitsiz binalar); akıllı depoların dolumu ölçüm süresince orkestratörde
    fixed = np.array([float(storage.fixed[j][step]) / 3600.0 for j in J])
    sidx = storage.index()
    cap = np.zeros(n)
    for k, j in enumerate(J):
        if j in sidx:
            i = sidx[j]
            space = max(0.0, float(storage.volume[i] - plan.level[i, step]))
            cap[k] = min(float(storage.inlet_max[i]), space * 60.0 / LEAK_EXCITE_MINUTES) / 3600.0
    snap = _Snap(twin, dma, settings[dma.name], {j: q for j, q in zip(J, fixed)})
    snap.pressure(fixed)
    quiet_inflow = snap.inflow_m3h

    # Kontrollü yükleme: hizmet basıncını bozmayan en büyük dolum oranı
    frac = 0.0
    for f in LEAK_EXCITE_STEPS:
        if snap.pressure(fixed + f * cap).min() >= MIN_SERVICE_PRESSURE_M + 2.0:
            frac = f
            break
    ctrl = frac * cap

    smart = set(storage.junctions)
    xy = np.array([twin.wn.get_node(j).coordinates for j in J])
    idx = {j: i for i, j in enumerate(J)}
    sensors = {"dense": [i for i, j in enumerate(J) if j in smart],
               "sparse": _spread(xy, n_sparse, idx[dma.inlet_junction])}
    lengths = node_leak_lengths(twin)
    L = np.array([lengths.get(j, 0.0) for j in J])
    total = float(L.sum())
    truths = rng.choice(n, size=min(n_events, n), replace=False)
    log(f"  sızıntı avı: {dma.name}, {n} aday düğüm, {len(sensors['dense'])} kitli düğüm, {hour:02d}:00, "
        f"kontrollü yükleme %{100 * frac:.0f} ({ctrl.sum() * 3600:.0f} m³/sa)")

    def evaluate(S, sigma, obs) -> list[LeakEvent]:
        out = []
        for t, r in zip(truths, obs):
            post = {"meter": np.full(n, 1.0 / n)}
            for k, s in sensors.items():
                post[k] = _posterior(r[s], S[:, s], max(sigma[k], 1e-4))
            ev = LeakEvent(true=J[t], posterior=post, search_m={}, hit={}, rank={}, error_m={},
                           drop_m=float(-(S[t, sensors["dense"]]).min()) if sensors["dense"] else 0.0)
            for k, p in post.items():
                sset = _search_set(p, conf) if k != "meter" else np.arange(n)
                ev.search_m[k] = float(L[sset].sum())
                ev.hit[k] = bool(int(t) in set(sset.tolist()))
                ev.rank[k] = int((p > p[t]).sum() + 1) if k != "meter" else (n + 1) // 2
                best = int(np.argmax(p)) if k != "meter" else idx[dma.inlet_junction]
                ev.error_m[k] = float(np.linalg.norm(xy[best] - xy[t]))
            out.append(ev)
        return out

    st = LeakStudy(dma=dma.name, hour=hour, leak_lps=leak_lps, junctions=J,
                   sensors={"meter": [], **{k: [J[i] for i in v] for k, v in sensors.items()}},
                   sigma_m=0.0, dma_pipe_m=total, node_len_m=L, excite_fraction=frac,
                   excite_m3h=float(ctrl.sum() * 3600.0), quiet_inflow_m3h=quiet_inflow,
                   demand_noise=demand_noise, sensor_noise_m=sensor_noise, confidence=conf)
    # Önce sessiz ölçüm (yükleme yok), sonra kontrollü yükleme; haritada ikincisi gösterilir
    S, sigma, obs, _ = _hunt(snap, fixed, np.zeros(n), sensors, truths, q_leak, rng, demand_noise, control_noise,
                             sensor_noise, noise_runs)
    st.events = evaluate(S, sigma, obs)
    st.quiet = st.summary()
    if frac > 0:
        S, sigma, obs, _ = _hunt(snap, fixed, ctrl, sensors, truths, q_leak, rng, demand_noise, control_noise,
                                 sensor_noise, noise_runs)
        st.events = evaluate(S, sigma, obs)
    st.sigma_m = sigma["dense"]
    m = st.summary()
    log(f"  arama alanı: sayaç {total / 1000:.1f} km; sessiz ölçüm yoğun {st.quiet['dense']['search_m'] / 1000:.2f} km; "
        f"yüklemeli seyrek {m['sparse']['search_m'] / 1000:.2f} km, yoğun {m['dense']['search_m'] / 1000:.2f} km "
        f"(isabet %{100 * m['dense']['hit_rate']:.0f})")
    return st
