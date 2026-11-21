"""Boru grafiğinden WNTR su şebekesi modeli kurar: DMA'lar, boru boyutlandırma, basınç ayarı ve kaçak.

Zaman adımı ayarlanabilir (standart 60 dk, yüksek çözünürlükte 15 dk); adım sayısı örüntünün uzunluğudur.
Her basınç bölgesi ya ideal bir girişten (sabit kotlu rezervuar) ya da bir basınç düşürücü vanadan (PRV) beslenir.
"""
from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import wntr
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import AgglomerativeClustering
from wntr.network import LinkStatus

from .config import (
    DEFAULT_DIAMETER_MM, ELEV_WEIGHT, HAZEN_WILLIAMS_C, HIGHWAY_DIAMETER_MM, LEAK_EXPONENT, LEAK_SHARE,
    MAX_DMA_ELEV_SPREAD_M, MAX_HEADLOSS_M_PER_KM, MAX_VELOCITY_MS, MIN_SERVICE_PRESSURE_M, NODES_PER_DMA,
    PIPE_SIZES_MM, SIZING_ITERATIONS, TARGET_CRITICAL_PRESSURE_M,
)

INLET_PIPE_LENGTH_M = 40.0
INLET_PIPE_DIAMETER_M = 0.6
MIN_DMA_NODES = 30


@dataclass
class Dma:
    """Basınç bölgesi. `feed` bölgeyi besleyen bağlantıdır: rezervuarlı girişte boru, aksi halde PRV."""
    index: int
    name: str
    junctions: list[str]
    inlet_junction: str
    feed: str
    reservoir: str | None = None
    parent: str | None = None   # basınç pilotunun alt bölgelerinde bağlı olduğu DMA'nın adı


@dataclass
class Twin:
    """Simülasyona hazır şebeke ve dışa aktarım için gereken yan bilgiler."""
    wn: wntr.network.WaterNetworkModel
    junctions: list[str]
    osm_id: dict[str, int]
    lonlat: dict[str, tuple[float, float]]
    elevation: dict[str, float]
    dma_of: dict[str, int]
    dmas: list[Dma]
    consumer_base: dict[str, float]          # m³/s, örüntü çarpanı 1 iken
    pattern: list[float]                     # adım başına çarpan, ortalaması 1
    pipe_geometry: dict[str, object]          # boru -> LineString (lon/lat)
    pipe_highway: dict[str, str]
    boundary_pipes: set[str] = field(default_factory=set)
    fixed_pipes: set[str] = field(default_factory=set)   # boyutlandırılmayan borular (servis, iletim)
    leak_coef: dict[str, float] = field(default_factory=dict)
    supply: object | None = None             # arz tarafı modellendiyse supply.Supply

    @property
    def steps(self) -> int:
        return len(self.pattern)

    @property
    def step_s(self) -> int:
        return 86400 // self.steps

    @property
    def step_h(self) -> float:
        return 24.0 / self.steps

    @property
    def peak_time_s(self) -> int:
        return int(np.argmax(self.pattern)) * self.step_s

    def hour_of_step(self) -> np.ndarray:
        return (np.arange(self.steps) * self.step_h).astype(int)

    def feed_links(self) -> set[str]:
        return {d.feed for d in self.dmas}

    def distribution_pipes(self) -> list[str]:
        """Boyutlandırılabilen, açık dağıtım boruları (giriş, sınır, servis ve iletim boruları hariç)."""
        skip = self.feed_links() | self.boundary_pipes | self.fixed_pipes
        return [p for p in self.wn.pipe_name_list if p not in skip]


def normalized_pattern(raw: list[float], steps: int = 24) -> list[float]:
    """Saatlik örüntüyü istenen adım sayısına periyodik doğrusal aradeğerlemeyle taşır, ortalamayı 1 yapar."""
    arr = np.asarray(raw, dtype=float)
    if steps != len(arr):
        x_new = np.arange(steps) * len(arr) / steps
        arr = np.interp(x_new, np.arange(len(arr)), arr, period=len(arr))
    return list(arr / arr.mean())


def set_time_options(wn: wntr.network.WaterNetworkModel, steps: int) -> None:
    step_s = 86400 // steps
    wn.options.time.duration = (steps - 1) * step_s
    wn.options.time.hydraulic_timestep = step_s
    wn.options.time.pattern_timestep = step_s
    wn.options.time.report_timestep = step_s


