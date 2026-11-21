"""Deprem günü: şebeke kırılınca bina depolarındaki temiz su.

Senaryo İBB'nin 2019 deprem kayıp tahmininden (7,5 Mw gece depremi): her mahalle için öngörülen içme suyu borusu
hasarı, mahallenin borularına uzunlukla orantılı ve sabit tohumla dağıtılır (mahalle eşlemesi yoksa ilçe toplamı
bütün borulara). HAZUS'a göre hasarın beşte biri kırık (borunun tam kesiti), gerisi sızıntıdır (kesit alanının
%5 kadarı). Her hasar noktası borunun ortasında atmosfere açılan bir uçtur: çek valfli kısa bir boru ve zemin
kotunda bir çıkış. Debi açıklık denklemine uyar, Q = Cd·A·√(2gH).

Şebeke saat saat, basınca bağlı talep (PDD) ile çözülür. Depremden sonra herkes yalnız temel ihtiyaç kadar su
kullanır. Şebeke suyu iki durumda şüpheli sayılır: DMA'da bir hasar noktası varsa (kırılma anındaki basınç dalgası
kırık ve çatlaklardan kirli suyu boruya çekebilir; su test edilene kadar içilemez) ya da DMA'da basınç 14 m'nin
altına inerse (kaynatma uyarısı eşiği). Orkestratör hasarlı DMA'yı sayaçtaki ani debi artışından tanır (en küçük
sızıntı bile birkaç L/s; sızıntı avındaki gibi) ve kitlerin basınç sensörlerinden basınç düşüşünü görür.

- Şamandıralı vana (yapay zekâ kapalı): depo kullanıldıkça şebekeden dolmaya devam eder. Şüpheli bölgede şebekeden
  su alan deponun bütün suyu kirlenme riskindedir.
- Akıllı kit: ivmeölçer sarsıntıyı algılayınca bütün akıllı depoların girişini kapatır; depodaki su temiz kalır.
  Bir saat sonra orkestratör şebeke suyu şüpheli olmayan DMA'larda girişleri açar ve depoları basıncı koruyarak
  tamamlar. Mühürlü bir depo boşalmak üzereyse kit girişi yeniden açar (bina susuz kalmasın); o depo şamandıra gibi
  dolar ve şüpheli su aldığı için kirlenme riskine girer.

Göstergeler: saat saat basınç, kırıklardan kaçan su, susuz kişi, temiz suyu olmayan kişi, depolardaki temiz su
(kişi-gün, 3 L/kişi/gün içme suyu) ve alan (mahalle ya da DMA) başına temiz su.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from wntr.morph import split_pipe

from .config import (
    HAZEN_WILLIAMS_C, MIN_SERVICE_PRESSURE_M, PDD_MINIMUM_PRESSURE_M, PDD_REQUIRED_PRESSURE_M, QUAKE_BREAK_SHARE,
    QUAKE_HEAD_DROP_M, QUAKE_HOUR, QUAKE_LEAK_AREA_FRACTION, QUAKE_ORIFICE_CD, QUAKE_REOPEN_AFTER_H,
    QUAKE_SUSPECT_PRESSURE_M, QUAKE_SUSPECT_SCOPE, QUAKE_USE_LPCD, TANK_INLET_M3H,
)
from .network import Twin, get_feed_setting, set_feed_setting, simulate
from .orchestrator import Plan
from .outage import HOURS, REFILL_STEPS, to_hourly
from .ref import mahalle_key, quake_pipe_damage
from .tanks import NodeStorage

@dataclass
class QuakeAreas:
    """Hasarın dağıtıldığı ve temiz suyun özetlendiği alanlar: mahalleler ya da (eşleşme yoksa) DMA'lar."""
    kind: str                                         # "mahalle" ya da "dma"
    damage: dict[str, int]                            # alan -> İBB boru hasarı (adet)
    pool: int = 0                                     # alana bağlanamayan hasar: bütün borulara dağıtılır
    pipe_area: dict[str, str] = field(default_factory=dict)      # boru -> alan (mahalle türünde)
    building_area: list[str] | None = None            # bina sırasıyla alan (mahalle türünde)
    geometry: dict[str, object] = field(default_factory=dict)    # alan -> lon/lat poligon (mahalle türünde)
    source: str = ""

    @property
    def total(self) -> int:
        return int(sum(self.damage.values()) + self.pool)


