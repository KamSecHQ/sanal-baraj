// Sağ panel: seçilen bina, düğüm, boru, DMA ya da vananın 24 saatlik geçmişi. Ayrıca harita üstü kısa ipucu.
import { state, set, shownSc } from "./state.js";
import { fmt0, fmt1, fmt2, hh, esc, $ } from "./format.js";
import { lineChart } from "./charts.js";
import { original, suspectDmaIds } from "./map.js";
import * as istanbul from "./istanbul.js";
import * as leak from "./leak.js";

let D = null;
export function setData(d) { D = d; }

const SC_LABEL = { off: "Kapalı", on: "Akıllı depo", pilot: "+ Pilot", solar: "Güneş" };
const OUT_LABEL = { off: "Şamandıra", on: "Orkestratör" };
const QUAKE_LABEL = { off: "Şamandıra", on: "Akıllı kit" };
const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
const series = (p, prefix) => Array.from({ length: 24 }, (_, h) => (p[`${prefix}${h}`] ?? NaN));
const has = (p, prefix) => p[`${prefix}0`] !== undefined;

export function init() {
  document.addEventListener("click", (e) => {
    if (e.target.closest("#insp-close")) set({ selection: null });
  });
}

export function render() {
  const el = $("inspector");
  const sel = state.selection;
  const ist = state.mode === "istanbul";
  const quakeOnly = sel && (sel.kind === "qbreak" || sel.kind === "qarea") && state.mode !== "quake";
  if (!sel || (!D && !ist) || ist !== (sel.kind === "ilce") || (sel.kind === "leakguess" && state.mode !== "leak") || quakeOnly) {
    el.hidden = true;
    return;
  }
  const html = sel.kind === "ilce" ? istanbul.inspector(sel) : sel.kind === "leakguess" ? leak.inspector(sel) : content(sel);
  if (!html) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<button type="button" id="insp-close" class="icon-btn close" aria-label="Seçimi kapat (Esc)">×</button>` + html.body;
  const svg = el.querySelector("svg.insp-chart");
  if (svg && html.chart) lineChart(svg, { pad: { l: 34, r: 8, t: 12, b: 18 }, ...html.chart, cursor: html.chart.cursor ?? state.hour });
}

function head(kind, title, sub = "") {
  return `<div class="insp-kind">${kind}</div><h2 class="insp-title">${title}</h2>${sub ? `<p class="insp-sub">${sub}</p>` : ""}`;
}

function legend(items) {
  return `<div class="legend-inline">${items.map(([cls, label]) => `<i class="sw ${cls}"></i>${label}`).join(" ")}</div>`;
}

function content(sel) {
  const f = original(sel.kind, sel.index);
  if (!f) return null;
  const p = f.properties;
  const h = state.hour;
  const sc = shownSc();
  const out = state.mode === "outage";
  const s = D.summary;
  if (state.mode === "quake" && D.quake) {
    const html = quakeContent(sel.kind, p, h, sc);
    if (html) return html;
  }

  if (sel.kind === "building") {
    let facts = row("Kat", fmt0.format(p.fl)) + row("Tahmini kişi", fmt0.format(p.kisi)) + row("Günlük tüketim", `${fmt1.format(p.q)} m³`);
    if (!(p.tv > 0)) {
      facts += row("Depo", "yok, şebekeden doğrudan");
      const note = out && p.dma === outId() ? "Deposuz bina: kesinti boyunca susuz kalır. Depo yaygınlaştırmak da çözümün parçası." : "Deposuz bina: suyu şebekeden anlık çeker, basınca doğrudan bağlı.";
      return { body: head("Bina", `${fmt0.format(p.fl)} katlı bina`, `DMA-${String(p.dma).padStart(2, "0")}`) + `<dl class="facts">${facts}</dl><p class="small">${note}</p>` };
    }
    facts += row("Depo", `${fmt1.format(p.tv)} m³, ${p.sm ? "akıllı kit" : "şamandıra"}`) + row("Hidrofor basma", `${fmt0.format(p.hb)} m`);
    const en = s.energy;
    if (en && p.ew !== undefined) {
      facts += row("Girişte boşa giden basınç", `${fmt1.format(p.ew)} W, gün ortalaması`) +
        row("Mikro türbinle", `${fmt1.format(p.et)} W (kit ${fmt0.format(en.kit_w)} W ister)`) +
        row("Şebeke basıncının yettiği kat", `${fmt0.format(p.nd)} / ${fmt0.format(p.fl)}`);
    }
    let chart, leg;
    if (out && has(p, "ol")) {
      chart = { series: [{ values: series(p, "ol"), cls: "off", main: sc === "off" }, { values: series(p, "oal"), cls: "on", main: sc === "on" }],
        yMax: 100, yTicks: [0, 40, 100], yFmt: (v) => `%${v}`, bands: [{ from: s.outage.start, to: s.outage.end, cls: "cut" }],
        refs: [{ y: 40, cls: "reserve" }], cursorFmt: (v) => `%${fmt0.format(v)}` };
      leg = [["off", OUT_LABEL.off], ["on", OUT_LABEL.on]];
    } else {
      const on = has(p, "l") ? series(p, "l") : Array(24).fill(100);
      const sol = sc === "solar" && has(p, "ls") ? [{ values: series(p, "ls"), cls: "solar", main: true, area: true }] : [];
      chart = { series: [{ values: Array(24).fill(100), cls: "off", main: sc === "off" }, { values: on, cls: "on", main: sc !== "off" && !sol.length, area: sc !== "off" && !sol.length }, ...sol],
        yMax: 100, yTicks: [0, 40, 100], yFmt: (v) => `%${v}`, refs: [{ y: 40, cls: "reserve", label: "yedek" }], cursorFmt: (v) => `%${fmt0.format(v)}` };
      leg = [["off", "Şamandıra"], ["on", "Akıllı depo"], ...(sol.length ? [["solar", "Güneş"]] : [])];
    }
    const now = chart.series.find((x) => x.main).values[h];
    return {
      body: head("Bina deposu", `%${fmt0.format(now)} dolu`, `${fmt0.format(p.fl)} katlı bina, DMA-${String(p.dma).padStart(2, "0")}, ${hh(h)}`) +
        `<div class="insp-chart-head">Depo doluluğu, 24 saat ${legend(leg)}</div><svg class="insp-chart"></svg><dl class="facts">${facts}</dl>`,
      chart,
    };
  }

  if (sel.kind === "node") {
    const min = s.min_service_pressure_m;
    let chart, leg, now;
    if (out) {
      if (!has(p, "o")) return { body: head("Düğüm", `Düğüm ${esc(p.id)}`) + `<p class="small">Bu düğüm kesinti DMA'sının dışında; olağan gününde.</p>` };
      chart = { series: [{ values: series(p, "o"), cls: "off", main: sc === "off" }, { values: series(p, "oa"), cls: "on", main: sc === "on" }],
        bands: [{ from: s.outage.start, to: s.outage.end, cls: "cut" }], refs: [{ y: min, cls: "alarm", label: `${min} m` }], cursorFmt: (v) => `${fmt1.format(v)} m` };
      leg = [["off", OUT_LABEL.off], ["on", OUT_LABEL.on]];
      now = p[`${sc === "on" ? "oa" : "o"}${h}`];
    } else {
      chart = { series: [["off", "p"], ["on", "pa"], ["pilot", "pb"], ["solar", "ps"]].filter(([, x]) => has(p, x)).map(([k, x]) => ({ values: series(p, x), cls: k, main: k === sc })),
        refs: [{ y: min, cls: "alarm", label: `${min} m` }], cursorFmt: (v) => `${fmt1.format(v)} m` };
      leg = [["off", SC_LABEL.off], ["on", SC_LABEL.on], ["pilot", SC_LABEL.pilot], ["solar", SC_LABEL.solar]];
      now = p[`${{ off: "p", on: "pa", pilot: "pb", solar: "ps" }[sc]}${h}`];
    }
    return {
      body: head("Düğüm basıncı", `${fmt1.format(now)} m`, `Düğüm ${esc(p.id)}, DMA-${String(p.dma).padStart(2, "0")}, ${hh(h)}`) +
        `<div class="insp-chart-head">Basınç, m ${legend(leg)}</div><svg class="insp-chart"></svg>` +
        `<dl class="facts">${row("Kot", `${fmt1.format(p.z)} m`)}${row("Ortalama tüketim", `${fmt2.format(p.q)} L/s`)}${row("Hizmet sınırı", `${min} m`)}</dl>` +
        `<p class="small">Akıllı kitteki basınç sensörü bu eğriyi her binada ölçer. Basınç pilotu ve sızıntı avı bu yoğun haritaya dayanır.</p>`,
      chart,
    };
  }

  if (sel.kind === "pipe") {
    const facts = row("Çap", `Ø${p.d} mm`) + row("Uzunluk", `${fmt0.format(p.L)} m`) + row("Gün içi en yüksek hız", `${fmt2.format(p.v)} m/s`) +
      row("Yol sınıfı", esc(p.hw)) + (p.b ? row("Durum", "DMA sınırı, kapalı vana") : p.bp ? row("Basınç pilotu", "alt bölge sınırı, pilotta kapalı") : "");
    if (p.b) return { body: head("Boru", `Ø${p.d} mm sınır borusu`) + `<dl class="facts">${facts}</dl>` };
    const chart = { series: [["off", "q"], ["on", "qa"], ["pilot", "qb"], ["solar", "qs"]].filter(([, x]) => has(p, x)).map(([k, x]) => ({ values: series(p, x), cls: k, main: k === sc && !out })),
      cursorFmt: (v) => `${fmt1.format(v)} L/s`, yFmt: (v) => fmt1.format(v) };
    const now = p[`${{ off: "q", on: "qa", pilot: "qb", solar: "qs" }[out ? "off" : sc]}${h}`];
    return {
      body: head("Boru debisi", `${fmt1.format(now)} L/s`, `Boru ${esc(p.id)}, Ø${p.d} mm, ${hh(h)}${out ? ", normal gün" : ""}`) +
        `<div class="insp-chart-head">Debi, L/s ${legend([["off", SC_LABEL.off], ["on", SC_LABEL.on], ["pilot", SC_LABEL.pilot], ["solar", SC_LABEL.solar]])}</div><svg class="insp-chart"></svg><dl class="facts">${facts}</dl>`,
      chart,
    };
  }

  if (sel.kind === "dma" || sel.kind === "inlet") {
    const r = s.dmas.find((d) => d.id === p.dma);
    if (!r) return null;
    const isOut = out && r.name === s.outage.dma;
    let chart, leg;
    if (isOut) {
      chart = { series: [{ values: s.outage.off.hourly.inflow_m3h, cls: "off", main: sc === "off" }, { values: s.outage.on.hourly.inflow_m3h, cls: "on", main: sc === "on", area: sc === "on" }],
        bands: [{ from: s.outage.start, to: s.outage.end, cls: "cut" }], cursorFmt: (v) => `${fmt0.format(v)} m³/sa` };
      leg = [["off", OUT_LABEL.off], ["on", OUT_LABEL.on]];
    } else {
      chart = { series: ["off", "on", "pilot", "solar"].filter((k) => r[k]).map((k) => ({ values: r[k].inflow_m3h, cls: k, main: k === (out ? "off" : sc), area: k === (out ? "off" : sc) })),
        cursorFmt: (v) => `${fmt0.format(v)} m³/sa` };
      leg = [["off", SC_LABEL.off], ["on", SC_LABEL.on], ["pilot", SC_LABEL.pilot], ["solar", SC_LABEL.solar]];
    }
    const k = r[out ? "off" : sc] ? (out ? "off" : sc) : "off";
    const bld = D.buildings.features.filter((b) => b.properties.dma === r.id);
    const persons = bld.reduce((a, b) => a + (b.properties.kisi || 0), 0);
    const tanks = bld.filter((b) => b.properties.tv > 0).length;
    const facts = row("Düğüm", fmt0.format(r.junctions)) + row("Bina", `${fmt0.format(bld.length)}, ${fmt0.format(tanks)} depolu`) +
      row("Tahmini kişi", fmt0.format(persons)) + row("Giriş enerji kotu", `${fmt1.format(r[k].head_m)} m`) +
      row(`Basınç aralığı, ${hh(h)}`, `${fmt1.format(r[k].p_min[h])}–${fmt1.format(r[k].p_max[h])} m`);
    return {
      body: head(isOut ? "Kesinti bölgesi" : "İzole ölçüm bölgesi", esc(r.name), `${fmt0.format(chart.series.find((x) => x.main)?.values[h] ?? 0)} m³/sa giriş, ${hh(h)}`) +
        `<div class="insp-chart-head">Giriş debisi, m³/sa ${legend(leg)}</div><svg class="insp-chart"></svg><dl class="facts">${facts}</dl>`,
      chart,
    };
  }

  if (sel.kind === "prv") {
    const P = s.pilot;
    const curve = P.curve_tl && P.curve_tl.length ? P.curve_tl : P.curve_m3d;
    const tl = Boolean(P.curve_tl && P.curve_tl.length);
    const unit = tl ? "TL/gün" : "m³/gün";
    const k = Math.min(Number(p.rank) - 1, curve.length - 1);
    const chart = { series: [{ values: curve, cls: "pilot", main: true, area: true }], n: curve.length, cursor: k,
      xTicks: [0, Math.round((curve.length - 1) / 2), curve.length - 1], xFmt: (i) => `${i + 1}`,
      yFmt: (v) => fmt0.format(v), cursorFmt: (v) => `${fmt0.format(v)} ${unit}` };
    const sign = (v, f = fmt0) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${f.format(Math.abs(v))}`;
    const facts = row("Atılabilen fazla basınç", `${fmt1.format(p.excess)} m`) +
      row("Kaçak azalması", `${fmt1.format(p.save)} m³/gün`) +
      (p.net !== undefined ? row("Basma maliyeti", `${sign(p.dtl)} TL/gün`) + row("Ana bölge giriş kotu", `${sign(p.dh, fmt1)} m`) +
        row("Net kazanç", `${fmt0.format(p.net)} TL/gün`) : "") + row("Ana bölge", esc(p.parent));
    return {
      body: head("Önerilen vana", `${fmt0.format(p.rank)}. sırada`, `${esc(p.name)} alt bölgesi, değerler simülasyondan`) +
        `<dl class="facts">${facts}</dl>` +
        `<div class="insp-chart-head">İlk k vananın toplam ${tl ? "net kazancı" : "kaçak azalması"}, ${unit}</div><svg class="insp-chart"></svg>` +
        `<p class="small">${P.candidates} aday vana DMA modelinde tek tek simüle edildi${P.accepted ? `; ${P.accepted} tanesi net kazançlı, en iyi ${P.prvs} tanesi seçildi` : ""}. ` +
        (tl ? `Net kazanç = kaçak azalması × ${fmt1.format(P.water_value_tl_m3)} TL/m³ (suyun değişken maliyeti, tahmin) − basma maliyeti artışı. ` : "") +
        `Vana kurulum maliyeti henüz hesapta yok.</p>`,
      chart,
    };
  }
  return null;
}

// --- Deprem günü -----------------------------------------------------------------

const dmaName = (id) => `DMA-${String(id).padStart(2, "0")}`;
const qBand = () => [{ from: D.summary.quake.hour, to: 24, cls: "cut" }];

function areaChart(a) {
  return { series: [{ values: a.days.off, cls: "off", main: shownSc() === "off" }, { values: a.days.on, cls: "on", main: shownSc() === "on", area: shownSc() === "on" }],
    bands: qBand(), cursorFmt: (v) => `${fmt1.format(v)} gün`, yFmt: (v) => fmt0.format(v) };
}

function quakeContent(kind, p, h, sc) {
  const Q = D.quake;
  const q = D.summary.quake;
  const after = h >= q.hour;
  const sus = new Set(suspectDmaIds(sc, h));
  if (kind === "qarea" || kind === "building") {
    const a = Q.areas[kind === "qarea" ? p.i : p.ar];
    if (!a) return null;
    const what = q.kind === "mahalle" ? "Mahalle" : "Bölge";
    if (kind === "qarea") {
      const facts = row("Tahmini kişi", fmt0.format(a.persons)) + row("Depolu bina", `${fmt0.format(a.tank_buildings)} / ${fmt0.format(a.buildings)}`) +
        row("Depo hacmi", `${fmt0.format(a.tank_m3)} m³`) +
        (a.damage !== null && a.damage !== undefined ? row("İBB boru hasarı", fmt0.format(a.damage)) : "") +
        row("Modelde hasar", `${fmt0.format(a.breaks)} kırık, ${fmt0.format(a.leaks)} sızıntı`) +
        row(`Temiz su, ${hh(h)}`, `${fmt0.format(a.clean_m3[sc][h])} m³`);
      return {
        body: head(`${what} temiz su haritası`, esc(a.name), `${fmt1.format(a.days[sc][h])} gün içme suyu, ${hh(h)}`) +
          `<div class="insp-chart-head">Temiz içme suyu, gün ${legend([["off", QUAKE_LABEL.off], ["on", QUAKE_LABEL.on]])}</div><svg class="insp-chart"></svg>` +
          `<dl class="facts">${facts}</dl><p class="small">Alandaki bina depolarında kalan temiz su, alanın bütün nüfusuna ${fmt0.format(q.drink_lpcd)} L/kişi/gün içme suyu olarak. Deposuz binalar komşu depolardan su alabilir.</p>`,
        chart: areaChart(a),
      };
    }
    // Bina
    let facts = row("Kat", fmt0.format(p.fl)) + row("Tahmini kişi", fmt0.format(p.kisi)) + row(q.kind === "mahalle" ? "Mahalle" : "Bölge", esc(a.name));
    let title, note;
    if (p.tv > 0) {
      const risk = p[sc === "on" ? "eka" : "ek"];
      const atRisk = after && risk !== undefined && risk <= h;
      const sealed = sc === "on" && p.sm && after && sus.has(p.dma);
      const rec = Q.dmas[dmaName(p.dma)];
      facts += row("Depo", `${fmt1.format(p.tv)} m³, ${p.sm ? "akıllı kit" : "şamandıra"}`) +
        (p.kisi > 0 ? row("Depo, kişi başı", `${fmt0.format((1000 * p.tv) / p.kisi)} L`) : "");
      title = !after ? "Depremden önce" : atRisk ? "Kirlenme riski" : sealed ? "Mühürlü, temiz" : "Temiz su";
      note = !after ? "Sarsıntı saat " + hh(q.hour) + " anında." : atRisk && sc === "on" && p.sm ? `Mühürlü depo boşalmak üzereydi; kit girişi ${hh(risk)} saatinde açtı. Bina susuz kalmadı ama depo şüpheli su aldı.`
        : atRisk ? `Depo ${hh(risk)} saatinde şüpheli şebeke suyu aldı; bütün suyu test edilene kadar içilemez.`
        : sealed ? "İvmeölçer sarsıntıda girişi kapattı. Depodaki su temiz; bina ve komşuları için içme suyu stoku."
        : sc === "on" && rec && rec.reopen !== null && rec.reopen !== undefined ? `Bu DMA'da hasar yok; orkestratör girişi ${hh(rec.reopen)} saatinde yeniden açtı.` : "Bu DMA'da şebeke suyu temiz kaldı.";
    } else {
      facts += row("Depo", "yok, şebekeden doğrudan");
      title = after && sus.has(p.dma) ? "Şebeke suyu şüpheli" : "Deposuz";
      note = after && sus.has(p.dma) ? "Deposuz bina: musluktan gelen su şüpheli. İçme suyu komşu depolardan ya da dağıtımdan gelmeli." : "Deposuz bina: suyu şebekeden anlık çeker.";
    }
    return {
      body: head("Bina", title, `${fmt0.format(p.fl)} katlı bina, ${dmaName(p.dma)}, ${hh(h)}`) +
        `<p class="small">${esc(note)}</p>` +
        `<div class="insp-chart-head">${esc(a.name)}: temiz içme suyu, gün ${legend([["off", QUAKE_LABEL.off], ["on", QUAKE_LABEL.on]])}</div><svg class="insp-chart"></svg>` +
        `<dl class="facts">${facts}</dl>`,
      chart: areaChart(a),
    };
  }
  if (kind === "qbreak") {
    const b = Q.breaks[p.i];
    if (!b) return null;
    const isBreak = b.kind === "kirik";
    const facts = row("Boru", `${esc(b.pipe)}, Ø${b.d} mm`) + row("Açıklık", isBreak ? "borunun tam kesiti" : `Ø${fmt0.format(b.o)} mm eşdeğer delik`) +
      row("Bölge", `${esc(b.dma)}${q.kind === "mahalle" ? `, ${esc(b.area)}` : ""}`);
    return {
      body: head("Boru hasarı", isBreak ? "Kırık" : "Sızıntı", `${fmt1.format(b.lps[sc][h])} L/s, ${hh(h)}`) +
        `<div class="insp-chart-head">Kaçan su, L/s ${legend([["off", QUAKE_LABEL.off], ["on", QUAKE_LABEL.on]])}</div><svg class="insp-chart"></svg>` +
        `<dl class="facts">${facts}</dl><p class="small">Yer İBB senaryosunun mahalle hasar sayısından, boru uzunluğuyla orantılı rastgele seçildi (sabit tohum). Akıllı kit, sayaçtaki ani debi artışı ve basınç sensörleriyle hasarlı DMA'yı ilk saatte gösterir.</p>`,
      chart: { series: [{ values: b.lps.off, cls: "off", main: sc === "off" }, { values: b.lps.on, cls: "on", main: sc === "on" }],
        bands: qBand(), cursorFmt: (v) => `${fmt1.format(v)} L/s`, yFmt: (v) => fmt0.format(v) },
    };
  }
  if (kind === "node") {
    const min = D.summary.min_service_pressure_m;
    const chart = { series: [{ values: series(p, "e"), cls: "off", main: sc === "off" }, { values: series(p, "ea"), cls: "on", main: sc === "on" }],
      bands: qBand(), refs: [{ y: min, cls: "alarm", label: `${min} m` }], cursorFmt: (v) => `${fmt1.format(v)} m` };
    return {
      body: head("Düğüm basıncı", `${fmt1.format(p[`${sc === "on" ? "ea" : "e"}${h}`])} m`, `Düğüm ${esc(p.id)}, ${dmaName(p.dma)}, ${hh(h)}`) +
        `<div class="insp-chart-head">Basınç, m ${legend([["off", QUAKE_LABEL.off], ["on", QUAKE_LABEL.on]])}</div><svg class="insp-chart"></svg>` +
        `<dl class="facts">${row("Kot", `${fmt1.format(p.z)} m`)}${row("Şebeke suyu", after && sus.has(p.dma) ? "şüpheli" : "temiz")}${row("Kaynatma uyarısı eşiği", `${fmt0.format(q.suspect_pressure_m)} m`)}</dl>`,
      chart,
    };
  }
  if (kind === "dma" || kind === "inlet") {
    const r = Q.dmas[dmaName(p.dma)];
    if (!r) return null;
    const nodes = D.nodes.features.filter((f) => f.properties.dma === p.dma);
    const minSeries = (pre) => Array.from({ length: 24 }, (_, k) => Math.min(...nodes.map((f) => f.properties[`${pre}${k}`] ?? Infinity)));
    const susH = r.suspect[sc];
    const facts = row("Modelde hasar", fmt0.format(r.damage)) +
      row("Şebeke suyu", susH === null || susH === undefined ? "temiz" : `şüpheli, ${hh(susH)} saatinden beri`) +
      (sc === "on" ? row("Akıllı depolar", r.reopen === null || r.reopen === undefined ? "gün boyu mühürlü" : `${hh(r.reopen)} saatinde açıldı`) : "");
    return {
      body: head(susH !== null && susH !== undefined ? "Şebeke suyu şüpheli bölge" : "İzole ölçüm bölgesi", esc(dmaName(p.dma)), hh(h)) +
        `<div class="insp-chart-head">En düşük basınç, m ${legend([["off", QUAKE_LABEL.off], ["on", QUAKE_LABEL.on]])}</div><svg class="insp-chart"></svg><dl class="facts">${facts}</dl>`,
      chart: { series: [{ values: minSeries("e"), cls: "off", main: sc === "off" }, { values: minSeries("ea"), cls: "on", main: sc === "on" }],
        bands: qBand(), refs: [{ y: q.suspect_pressure_m, cls: "alarm", label: `${fmt0.format(q.suspect_pressure_m)} m` }], cursorFmt: (v) => `${fmt1.format(v)} m` },
    };
  }
  return null;
}