def partition_dmas(graph: nx.Graph, nodes: list, xy: np.ndarray, elev: np.ndarray,
                   nodes_per_dma: int = NODES_PER_DMA, elev_weight: float = ELEV_WEIGHT,
                   max_spread: float = MAX_DMA_ELEV_SPREAD_M) -> np.ndarray:
    """Şebekeyi bağlı ve kot olarak benzer bölgelere (DMA) ayırır. Etiketler batıdan doğuya sıralıdır.

    Kot farkı `max_spread` metreyi aşan bölgeler ikiye bölünmeye devam eder; böylece hiçbir
    bölgede statik basınç aşırı yükselmez, düz bölgeler ise gereksiz yere parçalanmaz.
    """
    n = len(nodes)
    k = max(1, round(n / nodes_per_dma))
    X = np.column_stack([xy[:, 0], xy[:, 1], elev * elev_weight])
    A = nx.to_scipy_sparse_array(graph, nodelist=nodes, format="csr")
    labels = np.zeros(n, dtype=int)
    if k > 1:
        labels = AgglomerativeClustering(n_clusters=k, connectivity=A, linkage="ward").fit_predict(X)
    labels = _split_steep(A, X, elev, labels, max_spread)
    labels = _merge_small(graph, nodes, labels, elev, max_spread)
    order = sorted(set(labels), key=lambda c: xy[labels == c, 0].mean())
    remap = {old: new for new, old in enumerate(order)}
    return np.array([remap[c] for c in labels])


def _split_steep(A, X: np.ndarray, elev: np.ndarray, labels: np.ndarray, max_spread: float,
                 min_size: int = 20) -> np.ndarray:
    """Kot farkı sınırı aşan her bölgeyi, bağlılığı koruyarak ikiye böler; sınır sağlanana kadar tekrarlar."""
    labels = labels.copy()
    next_label = int(labels.max()) + 1
    queue = list(set(int(c) for c in labels))
    while queue:
        c = queue.pop()
        idx = np.where(labels == c)[0]
        if len(idx) < min_size or np.ptp(elev[idx]) <= max_spread:
            continue
        sub = A[idx][:, idx]
        n_comp, _ = connected_components(sub, directed=False)
        if n_comp != 1:
            continue
        halves = AgglomerativeClustering(n_clusters=2, connectivity=sub, linkage="ward").fit_predict(X[idx])
        labels[idx[halves == 1]] = next_label
        queue += [c, next_label]
        next_label += 1
    return labels


def _merge_small(graph: nx.Graph, nodes: list, labels: np.ndarray, elev: np.ndarray,
                 max_spread: float) -> np.ndarray:
    """MIN_DMA_NODES'tan küçük bölgeleri en çok sınır paylaştıkları komşuya katar.

    Birleşme komşunun kot farkını `max_spread` üstüne çıkaracaksa küçük bölge kendi başına kalır
    (sahada basınç düşürücü vanalı küçük bir bölgeye karşılık gelir).
    """
    labels = labels.copy()
    pos = {n: i for i, n in enumerate(nodes)}
    kept: set[int] = set()
    while True:
        sizes = {c: int((labels == c).sum()) for c in set(labels)}
        small = [c for c, s in sizes.items() if s < MIN_DMA_NODES and c not in kept]
        if not small or len(sizes) == 1:
            return labels
        c = min(small, key=lambda s: sizes[s])
        shared: dict[int, int] = {}
        for i in np.where(labels == c)[0]:
            for nb in graph.neighbors(nodes[i]):
                lc = labels[pos[nb]]
                if lc != c:
                    shared[lc] = shared.get(lc, 0) + 1
        spread_with = {lc: np.ptp(elev[(labels == c) | (labels == lc)]) for lc in shared}
        ok = {lc: s for lc, s in shared.items() if spread_with[lc] <= max_spread}
        if ok:
            labels[labels == c] = max(ok, key=ok.get)
        elif sizes[c] < 5 and min(spread_with.values()) <= 1.5 * max_spread:
            # Birkaç düğümlük bölge çoğunlukla kot verisindeki küçük bir sapmadır; en az zarar veren komşuya kat
            labels[labels == c] = min(spread_with, key=spread_with.get)
        else:
            # Gerçek bir vadi ya da tepe: sahada basınç düşürücü vanalı küçük bir bölge olur
            kept.add(c)


