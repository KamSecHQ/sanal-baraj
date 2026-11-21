// Sol panel: senaryo seçimi, sanal baraj göstergesi, saatlik göstergeler, gün akışı ve günün hesabı.
// Yapı mod ya da senaryo değişince bir kez kurulur; saat değişince yalnız sayılar güncellenir (odak kaybolmaz).
import { state, set, shownSc } from "./state.js";
import { fmt0, fmt1, hh, signedPct, change, esc, $ } from "./format.js";
import { normalDay, outageDay, quakeDay, inWindow } from "./data.js";

export const SCENARIOS = {
  normal: [
    { key: "off", label: "Yapay zekâ kapalı", desc: "Şamandıralı vana depoyu hep dolu tutar; herkes suyu aynı anda çeker." },
    { key: "on", label: "Akıllı depo", desc: "Orkestratör depoları ucuz ve sakin saatlerde doldurur; yedek hep %40 seviyesinin üstünde." },
    { key: "pilot", label: "Akıllı depo + basınç pilotu", desc: "Ek olarak en verimli basınç düşürücü vanalar alçak bölgelerdeki fazla basıncı atar." },
    { key: "solar", label: "Güneşle dolum", desc: "Orkestratör tarife yerine saatlik elektrik piyasa fiyatına bakar; depolar öğlen güneş elektriği bolken dolar." },
  ],
  outage: [
    { key: "off", label: "Şamandıralı vana", desc: "Kesinti habersiz geçer; su dönünce bütün depolar aynı anda dolmaya çalışır." },
    { key: "on", label: "Orkestratör", desc: "Depolar önceden dolar; su dönünce dolum basınç 15 m'nin altına inmeyecek şekilde sıraya girer." },
  ],
  quake: [
    { key: "off", label: "Şamandıralı vana", desc: "Depo kullanıldıkça şebekeden dolmaya devam eder; hasarlı bölgede şüpheli suyu da çeker." },
    { key: "on", label: "Akıllı kit", desc: "İvmeölçer sarsıntıda depo girişini mühürler. Hasarsız bölgelerde orkestratör girişi bir saat sonra açar." },
  ],
};

let D = null;           // yüklenmiş bölge verisi
let built = "";         // kurulan yapının anahtarı (mod + senaryo)
let events = [];

export function setData(d) { D = d; built = ""; }

export function render(force = false) {
  const el = $("panel");
  if (!D || state.mode === "istanbul" || state.mode === "leak") return;
  const sc = shownSc();
  const key = `${state.mode}|${sc}|${state.sc}`;
  if (force || key !== built) {
    built = key;
    const mode = state.mode;
    el.innerHTML = mode === "outage" ? outageShell() : mode === "quake" ? quakeShell() : normalShell();
    bind(el);
    events = mode === "outage" ? outageDay(D.summary, sc) : mode === "quake" ? quakeDay(D.summary, sc) : normalDay(D.summary, sc);
    $("p-flow").innerHTML = events.map((e, i) => `
      <li><button type="button" class="flow-item ${e.tone || ""}" data-i="${i}">
        <span class="flow-time">${e.to === e.from ? "gün boyu" : `${hh(e.from)}–${hh(e.to)}`}</span>
        <span class="flow-title">${esc(e.title)}</span>
        <span class="flow-text">${esc(e.text)}</span>
      </button></li>`).join("");
    for (const b of el.querySelectorAll(".flow-item")) {
      b.addEventListener("click", () => {
        const e = events[Number(b.dataset.i)];
        if (e.to !== e.from) set({ hour: e.from, playing: false });
      });
    }
    $("p-ledger").innerHTML = mode === "outage" ? outageLedger() : mode === "quake" ? quakeLedger() : normalLedger(sc);
  }
  updateHour();
}