@dataclass
class Break:
    pipe: str
    kind: str                    # "kirik" ya da "sizinti"
    area: str
    dma: str
    diameter_mm: float
    opening_mm: float            # eşdeğer açıklık çapı
    lonlat: tuple[float, float]


@dataclass
class QuakeRun:
    key: str
    label: str
    hourly: dict[str, np.ndarray]
    daily: dict[str, float]
    node_pressure: np.ndarray            # [24, N] bütün düğümler, saat sonunda
    break_lps: np.ndarray                # [24, k] her hasar noktasından çıkan su
    suspect_hour: dict[str, int]         # DMA -> şebeke suyunun şüpheli sayıldığı ilk saat
    reopen_hour: dict[str, int]          # DMA -> akıllı depo girişlerinin yeniden açıldığı saat
    risk_hour: np.ndarray                # [bina] deposunun kirlenme riskine girdiği saat, -1 = hiç
    area_clean_m3: dict[str, np.ndarray] # alan -> [24] saat sonunda depolardaki temiz su


@dataclass
class QuakeStudy:
    hour: int
    areas: QuakeAreas
    area_names: list[str]
    building_area: np.ndarray            # [bina] alan adı
    breaks: list[Break]
    runs: dict[str, QuakeRun]


# --- Alanlar -----------------------------------------------------------------------

def _display(name: str) -> str:
    return name.replace(" Mahallesi", "").strip()


def build_areas(twin: Twin, buildings: pd.DataFrame, ilce: str, mahalle: str | None = None,
                hoods: gpd.GeoDataFrame | None = None, boundary=None, utm=None, log=print) -> QuakeAreas | None:
    """İBB hasar tablosunu ilçenin borularına bağlar.

    mahalle verilirse bütün bölge o mahalledir. Aksi halde OSM mahalle sınırları (hoods) kullanılır: alanının en
    az yarısı ilçe içinde kalan mahalleler alınır, ilçe sınırına kırpılır; bina ve borular en yakın mahalleye
    bağlanır. Sınır ya da eşleşme yoksa ilçe toplamı bütün borulara dağıtılır ve alanlar DMA'lardır.
    """
    damage = quake_pipe_damage(ilce)
    if not damage:
        log("  deprem günü: İBB hasar tablosunda bu ilçe yok, atlanıyor")
        return None
    if mahalle:
        key = mahalle_key(mahalle)
        if key not in damage:
            return QuakeAreas("dma", {}, pool=sum(damage.values()), source=f"{ilce} ilçe toplamı (mahalle eşleşmedi)")
        name = _display(mahalle)
        return QuakeAreas("mahalle", {name: damage[key]}, pipe_area={p: name for p in twin.pipe_geometry},
                          building_area=[name] * len(buildings),
                          geometry={name: boundary} if boundary is not None else {},
                          source="İBB 2019 deprem senaryosu, mahalle")
    if hoods is None or hoods.empty or boundary is None or utm is None:
        return QuakeAreas("dma", {}, pool=sum(damage.values()), source="İBB 2019 deprem senaryosu, ilçe toplamı")

    poly = gpd.GeoSeries([boundary], crs=4326).to_crs(utm).iloc[0]
    hu = hoods.to_crs(utm)
    keep = []
    for i, row in hu.iterrows():
        area = row.geometry.area
        if area > 0 and row.geometry.intersection(poly).area >= 0.5 * area and mahalle_key(str(row["mahalle"])) in damage:
            keep.append(i)
    if not keep:
        return QuakeAreas("dma", {}, pool=sum(damage.values()), source="İBB 2019 deprem senaryosu, ilçe toplamı")
    hu = hu.loc[keep].copy()
    hu["geometry"] = hu.geometry.intersection(poly)
    hu["name"] = [_display(str(m)) for m in hu["mahalle"]]
    hu = hu.reset_index(drop=True)

    pts = gpd.GeoDataFrame(geometry=[Point(x, y) for x, y in zip(buildings["cx"], buildings["cy"])], crs=utm)
    b_area = gpd.sjoin_nearest(pts, hu[["name", "geometry"]], how="left").groupby(level=0)["name"].first()
    pipes = list(twin.pipe_geometry)
    mids = gpd.GeoSeries([twin.pipe_geometry[p].interpolate(0.5, normalized=True) for p in pipes], crs=4326).to_crs(utm)
    p_area = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=mids), hu[["name", "geometry"]], how="left") \
        .groupby(level=0)["name"].first()

    by_key = {mahalle_key(n): n for n in hu["name"]}
    dmg = {by_key[k]: v for k, v in damage.items() if k in by_key}
    pool = sum(v for k, v in damage.items() if k not in by_key)
    geom = gpd.GeoSeries(hu.geometry.values, crs=utm).to_crs(4326).simplify(0.00004)
    log(f"  deprem günü: {len(dmg)} mahalle eşlendi, {sum(dmg.values())} hasar mahalleye, {pool} hasar ilçe geneline")
    return QuakeAreas("mahalle", dmg, pool=pool, pipe_area=dict(zip(pipes, p_area.reindex(range(len(pipes))))),
                      building_area=list(b_area.reindex(range(len(buildings)))),
                      geometry=dict(zip(hu["name"], geom)), source="İBB 2019 deprem senaryosu, mahalle")