def build_model(graph: nx.Graph, lonlat: dict, xy: dict, elev: dict, consumer_m3s: dict,
                pattern_raw: list[float], nodes_per_dma: int = NODES_PER_DMA,
                max_spread: float = MAX_DMA_ELEV_SPREAD_M, roughness: float = HAZEN_WILLIAMS_C,
                step_minutes: int = 60, pipe_roughness: dict | None = None) -> Twin:
    """OSM düğüm kimlikli grafikten WNTR modeli kurar. xy UTM metre, consumer_m3s düğüm başı taban talep.

    pipe_roughness: (u, v) kenarı -> Hazen-Williams C; verilmeyen borular `roughness` alır.
    """
    nodes = list(graph.nodes)
    xy_arr = np.array([xy[n] for n in nodes])
    z_arr = np.array([elev[n] for n in nodes])
    labels = partition_dmas(graph, nodes, xy_arr, z_arr, nodes_per_dma, max_spread=max_spread)

    steps = 1440 // step_minutes
    pattern = normalized_pattern(pattern_raw, steps)
    wn = wntr.network.WaterNetworkModel()
    set_time_options(wn, steps)
    wn.options.hydraulic.headloss = "H-W"
    wn.options.hydraulic.inpfile_units = "LPS"
    wn.add_pattern("konut", pattern)

    name_of = {n: f"J{i + 1}" for i, n in enumerate(nodes)}
    junctions, osm_id, j_lonlat, j_elev, dma_of, base = [], {}, {}, {}, {}, {}
    for i, n in enumerate(nodes):
        j = name_of[n]
        q = float(consumer_m3s.get(n, 0.0))
        wn.add_junction(j, base_demand=q, demand_pattern="konut", elevation=float(elev[n]),
                        coordinates=tuple(map(float, xy[n])))
        junctions.append(j)
        osm_id[j] = int(n)
        j_lonlat[j] = lonlat[n]
        j_elev[j] = float(elev[n])
        dma_of[j] = int(labels[i])
        base[j] = q

    pipe_geometry, pipe_highway, boundary = {}, {}, set()
    for k, (u, v, d) in enumerate(graph.edges(data=True)):
        p = f"P{k + 1}"
        dia = HIGHWAY_DIAMETER_MM.get(d["highway"], DEFAULT_DIAMETER_MM) / 1000.0
        c = (pipe_roughness or {}).get((u, v), (pipe_roughness or {}).get((v, u), roughness))
        wn.add_pipe(p, name_of[u], name_of[v], length=float(d["length"]), diameter=dia, roughness=c)
        if dma_of[name_of[u]] != dma_of[name_of[v]]:
            wn.get_link(p).initial_status = LinkStatus.Closed
            boundary.add(p)
        pipe_geometry[p] = d["geometry"]
        pipe_highway[p] = d["highway"]

    dmas = []
    for c in sorted({int(label) for label in labels}):
        members = [j for j in junctions if dma_of[j] == c]
        inlet = max(members, key=lambda j: j_elev[j])
        r, ip = f"R-DMA{c + 1:02d}", f"GIRIS-DMA{c + 1:02d}"
        ix, iy = wn.get_node(inlet).coordinates
        wn.add_reservoir(r, base_head=j_elev[inlet] + TARGET_CRITICAL_PRESSURE_M + 10.0,
                         coordinates=(ix + INLET_PIPE_LENGTH_M, iy))
        wn.add_pipe(ip, r, inlet, length=INLET_PIPE_LENGTH_M, diameter=INLET_PIPE_DIAMETER_M,
                    roughness=HAZEN_WILLIAMS_C)
        dmas.append(Dma(c, f"DMA-{c + 1:02d}", members, inlet, ip, reservoir=r))

    return Twin(wn=wn, junctions=junctions, osm_id=osm_id, lonlat=j_lonlat, elevation=j_elev,
                dma_of=dma_of, dmas=dmas, consumer_base=base, pattern=pattern,
                pipe_geometry=pipe_geometry, pipe_highway=pipe_highway, boundary_pipes=boundary)


def simulate(twin: Twin):
    """Bir günlük genişletilmiş süre simülasyonu (EPANET)."""
    with tempfile.TemporaryDirectory() as tmp:
        return wntr.sim.EpanetSimulator(twin.wn).run_sim(file_prefix=str(Path(tmp) / "sim"))


def get_feed_setting(twin: Twin, d: Dma) -> float:
    """Rezervuarlı girişte enerji kotu (m), PRV'de çıkış basıncı (m)."""
    if d.reservoir:
        return float(twin.wn.get_node(d.reservoir).base_head)
    return float(twin.wn.get_link(d.feed).initial_setting)