function scenarioList() {
  const list = SCENARIOS[state.mode];
  const sc = shownSc();
  return `<div class="scen-list" role="radiogroup" aria-label="Senaryo">` + list.map((x, i) => `
    <button type="button" role="radio" class="scen-opt ${x.key}" data-sc="${x.key}" aria-checked="${x.key === sc}">
      <kbd class="scen-key">${i + 1}</kbd>
      <span class="scen-name">${x.label}</span>
      <span class="scen-desc">${x.desc}</span>
    </button>`).join("") + `</div>
    <p class="hint">${state.peek ? "Yapay zekâ kapalı hali gösteriliyor" : "<kbd>B</kbd> tuşunu basılı tutun: aynı an yapay zekâ kapalıyken nasıldı"}</p>`;
}

function normalShell() {
  return `
    <section class="p-sec">${scenarioList()}</section>
    <section class="p-sec reservoir" id="p-res"></section>
    <section class="p-sec"><h2 class="p-h">Bu saat <span id="p-hour" class="p-h-aside"></span></h2><div class="kpis" id="p-kpis"></div></section>
    <section class="p-sec"><h2 class="p-h">Gün akışı</h2><ol class="flow" id="p-flow"></ol></section>
    <section class="p-sec"><h2 class="p-h">Günün hesabı</h2><div class="ledger-wrap"><table class="ledger" id="p-ledger"></table></div></section>
    ${energyNote()}
    <footer class="p-foot">${footNote()}</footer>`;
}

// Basınçtan enerji: depo girişinde boşa giden şebeke basıncı (twin/energy.py)
function energyNote() {
  const e = D.summary.energy;
  if (!e) return "";
  return `<section class="p-sec"><h2 class="p-h">Basınçtan enerji</h2>
    <p class="small">Su depoya ortalama ${fmt1.format(e.inlet_p_mean)} m basınçla geliyor; vana bu basıncı yok ediyor: günde ${fmt0.format(e.inlet_kwh_d)} kWh. Hidroforlar suyu yeniden basmak için ${fmt0.format(e.booster_kwh_d)} kWh harcıyor.
    Girişe mikro türbin konursa günde ${fmt0.format(e.turbine_kwh_d)} kWh elektrik; depolu binaların %${fmt0.format(100 * e.self_powered_share)} kadarında kit kendi enerjisini üretir.</p></section>`;
}

function outageShell() {
  const o = D.summary.outage;
  return `
    <section class="p-sec">${scenarioList()}</section>
    <section class="p-sec">
      <h2 class="p-h">${esc(o.dma)} · planlı çalışma ${hh(o.start)}–${hh(o.end)}</h2>
      <div class="phases" id="p-phases">
        <button type="button" data-h="0" style="flex:${o.start}">Önce</button>
        <button type="button" data-h="${o.start}" class="cut" style="flex:${o.end - o.start}">Kesinti</button>
        <button type="button" data-h="${o.end}" style="flex:${24 - o.end}">Dönüş</button>
      </div>
    </section>
    <section class="p-sec reservoir" id="p-res"></section>
    <section class="p-sec"><h2 class="p-h">Bu saat <span id="p-hour" class="p-h-aside"></span></h2><div class="kpis" id="p-kpis"></div></section>
    <section class="p-sec"><h2 class="p-h">Gün akışı</h2><ol class="flow" id="p-flow"></ol></section>
    <section class="p-sec"><h2 class="p-h">Kesinti gününün hesabı</h2><div class="ledger-wrap"><table class="ledger" id="p-ledger"></table></div>
      <p class="small">Kesinti boyunca susuz kalanlar deposuz binalardaki ${fmt0.format(o.persons_no_tank)} kişi; iki senaryoda da aynı. Depolu binalarda kimse susuz kalmıyor.</p></section>
    <footer class="p-foot">${footNote()}</footer>`;
}