# --- Hasar noktaları ------------------------------------------------------------------

def _dma_names(twin: Twin) -> dict[int, str]:
    return {d.index: d.name for d in twin.dmas}


def _text(x) -> str | None:
    """Boş ya da NaN alan adını None yapar."""
    return x if isinstance(x, str) and x else None


def place_breaks(twin: Twin, areas: QuakeAreas, rng: np.random.Generator,
                 break_share: float = QUAKE_BREAK_SHARE) -> list[Break]:
    """Hasarları borulara uzunlukla orantılı dağıtır (bir boruya en çok bir hasar); bir kısmını kırık seçer."""
    skip = twin.feed_links() | twin.boundary_pipes | twin.fixed_pipes
    pipes = [p for p in twin.pipe_geometry if p not in skip]
    length = {p: twin.wn.get_link(p).length for p in pipes}
    used: list[tuple[str, str]] = []
    taken: set[str] = set()

    def draw(cands: list[str], n: int, area: str | None) -> int:
        cands = [p for p in cands if p not in taken]
        n = min(n, len(cands))
        if n <= 0:
            return 0
        w = np.array([length[p] for p in cands])
        for p in rng.choice(cands, size=n, replace=False, p=w / w.sum()):
            taken.add(str(p))
            used.append((str(p), area))
        return n

    pool = areas.pool
    for name in sorted(areas.damage):
        n = areas.damage[name]
        got = draw([p for p in pipes if areas.pipe_area.get(p) == name], n, name)
        pool += n - got
    draw(pipes, pool, None)

    dma_name = _dma_names(twin)
    n_break = int(np.floor(len(used) * break_share + 0.5))
    is_break = np.zeros(len(used), dtype=bool)
    if n_break:
        is_break[rng.choice(len(used), size=n_break, replace=False)] = True
    out = []
    for (p, area), brk in zip(used, is_break):
        link = twin.wn.get_link(p)
        dma = dma_name[twin.dma_of[link.start_node_name]]
        d_mm = link.diameter * 1000.0
        mid = twin.pipe_geometry[p].interpolate(0.5, normalized=True)
        out.append(Break(pipe=p, kind="kirik" if brk else "sizinti",
                         area=area or (_text(areas.pipe_area.get(p)) if areas.kind == "mahalle" else None) or dma,
                         dma=dma, diameter_mm=d_mm,
                         opening_mm=d_mm if brk else d_mm * float(np.sqrt(QUAKE_LEAK_AREA_FRACTION)),
                         lonlat=(float(mid.x), float(mid.y))))
    return out


def _add_breaks(tw: Twin, breaks: list[Break]) -> list[str]:
    """Her hasar noktasında boruyu ortadan böler, oraya çek valfli kısa bir çıkış borusu ve zemin kotunda bir
    çıkış (sabit kotlu rezervuar) ekler. Çıkış borularının adlarını döndürür."""
    wn = tw.wn
    k_loss = 1.0 / QUAKE_ORIFICE_CD ** 2
    names = []
    for k, br in enumerate(breaks):
        j = f"K{k + 1}"
        split_pipe(wn, br.pipe, f"{br.pipe}-K", j, return_copy=False)
        node = wn.get_node(j)
        x, y = node.coordinates
        wn.add_reservoir(f"KR{k + 1}", base_head=float(node.elevation), coordinates=(x + 1.0, y + 1.0))
        wn.add_pipe(f"KB{k + 1}", j, f"KR{k + 1}", length=1.0, diameter=br.opening_mm / 1000.0,
                    roughness=HAZEN_WILLIAMS_C, minor_loss=k_loss, check_valve=True)
        names.append(f"KB{k + 1}")
    return names


# --- Simülasyon -----------------------------------------------------------------------

