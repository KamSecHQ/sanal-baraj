"""Basınç pilotu: kaçağı düşürmek için basınç düşürücü vana (PRV) yerlerini önerir ve etkisini simüle eder.

M1'in bulgusu: depo zamanlaması kaçağı az düşürür, çünkü DMA'lardaki fazla basıncın çoğu kot
farkından gelir. Bunu çözmenin yolu, dik DMA'ların alçak kısımlarını kendi PRV'siyle beslenen
alt bölgelere ayırmaktır. Her alt bölgenin kritik düğümü hedef basıncı görecek şekilde ayarlanır.

Pilot önce her DMA'yı kot farkı küçük alt bölgelere böler (aday vanalar) ve her adayın günlük kaçak
kazancını basınç sensörü verisinden (simülasyonda düğüm basınçlarından) tahmin eder. Bu, her binadaki
sensörün sağladığı yoğun basınç haritası olmadan yapılamaz: kritik düğümün yerini ve fazla basıncın nerede
biriktiğini o harita gösterir.

Tahmin tek başına yetmez: alt bölgenin sınır boruları kapanınca ana bölgenin suyu daha uzun yoldan gider,
giriş kotu yükselir, hem basma enerjisi hem ana bölgedeki kaçak artabilir (Bayrampaşa DMA-03'te giriş kotu
80 m yükseliyordu). Bu yüzden her aday, DMA'nın tek başına modelinde (`network.dma_twin`) gün boyu simüle
edilir ve net değeriyle seçilir:

    net (TL/gün) = kaçak azalması × suyun değeri − basma enerjisi maliyetindeki artış

Basma maliyeti azalan kaçağın enerjisini de içerir. Aynı DMA'daki adaylar sırayla eklenir; her birinin
değeri öncekiler kurulmuşken ölçülür (marjinal). Net değeri pozitif olmayan aday alınmaz.

Seçilen her alt bölge, ana bölgeyle arasındaki bir sınır borusuna paralel konan bir PRV'den beslenir;
diğer sınır boruları kapanır. Su ana bölgenin girişinden geçtiği için enerji hesabı kendiliğinden doğrudur.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import networkx as nx
import numpy as np
from wntr.network import LinkStatus

from .config import (
    MIN_SERVICE_PRESSURE_M, PILOT_MAX_PRVS, PILOT_MIN_NET_TL_D, SUBZONE_ELEV_SPREAD_M, TARGET_CRITICAL_PRESSURE_M,
    UTILITY_PUMP_EFFICIENCY, WATER_VALUE_TL_M3,
)
from .network import Dma, Twin, dma_twin, get_feed_setting, partition_dmas, simulate, tune_heads
from .scenario import apply_demands, step_prices


@dataclass
class ZoneCandidate:
    dma: str               # ana DMA adı
    zone: list[str]        # alt bölgenin düğümleri
    inlet: str             # bölgenin en yüksek (kritik) düğümü
    excess_m: float        # günün en kötü anında bile atılabilecek fazla basınç
    saving_m3d: float      # tahmini günlük kaçak kazancı (sıralama için; seçim simülasyonla)
    value: ZoneValue | None = None   # alt modelde ölçülen marjinal etki


@dataclass
class ZoneValue:
    """Bir adayın simülasyonla ölçülen marjinal etkisi (aynı DMA'da önceki seçilenler kurulmuşken)."""
    leak_m3d: float        # kaçak azalması (+ iyi)
    energy_kwh_d: float    # basma enerjisi değişimi (+ kötü)
    cost_tl_d: float       # basma maliyeti değişimi (+ kötü)
    head_m: float          # ana bölgenin giriş kotu değişimi
    net_tl_d: float        # kaçak değeri − maliyet değişimi
    ok: bool               # hizmet basıncı korunuyor mu


def _dma_graph(twin: Twin, members: list[str]) -> nx.Graph:
    member_set = set(members)
    skip = twin.feed_links()
    G = nx.Graph()
    G.add_nodes_from(members)
    for p in twin.wn.pipe_name_list:
        if p in skip or p in twin.boundary_pipes:
            continue
        pipe = twin.wn.get_link(p)
        u, v = pipe.start_node_name, pipe.end_node_name
        if u in member_set and v in member_set:
            G.add_edge(u, v, name=p)
    return G


def candidate_zones(twin: Twin, res, max_spread: float = SUBZONE_ELEV_SPREAD_M,
                    target: float = TARGET_CRITICAL_PRESSURE_M) -> list[ZoneCandidate]:
    """Her dik DMA için aday alt bölgeler; tahmini kaçak kazancına göre azalan sırada."""
    P = res.node["pressure"]
    n_exp = float(twin.wn.options.hydraulic.emitter_exponent)
    out: list[ZoneCandidate] = []
    for d in twin.dmas:
        members = d.junctions
        z = np.array([twin.elevation[j] for j in members])
        if len(members) < 20 or np.ptp(z) <= max_spread:
            continue
        G = _dma_graph(twin, members)
        if not nx.is_connected(G):
            continue
        xy = np.array([twin.wn.get_node(j).coordinates for j in members])
        labels = partition_dmas(G, members, xy, z, nodes_per_dma=10**9, max_spread=max_spread)
        label_of = dict(zip(members, labels))
        main = label_of[d.inlet_junction]
        for lab in set(labels):
            if lab == main:
                continue
            zone = [j for j in members if label_of[j] == lab]
            p = P[zone].to_numpy()[:twin.steps]
            excess = float(p.min() - target)
            if excess <= 0.5:
                continue
            C = np.array([twin.leak_coef.get(j, 0.0) for j in zone])
            pos = np.clip(p, 0, None)
            saving = float((C * (pos ** n_exp - np.clip(p - excess, 0, None) ** n_exp)).sum() * twin.step_s)
            out.append(ZoneCandidate(d.name, zone, max(zone, key=lambda j: twin.elevation[j]), excess, saving))
    out.sort(key=lambda c: c.saving_m3d, reverse=True)
    return out


def zones_feasible(G: nx.Graph, members: list[str], zones: list[list[str]]) -> bool:
    """Alt bölgeler ayrıldıktan sonra ana bölge bağlı kalıyor ve her alt bölge ana bölgeye doğrudan değiyor mu?

    Her alt bölgenin vanası ana bölgeyle arasındaki bir sınır borusuna konur; başka bir alt bölgenin
    arkasında kalan bölge beslenemez.
    """
    removed = {j for z in zones for j in z}
    remaining = {j for j in members if j not in removed}
    if not remaining or not nx.is_connected(G.subgraph(remaining)):
        return False
    return all(any(v in remaining for u in z for v in G.neighbors(u)) for z in zones)


@dataclass
class _Run:
    leak_m3d: float
    energy_kwh_d: float
    cost_tl_d: float
    head_m: float
    p_min: float


def _simulate_dma(sub: Twin, zones: list[ZoneCandidate], demand: np.ndarray, prices: np.ndarray) -> _Run:
    """DMA alt modelinde seçili alt bölgelerle bir gün: kaçak, basma enerjisi ve maliyeti (pipeline ile aynı tanımlar)."""
    tw, _ = apply_zones(sub, zones)
    apply_demands(tw, demand)
    res = simulate(tw)
    for _ in range(3):
        if tune_heads(tw, res) < 0.2:
            break
        res = simulate(tw)
    T, dt = tw.steps, tw.step_h
    parent = tw.dmas[0]
    P = res.node["pressure"][tw.junctions].to_numpy()[:T]
    got = res.node["demand"][tw.junctions].to_numpy()[:T]
    leak = float(np.clip(got - demand, 0.0, None).sum() * tw.step_s)
    q_in = -res.node["demand"][parent.reservoir].to_numpy()[:T]
    head = get_feed_setting(tw, parent)
    kw = 9.81 * q_in * head / UTILITY_PUMP_EFFICIENCY
    return _Run(leak, float(kw.sum() * dt), float((kw * prices).sum() * dt), head, float(P.min()))


def evaluate(twin: Twin, candidates: list[ZoneCandidate], demand: np.ndarray, settings: dict[str, float],
             water_value: float = WATER_VALUE_TL_M3, min_net: float = PILOT_MIN_NET_TL_D,
             log=print) -> dict[str, list[ZoneCandidate]]:
    """Adayları DMA başına sırayla simüle eder; her DMA için kabul edilenleri kabul sırasıyla döndürür.

    demand: senaryonun [T, N] talebi (m³/s, kaçak hariç); settings: senaryonun bölge besleme ayarları.
    Her adaya `value` yazılır (kabul edilmese de).
    """
    col = {j: i for i, j in enumerate(twin.junctions)}
    prices = step_prices(twin.steps)
    by_dma: dict[str, list[ZoneCandidate]] = {}
    for c in candidates:
        by_dma.setdefault(c.dma, []).append(c)
    dmas = {d.name: d for d in twin.dmas}
    accepted: dict[str, list[ZoneCandidate]] = {}
    for name, cands in by_dma.items():
        d = dmas[name]
        sub = dma_twin(twin, d, settings[name])
        D = demand[:, [col[j] for j in d.junctions]]
        G = _dma_graph(sub, d.junctions)
        cur = _simulate_dma(sub, [], D, prices)
        taken: list[ZoneCandidate] = []
        for c in cands:
            if not zones_feasible(G, d.junctions, [z.zone for z in taken] + [c.zone]):
                continue
            r = _simulate_dma(sub, taken + [c], D, prices)
            saved = cur.leak_m3d - r.leak_m3d
            dcost = r.cost_tl_d - cur.cost_tl_d
            c.value = ZoneValue(leak_m3d=saved, energy_kwh_d=r.energy_kwh_d - cur.energy_kwh_d, cost_tl_d=dcost,
                                head_m=r.head_m - cur.head_m, net_tl_d=saved * water_value - dcost,
                                ok=r.p_min >= MIN_SERVICE_PRESSURE_M - 0.5)
            if c.value.ok and c.value.net_tl_d > min_net:
                taken.append(c)
                cur = r
        if taken:
            accepted[name] = taken
    return accepted


def merge(accepted: dict[str, list[ZoneCandidate]], max_prvs: int = PILOT_MAX_PRVS) -> list[ZoneCandidate]:
    """DMA'ların kabul listelerinden en değerli olanları seçer. Her DMA'dan kabul sırasının başı alınır,
    çünkü sonraki adayın değeri öncekiler kurulmuşken ölçüldü."""
    queues = {k: list(v) for k, v in accepted.items()}
    out: list[ZoneCandidate] = []
    while len(out) < max_prvs:
        heads = [(q[0].value.net_tl_d, k) for k, q in queues.items() if q]
        if not heads:
            break
        _, k = max(heads)
        out.append(queues[k].pop(0))
    return out


@dataclass
class Prv:
    name: str                       # alt bölge adı, ör. DMA-12/2
    parent: str
    junction: str                   # vananın beslediği düğüm
    lonlat: tuple[float, float]
    saving_m3d: float
    excess_m: float
    rank: int
    net_tl_d: float = 0.0          # simülasyonla ölçülen net kazanç
    cost_tl_d: float = 0.0         # basma maliyeti değişimi (+ artış)
    head_m: float = 0.0            # ana bölge giriş kotu değişimi


def apply_zones(twin: Twin, chosen: list[ZoneCandidate],
                target: float = TARGET_CRITICAL_PRESSURE_M) -> tuple[Twin, list[Prv]]:
    """Twin'in kopyasında seçilen alt bölgeleri PRV'li ayrı bölgelere dönüştürür."""
    tw = copy.deepcopy(twin)
    by_dma: dict[str, list[ZoneCandidate]] = {}
    for c in chosen:
        by_dma.setdefault(c.dma, []).append(c)
    rank = {id(c): i + 1 for i, c in enumerate(chosen)}

    new_dmas: list[Dma] = []
    prvs: list[Prv] = []
    for d in twin.dmas:
        zones = by_dma.get(d.name, [])
        if not zones:
            new_dmas.append(copy.copy(d))
            continue
        label_of = {j: 0 for j in d.junctions}
        for k, c in enumerate(zones, start=1):
            for j in c.zone:
                label_of[j] = k
        G = _dma_graph(twin, d.junctions)
        crossings: dict[int, list[tuple[str, str, str]]] = {}
        for u, v, data in G.edges(data=True):
            if label_of[u] != label_of[v]:
                tw.wn.get_link(data["name"]).initial_status = LinkStatus.Closed
                tw.boundary_pipes.add(data["name"])
                for a, b in ((u, v), (v, u)):
                    if label_of[a] == 0 and label_of[b] > 0:
                        crossings.setdefault(label_of[b], []).append((a, b, data["name"]))
        new_dmas.append(Dma(d.index, d.name, [j for j in d.junctions if label_of[j] == 0],
                            d.inlet_junction, d.feed, reservoir=d.reservoir))
        for k, c in enumerate(zones, start=1):
            # Vanayı ana bölgeden gelen en büyük çaplı sınır borusuna paralel koy
            up, down, pipe = max(crossings[k], key=lambda e: (tw.wn.get_link(e[2]).diameter,
                                                               twin.elevation[e[1]]))
            setting = target + max(0.0, twin.elevation[c.inlet] - twin.elevation[down]) + 2.0
            vname, name = f"PRV-{d.name}-{k}", f"{d.name}/{k + 1}"
            tw.wn.add_valve(vname, up, down, diameter=tw.wn.get_link(pipe).diameter, valve_type="PRV",
                            minor_loss=0.0, initial_setting=setting)
            new_dmas.append(Dma(d.index, name, c.zone, down, vname, parent=d.name))
            v = c.value
            prvs.append(Prv(name, d.name, down, twin.lonlat[down], v.leak_m3d if v else c.saving_m3d, c.excess_m,
                            rank[id(c)], v.net_tl_d if v else 0.0, v.cost_tl_d if v else 0.0, v.head_m if v else 0.0))
    tw.dmas = new_dmas
    return tw, prvs


def savings_curve(candidates: list[ZoneCandidate]) -> list[float]:
    """İlk k vananın toplam günlük kaçak kazancı (k = 1..n); simüle edilmişse ölçülen, değilse tahmin."""
    return list(np.cumsum([c.value.leak_m3d if c.value else c.saving_m3d for c in candidates]))


def net_curve(candidates: list[ZoneCandidate]) -> list[float]:
    """İlk k vananın toplam net kazancı (TL/gün)."""
    return list(np.cumsum([c.value.net_tl_d for c in candidates if c.value]))