function quakeShell() {
  const q = D.summary.quake;
  const off = q.off.daily;
  const where = q.kind !== "mahalle" ? "ilçenin bütün borularına" : q.areas > 1 ? `${fmt0.format(q.areas)} mahallenin borularına` : "mahallenin borularına";
  return `
    <section class="p-sec">${scenarioList()}</section>
    <section class="p-sec">
      <h2 class="p-h">7,5 Mw gece depremi · sarsıntı ${hh(q.hour)}</h2>
      <div class="phases" id="p-phases">
        <button type="button" data-h="0" style="flex:${q.hour}">Önce</button>
        <button type="button" data-h="${q.hour}" class="cut" style="flex:${24 - q.hour}">Deprem sonrası</button>
      </div>
    </section>
    <section class="p-sec reservoir" id="p-res"></section>
    <section class="p-sec"><h2 class="p-h">Bu saat <span id="p-hour" class="p-h-aside"></span></h2><div class="kpis" id="p-kpis"></div></section>
    <section class="p-sec"><h2 class="p-h">Gün akışı</h2><ol class="flow" id="p-flow"></ol></section>
    <section class="p-sec"><h2 class="p-h">Deprem gününün hesabı</h2><div class="ledger-wrap"><table class="ledger" id="p-ledger"></table></div>
      <p class="small">İBB 2019 deprem senaryosundaki ${fmt0.format(q.damage_ibb)} içme suyu borusu hasarı ${where} uzunlukla orantılı dağıtıldı; HAZUS oranıyla ${fmt0.format(off.breaks)} kırık, ${fmt0.format(off.leaks)} sızıntı. Depremden sonra herkes ${fmt0.format(q.use_lpcd)} L/kişi/gün kullanır. Hasar noktası olan ya da basıncı ${fmt0.format(q.suspect_pressure_m)} m altına inen DMA'nın şebeke suyu şüpheli sayılır. İçme suyu stoku ${fmt0.format(q.drink_lpcd)} L/kişi/gün ile hesaplanır.</p>
      <p class="small">DMA girişleri modelde sınırsız kaynak: terfi merkezi, iletim hattı ve elektrik kesintisi yok. Bu yüzden basınç yalnız hasarın çevresinde düşüyor; gerçekte daha geniş bir alanda düşebilir.</p></section>
    <footer class="p-foot">${footNote()}</footer>`;
}

const footNote = () => `Sentetik şebeke: yollar OpenStreetMap, kotlar Copernicus GLO-30, talep İBB verisi. Gerçek İSKİ şebekesi değildir; varsayımlar <code>twin/config.py</code> içinde.`;

function bind(el) {
  for (const b of el.querySelectorAll(".scen-opt")) b.addEventListener("click", () => set({ sc: b.dataset.sc, peek: false }));
  for (const b of el.querySelectorAll("#p-phases button")) b.addEventListener("click", () => set({ hour: Number(b.dataset.h), playing: false }));
}

// --- Saatlik güncelleme ------------------------------------------------------