def simulate_quake(twin: Twin, b: pd.DataFrame, storage: NodeStorage, plan: Plan, settings: dict[str, float],
                   breaks: list[Break], area: np.ndarray, area_names: list[str], mode: str,
                   hour: int = QUAKE_HOUR, suspect_scope: str = QUAKE_SUSPECT_SCOPE,
                   head_drop_m: float = QUAKE_HEAD_DROP_M) -> QuakeRun:
    """mode: "off" (şamandıra) ya da "on" (akıllı kit). b: depo atanmış bina tablosu, area: bina sırasıyla alan.

    suspect_scope "ilce" ise sarsıntıdan itibaren bütün DMA'ların suyu şüphelidir; head_drop_m sarsıntıdan sonra
    bütün DMA girişlerinin kotunu düşürür (arz tarafı zayıflarsa, duyarlılık için).
    """
    tw = copy.deepcopy(twin)
    wn = tw.wn
    wn.options.time.duration = 0
    wn.options.hydraulic.demand_model = "PDD"
    wn.options.hydraulic.required_pressure = PDD_REQUIRED_PRESSURE_M
    wn.options.hydraulic.minimum_pressure = PDD_MINIMUM_PRESSURE_M
    if "sabit" not in wn.pattern_name_list:
        wn.add_pattern("sabit", [1.0])
    for d in tw.dmas:
        if d.name in settings:
            set_feed_setting(tw, d, settings[d.name])
    for j in tw.junctions:
        wn.get_node(j).demand_timeseries_list[0].pattern_name = "sabit"
    pattern = to_hourly(np.asarray(tw.pattern))

    J = tw.junctions
    N = len(J)
    col = {j: i for i, j in enumerate(J)}
    dma_name = _dma_names(tw)
    jdma = np.array([dma_name[tw.dma_of[j]] for j in J])
    jidx = b["junction"].map(col).to_numpy()
    bdma = jdma[jidx]
    vol = b["tank_m3"].to_numpy(dtype=float)
    has_tank = vol > 0
    smart = has_tank & b["smart"].to_numpy(dtype=bool) & (mode == "on")
    dumb = has_tank & ~smart
    persons = b["persons"].to_numpy(dtype=float)
    q = b["q_m3d"].to_numpy(dtype=float)
    cons = np.outer(q / 24.0, pattern)
    use = np.outer(np.minimum(q, persons * QUAKE_USE_LPCD / 1000.0) / 24.0, pattern)
    cap = np.where(has_tank, TANK_INLET_M3H, 0.0)

    # Başlangıç: şamandıralı depolar dolu; akıllı depolar orkestratörün planındaki seviyede, planın dolumuyla
    L = vol.copy()
    plan_b = np.zeros((len(b), HOURS))
    if smart.any():
        sidx = storage.index()
        plan_in = to_hourly(plan.inflow, axis=1)
        q_smart = pd.Series(q[smart]).groupby(b["junction"].to_numpy()[smart]).sum()
        for k in np.where(smart)[0]:
            i = sidx.get(b["junction"].iat[k])
            if i is None:
                continue
            L[k] = vol[k] * plan.level[i, 0] / max(storage.volume[i], 1e-9)
            plan_b[k] = plan_in[i] * q[k] / max(float(q_smart[b["junction"].iat[k]]), 1e-12)

    leak_coef = np.array([tw.leak_coef.get(j, 0.0) for j in J])
    n_exp = float(wn.options.hydraulic.emitter_exponent)
    reservoirs = [d.reservoir for d in tw.dmas if d.reservoir]
    hit_dmas = {br.dma for br in breaks}
    hit_mask = np.isin(jdma, list(hit_dmas))
    codes = pd.Categorical(area, categories=area_names).codes

    def solve(req: np.ndarray):
        dem = np.bincount(jidx, weights=req, minlength=N)
        for i, j in enumerate(J):
            wn.get_node(j).demand_timeseries_list[0].base_value = float(dem[i] / 3600.0)
        res = simulate(tw)
        p = res.node["pressure"][J].to_numpy()[0]
        got = res.node["demand"][J].to_numpy()[0] * 3600.0
        leak = leak_coef * np.clip(p, 0, None) ** n_exp * 3600.0
        delivered = np.clip(got - leak, 0, None)
        f = np.where(dem > 1e-9, np.minimum(1.0, delivered / np.maximum(dem, 1e-9)), 1.0)
        return res, p, f

    keys = ("inflow_m3h", "break_m3h", "p_min", "p_mean", "p_mean_hit", "low_nodes", "suspect_dmas",
            "stored_m3", "clean_m3", "risk_m3", "dry_persons", "no_clean_persons")
    rec = {k: np.zeros(HOURS) for k in keys}
    node_p = np.zeros((HOURS, N))
    break_lps = np.zeros((HOURS, len(breaks)))
    area_clean = np.zeros((HOURS, len(area_names)))
    suspect: dict[str, int] = {}
    reopen: dict[str, int] = {}
    open_dmas: set[str] = set()
    risk = np.full(len(b), -1)
    fallback = np.zeros(len(b), dtype=bool)   # boşalan mühürlü depo: kit girişi açar, şamandıra gibi dolar
    break_links: list[str] = []
    stock0 = float(L.sum())

    for t in range(HOURS):
        quake = t >= hour
        if t == hour and breaks:
            break_links = _add_breaks(tw, breaks)
        if t == hour and head_drop_m:
            for d in tw.dmas:
                set_feed_setting(tw, d, get_feed_setting(tw, d) - head_drop_m)
        c = use[:, t] if quake else cons[:, t]
        req = np.where(has_tank, 0.0, c)
        if quake and mode == "on" and t == hour + QUAKE_REOPEN_AFTER_H:
            for d in tw.dmas:
                if d.name not in suspect:
                    open_dmas.add(d.name)
                    reopen[d.name] = t
        opened = smart & np.isin(bdma, list(open_dmas)) & ~fallback
        if quake:
            fallback |= smart & ~opened & (L < c)
        floating = dumb | fallback
        req[floating] = np.minimum(cap, np.clip(vol - L + c, 0, None))[floating]
        if not quake:
            req[smart] = plan_b[smart, t]
            res, p, f = solve(req)
        else:
            extra = np.where(opened, np.minimum(np.clip(vol - L, 0, None), np.clip(cap - c, 0, None)), 0.0)
            if opened.any() and extra.sum() > 1e-6:
                # Basınç 15 m'nin altına inmeyecek kadar dolum (kesinti günündeki gibi)
                check = np.isin(jdma, list(open_dmas))
                for step in REFILL_STEPS:
                    req_try = req.copy()
                    req_try[opened] = c[opened] + step * extra[opened]
                    res, p, f = solve(req_try)
                    if p[check].min() >= MIN_SERVICE_PRESSURE_M:
                        break
                req = req_try
            else:
                req[opened] = c[opened]
                res, p, f = solve(req)

        got = f[jidx] * req
        L = L + np.where(has_tank, got - c, 0.0)
        short = np.where(has_tank, np.clip(-L, 0, None), c - got)
        L = np.clip(L, 0, vol)
        with np.errstate(divide="ignore", invalid="ignore"):
            dry = np.nan_to_num(persons * np.clip(short, 0, None) / c)
        dry = np.minimum(dry, persons)

        if quake:
            for d in tw.dmas:
                if d.name not in suspect and (suspect_scope == "ilce" or d.name in hit_dmas
                                              or p[jdma == d.name].min() < QUAKE_SUSPECT_PRESSURE_M):
                    suspect[d.name] = t
                    open_dmas.discard(d.name)   # kit basınç düşüşünü dakikalar içinde görür, girişi kapatır
            sus_b = np.isin(bdma, list(suspect))
            newly = (dumb | fallback) & sus_b & (got > 1e-6) & (risk < 0)
            risk[newly] = t
        else:
            sus_b = np.zeros(len(b), dtype=bool)
        risky = risk >= 0
        clean_l = np.where(has_tank & ~risky, L, 0.0)
        no_clean = np.where(~has_tank & sus_b, persons, np.where(has_tank & risky, persons, dry))

        if reservoirs:
            rec["inflow_m3h"][t] = -res.node["demand"][reservoirs].to_numpy()[0].sum() * 3600.0
        if break_links:
            qb = res.link["flowrate"][break_links].to_numpy()[0]
            break_lps[t] = np.clip(qb, 0, None) * 1000.0
            rec["break_m3h"][t] = break_lps[t].sum() * 3.6
        pc = np.clip(p, 0, None)
        rec["p_min"][t] = pc.min()
        rec["p_mean"][t] = pc.mean()
        rec["p_mean_hit"][t] = pc[hit_mask].mean() if hit_mask.any() else pc.mean()
        rec["low_nodes"][t] = int((p < MIN_SERVICE_PRESSURE_M).sum())
        rec["suspect_dmas"][t] = len(suspect)
        rec["stored_m3"][t] = L.sum()
        rec["clean_m3"][t] = clean_l.sum()
        rec["risk_m3"][t] = np.where(has_tank & risky, L, 0.0).sum()
        rec["dry_persons"][t] = dry.sum()
        rec["no_clean_persons"][t] = no_clean.sum()
        node_p[t] = pc
        area_clean[t] = np.bincount(codes, weights=clean_l, minlength=len(area_names))

    after = slice(hour, HOURS)
    stock = rec["clean_m3"][hour - 1] if hour > 0 else stock0
    sus_persons = float(persons[np.isin(bdma, list(suspect))].sum())
    sealed_end = smart & ~np.isin(bdma, list(open_dmas)) & ~fallback
    daily = {
        "damage": float(len(breaks)),
        "breaks": float(sum(br.kind == "kirik" for br in breaks)),
        "leaks": float(sum(br.kind == "sizinti" for br in breaks)),
        "damaged_dmas": float(len(hit_dmas)),
        "suspect_dmas": float(len(suspect)),
        "suspect_persons": sus_persons,
        "stock_m3": float(stock),
        "clean_m3_end": float(rec["clean_m3"][-1]),
        "risk_m3_end": float(rec["risk_m3"][-1]),
        "risk_tanks": float((risk >= 0).sum()),
        "risk_persons": float(persons[risk >= 0].sum()),
        "sealed_tanks_end": float(sealed_end.sum()),
        "emptied_tanks": float(fallback.sum()),
        "reopened_dmas": float(len(reopen)),
        "dry_ph": float(rec["dry_persons"][after].sum()),
        "dry_max": float(rec["dry_persons"][after].max()),
        "no_clean_end": float(rec["no_clean_persons"][-1]),
        "no_clean_ph": float(rec["no_clean_persons"][after].sum()),
        "p_min_after": float(rec["p_min"][after].min()),
        "p_mean_hit_min": float(rec["p_mean_hit"][after].min()),
        "low_node_hours": float(rec["low_nodes"][after].sum()),
        "break_m3": float(rec["break_m3h"][after].sum()),
        "break_peak_m3h": float(rec["break_m3h"][after].max()),
    }
    label = "Akıllı kit" if mode == "on" else "Şamandıralı vana"
    return QuakeRun(mode, label, rec, daily, node_p, break_lps, suspect, reopen, risk,
                    {a: area_clean[:, i] for i, a in enumerate(area_names)})


