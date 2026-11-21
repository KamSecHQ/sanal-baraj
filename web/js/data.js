// Veri yükleme (ilerleme göstergesiyle) ve simülasyon sonuçlarından türetilen "gün akışı" anlatımı.
import { fmt0, fmt1, fmt2, hh, signedPct, change, sum } from "./format.js";

export const DATA_ROOT = "../data";
const EMPTY_FC = { type: "FeatureCollection", features: [] };

async function fetchWithProgress(url, onBytes, optional = false) {
  const r = await fetch(url);
  if (!r.ok) {
    if (optional) return null;
    throw new Error(`${url.replace(DATA_ROOT + "/", "")} okunamadı (HTTP ${r.status})`);
  }
  const total = Number(r.headers.get("content-length")) || 0;
  if (!r.body || !total) return r.json();
  const reader = r.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onBytes(value.length, 0);
  }
  const buf = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) { buf.set(c, o); o += c.length; }
  return JSON.parse(new TextDecoder().decode(buf));
}

export async function loadIndex() {
  try {
    const r = await fetch(`${DATA_ROOT}/index.json`);
    return r.ok ? r.json() : [];
  } catch (_) { return []; }
}

// Bir bölgenin bütün dosyaları. onProgress(okunanBayt, bitenDosya, toplamDosya)
export async function loadDistrict(slug, onProgress = () => {}) {
  const base = `${DATA_ROOT}/${slug}`;
  const files = [
    ["summary", "summary.json", false], ["nodes", "nodes.geojson", false], ["pipes", "pipes.geojson", false],
    ["buildings", "buildings.geojson", true], ["dmas", "dmas.geojson", true], ["inlets", "inlets.geojson", true],
    ["prvs", "prvs.geojson", true], ["leak", "leak.json", true], ["quake", "quake.json", true],
  ];
  let bytes = 0, done = 0;
  const out = {};
  await Promise.all(files.map(async ([key, name, optional]) => {
    out[key] = await fetchWithProgress(`${base}/${name}`, (n) => { bytes += n; onProgress(bytes, done, files.length); }, optional);
    done += 1;
    onProgress(bytes, done, files.length);
  }));
  for (const k of ["buildings", "dmas", "inlets", "prvs"]) out[k] = out[k] || EMPTY_FC;
  return out;
}

// İstanbul görünümü: ilçe sınırları + öncelik tablosu (data/ref, sürüme dahil)
export async function loadIstanbul() {
  const [geo, csv] = await Promise.all([
    fetch(`${DATA_ROOT}/ref/ilceler.geojson`).then((r) => (r.ok ? r.json() : null)),
    fetch(`${DATA_ROOT}/ref/ilce_oncelik.csv`).then((r) => (r.ok ? r.text() : null)),
  ]);
  if (!geo || !csv) throw new Error("İstanbul verisi yok: scripts/fetch_ilce_sinirlari.py ve scripts/oncelik.py çalıştırın");
  const [head, ...lines] = csv.trim().split(/\r?\n/);
  const cols = head.split(",");
  const rows = lines.map((line, i) => {
    const v = line.split(",");
    const o = { rank: i + 1 };
    cols.forEach((c, k) => { o[c] = k === 0 ? v[k] : Number(v[k]); });
    return o;
  });
  const byIlce = Object.fromEntries(rows.map((r) => [r.ilce, r]));
  for (const f of geo.features) {
    f.properties = { ...f.properties, ...(byIlce[f.properties.ilce] || {}) };
  }
  return { geo, rows, byIlce };
}

// --- Gün akışı: yapay zekânın gün içinde ne yaptığı, simülasyon sonuçlarından ---------------

