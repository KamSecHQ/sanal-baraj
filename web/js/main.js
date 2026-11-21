// Sanal Baraj dijital ikiz görüntüleyici: data/<bölge>/ çıktılarını yükler, modülleri bağlar.
// Görünümler: normal gün (3 senaryo) · kesinti günü (2) · deprem günü (2) · sızıntı avı (2) · nereden başlamalı.
import { state, set, subscribe, readUrl, writeUrl, SC_KEYS } from "./state.js";
import { $, esc, fmt0 } from "./format.js";
import { loadIndex, loadDistrict } from "./data.js";
import * as map from "./map.js";
import * as panel from "./panel.js";
import * as timeline from "./timeline.js";
import * as inspector from "./inspector.js";
import * as legend from "./legend.js";
import * as story from "./story.js";
import * as istanbul from "./istanbul.js";
import * as leak from "./leak.js";

let D = null;
const PREFERRED = "bayrampasa";   // ana ilçe (docs/RAPOR.md bölüm 8)

function fail(html) {
  $("loader").hidden = true;
  const el = $("error");
  el.innerHTML = html;
  el.hidden = false;
}

function progress(bytes, done, total) {
  $("loader-msg").textContent = `Şebeke yükleniyor: ${done}/${total} dosya, ${fmt0.format(bytes / 1048576)} MB`;
  const fill = document.querySelector(".ld-fill");
  if (fill) { const h = 22 * (done / total); fill.setAttribute("y", String(27 - h)); fill.setAttribute("height", String(h)); }
}

async function boot() {
  Object.assign(state, readUrl());
  document.documentElement.dataset.theme = state.theme;
  const index = await loadIndex();
  istanbul.setIndex(index);
  const slug = state.slug || (index.find((i) => i.slug === PREFERRED) || index[0] || {}).slug;
  if (!slug) {
    fail(`<strong>Henüz üretilmiş bölge yok.</strong><p>Önce bir ilçe üretin:</p><code>.venv/bin/python -m twin.build Bayrampaşa</code>`);
    return;
  }
  state.slug = slug;
  const sel = $("district");
  for (const item of index) sel.add(new Option(item.name, item.slug, false, item.slug === slug));
  sel.addEventListener("change", () => {
    const p = new URLSearchParams(location.search);
    p.set("d", sel.value);
    location.search = `?${p}`;
  });

  try {
    D = await loadDistrict(slug, progress);
  } catch (e) {
    fail(`<strong>Veri yüklenemedi.</strong><p>${esc(e.message)}</p><p>Sunucuyu proje kökünden başlatın: <code>python3 scripts/serve.py</code></p>`);
    return;
  }
  const s = D.summary;
  if (!s.scenarios || !s.scenarios.pilot) {
    fail(`<strong>Bu bölgenin verisi eski biçimde.</strong><p>Yeniden üretin:</p><code>.venv/bin/python -m twin.build ${esc(s.ilce)}</code>`);
    return;
  }
  document.title = `${s.name} · Sanal Baraj`;
  for (const m of [panel, timeline, inspector, story, leak]) m.setData(D);

  $("loader-msg").textContent = "Harita hazırlanıyor";
  await map.createMap(state.theme, s.center, { onHover, onSelect });
  map.setDistrict(D);
  if (leak.available()) leak.syncMap();

  // Verisi olmayan görünümleri kapat
  const avail = { normal: true, outage: Boolean(s.outage), quake: Boolean(s.quake && D.quake), leak: leak.available(), istanbul: true };
  for (const b of document.querySelectorAll(".mode")) {
    b.disabled = !avail[b.dataset.mode];
    if (b.disabled) b.title = "Bu bölgenin verisinde yok";
    b.addEventListener("click", () => goMode(b.dataset.mode));
  }
  if (!avail[state.mode]) state.mode = "normal";
  if (!SC_KEYS[state.mode].includes(state.sc)) state.sc = state.mode === "istanbul" ? state.sc : "on";

  bindControls();
  timeline.init();
  inspector.init();
  subscribe(onChange);
  if (state.mode === "leak") state.hour = D.leak.hour;
  if (state.mode === "istanbul") await enterIstanbul();
  renderAll(true);
  frame(state.mode, 0);
  window.__sbReady = performance.now();
  $("loader").classList.add("done");
  setTimeout(() => { $("loader").hidden = true; }, 500);
  welcome();
  if (!map.isOnline()) toast("İnternet yok: altlık harita kapalı, simülasyon verisi tam.");
}