def study(twin: Twin, b: pd.DataFrame, storage: NodeStorage, scenarios: dict, areas: QuakeAreas,
          rng: np.random.Generator, hour: int = QUAKE_HOUR, break_share: float = QUAKE_BREAK_SHARE,
          suspect_scope: str = QUAKE_SUSPECT_SCOPE, head_drop_m: float = QUAKE_HEAD_DROP_M,
          log=print) -> QuakeStudy | None:
    """scenarios: {"off": Scenario, "on": Scenario} (plan ve besleme ayarları normal günden gelir)."""
    breaks = place_breaks(twin, areas, rng, break_share=break_share)
    if not breaks:
        log("  deprem günü: dağıtılacak boru hasarı yok")
        return None
    dma_name = _dma_names(twin)
    if areas.kind == "mahalle" and areas.building_area is not None:
        fallback = [dma_name[twin.dma_of[j]] for j in b["junction"]]
        area = np.array([_text(a) or f for a, f in zip(areas.building_area, fallback)], dtype=object)
    else:
        area = np.array([dma_name[twin.dma_of[j]] for j in b["junction"]], dtype=object)
    names = sorted(set(area))
    runs = {}
    for key in ("off", "on"):
        sc = scenarios[key]
        runs[key] = simulate_quake(twin, b, storage, sc.plan, sc.settings, breaks, area, names, key, hour=hour,
                                   suspect_scope=suspect_scope, head_drop_m=head_drop_m)
    off, on = runs["off"].daily, runs["on"].daily
    log(f"  deprem günü: {int(off['breaks'])} kırık, {int(off['leaks'])} sızıntı; şebeke suyu şüpheli DMA "
        f"{int(off['suspect_dmas'])}; gün sonunda temiz su şamandırada {off['clean_m3_end']:,.0f} m³, "
        f"kitle {on['clean_m3_end']:,.0f} m³")
    return QuakeStudy(hour=hour, areas=areas, area_names=names, building_area=area, breaks=breaks, runs=runs)