// Dairesel dizide koşul sağlanan ardışık saat blokları: [{from, to, hours[]}], to dahil değil
function runs(pred) {
  const ok = Array.from({ length: 24 }, (_, h) => pred(h));
  if (ok.every(Boolean)) return [{ from: 0, to: 24, hours: [...Array(24).keys()] }];
  const start = ok.findIndex((x) => !x);
  const out = [];
  let cur = null;
  for (let k = 1; k <= 24; k++) {
    const h = (start + k) % 24;
    if (ok[h]) {
      if (!cur) cur = { from: h, hours: [] };
      cur.hours.push(h);
    } else if (cur) {
      cur.to = (cur.hours.at(-1) + 1) % 24;
      out.push(cur);
      cur = null;
    }
  }
  return out;
}

export function inWindow(h, ev) {
  if (ev.to === ev.from) return true;
  return ev.from < ev.to ? h >= ev.from && h < ev.to : h >= ev.from || h < ev.to;
}

export function normalDay(s, sc) {
  const H = s.scenarios[sc].hourly;
  const R = s.scenarios.off.hourly;
  const cap = s.tank_volume_m3 || Math.max(...H.stored_m3);
  const fill = H.stored_m3.map((v) => (100 * v) / cap);
  const c = s.comparison;
  const period = s.tariff.period;
  const price = s.tariff.tl_per_kwh;
  const peakH = R.inflow_m3h.indexOf(Math.max(...R.inflow_m3h));
  const puant = [...Array(24).keys()].filter((h) => period[h] === "puant");
  const puantSpan = runs((h) => period[h] === "puant")[0];
  const avg = (arr, hs) => sum(hs.map((h) => arr[h])) / Math.max(hs.length, 1);
  const ev = [];

  if (sc === "off") {
    ev.push({ from: 0, to: 6, title: "Depolar hep dolu",
      text: `Şamandıralı vana her çekişte depoyu hemen tamamlıyor. Su depoda ortalama ${fmt0.format(c.water_age_h.off)} saat bekliyor.` });
    ev.push({ from: peakH, to: peakH + 1, title: peakH < 12 ? "Sabah tepesi" : "Akşam tepesi",
      text: `Herkes aynı anda su çekiyor: şebeke ${fmt0.format(R.inflow_m3h[peakH])} m³/sa ile günün en yüksek debisinde.` });
    if (puantSpan) ev.push({ from: puantSpan.from, to: puantSpan.to, title: "Puant tarifesi",
      text: `Elektriğin en pahalı olduğu saatlerde (${fmt2.format(price.puant)} TL/kWh) giriş ortalama ${fmt0.format(avg(R.inflow_m3h, puant))} m³/sa.` });
    return ev;
  }

  const d = H.stored_m3.map((v, h) => H.stored_m3[(h + 1) % 24] - v);
  const fills = runs((h) => d[h] > 0.002 * cap).sort((a, b) => sum(b.hours.map((h) => d[h])) - sum(a.hours.map((h) => d[h])));
  if (fills.length) {
    const f = fills[0];
    const night = f.hours.filter((h) => period[h] === "gece").length;
    ev.push({ from: f.from, to: f.to, title: "Depolar dolduruluyor", tone: "water",
      text: `Sanal baraj %${fmt0.format(fill[f.from])} → %${fmt0.format(fill[f.to % 24])}: ${fmt0.format(sum(f.hours.map((h) => d[h])))} m³ su` +
        (night >= f.hours.length / 2 ? `, çoğu gece tarifesinde (${fmt2.format(price.gece)} TL/kWh).` : " alındı.") });
  }
  ev.push({ from: peakH, to: peakH + 1, title: peakH < 12 ? "Sabah tepesi" : "Akşam tepesi",
    text: `Binalar depodan içiyor. Kapalıyken şebeke ${fmt0.format(R.inflow_m3h[peakH])} m³/sa çekerdi, şimdi ${fmt0.format(H.inflow_m3h[peakH])} (${signedPct(change(H.inflow_m3h[peakH], R.inflow_m3h[peakH]))}).` });
  if (puantSpan) {
    const save = sum(puant.map((h) => R.pump_tl[h] - H.pump_tl[h]));
    ev.push({ from: puantSpan.from, to: puantSpan.to, title: "Puant saatleri", tone: "ochre",
      text: `Dolum kısıldı: giriş ortalama ${fmt0.format(avg(H.inflow_m3h, puant))} m³/sa (kapalıyken ${fmt0.format(avg(R.inflow_m3h, puant))}). Bu ${puant.length} saatte ${fmt0.format(save)} TL daha az elektrik.` });
  }
  const minF = Math.min(...fill);
  const minH = fill.indexOf(minF);
  const reserve = 100 * ((s.params && s.params.reserve_fraction) || 0.4);
  ev.push({ from: minH, to: minH + 1, title: "En düşük doluluk",
    text: `Sanal baraj %${fmt0.format(minF)}. Kural: hiçbir depo %${fmt0.format(reserve)} yedeğin altına inmez; kesinti ve deprem için su hep hazır.` });
  if (sc === "pilot" && c.leak_m3 && c.leak_m3.pilot !== undefined) {
    ev.push({ from: 0, to: 0, title: "Basınç pilotu", tone: "ochre",
      text: `${s.pilot.prvs} basınç düşürücü vana fazla basıncı atıyor: kaçak günde ${fmt0.format(c.leak_m3.off - c.leak_m3.pilot)} m³ az (${signedPct(c.leak_m3.pct_pilot)}).` });
  }
  return ev.sort((a, b) => (a.to === a.from) - (b.to === b.from) || ((a.from + 1) % 24) - ((b.from + 1) % 24));
}