def set_feed_setting(twin: Twin, d: Dma, value: float) -> None:
    if d.reservoir:
        twin.wn.get_node(d.reservoir).base_head = value
    else:
        twin.wn.get_link(d.feed).initial_setting = max(0.0, value)


def tune_heads(twin: Twin, res, target: float = TARGET_CRITICAL_PRESSURE_M) -> float:
    """Her bölgenin beslemesini, kritik düğüm günün en kötü anında hedef basıncı görecek şekilde ayarlar.

    Sabit çıkışlı basınç düşürücü vana ile basınç yönetimine karşılık gelir. En büyük düzeltmeyi (m) döndürür.
    """
    p_min = res.node["pressure"].min(axis=0)
    worst = 0.0
    for d in twin.dmas:
        delta = target - float(p_min[d.junctions].min())
        set_feed_setting(twin, d, get_feed_setting(twin, d) + delta)
        worst = max(worst, abs(delta))
    return worst


def _next_size_mm(required_mm: float) -> int | None:
    for s in PIPE_SIZES_MM:
        if s >= required_mm - 1e-6:
            return s
    return None


def size_pipes(twin: Twin, max_velocity: float = MAX_VELOCITY_MS, max_headloss: float = MAX_HEADLOSS_M_PER_KM,
               log=print) -> None:
    """Tepe anında hız ve yük kaybı sınırlarını aşan boruları büyütür, bölge beslemelerini ayarlar."""
    t_peak = twin.peak_time_s
    pipes = twin.distribution_pipes()
    for it in range(SIZING_ITERATIONS):
        res = simulate(twin)
        head = res.node["head"].loc[t_peak]
        flow = res.link["flowrate"].loc[t_peak].abs()
        changed = 0
        for p in pipes:
            pipe = twin.wn.get_link(p)
            d_mm = pipe.diameter * 1000.0
            q = float(flow[p])
            if q <= 0:
                continue
            req_v = math.sqrt(4.0 * q / (math.pi * max_velocity)) * 1000.0
            grad = abs(head[pipe.start_node_name] - head[pipe.end_node_name]) / pipe.length * 1000.0
            req_h = d_mm * (grad / max_headloss) ** (1 / 4.87) if grad > max_headloss else 0.0
            need = max(req_v, req_h)
            if need > d_mm + 1:
                new = _next_size_mm(need) or PIPE_SIZES_MM[-1]
                if new > d_mm + 1:
                    pipe.diameter = new / 1000.0
                    changed += 1
        moved = tune_heads(twin, res)
        log(f"  boyutlandırma {it + 1}: {changed} boru büyütüldü, giriş basıncı düzeltmesi {moved:.1f} m")
        if changed == 0 and moved < 0.5:
            break


def node_leak_lengths(twin: Twin) -> dict[str, float]:
    """Her düğüme bağlı dağıtım borusu uzunluğunun yarısı (besleme ve iletim boruları hariç)."""
    skip = twin.feed_links() | (twin.fixed_pipes - getattr(twin, "service_pipes", set()))
    lengths = {j: 0.0 for j in twin.junctions}
    for p in twin.wn.pipe_name_list:
        if p in skip:
            continue
        pipe = twin.wn.get_link(p)
        for n in (pipe.start_node_name, pipe.end_node_name):
            if n in lengths:
                lengths[n] += pipe.length / 2.0
    return lengths


def calibrate_leakage(twin: Twin, res, share: float = LEAK_SHARE, exponent: float = LEAK_EXPONENT,
                      node_weights: dict[str, float] | None = None) -> None:
    """Basınca bağlı arka plan kaçağını (EPANET emitter) günlük ortalama kaçak payı `share` olacak şekilde dağıtır.

    node_weights: düğüm başına göreli kaçak ağırlığı (verilmezse bağlı boru uzunluğu).
    """
    if share <= 0:
        return
    P = res.node["pressure"][twin.junctions].clip(lower=0.0).to_numpy()
    weights_raw = node_weights or node_leak_lengths(twin)
    L = np.array([weights_raw.get(j, 0.0) for j in twin.junctions])
    consumer_avg = sum(twin.consumer_base.values()) * float(np.mean(twin.pattern))
    target = share / (1.0 - share) * consumer_avg
    weights = L * (P ** exponent).mean(axis=0)
    k = target / weights.sum()
    twin.wn.options.hydraulic.emitter_exponent = exponent
    twin.leak_coef = {}
    for j, l in zip(twin.junctions, L):
        c = float(k * l)
        twin.wn.get_node(j).emitter_coefficient = c
        twin.leak_coef[j] = c


