// Harita: altlık, katmanlar, saat ve senaryoya göre renkler, üzerine gelme ve seçim.
// Bizim kaynak ve katmanlarımız "sb-" ile başlar; tema değişince altlık değişir, bunlar korunur.
import { state, shownSc } from "./state.js";

const STYLES = {
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
};

// Tema başına harita renkleri. Basınç rampası iki temada da aynı anlamı taşır: kırmızı yetersiz, mor aşırı.
export const PAL = {
  dark: {
    bg: "#0A161D",
    pressure: ["#FF5A4E", 15, "#F2B544", 25, "#3CC8A8", 45, "#4AA3F0", 60, "#A57CF5"],
    pipeFlow: ["#24505E", "#3A8BA1", "#4FC0D8", "#9CE8F5", "#E8FBFF"],
    pipeDim: "#2C5562", pipeClosed: "#8EA1A8",
    bNone: "#25414C", bFull: "#2E6B7E", bLow: "#E6A64A", bMid: "#56B3C8", bHigh: "#A8E7F3", bDry: "#E0482F", bDim: "#17282F",
    dma: "#42B9DD", dmaOut: "#F2925C", inletFill: "#E8F1F3", prv: "#EBA43C", sel: "#FFFFFF",
    ist: ["#13303B", "#1D5566", "#2A8099", "#55B5CF", "#B5EAF5"], istLine: "#0A161D", istMain: "#EBA43C",
    leakHeat: ["rgba(242,90,67,0)", "rgba(242,90,67,0.35)", "#F25A43", "#FFD08A"], leakTrue: "#FFFFFF",
    bRisk: "#B9732F", quakeDays: ["#E0482F", "#E6A64A", "#3CC8A8", "#4AA3F0"], quakeBreak: "#FF5A4E", quakeLine: "#E8F1F3",
  },
  light: {
    bg: "#E6ECEE",
    pressure: ["#D7362B", 15, "#E09612", 25, "#169C76", 45, "#2C79C9", 60, "#8150D1"],
    pipeFlow: ["#A9C0C8", "#6E9DAE", "#2F7F9C", "#0C5A78", "#05334A"],
    pipeDim: "#B9C9CF", pipeClosed: "#7D8E95",
    bNone: "#C9D4D8", bFull: "#86B3C3", bLow: "#E39A2D", bMid: "#3E9DB8", bHigh: "#0B6F91", bDry: "#D2391F", bDim: "#DDE4E6",
    dma: "#0A7EA6", dmaOut: "#D2611F", inletFill: "#0E2430", prv: "#C27500", sel: "#0E2430",
    ist: ["#E4EEF1", "#B4D6E0", "#6FB2C8", "#2B87A6", "#0B5873"], istLine: "#FFFFFF", istMain: "#C27500",
    leakHeat: ["rgba(210,57,31,0)", "rgba(210,57,31,0.3)", "#D2391F", "#7A1A0B"], leakTrue: "#0E2430",
    bRisk: "#9A5A1C", quakeDays: ["#D7362B", "#E09612", "#169C76", "#2C79C9"], quakeBreak: "#D2391F", quakeLine: "#0E2430",
  },
};
// Deprem günü alan renginin durakları: alan nüfusuna kaç günlük temiz içme suyu
export const QUAKE_DAY_STOPS = [0, 3, 10, 30];