function updateHour() {
  const h = state.hour;
  const sc = shownSc();
  $("p-hour").textContent = hh(h);
  if (state.mode === "quake") {
    const q = D.summary.quake;
    const H = q[sc].hourly;
    const after = h >= q.hour;
    const days = (1000 * H.clean_m3[h]) / (q.drink_lpcd * q.population);
    const sealed = h < q.hour + q.reopen_after_h ? q.smart_tanks : q.on.daily.sealed_tanks_end;
    const status = !after ? "Depremden önce" : sc === "on"
      ? `${fmt0.format(sealed)} depo mühürlü${H.risk_m3[h] > 0.5 ? `, ${fmt0.format(H.risk_m3[h])} m³ kirlenme riskinde` : ""}`
      : `Kirlenme riskinde ${fmt0.format(H.risk_m3[h])} m³`;
    $("p-res").innerHTML = reservoir(100 * H.clean_m3[h] / q.tank_m3, H.clean_m3[h], "Depolardaki temiz su",
      `${fmt0.format(q.tank_buildings)} depolu bina, ${fmt0.format(q.tank_m3)} m³ kapasite`, status);
    const min = D.summary.min_service_pressure_m;
    $("p-kpis").innerHTML =
      kpi("İçme suyu stoku", fmt1.format(days), `gün, ilçe nüfusuna ${fmt0.format(q.drink_lpcd)} L/kişi`, after && days < 3 ? "alarm" : "") +
      kpi("Hasardan kaçan su", fmt0.format(H.break_m3h[h]), "m³/sa", H.break_m3h[h] > 0 ? "alarm" : "") +
      kpi("Şebeke suyu şüpheli", fmt0.format(H.suspect_dmas[h]), `DMA, ${D.summary.counts.dmas} DMA içinde`, H.suspect_dmas[h] > 0 ? "alarm" : "") +
      kpi("En düşük basınç", fmt1.format(H.p_min[h]), "m", H.p_min[h] < min ? "alarm" : "") +
      kpi("Susuz", fmt0.format(H.dry_persons[h]), "kişi, bu saat", H.dry_persons[h] >= 1 ? "alarm" : "") +
      kpi("Temiz suyu olmayan", fmt0.format(H.no_clean_persons[h]), "kişi, binasında", H.no_clean_persons[h] >= 1 ? "alarm" : "");
    for (const b of document.querySelectorAll("#p-phases button")) {
      const from = Number(b.dataset.h);
      b.classList.toggle("on", from === 0 ? !after : after);
    }
  } else if (state.mode === "outage") {
    const o = D.summary.outage;
    const H = o[sc].hourly;
    const cap = o.tank_m3 || Math.max(...o.off.hourly.stored_m3, ...o.on.hourly.stored_m3);
    $("p-res").innerHTML = reservoir(100 * H.stored_m3[h] / cap, H.stored_m3[h], `${o.dma} depoları`,
      `${fmt0.format(o.tank_buildings)} binada depo, ${fmt0.format(o.buildings - o.tank_buildings)} bina deposuz`,
      trend(H.stored_m3, h, true));
    const cut = h >= o.start && h < o.end;
    const min = D.summary.min_service_pressure_m;
    $("p-kpis").innerHTML =
      kpi(`${o.dma} girişi`, cut ? "kapalı" : fmt0.format(H.inflow_m3h[h]), cut ? "planlı çalışma" : "m³/sa") +
      kpi("En düşük basınç", fmt1.format(H.p_min[h]), "m", !cut && H.p_min[h] < min ? "alarm" : "") +
      kpi("Basıncı yetersiz", fmt0.format(H.low_nodes[h]), `düğüm, ${min} m altı`, H.low_nodes[h] > 0 ? "alarm" : "") +
      kpi("Susuz", fmt0.format(H.unserved_ph[h]), "kişi, bu saat", H.unserved_ph[h] > 0 ? "alarm" : "");
    for (const b of document.querySelectorAll("#p-phases button")) {
      const from = Number(b.dataset.h);
      const to = from === 0 ? o.start : from === o.start ? o.end : 24;
      b.classList.toggle("on", h >= from && h < to);
    }
  } else {
    const s = D.summary;
    const H = s.scenarios[sc].hourly;
    const R = s.scenarios.off.hourly;
    const cap = s.tank_volume_m3;
    $("p-res").innerHTML = reservoir(100 * H.stored_m3[h] / cap, H.stored_m3[h], "Sanal baraj",
      `${fmt0.format(s.counts.smart_tanks)} akıllı depo, ${fmt0.format(cap)} m³ kapasite`,
      sc === "off" ? "Şamandıra: hep dolu" : trend(H.stored_m3, h, false), H.stored_hours[h]);
    const min = s.min_service_pressure_m;
    const d = (cur, ref, judge) => (sc === "off" ? "" : delta(cur, ref, judge));
    const sol = s.solar;
    const cost = sc === "solar" && sol
      ? kpi("Piyasa maliyeti", fmt0.format((H.pump_kw[h] * sol.price_tl_mwh[h]) / 1000), `TL/sa, fiyat ${fmt0.format(sol.price_tl_mwh[h])} TL/MWh`, "",
        // Fiyat sıfıra yakınken birkaç liralık farkın yüzdesi yanıltır; o saatte değişim gösterilmez
        sol.price_tl_mwh[h] < 200 ? "" : d(H.pump_kw[h] * sol.price_tl_mwh[h], R.pump_kw[h] * sol.price_tl_mwh[h]))
      : kpi("Basma maliyeti", fmt0.format(H.pump_tl[h]), "TL/sa", "", d(H.pump_tl[h], R.pump_tl[h]));
    $("p-kpis").innerHTML =
      kpi("Şebekeye giren", fmt0.format(H.inflow_m3h[h]), "m³/sa", "", d(H.inflow_m3h[h], R.inflow_m3h[h], "neutral")) +
      cost +
      kpi("Kaçak", fmt0.format(H.leak_m3h[h]), `m³/sa, giriş payı %${fmt1.format((100 * H.leak_m3h[h]) / H.inflow_m3h[h])}`, "", d(H.leak_m3h[h], R.leak_m3h[h])) +
      kpi("Ortalama basınç", fmt1.format(H.p_mean[h]), "m", "", d(H.p_mean[h], R.p_mean[h])) +
      kpi("En düşük basınç", fmt1.format(H.p_min[h]), "m", H.p_min[h] < min ? "alarm" : "") +
      kpi("Basıncı yetersiz", fmt0.format(H.low_nodes[h]), `düğüm, ${min} m altı`, H.low_nodes[h] > 0 ? "alarm" : "");
  }
  document.querySelectorAll(".flow-item").forEach((b) => {
    const e = events[Number(b.dataset.i)];
    b.classList.toggle("now", e.to !== e.from && inWindow(h, e));
  });
}

