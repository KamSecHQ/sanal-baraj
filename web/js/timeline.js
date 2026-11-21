// Alt şerit: oynat/durdur, saat, tarife ya da kesinti evresi ve sürüklenebilir 24 saatlik grafik.
import { state, set, shownSc } from "./state.js";
import { fmt0, fmt2, hh, $ } from "./format.js";
import { lineChart, groupBands } from "./charts.js";

const TARIFF = { gece: "Gece", gunduz: "Gündüz", puant: "Puant" };
let D = null;
let chart = null;
let timer = null;

export function setData(d) { D = d; }

export function init() {
  $("play").addEventListener("click", () => set({ playing: !state.playing }));
  $("speed").addEventListener("click", () => set({ speed: state.speed === 1 ? 2 : state.speed === 2 ? 4 : 1 }));
  const svg = $("dock-svg");
  let drag = false;
  const at = (e) => chart && set({ hour: chart.hourAt(e.clientX), playing: false });
  svg.addEventListener("pointerdown", (e) => { drag = true; svg.setPointerCapture(e.pointerId); at(e); });
  svg.addEventListener("pointermove", (e) => { if (drag) at(e); });
  svg.addEventListener("pointerup", () => { drag = false; });
  svg.addEventListener("keydown", (e) => {
    if (e.key === "Home") { set({ hour: 0 }); e.preventDefault(); }
    if (e.key === "End") { set({ hour: 23 }); e.preventDefault(); }
  });
  new ResizeObserver(() => render()).observe(svg);
}

// Oynatma: hız 1× saatte 0,8 sn
export function syncPlayback() {
  const btn = $("play");
  btn.setAttribute("aria-pressed", String(state.playing));
  btn.setAttribute("aria-label", state.playing ? "Durdur (boşluk)" : "Oynat (boşluk)");
  $("speed").textContent = `${state.speed}×`;
  clearInterval(timer);
  timer = null;
  if (state.playing) timer = setInterval(() => set({ hour: (state.hour + 1) % 24 }), 800 / state.speed);
}