// İlk açılışta kısa karşılama; ?story=1 ile doğrudan sunum modu
function welcome() {
  const p = new URLSearchParams(location.search);
  if (p.get("story")) { story.start(); return; }
  let seen = false;
  try { seen = localStorage.getItem("sb-welcome") === "1"; } catch { /* özel pencere */ }
  if (seen) return;
  const box = $("welcome");
  const close = () => { box.hidden = true; try { localStorage.setItem("sb-welcome", "1"); } catch { /* yok */ } };
  $("wl-close").addEventListener("click", close);
  $("wl-story").addEventListener("click", () => { close(); story.start(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !box.hidden) close(); });
  box.hidden = false;
}

// --- Görünüm değişimi ----------------------------------------------------------

function goMode(mode) {
  if (mode === state.mode) { frame(mode); return; }
  const patch = { mode, selection: null, playing: false, peek: false };
  if (mode === "outage") { patch.hour = D.summary.outage.end; patch.sc = SC_KEYS.outage.includes(state.sc) ? state.sc : "on"; }
  if (mode === "leak") { patch.hour = D.leak.hour; patch.sc = "on"; }
  if (mode === "quake") { patch.hour = D.summary.quake.hour; patch.sc = SC_KEYS.quake.includes(state.sc) ? state.sc : "off"; }
  if (mode === "normal" && !SC_KEYS.normal.includes(state.sc)) patch.sc = "on";
  if (mode === "normal" && state.mode !== "normal") patch.hour = 8;
  set(patch);
  if (mode !== "istanbul") frame(mode);
}

async function enterIstanbul() {
  try {
    const ist = await istanbul.ensure();
    legend.setIstanbulRows(ist.rows);
    map.update();
    istanbul.render();
    istanbul.syncMarkers();
    istanbul.syncSelection();
    inspector.render();
    legend.render();
    frame("istanbul");
  } catch (e) {
    toast(e.message);
  }
}

function frame(mode, duration) {
  const s = D.summary;
  const opts = duration === undefined ? {} : { duration };
  if (mode === "outage" && s.outage) map.fitTo(s.outage.bbox, { ...opts, pitch: 50, bearing: -20 });
  else if (mode === "leak" && leak.available()) map.fitTo(leak.bbox(), { ...opts, pitch: 45, bearing: 8 });
  else if (mode === "quake" && s.quake) map.fitTo(s.quake.bbox, { ...opts, pitch: 45, bearing: -10 });
  else if (mode === "istanbul") { try { map.fitTo(istanbul.bbox(), { ...opts, pitch: 0, bearing: 0, maxZoom: 10 }); } catch (_) { /* yüklenmedi */ } }
  else map.fitTo(s.bbox, opts);
}

// --- Durum değişince ------------------------------------------------------------

function onChange(st, ch) {
  if (ch.theme) {
    document.documentElement.dataset.theme = st.theme;
    map.setTheme(st.theme);
  }
  if (ch.playing || ch.speed) timeline.syncPlayback();
  if (ch.mode) {
    document.body.dataset.mode = st.mode;
    if (st.mode === "istanbul") enterIstanbul();
    else istanbul.syncMarkers();
    istanbul.syncSelection();
  }
  if (ch.metric) { istanbul.syncMarkers(); }
  if (ch.ilce) { istanbul.syncSelection(); if (!story.active()) istanbul.focusSelected(); }
  if (ch.leakEvent) leak.syncMap();
  if (ch.selection) {
    const sel = st.selection;
    if (sel && sel.kind !== "ilce") map.setSelection(map.original(sel.kind, sel.index), sel.kind);
    else map.setSelection(null);
  }
  renderAll(Boolean(ch.mode || ch.theme));
  writeUrl();
}

function renderAll(force = false) {
  syncChrome();
  map.update();
  if (state.mode === "istanbul") istanbul.render();
  else if (state.mode === "leak") leak.render();
  else panel.render(force);
  timeline.render();
  inspector.render();
  legend.render();
  story.render();
}