function trend(series, h, endOfHour) {
  const prev = endOfHour ? series[(h + 23) % 24] : series[h];
  const next = endOfHour ? series[h] : series[(h + 1) % 24];
  const dv = next - prev;
  if (Math.abs(dv) < 0.002 * Math.max(...series)) return "Dengede";
  return dv > 0 ? `Doluyor, +${fmt0.format(dv)} m³/sa` : `Kullanılıyor, −${fmt0.format(-dv)} m³/sa`;
}

function delta(cur, ref, judge = "lower") {
  const p = change(cur, ref);
  if (Math.abs(p) < 0.05) return "";
  const cls = judge === "neutral" ? "" : p < 0 ? "good" : "bad";
  return `<span class="delta ${cls}">${signedPct(p)}</span>`;
}

function kpi(label, value, unit, tone = "", deltaHtml = "") {
  return `<div class="kpi ${tone}"><span class="k">${label}</span><span class="v">${value}${deltaHtml}</span><span class="u">${unit}</span></div>`;
}

// Sanal baraj: vadiye yaslanmış bir baraj kesiti. Su seviyesi doluluk oranı, kesikli çizgi %40 yedek.
export function reservoir(fillPct, m3, title, sub, status, hours) {
  const f = Math.max(0, Math.min(100, fillPct));
  const reserve = 100 * ((D?.summary?.params?.reserve_fraction) ?? 0.4);
  const top = 10, bottom = 86, H = bottom - top;
  const yr = bottom - (H * reserve) / 100;
  const shift = (H * (100 - f)) / 100;
  return `
    <svg class="dam" viewBox="0 0 132 96" aria-hidden="true">
      <defs><clipPath id="dam-basin"><path d="M4 ${top}L26 ${bottom}H96L100 ${top}Z"/></clipPath></defs>
      <path class="dam-basin" d="M4 ${top}L26 ${bottom}H96L100 ${top}Z"/>
      <g clip-path="url(#dam-basin)">
        <g class="dam-water" style="transform:translateY(${shift.toFixed(1)}px)">
          <path class="dam-fill" d="M0 ${top}c10-3 20 3 30 0s20-3 30 0 20 3 30 0 20-3 30 0V${bottom + 2}H0Z"/>
        </g>
      </g>
      <line class="dam-reserve" x1="10" x2="99" y1="${yr}" y2="${yr}"/>
      <path class="dam-wall" d="M96 ${bottom}H124L110 ${top - 4}H100Z"/>
      <path class="dam-ground" d="M0 ${bottom}H132"/>
    </svg>
    <div class="dam-text">
      <span class="dam-title">${esc(title)}</span>
      <span class="dam-pct">%${fmt0.format(f)}</span>
      <span class="dam-m3">${fmt0.format(m3)} m³${hours !== undefined ? `, ${fmt0.format(hours)} saat yeter` : ""}</span>
      <span class="dam-status">${esc(status)}</span>
      <span class="dam-sub">${esc(sub)} · kesikli çizgi %${fmt0.format(reserve)} yedek</span>
    </div>`;
}