export function outageDay(s, sc) {
  const O = s.outage;
  const H = O[sc].hourly;
  const D = O[sc].daily;
  const st = O.start, en = O.end;
  const ev = [];
  const before = H.stored_m3[Math.max(st - 1, 0)];
  if (sc === "on") {
    ev.push({ from: 0, to: st, title: "Önceden dolum", tone: "water",
      text: `Orkestratör kesintiyi önceden biliyor: depolar kesintiden önceki saatlerde dolduruldu, başlangıçta ${fmt0.format(before)} m³ su hazır.` });
  } else {
    ev.push({ from: 0, to: st, title: "Habersiz sabah",
      text: `Şamandıralı depolar dolu (${fmt0.format(before)} m³); deposuz binaların hiçbir yedeği yok.` });
  }
  ev.push({ from: st, to: en, title: `Kesinti: ${O.dma}`, tone: "alarm",
    text: `${fmt0.format(O.persons_no_tank)} kişi deposuz binada susuz. Depolu binalar depodan içiyor (${fmt0.format(before)} → ${fmt0.format(H.stored_m3[en - 1])} m³).` });
  const fullH = D.tanks_full_hour >= 0 ? D.tanks_full_hour + 1 : 24;
  if (sc === "on") {
    ev.push({ from: en, to: Math.max(fullH, en + 1), title: "Su döndü, dolum sırada", tone: "water",
      text: `Tepe ${fmt0.format(D.refill_peak_m3h)} m³/sa (normal tepe ${fmt0.format(D.normal_peak_m3h)}), en düşük basınç ${fmt1.format(D.min_pressure_after)} m. Dönüşten sonra susuz kalan yok.` });
  } else {
    ev.push({ from: en, to: Math.max(fullH, en + 1), title: "Su döndü, herkes aynı anda", tone: "alarm",
      text: `Bütün depolar birden doluyor: tepe ${fmt0.format(D.refill_peak_m3h)} m³/sa, basınç ${fmt1.format(D.min_pressure_after)} m seviyesine düştü. ${fmt0.format(D.low_node_hours_after)} düğüm-saat yetersiz basınç, ${fmt0.format(D.unserved_after_ph)} kişi-saat susuz.` });
  }
  if (fullH < 24) {
    ev.push({ from: fullH, to: 24, title: "Normale dönüş",
      text: `Depolar ${hh(fullH - 1)} sonunda doldu; şebeke olağan gününe döndü.` });
  }
  return ev;
}