export function render() {
  if (!D || state.mode === "istanbul") return;
  const s = D.summary;
  const h = state.hour;
  const sc = shownSc();
  $("time").textContent = hh(h);
  $("dock-svg").setAttribute("aria-valuenow", String(h));
  $("dock-svg").setAttribute("aria-valuetext", hh(h));
  const phase = $("phase");

  if (state.mode === "outage") {
    const o = s.outage;
    const cut = h >= o.start && h < o.end;
    phase.textContent = h < o.start ? "Kesintiden önce" : cut ? `Kesinti, ${o.dma} susuz` : "Su geri geldi";
    phase.className = `phase ${cut ? "alarm" : h >= o.end ? "water" : ""}`;
    $("dock-title").textContent = `${o.dma} giriş debisi, m³/sa`;
    $("dock-legend").innerHTML = `<i class="sw off"></i>Şamandıra <i class="sw on"></i>Orkestratör <i class="sw cut"></i>Kesinti <i class="sw ref"></i>Normal günün tepesi`;
    chart = lineChart($("dock-svg"), {
      series: [
        { values: o.off.hourly.inflow_m3h, cls: "off", main: sc === "off", area: sc === "off" },
        { values: o.on.hourly.inflow_m3h, cls: "on", main: sc === "on", area: sc === "on" },
      ],
      bands: [{ from: o.start, to: o.end, cls: "cut", label: "Kesinti" }],
      refs: [{ y: o.off.daily.normal_peak_m3h, cls: "peak" }],
      cursor: h, cursorFmt: (v) => `${fmt0.format(v)} m³/sa`,
    });
    return;
  }
  if (state.mode === "quake") {
    const q = s.quake;
    const after = h >= q.hour;
    const d = q.off.daily;
    phase.textContent = after ? `Deprem: ${fmt0.format(d.breaks)} kırık, ${fmt0.format(d.leaks)} sızıntı` : "Depremden önce, gece";
    phase.className = `phase ${after ? "alarm" : "water"}`;
    $("dock-title").textContent = "Depolardaki temiz su, m³";
    $("dock-legend").innerHTML = `<i class="sw off"></i>Şamandıra <i class="sw on"></i>Akıllı kit <i class="sw cut"></i>Deprem sonrası <i class="sw ref"></i>Depo kapasitesi`;
    chart = lineChart($("dock-svg"), {
      series: [
        { values: q.off.hourly.clean_m3, cls: "off", main: sc === "off", area: sc === "off" },
        { values: q.on.hourly.clean_m3, cls: "on", main: sc === "on", area: sc === "on" },
      ],
      bands: [{ from: q.hour, to: 24, cls: "cut", label: "Deprem" }],
      refs: [{ y: q.tank_m3, cls: "peak" }],
      cursor: h, cursorFmt: (v) => `${fmt0.format(v)} m³`,
    });
    return;
  }
  if (state.mode === "leak") {
    const L = D.leak;
    phase.textContent = L ? "Gece en düşük debi saatlerinde ölçüm" : "";
    phase.className = "phase";
    $("dock-title").textContent = "DMA girişindeki debi, m³/sa";
    $("dock-legend").innerHTML = `<i class="sw on"></i>Sızıntıyla <i class="sw off"></i>Sızıntısız <span>akıllı depo senaryosu, sabit ${String(L?.leak_lps ?? "").replace(".", ",")} L/s</span>`;
    const ev = L?.events[state.leakEvent];
    if (!ev) { $("dock-svg").innerHTML = ""; return; }
    const lo = Math.min(...ev.inflow_base), hi = Math.max(...ev.inflow_leak);
    const yMin = Math.max(0, Math.floor((lo - 0.6 * (hi - lo + 10)) / 10) * 10);
    chart = lineChart($("dock-svg"), {
      yMin, yMax: Math.ceil((hi + 0.4 * (hi - lo + 10)) / 10) * 10,
      series: [
        { values: ev.inflow_base, cls: "off", ghost: false },
        { values: ev.inflow_leak, cls: "on", main: true },
      ],
      bands: groupBands(L.night_hours ? Array.from({ length: 24 }, (_, i) => L.night_hours.includes(i) && "gece") : [], "night", () => "Ölçüm"),
      cursor: h, cursorFmt: (v) => `${fmt0.format(v)} m³/sa`,
    });
    return;
  }

  const period = s.tariff.period[h];
  const S = s.scenarios;
  const solar = sc === "solar" && s.solar;
  if (solar) {
    const price = s.solar.price_tl_mwh[h];
    const [a, b] = s.solar.hours;
    phase.textContent = `Piyasa fiyatı ${fmt0.format(price)} TL/MWh`;
    phase.className = `phase ${h >= a && h < b ? "ochre" : ""}`;
  } else {
    phase.textContent = `${TARIFF[period]} tarifesi, ${fmt2.format(s.tariff.tl_per_kwh[period])} TL/kWh`;
    phase.className = `phase ${period === "puant" ? "ochre" : period === "gece" ? "water" : ""}`;
  }
  $("dock-title").textContent = "Şebekeye giren su, m³/sa";
  $("dock-legend").innerHTML = `<i class="sw off"></i>Kapalı <i class="sw on"></i>Akıllı depo <i class="sw pilot"></i>+ Pilot${S.solar ? ` <i class="sw solar"></i>Güneş` : ""}`;
  chart = lineChart($("dock-svg"), {
    series: ["off", "on", "pilot", "solar"].filter((k) => S[k] && (k !== "solar" || sc === "solar") && (k !== "pilot" || sc !== "solar")).map((k) => ({
      values: S[k].hourly.inflow_m3h, cls: k, main: k === sc, area: k === sc,
    })),
    bands: solar ? [{ from: s.solar.hours[0], to: s.solar.hours[1], cls: "sun", label: "Güneş saatleri" }]
      : groupBands(s.tariff.period.map((p) => (p === "gunduz" ? false : p)), (p) => p, (p) => TARIFF[p]),
    cursor: h, cursorFmt: (v) => `${fmt0.format(v)} m³/sa`,
  });
}