const outId = () => (D.summary.dmas.find((d) => d.name === D.summary.outage?.dma) || {}).id;

// Harita üstü kısa ipucu
export function tooltip(hit) {
  if (!hit || !D) return "";
  const p = hit.props;
  const h = state.hour;
  const sc = shownSc();
  const out = state.mode === "outage";
  if (state.mode === "quake" && D.quake) {
    const q = D.summary.quake;
    const after = h >= q.hour;
    if (hit.kind === "qbreak") {
      const b = D.quake.breaks[p.i];
      return b ? `${b.kind === "kirik" ? "Kırık" : "Sızıntı"} · Ø${b.d} mm · ${fmt1.format(b.lps[sc][h])} L/s` : "";
    }
    if (hit.kind === "qarea") {
      const a = D.quake.areas[p.i];
      return a ? `${a.name} · ${fmt1.format(a.days[sc][h])} gün içme suyu` : "";
    }
    if (hit.kind === "node") return `Düğüm · ${fmt1.format(p[`${sc === "on" ? "ea" : "e"}${h}`])} m basınç`;
    if (hit.kind === "building" && after) {
      const sus = suspectDmaIds(sc, h).includes(p.dma);
      if (!(p.tv > 0)) return `${p.fl} katlı bina · deposuz${sus ? ", şebeke suyu şüpheli" : ""}`;
      const risk = p[sc === "on" ? "eka" : "ek"];
      return `${p.fl} katlı bina · ${risk !== undefined && risk <= h ? "depo kirlenme riskinde" : sc === "on" && p.sm && sus ? "depo mühürlü, temiz" : "depoda temiz su"}`;
    }
  }
  switch (hit.kind) {
    case "building": {
      if (!(p.tv > 0)) return `${p.fl} katlı bina · deposuz`;
      let l = 100;
      if (out && p[`ol${h}`] !== undefined) l = p[`${sc === "on" ? "oal" : "ol"}${h}`];
      else if (!out && sc !== "off" && p[`${sc === "solar" ? "ls" : "l"}${h}`] !== undefined) l = p[`${sc === "solar" ? "ls" : "l"}${h}`];
      return `${p.fl} katlı bina · depo %${fmt0.format(l)}`;
    }
    case "node": {
      const v = out ? p[`${sc === "on" ? "oa" : "o"}${h}`] : p[`${{ off: "p", on: "pa", pilot: "pb", solar: "ps" }[sc]}${h}`];
      return v === undefined ? `Düğüm ${p.id}` : `Düğüm · ${fmt1.format(v)} m basınç`;
    }
    case "pipe": return p.b ? `Ø${p.d} sınır borusu · kapalı` : `Ø${p.d} boru · ${fmt1.format(p[`${{ off: "q", on: "qa", pilot: "qb", solar: "qs" }[out ? "off" : sc]}${h}`])} L/s`;
    case "prv": return p.net !== undefined ? `Vana ${p.rank}. sıra · net ${fmt0.format(p.net)} TL/gün` : `Vana ${p.rank}. sıra · ${fmt1.format(p.save)} m³/gün kazanç`;
    case "inlet": return `${p.name} girişi`;
    case "dma": return `${p.name} · ${fmt0.format(p.n)} düğüm`;
    case "ilce": return p.name ? `${p.name} · ${p.rank}. sıra` : "";
    case "leakguess": return `Aday ${p.r}. sıra · olasılık %${fmt0.format(100 * (p.pa || 0))}`;
    default: return "";
  }
}