// Deprem günü: sarsıntı, şamandıranın şüpheli suyu çekmesi ya da kitin mühürlemesi, sağlam bölgelerde dolum
export function quakeDay(s, sc) {
  const Q = s.quake;
  const H = Q[sc].hourly;
  const D = Q[sc].daily;
  const qh = Q.hour;
  const days = (m3) => (1000 * m3) / (Q.drink_lpcd * Q.population);
  const ev = [];
  if (sc === "on") {
    ev.push({ from: 0, to: qh, title: "Gece dolumu", tone: "water",
      text: `Orkestratör depoları ucuz gece saatlerinde dolduruyor; sarsıntıdan hemen önce depolarda ${fmt0.format(D.stock_m3)} m³ su var. Hiçbir depo yedeğin altına inmiyor.` });
  } else {
    ev.push({ from: 0, to: qh, title: "Depolar dolu",
      text: `Şamandıralı vana depoları hep dolu tutuyor: ${fmt0.format(D.stock_m3)} m³ su.` });
  }
  ev.push({ from: qh, to: qh + 1, title: "Sarsıntı", tone: "alarm",
    text: `İBB senaryosundaki ${fmt0.format(D.damage)} boru hasarı: ${fmt0.format(D.breaks)} kırık, ${fmt0.format(D.leaks)} sızıntı. Hasar saatte ${fmt0.format(H.break_m3h[qh])} m³ su kaçırıyor. ${fmt0.format(D.suspect_dmas)} DMA'da şebeke suyu artık şüpheli: ${fmt0.format(D.suspect_persons)} kişi.` });
  if (sc === "on") {
    ev.push({ from: qh, to: qh + 1, title: "Kit girişleri mühürledi", tone: "water",
      text: `İvmeölçer sarsıntıyı algıladı, ${fmt0.format(Q.smart_tanks)} akıllı deponun girişi kapandı. Depodaki su şüpheli şebeke suyuyla karışmıyor.` });
    const peak = H.clean_m3.indexOf(Math.max(...H.clean_m3.slice(qh)), qh);
    if (D.reopened_dmas > 0) {
      ev.push({ from: qh + 1, to: Math.max(peak + 1, qh + 2), title: "Sağlam bölgelerde dolum", tone: "water",
        text: `${fmt0.format(D.reopened_dmas)} DMA'da hasar yok, basınç düşmedi: orkestratör girişleri açtı, depoları basıncı koruyarak tamamladı (${fmt0.format(H.clean_m3[qh])} → ${fmt0.format(H.clean_m3[peak])} m³).` });
    }
    const emptied = D.emptied_tanks > 0
      ? ` ${fmt0.format(D.emptied_tanks)} mühürlü depo boşalmak üzereyken kit girişi açtı; bina susuz kalmadı ama bu depolar şüpheli su aldı.` : "";
    ev.push({ from: 23, to: 24, title: "Gün sonu", tone: "water",
      text: `Depolarda ${fmt0.format(D.clean_m3_end)} m³ temiz su. İlçenin bütün nüfusuna ${fmt1.format(days(D.clean_m3_end))} gün içme suyu (${fmt0.format(Q.drink_lpcd)} L/kişi/gün). ${fmt0.format(D.sealed_tanks_end)} depo hasarlı bölgelerde mühürlü.${emptied}` });
  } else {
    ev.push({ from: qh, to: qh + 1, title: "Şamandıralar şüpheli suyu çekiyor", tone: "alarm",
      text: `Su kullanıldıkça depolar şebekeden dolmaya devam ediyor. Hasarlı bölgelerde ${fmt0.format(D.risk_tanks)} binanın deposu şüpheli su aldı: ${fmt0.format(D.risk_m3_end)} m³ su kirlenme riskinde.` });
    ev.push({ from: 23, to: 24, title: "Gün sonu", tone: "alarm",
      text: `Temiz su ${fmt0.format(D.clean_m3_end)} m³, ilçe nüfusuna ${fmt1.format(days(D.clean_m3_end))} gün. ${fmt0.format(D.no_clean_end)} kişinin binasında temiz su yok.` });
  }
  return ev;
}