const DISTRICT_LAYERS = ["sb-dma-fill", "sb-dma-line", "sb-buildings", "sb-pipes-closed", "sb-pipes", "sb-nodes", "sb-inlets", "sb-prvs"];
const LEAK_LAYERS = ["sb-leak-heat", "sb-leak-sensors", "sb-leak-true", "sb-leak-guess"];
const QUAKE_LAYERS = ["sb-quake-fill", "sb-quake-line", "sb-quake-breaks"];
const IST_LAYERS = ["sb-ist-fill", "sb-ist-line", "sb-ist-main", "sb-ist-sel"];
const SEL_LAYERS = ["sb-sel-fill", "sb-sel-line", "sb-sel-point"];
const KIND = {
  "sb-buildings": "building", "sb-nodes": "node", "sb-pipes": "pipe", "sb-prvs": "prv", "sb-inlets": "inlet",
  "sb-dma-fill": "dma", "sb-ist-fill": "ilce", "sb-leak-guess": "leakguess", "sb-quake-breaks": "qbreak", "sb-quake-fill": "qarea",
};
const PICK_ORDER = ["sb-leak-guess", "sb-quake-breaks", "sb-prvs", "sb-inlets", "sb-nodes", "sb-pipes", "sb-buildings", "sb-quake-fill", "sb-dma-fill", "sb-ist-fill"];
const EMPTY = { type: "FeatureCollection", features: [] };

let map = null;
let data = null;
let online = true;
let hooks = {};

const fallbackStyle = (theme) => ({
  version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": PAL[theme].bg } }],
});

async function styleFor(theme) {
  if (!online) return fallbackStyle(theme);
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 3500);
    const r = await fetch(STYLES[theme], { signal: ctrl.signal });
    clearTimeout(t);
    if (r.ok) return STYLES[theme];
  } catch (_) { /* internet yok: düz zemin */ }
  online = false;
  return fallbackStyle(theme);
}

export const getMap = () => map;
export const isOnline = () => online;

export async function createMap(theme, center, h) {
  hooks = h;
  const style = await styleFor(theme);
  map = new maplibregl.Map({
    container: "map", style, center: center || [28.97, 41.03], zoom: 12, pitch: 0, bearing: 0,
    attributionControl: false, fadeDuration: 0,
  });
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.AttributionControl({ compact: true,
    customAttribution: "Şebeke © OpenStreetMap katkıcıları · Copernicus GLO-30 · İBB Açık Veri" }), "bottom-left");
  // Altlık karolarını bekleme ("load" onları da bekler): yavaş internette bile ikiz hemen açılsın
  await new Promise((res) => (map.isStyleLoaded() ? res() : map.once("style.load", res)));
  // Kaynak satırı kapalı başlasın; (i) düğmesiyle açılır
  document.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
  bindPointer();
  window.__sbMap = map;   // tarayıcı konsolunda inceleme için
  return map;
}

export async function setTheme(theme) {
  if (!map) return;
  const next = await styleFor(theme);
  map.setStyle(next, {
    diff: false,
    transformStyle: (prev, nextStyle) => {
      if (!prev) return nextStyle;
      const sources = { ...nextStyle.sources };
      for (const [k, v] of Object.entries(prev.sources)) if (k.startsWith("sb-")) sources[k] = v;
      return { ...nextStyle, sources, layers: [...nextStyle.layers, ...prev.layers.filter((l) => l.id.startsWith("sb-"))] };
    },
  });
  map.once("style.load", () => { if (data) restoreData(); update(); });
}

// Stil değişince GeoJSON kaynakları serileştirilmiş halleriyle geri gelir; büyük veriyi tekrar bağla
function restoreData() {
  for (const [id, fc] of Object.entries(sourceData)) map.getSource(id)?.setData(fc);
}
const sourceData = {};
function addSource(id, fc) {
  sourceData[id] = fc;
  if (map.getSource(id)) map.getSource(id).setData(fc);
  else map.addSource(id, { type: "geojson", data: fc, generateId: true });
}