def finalize(twin: Twin, leak_share: float = LEAK_SHARE, max_velocity: float = MAX_VELOCITY_MS,
             max_headloss: float = MAX_HEADLOSS_M_PER_KM, node_weights: dict[str, float] | None = None, log=print):
    """Boyutlandırma + kaçak kalibrasyonu + son basınç ayarı; son simülasyon sonucunu döndürür."""
    size_pipes(twin, max_velocity=max_velocity, max_headloss=max_headloss, log=log)
    res = simulate(twin)
    for _ in range(2):
        calibrate_leakage(twin, res, share=leak_share, node_weights=node_weights)
        res = simulate(twin)
        tune_heads(twin, res)
        res = simulate(twin)
    p_peak = res.node["pressure"].loc[twin.peak_time_s][twin.junctions]
    low = int((p_peak < MIN_SERVICE_PRESSURE_M).sum())
    log(f"  tepe anında {MIN_SERVICE_PRESSURE_M:.0f} m altı düğüm: {low}")
    return res


def copy_hydraulic_options(src: wntr.network.WaterNetworkModel, dst: wntr.network.WaterNetworkModel) -> None:
    """Alt modellerin tam modelle aynı sonucu vermesi için hidrolik seçenekleri taşır.

    INP birimi önemli: WNTR emitter (kaçak) katsayısını EPANET'e yazarken üssü 0,5 varsayarak çevirir; LPS'de
    basınç metre olduğu için çeviri etkisizdir, ABD birimlerinde ise üs 1,0 iken kaçak %20'ye yakın şişer.
    """
    h, g = src.options.hydraulic, dst.options.hydraulic
    for k in ("headloss", "inpfile_units", "emitter_exponent", "accuracy", "trials", "viscosity", "specific_gravity"):
        setattr(g, k, getattr(h, k))


def dma_twin(twin: Twin, d: Dma, head_m: float | None = None) -> Twin:
    """Bir DMA'nın tek başına modeli (iç borular, kaçak katsayıları, giriş rezervuarı ve borusu).

    Sınır boruları kapalı ve giriş sabit kotlu olduğu için bölge diğerlerinden hidrolik olarak bağımsızdır:
    alt modelin sonucu tam modeldekiyle aynıdır, ama çözümü çok daha hızlıdır. Talep örüntüsü boş gelir.
    """
    if not d.reservoir:
        raise ValueError(f"{d.name} rezervuarla beslenmiyor; alt model yalnız ana DMA'lar için")
    src = twin.wn
    wn = wntr.network.WaterNetworkModel()
    set_time_options(wn, twin.steps)
    copy_hydraulic_options(src, wn)
    members = set(d.junctions)
    for j in d.junctions:
        n = src.get_node(j)
        wn.add_junction(j, base_demand=0.0, elevation=n.elevation, coordinates=n.coordinates)
        wn.get_node(j).emitter_coefficient = twin.leak_coef.get(j, 0.0)
    r = src.get_node(d.reservoir)
    wn.add_reservoir(d.reservoir, base_head=float(r.base_head if head_m is None else head_m), coordinates=r.coordinates)
    for p in src.pipe_name_list:
        pipe = src.get_link(p)
        u, v = pipe.start_node_name, pipe.end_node_name
        if p == d.feed or (u in members and v in members and p not in twin.boundary_pipes):
            wn.add_pipe(p, u, v, length=pipe.length, diameter=pipe.diameter, roughness=pipe.roughness,
                        minor_loss=pipe.minor_loss, initial_status=pipe.initial_status)
    J = list(d.junctions)
    return Twin(wn=wn, junctions=J, osm_id={j: twin.osm_id[j] for j in J}, lonlat={j: twin.lonlat[j] for j in J},
                elevation={j: twin.elevation[j] for j in J}, dma_of={j: d.index for j in J},
                dmas=[Dma(d.index, d.name, J, d.inlet_junction, d.feed, reservoir=d.reservoir)],
                consumer_base={j: twin.consumer_base.get(j, 0.0) for j in J}, pattern=list(twin.pattern),
                pipe_geometry={}, pipe_highway={}, leak_coef={j: twin.leak_coef.get(j, 0.0) for j in J})