// --- Günün hesabı ------------------------------------------------------------

function cell(v, p, f, lower = true, active = false) {
  const cls = p === undefined || Math.abs(p) < 0.5 ? "" : (lower ? p < 0 : p > 0) ? "good" : "bad";
  const chip = p === undefined ? "" : `<small class="${cls}">${signedPct(p)}</small>`;
  return `<td class="${active ? "active" : ""}">${f(v)}${chip}</td>`;
}

function solarLedger() {
  const s = D.summary;
  const c = s.comparison, x = s.solar;
  const rows = [
    ["Piyasa maliyeti", "TL/gün", x.ptf_tl, (v) => fmt0.format(v), true],
    ["Güneş saatlerinde pompalama", "%", x.solar_share, (v) => fmt1.format(100 * v), false],
    ["Tepe debisi", "m³/sa", { off: c.peak_inflow_m3h.off, on: c.peak_inflow_m3h.on, solar: c.peak_inflow_m3h.solar }, (v) => fmt0.format(v), true],
    ["Basma enerjisi", "kWh/gün", { off: c.pump_kwh.off, on: c.pump_kwh.on, solar: c.pump_kwh.solar }, (v) => fmt0.format(v), true],
  ];
  const head = `<thead><tr><th></th><th>Kapalı</th><th>Akıllı depo</th><th class="active">Güneş</th></tr></thead>`;
  return head + "<tbody>" + rows.map(([label, unit, r, f, lower]) =>
    `<tr><th scope="row">${label}<span>${unit}</span></th><td>${f(r.off)}</td>${cell(r.on, r.off ? change(r.on, r.off) : undefined, f, lower)}${cell(r.solar, r.off ? change(r.solar, r.off) : undefined, f, lower, true)}</tr>`).join("") +
    "</tbody>" + `<caption class="small" style="caption-side:bottom;text-align:left;padding-top:0.5rem">Piyasa fiyatı: EPİAŞ Gün Öncesi Piyasası, ${esc(x.date)} (gerçek saatlik fiyat). Bugünkü tarifeyle optimize edilen akıllı depo bu günde ${fmt0.format(x.ptf_tl.on)} TL tutuyor.</caption>`;
}