export function setDistrict(d) {
  data = d;
  const P = PAL[state.theme];
  addSource("sb-dmas", d.dmas);
  addSource("sb-buildings", d.buildings);
  addSource("sb-pipes", d.pipes);
  addSource("sb-nodes", d.nodes);
  addSource("sb-inlets", d.inlets);
  addSource("sb-prvs", d.prvs);
  addSource("sb-sel", EMPTY);
  addSource("sb-leak", EMPTY);
  addSource("sb-quake", quakeFeatures(d.quake));
  if (map.getLayer("sb-dma-fill")) return;

  map.addLayer({ id: "sb-dma-fill", type: "fill", source: "sb-dmas", paint: { "fill-color": P.dma, "fill-opacity": 0.03 } });
  map.addLayer({ id: "sb-dma-line", type: "line", source: "sb-dmas", paint: { "line-dasharray": [3, 2], "line-color": P.dma } });
  // Deprem günü: alan (mahalle ya da DMA) başına temiz su, binaların altında
  map.addLayer({ id: "sb-quake-fill", type: "fill", source: "sb-quake", filter: ["==", ["get", "k"], "area"],
    layout: { visibility: "none" }, paint: { "fill-opacity": 0.3 } });
  map.addLayer({ id: "sb-quake-line", type: "line", source: "sb-quake", filter: ["==", ["get", "k"], "area"],
    layout: { visibility: "none" }, paint: { "line-width": 1.2, "line-opacity": 0.55 } });
  map.addLayer({ id: "sb-buildings", type: "fill-extrusion", source: "sb-buildings", minzoom: 12,
    paint: { "fill-extrusion-height": ["get", "h"], "fill-extrusion-opacity": 0.82, "fill-extrusion-color": P.bNone } });
  map.addLayer({ id: "sb-pipes-closed", type: "line", source: "sb-pipes",
    paint: { "line-color": P.pipeClosed, "line-opacity": 0.55, "line-width": 1, "line-dasharray": [1, 2] } });
  map.addLayer({ id: "sb-pipes", type: "line", source: "sb-pipes", layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-width": ["interpolate", ["linear"], ["zoom"],
      11, ["interpolate", ["linear"], ["get", "d"], 100, 0.6, 600, 2.6],
      16, ["interpolate", ["linear"], ["get", "d"], 100, 2.2, 600, 9]] } });
  map.addLayer({ id: "sb-nodes", type: "circle", source: "sb-nodes",
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 0.8, 13, 1.3, 15, 3, 17, 6], "circle-stroke-width": 0 } });
  map.addLayer({ id: "sb-inlets", type: "circle", source: "sb-inlets",
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 1.8, 15, 5.5], "circle-color": P.bg,
      "circle-stroke-color": P.inletFill, "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 11, 1, 15, 2.5] } });
  map.addLayer({ id: "sb-prvs", type: "circle", source: "sb-prvs",
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, ["interpolate", ["linear"], ["get", "rank"], 1, 5, 40, 3],
      15, ["interpolate", ["linear"], ["get", "rank"], 1, 12, 40, 7]],
    "circle-color": P.prv, "circle-stroke-color": P.bg, "circle-stroke-width": 1.5 } });
  // Sızıntı avı: olası yerlerin ısısı, sensörler, gerçek sızıntı (yalnız sızıntı modunda görünür)
  map.addLayer({ id: "sb-leak-sensors", type: "circle", source: "sb-leak", filter: ["==", ["get", "k"], "sensor"],
    layout: { visibility: "none" },
    paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4], "circle-color": P.dma, "circle-opacity": 0.6 } });
  map.addLayer({ id: "sb-leak-heat", type: "circle", source: "sb-leak", filter: ["==", ["get", "k"], "cand"],
    layout: { visibility: "none" }, paint: {} });
  map.addLayer({ id: "sb-leak-guess", type: "circle", source: "sb-leak", filter: ["==", ["get", "k"], "guess"],
    layout: { visibility: "none" }, paint: {} });
  map.addLayer({ id: "sb-leak-true", type: "circle", source: "sb-leak", filter: ["==", ["get", "k"], "true"],
    layout: { visibility: "none" }, paint: {} });
  map.addLayer({ id: "sb-quake-breaks", type: "circle", source: "sb-quake", filter: ["==", ["get", "k"], "break"],
    layout: { visibility: "none" }, paint: {} });
  map.addLayer({ id: "sb-sel-fill", type: "fill-extrusion", source: "sb-sel", filter: ["==", ["get", "_k"], "building"],
    paint: { "fill-extrusion-height": ["+", ["get", "h"], 1.5], "fill-extrusion-color": P.sel, "fill-extrusion-opacity": 0.95 } });
  map.addLayer({ id: "sb-sel-line", type: "line", source: "sb-sel", filter: ["in", ["get", "_k"], ["literal", ["pipe", "dma", "ilce", "qarea"]]],
    layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": P.sel, "line-width": 3.5 } });
  map.addLayer({ id: "sb-sel-point", type: "circle", source: "sb-sel", filter: ["in", ["get", "_k"], ["literal", ["node", "prv", "inlet", "leakguess", "qbreak"]]],
    paint: { "circle-radius": 9, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": P.sel, "circle-stroke-width": 2.5 } });
}

// Deprem günü kaynağı: alanlar (saat başına temiz su günü: o{h} şamandıra, a{h} kit) ve hasar noktaları
export function quakeFeatures(q) {
  if (!q) return EMPTY;
  const f = [];
  q.areas.forEach((a, i) => {
    if (!a.geometry) return;
    const props = { k: "area", i, name: a.name };
    for (let h = 0; h < 24; h++) { props[`o${h}`] = a.days.off[h]; props[`a${h}`] = a.days.on[h]; }
    f.push({ type: "Feature", geometry: a.geometry, properties: props });
  });
  q.breaks.forEach((b, i) => {
    f.push({ type: "Feature", geometry: { type: "Point", coordinates: b.ll },
      properties: { k: "break", i, kind: b.kind, d: b.d, dma: b.dma_id } });
  });
  return { type: "FeatureCollection", features: f };
}

export function setLeakFeatures(fc) {
  sourceData["sb-leak"] = fc;
  map.getSource("sb-leak")?.setData(fc);
}

export function setIstanbul(geo) {
  const P = PAL[state.theme];
  addSource("sb-ist", geo);
  addSource("sb-ist-sel", EMPTY);
  if (map.getLayer("sb-ist-fill")) return;
  const before = map.getLayer("sb-dma-fill") ? "sb-dma-fill" : undefined;
  map.addLayer({ id: "sb-ist-fill", type: "fill", source: "sb-ist", layout: { visibility: "none" },
    paint: { "fill-opacity": 0.82, "fill-color": P.ist[0] } }, before);
  map.addLayer({ id: "sb-ist-line", type: "line", source: "sb-ist", layout: { visibility: "none" },
    paint: { "line-color": P.istLine, "line-width": 1 } }, before);
  map.addLayer({ id: "sb-ist-main", type: "line", source: "sb-ist", layout: { visibility: "none" },
    paint: { "line-color": P.istMain, "line-width": 2.5 } }, before);
  map.addLayer({ id: "sb-ist-sel", type: "line", source: "sb-ist-sel", layout: { visibility: "none" },
    paint: { "line-color": P.sel, "line-width": 3 } }, before);
}

export function setSelection(feature, kind) {
  const fc = feature ? { type: "FeatureCollection", features: [{ ...feature, properties: { ...feature.properties, _k: kind } }] } : EMPTY;
  sourceData["sb-sel"] = fc;
  map?.getSource("sb-sel")?.setData(fc);
}

export function setIstanbulSelection(feature) {
  const fc = feature ? { type: "FeatureCollection", features: [feature] } : EMPTY;
  sourceData["sb-ist-sel"] = fc;
  map?.getSource("sb-ist-sel")?.setData(fc);
}

// Panellerin kapladığı alanı haritanın kenar boşluğu olarak hesapla
export function padding() {
  const W = window.innerWidth, H = window.innerHeight;
  // Sabit konumlu ögelerde offsetParent hep boştur; görünürlüğü stilden oku
  const rect = (id) => {
    const el = document.getElementById(id);
    if (!el || el.hidden || getComputedStyle(el).display === "none") return null;
    const r = el.getBoundingClientRect();
    return r.width && r.height ? r : null;
  };
  const pad = { top: 72, bottom: 40, left: 40, right: 60 };
  const top = document.querySelector(".topbar")?.getBoundingClientRect();
  if (top) pad.top = top.bottom + 24;
  if (W > 900) {
    const p = rect("panel") || rect("story");
    if (p) pad.left = p.right + 32;
    const i = rect("inspector");
    if (i) pad.right = W - i.left + 32;
    const d = rect("dock");
    if (d) pad.bottom = H - d.top + 24;
  } else {
    // Dar ekranda paneller alttan açılır: en üstteki alt panelin üstüne sığdır
    const tops = ["panel", "story", "inspector", "dock"].map(rect).filter(Boolean).map((r) => r.top);
    pad.bottom = tops.length ? H - Math.min(...tops) + 16 : 40;
    const lg = rect("legend");
    if (lg) pad.top = Math.max(pad.top, lg.bottom - 0 + 12);
    pad.left = 16; pad.right = 56;
  }
  return pad;
}

export function fitTo(bbox, opts = {}) {
  if (!map || !bbox) return;
  const [x0, y0, x1, y1] = bbox;
  const narrow = window.innerWidth <= 960;   // telefonda düz harita: sığdırma eğik görünümde taşar
  map.fitBounds([[x0, y0], [x1, y1]], {
    padding: padding(), pitch: narrow ? 0 : opts.pitch ?? 40, bearing: narrow ? 0 : opts.bearing ?? -12,
    duration: opts.duration ?? 900, maxZoom: opts.maxZoom ?? 16.5, essential: true,
  });
}

// --- Renklendirme --------------------------------------------------------------

const vis = (id, on) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");

function buildingColor(P, mode, sc, h) {
  const s = data.summary;
  if (mode === "outage") {
    const l = `${sc === "on" ? "oal" : "ol"}${h}`;
    const outId = (s.dmas.find((d) => d.name === s.outage.dma) || {}).id ?? -1;
    const cut = h >= s.outage.start && h < s.outage.end;
    return ["case",
      ["has", l], ["interpolate", ["linear"], ["get", l], 0, P.bDry, 40, P.bLow, 70, P.bMid, 100, P.bHigh],
      ["all", ["==", ["get", "dma"], outId], ["==", ["get", "tv"], 0]], cut ? P.bDry : P.bNone,
      P.bDim];
  }
  if (mode === "quake") {
    const q = s.quake;
    if (h < q.hour) return sc === "off" ? ["case", [">", ["get", "tv"], 0], P.bFull, P.bNone] : ["case", [">", ["get", "tv"], 0], P.bHigh, P.bNone];
    const risk = sc === "on" ? "eka" : "ek";
    const sus = suspectDmaIds(sc, h);
    return ["case",
      [">", ["get", "tv"], 0], ["case", ["all", ["has", risk], ["<=", ["get", risk], h]], P.bRisk, P.bHigh],
      ["in", ["get", "dma"], ["literal", sus]], P.bDry,
      P.bNone];
  }
  if (mode === "leak") return ["case", [">", ["get", "tv"], 0], P.bDim, P.bDim];
  if (sc === "off") return ["case", [">", ["get", "tv"], 0], P.bFull, P.bNone];
  return ["case",
    ["has", `l${h}`], ["interpolate", ["linear"], ["get", `l${h}`], 40, P.bLow, 70, P.bMid, 100, P.bHigh],
    [">", ["get", "tv"], 0], P.bFull, P.bNone];
}

// Deprem günü: bu saatte şebeke suyu şüpheli olan DMA'ların numaraları
export function suspectDmaIds(sc, h) {
  const dmas = data?.quake?.dmas || {};
  return Object.values(dmas).filter((d) => d.suspect[sc] !== null && d.suspect[sc] !== undefined && d.suspect[sc] <= h).map((d) => d.id);
}

export function update() {
  if (!map || !data || !map.getLayer("sb-nodes")) return;
  const P = PAL[state.theme];
  const mode = state.mode;
  const sc = shownSc();
  const h = state.hour;
  const L = state.layers;
  const ist = mode === "istanbul";

  for (const id of IST_LAYERS) vis(id, ist);
  for (const id of LEAK_LAYERS) vis(id, mode === "leak");
  for (const id of QUAKE_LAYERS) vis(id, mode === "quake" && (id === "sb-quake-breaks" ? state.hour >= (data.summary.quake?.hour ?? 0) : L.areas));
  for (const id of SEL_LAYERS) vis(id, true);
  if (ist) {
    for (const id of DISTRICT_LAYERS) vis(id, false);
    updateIstanbul(P);
    return;
  }
  vis("sb-buildings", L.buildings);
  vis("sb-pipes", L.pipes);
  vis("sb-pipes-closed", L.pipes);
  vis("sb-nodes", L.nodes && mode !== "leak");
  vis("sb-dma-fill", L.dmas);
  vis("sb-dma-line", L.dmas);
  vis("sb-inlets", L.dmas && mode !== "leak");
  vis("sb-prvs", L.prvs && mode === "normal" && sc === "pilot");

  const pilot = mode === "normal" && sc === "pilot";
  if (mode === "quake") {
    const qp = `${sc === "on" ? "ea" : "e"}${h}`;
    map.setPaintProperty("sb-nodes", "circle-color", ["case", ["has", qp], ["step", ["get", qp], ...P.pressure], P.pipeDim]);
    map.setPaintProperty("sb-nodes", "circle-opacity", ["interpolate", ["linear"], ["zoom"], 12, 0.55, 15, 1]);
    map.setPaintProperty("sb-pipes", "line-color", P.pipeDim);
    map.setPaintProperty("sb-pipes", "line-opacity", 0.6);
    updateQuake(P, sc, h);
  } else if (mode === "outage") {
    const op = `${sc === "on" ? "oa" : "o"}${h}`;
    map.setPaintProperty("sb-nodes", "circle-color", ["case", ["has", op], ["step", ["get", op], ...P.pressure], P.pipeDim]);
    map.setPaintProperty("sb-nodes", "circle-opacity", ["case", ["has", "o0"], 1, 0.25]);
    map.setPaintProperty("sb-pipes", "line-color", P.pipeDim);
    map.setPaintProperty("sb-pipes", "line-opacity", 0.55);
  } else if (mode === "leak") {
    map.setPaintProperty("sb-pipes", "line-color", P.pipeDim);
    map.setPaintProperty("sb-pipes", "line-opacity", 0.7);
    updateLeak(P);
  } else {
    const pre = { off: ["p", "q"], on: ["pa", "qa"], pilot: ["pb", "qb"] }[sc];
    map.setPaintProperty("sb-nodes", "circle-color", ["step", ["get", `${pre[0]}${h}`], ...P.pressure]);
    map.setPaintProperty("sb-nodes", "circle-opacity", ["interpolate", ["linear"], ["zoom"], 12, 0.55, 15, 1]);
    const f = P.pipeFlow;
    map.setPaintProperty("sb-pipes", "line-color", ["interpolate", ["linear"], ["get", `${pre[1]}${h}`], 0, f[0], 2, f[1], 10, f[2], 40, f[3], 150, f[4]]);
    map.setPaintProperty("sb-pipes", "line-opacity", 0.92);
  }
  map.setFilter("sb-pipes", pilot ? ["all", ["==", ["get", "b"], 0], ["==", ["get", "bp"], 0]] : ["==", ["get", "b"], 0]);
  map.setFilter("sb-pipes-closed", pilot ? ["any", ["==", ["get", "b"], 1], ["==", ["get", "bp"], 1]] : ["==", ["get", "b"], 1]);
  map.setPaintProperty("sb-buildings", "fill-extrusion-color", buildingColor(P, mode, sc, h));
  const out = mode === "outage";
  // Kesinti günü: kesinti DMA'sı; deprem günü: şebeke suyu şüpheli DMA'lar vurgulanır
  const hot = out ? ["==", ["get", "out"], 1]
    : mode === "quake" ? ["in", ["get", "dma"], ["literal", suspectDmaIds(sc, h)]] : null;
  map.setPaintProperty("sb-dma-line", "line-color", hot ? ["case", hot, P.dmaOut, P.dma] : P.dma);
  map.setPaintProperty("sb-dma-line", "line-width", hot ? ["case", hot, 2.6, 1] : 1.1);
  map.setPaintProperty("sb-dma-line", "line-opacity", hot ? ["case", hot, 0.95, 0.2] : 0.4);
  map.setPaintProperty("sb-dma-fill", "fill-color", hot ? ["case", hot, P.dmaOut, P.dma] : P.dma);
  map.setPaintProperty("sb-dma-fill", "fill-opacity", hot ? ["case", hot, out ? 0.06 : 0.0, 0.0] : 0.03);
  map.setPaintProperty("sb-inlets", "circle-stroke-color", P.inletFill);
  map.setPaintProperty("sb-inlets", "circle-color", P.bg);
  map.setPaintProperty("sb-prvs", "circle-color", P.prv);
  map.setPaintProperty("sb-prvs", "circle-stroke-color", P.bg);
  map.setPaintProperty("sb-pipes-closed", "line-color", P.pipeClosed);
  map.setPaintProperty("sb-sel-fill", "fill-extrusion-color", P.sel);
  map.setPaintProperty("sb-sel-line", "line-color", P.sel);
  map.setPaintProperty("sb-sel-point", "circle-stroke-color", P.sel);
}

function updateQuake(P, sc, h) {
  const key = `${sc === "on" ? "a" : "o"}${h}`;
  const st = QUAKE_DAY_STOPS;
  map.setPaintProperty("sb-quake-fill", "fill-color", ["interpolate", ["linear"], ["get", key],
    st[0], P.quakeDays[0], st[1], P.quakeDays[1], st[2], P.quakeDays[2], st[3], P.quakeDays[3]]);
  map.setPaintProperty("sb-quake-line", "line-color", P.quakeLine);
  map.setPaintProperty("sb-quake-breaks", "circle-radius", ["interpolate", ["linear"], ["zoom"], 11,
    ["case", ["==", ["get", "kind"], "kirik"], 6, 3.5], 16, ["case", ["==", ["get", "kind"], "kirik"], 15, 9]]);
  map.setPaintProperty("sb-quake-breaks", "circle-color", ["case", ["==", ["get", "kind"], "kirik"], P.quakeBreak, "rgba(0,0,0,0)"]);
  map.setPaintProperty("sb-quake-breaks", "circle-stroke-color", P.quakeBreak);
  map.setPaintProperty("sb-quake-breaks", "circle-stroke-width", 2.5);
}

function updateLeak(P) {
  const sc = shownSc();
  // Isı: olasılık payı (0–1) yarıçap ve renkle; kapalıda (yalnız DMA sayacı) bütün bölge aynı soluk renkte
  const pv = sc === "on" ? "pa" : "po";
  map.setPaintProperty("sb-leak-heat", "circle-radius", ["interpolate", ["linear"], ["zoom"], 12,
    ["interpolate", ["linear"], ["get", pv], 0, 1.5, 1, 9], 16, ["interpolate", ["linear"], ["get", pv], 0, 3, 1, 26]]);
  map.setPaintProperty("sb-leak-heat", "circle-color", ["interpolate", ["linear"], ["get", pv], 0, P.leakHeat[0], 0.15, P.leakHeat[1], 0.6, P.leakHeat[2], 1, P.leakHeat[3]]);
  map.setPaintProperty("sb-leak-heat", "circle-blur", 0.35);
  map.setPaintProperty("sb-leak-guess", "circle-radius", ["interpolate", ["linear"], ["zoom"], 12, 5, 16, 11]);
  map.setPaintProperty("sb-leak-guess", "circle-color", "rgba(0,0,0,0)");
  map.setPaintProperty("sb-leak-guess", "circle-stroke-color", P.prv);
  map.setPaintProperty("sb-leak-guess", "circle-stroke-width", 2.5);
  map.setPaintProperty("sb-leak-true", "circle-radius", ["interpolate", ["linear"], ["zoom"], 12, 4, 16, 8]);
  map.setPaintProperty("sb-leak-true", "circle-color", P.leakTrue);
  map.setPaintProperty("sb-leak-true", "circle-stroke-color", P.bDry);
  map.setPaintProperty("sb-leak-true", "circle-stroke-width", 3);
  map.setPaintProperty("sb-leak-sensors", "circle-color", P.dma);
  vis("sb-leak-sensors", sc === "on");
  vis("sb-leak-guess", sc === "on");
}

export function istanbulRamp(metric, rows) {
  const vals = rows.map((r) => r[metric]).filter(Number.isFinite).sort((a, b) => a - b);
  const q = (p) => vals[Math.min(vals.length - 1, Math.floor(p * (vals.length - 1)))];
  return [q(0), q(0.25), q(0.5), q(0.75), q(1)];
}

let istRows = [];
let istMain = null;
export function setIstanbulRows(rows, main) { istRows = rows; istMain = main; }

function updateIstanbul(P) {
  if (!map.getLayer("sb-ist-fill")) return;
  const m = state.metric;
  const stops = istanbulRamp(m, istRows);
  const expr = ["interpolate", ["linear"], ["to-number", ["get", m], 0]];
  // Eşit değerli duraklar ifadeyi bozar; artan olmasını sağla
  let last = -Infinity;
  stops.forEach((v, i) => { const s = Math.max(v, last + 1e-6); expr.push(s, P.ist[i]); last = s; });
  map.setPaintProperty("sb-ist-fill", "fill-color", expr);
  map.setPaintProperty("sb-ist-line", "line-color", P.istLine);
  map.setPaintProperty("sb-ist-main", "line-color", P.istMain);
  map.setFilter("sb-ist-main", ["==", ["get", "ilce"], istMain || ""]);
  map.setPaintProperty("sb-ist-sel", "line-color", P.sel);
}

// --- Üzerine gelme ve seçim ----------------------------------------------------

function pickLayers() {
  return PICK_ORDER.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");
}

function pick(point) {
  const layers = pickLayers();
  if (!layers.length) return null;
  const bbox = [[point.x - 4, point.y - 4], [point.x + 4, point.y + 4]];
  const hits = map.queryRenderedFeatures(bbox, { layers });
  if (!hits.length) return null;
  hits.sort((a, b) => PICK_ORDER.indexOf(a.layer.id) - PICK_ORDER.indexOf(b.layer.id));
  const f = hits[0];
  return { kind: KIND[f.layer.id], index: f.id, props: f.properties };
}

// Seçilen öğenin kırpılmamış özgün geometrisi
export function original(kind, index) {
  if (!data) return null;
  const src = { building: data.buildings, node: data.nodes, pipe: data.pipes, prv: data.prvs, inlet: data.inlets, dma: data.dmas }[kind];
  if (src) return src.features[index] || null;
  if (kind === "ilce") return sourceData["sb-ist"]?.features[index] || null;
  if (kind === "leakguess") return sourceData["sb-leak"]?.features[index] || null;
  if (kind === "qbreak" || kind === "qarea") return sourceData["sb-quake"]?.features[index] || null;
  return null;
}

function bindPointer() {
  let raf = 0, last = null;
  map.on("mousemove", (e) => {
    last = e;
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const hit = pick(last.point);
      map.getCanvas().style.cursor = hit ? "pointer" : "";
      hooks.onHover?.(hit, last.point);
    });
  });
  map.on("mouseout", () => hooks.onHover?.(null));
  map.on("click", (e) => hooks.onSelect?.(pick(e.point)));
}
