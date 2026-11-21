// Uygulama durumu: tek nesne, değişince abonelere haber verir; URL ile eşlenir (sunumda yer imi olarak kullanılabilir).
export const MODES = ["normal", "outage", "quake", "leak", "istanbul"];
export const SC_KEYS = { normal: ["off", "on", "pilot"], outage: ["off", "on"], quake: ["off", "on"], leak: ["off", "on"], istanbul: [] };

export const state = {
  slug: null,
  mode: "normal",
  sc: "on",
  hour: 8,
  playing: false,
  speed: 1,
  theme: "dark",
  peek: false,        // B tuşu basılıyken "yapay zekâ kapalı" gösterilir
  selection: null,    // { kind, index, props }
  layers: { buildings: true, pipes: true, nodes: true, dmas: true, prvs: true, areas: true },
  story: null,        // sunum modunda adım sırası
  metric: "oncelik",  // İstanbul görünümünde haritanın gösterdiği gösterge
  ilce: null,         // İstanbul görünümünde seçilen ilçe
  leakEvent: 0,       // sızıntı avında seçilen olay
};

const listeners = new Set();
export function subscribe(fn) { listeners.add(fn); }

export function set(patch) {
  const changed = {};
  for (const [k, v] of Object.entries(patch)) {
    if (state[k] !== v) { changed[k] = true; state[k] = v; }
  }
  if (Object.keys(changed).length) for (const fn of listeners) fn(state, changed);
}

// Ekranda gösterilen senaryo (B ile anlık karşılaştırmada "kapalı")
export const shownSc = () => (state.peek && state.mode !== "istanbul" ? "off" : state.sc);

export function readUrl() {
  const p = new URLSearchParams(location.search);
  const out = {};
  if (p.get("d")) out.slug = p.get("d");
  if (MODES.includes(p.get("m"))) out.mode = p.get("m");
  if (p.get("s")) out.sc = p.get("s");
  const h = Number(p.get("h"));
  if (p.has("h") && Number.isInteger(h) && h >= 0 && h < 24) out.hour = h;
  if (["dark", "light"].includes(p.get("t"))) out.theme = p.get("t");
  if (p.get("i")) out.ilce = p.get("i");
  return out;
}

let urlTimer = null;
export function writeUrl() {
  clearTimeout(urlTimer);
  urlTimer = setTimeout(() => {
    const p = new URLSearchParams();
    if (state.slug) p.set("d", state.slug);
    p.set("m", state.mode);
    if (state.mode !== "istanbul") { p.set("s", state.sc); p.set("h", String(state.hour)); }
    if (state.mode === "istanbul" && state.ilce) p.set("i", state.ilce);
    if (state.theme !== "dark") p.set("t", state.theme);
    history.replaceState(null, "", `?${p}`);
  }, 250);
}