function normalLedger(sc) {
  if (sc === "solar" && D.summary.solar) return solarLedger();
  const c = D.summary.comparison;
  const rows = [
    ["Tepe debisi", "m³/sa", "peak_inflow_m3h", (v) => fmt0.format(v), true],
    ["Puant payı", "%", "puant_share", (v) => fmt1.format(100 * v), true],
    ["Basma maliyeti", "TL/gün", "pump_tl", (v) => fmt0.format(v), true],
    ["Kaçak", "m³/gün", "leak_m3", (v) => fmt0.format(v), true],
    ["Ortalama basınç", "m", "p_mean", (v) => fmt1.format(v), true],
    ["Depoda su yaşı", "saat", "water_age_h", (v) => fmt1.format(v), true],
    ["En düşük yedek", "saat", "min_reserve_hours", (v) => fmt1.format(v), false],
  ];
  const head = `<thead><tr><th></th><th class="${sc === "off" ? "active" : ""}">Kapalı</th><th class="${sc === "on" ? "active" : ""}">Akıllı depo</th><th class="${sc === "pilot" ? "active" : ""}">+ Pilot</th></tr></thead>`;
  return head + "<tbody>" + rows.filter(([, , k]) => c[k]).map(([label, unit, k, f, lower]) => {
    const r = c[k];
    return `<tr><th scope="row">${label}<span>${unit}</span></th><td class="${sc === "off" ? "active" : ""}">${f(r.off)}</td>${cell(r.on, r.pct, f, lower, sc === "on")}${cell(r.pilot, r.pct_pilot, f, lower, sc === "pilot")}</tr>`;
  }).join("") + "</tbody>";
}

function quakeLedger() {
  const q = D.summary.quake;
  const sc = shownSc();
  const days = (m3) => (1000 * m3) / (q.drink_lpcd * q.population);
  const rows = [
    ["Temiz su, gün sonu", "m³", (d) => d.clean_m3_end, fmt0, false],
    ["İçme suyu, gün sonu", "gün", (d) => days(d.clean_m3_end), fmt1, false],
    ["Kirlenme riskindeki depo", "bina", (d) => d.risk_tanks, fmt0, true],
    ["Temiz suyu olmayan, gün sonu", "kişi", (d) => d.no_clean_end, fmt0, true],
    ["Susuz, depremden sonra", "kişi-saat", (d) => d.dry_ph, fmt0, true],
    ["Hasardan kaçan su", "m³", (d) => d.break_m3, fmt0, true],
    ["En düşük basınç", "m", (d) => d.p_min_after, fmt1, false],
  ];
  const head = `<thead><tr><th></th><th class="${sc === "off" ? "active" : ""}">Şamandıra</th><th class="${sc === "on" ? "active" : ""}">Akıllı kit</th></tr></thead>`;
  return head + "<tbody>" + rows.map(([label, unit, get, f, lower]) => {
    const a = get(q.off.daily), b = get(q.on.daily);
    const p = a ? change(b, a) : undefined;
    return `<tr><th scope="row">${label}<span>${unit}</span></th><td class="${sc === "off" ? "active" : ""}">${f.format(a)}</td>${cell(b, p, (v) => f.format(v), lower, sc === "on")}</tr>`;
  }).join("") + "</tbody>";
}

function outageLedger() {
  const o = D.summary.outage;
  const sc = shownSc();
  const rows = [
    ["Dönüşte tepe debisi", "m³/sa", "refill_peak_m3h", fmt0, true],
    ["Dönüşte en düşük basınç", "m", "min_pressure_after", fmt1, false],
    ["Dönüşte yetersiz basınç", "düğüm-saat", "low_node_hours_after", fmt0, true],
    ["Dönüş sonrası susuz", "kişi-saat", "unserved_after_ph", fmt0, true],
    ["Kesinti boyunca susuz", "kişi-saat", "unserved_during_ph", fmt0, true],
  ];
  const head = `<thead><tr><th></th><th class="${sc === "off" ? "active" : ""}">Şamandıra</th><th class="${sc === "on" ? "active" : ""}">Orkestratör</th></tr></thead>`;
  return head + "<tbody>" + rows.map(([label, unit, k, f, lower]) => {
    const a = o.off.daily[k], b = o.on.daily[k];
    const p = a ? change(b, a) : undefined;
    return `<tr><th scope="row">${label}<span>${unit}</span></th><td class="${sc === "off" ? "active" : ""}">${f.format(a)}</td>${cell(b, p, (v) => f.format(v), lower, sc === "on")}</tr>`;
  }).join("") + "</tbody>";
}