function syncChrome() {
  document.body.dataset.mode = state.mode;
  for (const b of document.querySelectorAll(".mode")) {
    const on = b.dataset.mode === state.mode;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  }
  $("dock").hidden = state.mode === "istanbul";
  document.body.classList.toggle("peek", state.peek);
}

// --- Harita etkileşimi ------------------------------------------------------------

function onHover(hit, point) {
  const tip = $("tooltip");
  const text = hit ? inspector.tooltip(hit) : "";
  if (!text || window.matchMedia("(hover: none)").matches) { tip.hidden = true; return; }
  tip.textContent = text;
  tip.hidden = false;
  const r = $("map").getBoundingClientRect();
  tip.style.transform = `translate(${Math.round(r.left + point.x + 14)}px, ${Math.round(r.top + point.y + 14)}px)`;
}

function onSelect(hit) {
  if (!hit) { set({ selection: null }); return; }
  if (hit.kind === "ilce") { set({ ilce: hit.props.ilce, selection: { kind: "ilce", ilce: hit.props.ilce } }); return; }
  set({ selection: { kind: hit.kind, index: hit.index, props: hit.props } });
}

// --- Düğmeler ve klavye --------------------------------------------------------------

function bindControls() {
  $("story-btn").addEventListener("click", () => (story.active() ? story.stop() : story.start()));
  $("theme-btn").addEventListener("click", () => set({ theme: state.theme === "dark" ? "light" : "dark" }));
  $("help-btn").addEventListener("click", () => $("help").showModal());
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", (e) => { if (e.key === "b" || e.key === "B") set({ peek: false }); });
  window.addEventListener("blur", () => set({ peek: false }));
}

function scenarioKeys() {
  return state.mode === "istanbul" ? [] : SC_KEYS[state.mode];
}

function onKey(e) {
  const tag = (e.target.tagName || "").toLowerCase();
  if (["input", "select", "textarea"].includes(tag) && e.key !== "Escape") return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if ($("help").open) return;
  const k = e.key;

  if (story.active()) {
    if (["ArrowRight", "PageDown", " ", "Enter"].includes(k)) { story.next(); e.preventDefault(); return; }
    if (["ArrowLeft", "PageUp", "Backspace"].includes(k)) { story.prev(); e.preventDefault(); return; }
    if (k === "Escape") { story.stop(); return; }
  }
  if (k === " " && state.mode !== "istanbul") {
    if (tag === "button") return;
    set({ playing: !state.playing });
    e.preventDefault();
  } else if (k === "ArrowRight" || k === "ArrowLeft") {
    if (state.mode === "istanbul") return;
    set({ hour: (state.hour + (k === "ArrowRight" ? 1 : 23)) % 24, playing: false });
    e.preventDefault();
  } else if (["1", "2", "3", "4"].includes(k)) {
    const key = scenarioKeys()[Number(k) - 1];
    if (key) set({ sc: key, peek: false });
  } else if ((k === "b" || k === "B") && !e.repeat && state.mode !== "istanbul") {
    set({ peek: true });
  } else if ("nNkKdDlLiI".includes(k) && k.length === 1) {
    const mode = { n: "normal", k: "outage", d: "quake", l: "leak", i: "istanbul" }[k.toLowerCase()];
    const btn = document.querySelector(`.mode[data-mode="${mode}"]`);
    if (btn && !btn.disabled) goMode(mode);
  } else if (k === "s" || k === "S") {
    story.active() ? story.stop() : story.start();
  } else if (k === "f" || k === "F") {
    frame(state.mode);
  } else if (k === "t" || k === "T") {
    set({ theme: state.theme === "dark" ? "light" : "dark" });
  } else if (k === "?" || k === "h" || k === "H") {
    $("help").showModal();
  } else if (k === "Escape") {
    set({ selection: null });
  }
}

let toastTimer = null;
function toast(msg) {
  let el = document.querySelector(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
  el.textContent = msg;
  el.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("on"), 5000);
}

boot().catch((e) => fail(`<strong>Beklenmeyen hata.</strong><p>${esc(e.message)}</p>`));
