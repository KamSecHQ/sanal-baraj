// "Nereden başlamalı": İstanbul ilçelerinin su sorunu ve Sanal Baraj'a uygunluk sıralaması (scripts/oncelik.py).
import { state, set } from "./state.js";
import { fmt0, fmt1, fmt2, esc, $ } from "./format.js";
import { getMap, setIstanbul, setIstanbulRows, setIstanbulSelection, fitTo } from "./map.js";
import { loadIstanbul } from "./data.js";

// Proje kararları (docs/RAPOR.md bölüm 8)
export const MAIN = "BAYRAMPAŞA";
export const VALIDATION = ["FATİH", "BAĞCILAR", "KÜÇÜKÇEKMECE", "ESENLER"];

const METRICS = [
  { key: "oncelik", label: "Öncelik", desc: "Su sorunu ile uygunluğun geometrik ortalaması", f: fmt1 },
  { key: "sorun", label: "Su sorunu", desc: "Şikâyet, arıza, kesinti, basınç olayı ve deprem hasarı göstergelerinin yüzdelik sırası", f: fmt1 },
  { key: "uygunluk", label: "Uygunluk", desc: "5 ve üzeri katlı bina sayısı ve payı: Sanal Baraj apartman depolarıyla çalışır", f: fmt1 },
  { key: "susuzluk_1000", label: "Susuzluk şikâyeti", desc: "1.000 abone başına, İSKİ 2023", f: fmt1 },
];

let IST = null;
let index = [];
let markers = [];
let loading = null;

const slug = (s) => s.toLocaleLowerCase("tr").replace(/[çğıöşü]/g, (c) => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u" })[c]).replace(/[^a-z0-9]+/g, "-");
const built = (r) => index.find((i) => i.slug === slug(r.ilce.toLocaleLowerCase("tr")));

export function setIndex(i) { index = i; }

export async function ensure() {
  if (IST) return IST;
  loading = loading || loadIstanbul().then((d) => {
    IST = d;
    setIstanbul(d.geo);
    setIstanbulRows(d.rows, MAIN);
    return d;
  });
  return loading;
}

// Kadraj: öncelikte ilk 12 ilçe ile ana ve doğrulama ilçeleri (kent çekirdeği); uzak ilçeler kaydırınca görünür
export function bbox() {
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const walk = (c) => (typeof c[0] === "number" ? ((x0 = Math.min(x0, c[0])), (y0 = Math.min(y0, c[1])), (x1 = Math.max(x1, c[0])), (y1 = Math.max(y1, c[1]))) : c.forEach(walk));
  const keep = new Set([...IST.rows.slice(0, 12).map((r) => r.ilce), MAIN, ...VALIDATION]);
  for (const f of IST.geo.features) if (keep.has(f.properties.ilce)) walk(f.geometry.coordinates);
  return [x0, y0, x1, y1];
}

function centroid(geom) {
  const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.coordinates;
  let best = null, bestA = -1;
  for (const poly of polys) {
    const ring = poly[0];
    let a = 0, cx = 0, cy = 0;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const k = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
      a += k; cx += (ring[j][0] + ring[i][0]) * k; cy += (ring[j][1] + ring[i][1]) * k;
    }
    if (Math.abs(a) > bestA) { bestA = Math.abs(a); best = [cx / (3 * a), cy / (3 * a)]; }
  }
  return best;
}

export function syncMarkers() {
  for (const m of markers) m.remove();
  markers = [];
  if (state.mode !== "istanbul" || !IST) return;
  const m = state.metric;
  const ranked = [...IST.rows].sort((a, b) => b[m] - a[m]);
  const pos = new Map(ranked.map((r, i) => [r.ilce, i + 1]));
  for (const f of IST.geo.features) {
    const r = IST.byIlce[f.properties.ilce];
    if (!r) continue;
    const p = pos.get(r.ilce);
    const role = r.ilce === MAIN ? "main" : VALIDATION.includes(r.ilce) ? "val" : "";
    if (p > 10 && !role) continue;
    const el = document.createElement("button");
    el.type = "button";
    el.className = `ist-pin ${role}`;
    el.innerHTML = `<b>${p}</b>${role || p <= 5 ? `<span>${esc(f.properties.name)}</span>` : ""}`;
    el.title = `${f.properties.name}: ${p}. sıra`;
    el.addEventListener("click", (e) => { e.stopPropagation(); set({ ilce: r.ilce, selection: { kind: "ilce", ilce: r.ilce } }); });
    markers.push(new maplibregl.Marker({ element: el }).setLngLat(centroid(f.geometry)).addTo(getMap()));
  }
}

export function syncSelection() {
  if (!IST) return;
  const f = state.mode === "istanbul" && state.ilce ? IST.geo.features.find((x) => x.properties.ilce === state.ilce) : null;
  setIstanbulSelection(f || null);
}

export function render() {
  if (state.mode !== "istanbul") return;
  const el = $("panel");
  if (!IST) { el.innerHTML = `<section class="p-sec"><p class="small">İlçe verisi yükleniyor…</p></section>`; return; }
  const m = METRICS.find((x) => x.key === state.metric) || METRICS[0];
  const rows = [...IST.rows].sort((a, b) => b[m.key] - a[m.key]);
  const max = Math.max(...rows.map((r) => r[m.key]));
  el.innerHTML = `
    <section class="p-sec">
      <h2 class="p-h">İstanbul'un 39 ilçesi</h2>
      <p class="lead">Sanal Baraj nereden başlamalı? Su sorunu çok, apartmanı çok olan yerden. İki ölçütü İBB açık verisinden hesapladık.</p>
      <div class="metrics" role="radiogroup" aria-label="Gösterge">${METRICS.map((x) => `<button type="button" role="radio" data-m="${x.key}" aria-checked="${x.key === m.key}">${x.label}</button>`).join("")}</div>
      <p class="small">${m.desc}.</p>
    </section>
    <section class="p-sec">
      <ol class="rank" id="ist-rank">${rows.map((r, i) => {
        const role = r.ilce === MAIN ? `<em class="tag main">ana ilçe</em>` : VALIDATION.includes(r.ilce) ? `<em class="tag val">doğrulama</em>` : "";
        const twin = built(r) ? `<em class="tag twin">ikiz hazır</em>` : "";
        const name = IST.geo.features.find((f) => f.properties.ilce === r.ilce)?.properties.name || r.ilce;
        return `<li><button type="button" data-ilce="${esc(r.ilce)}" aria-pressed="${state.ilce === r.ilce}">
          <span class="rank-n">${i + 1}</span><span class="rank-name">${esc(name)} ${role}${twin}</span>
          <span class="rank-v">${m.f.format(r[m.key])}</span>
          <span class="rank-bar"><i style="width:${(100 * r[m.key]) / max}%"></i></span></button></li>`;
      }).join("")}</ol>
    </section>
    <section class="p-sec">
      <p class="small">En çok su sorunu yaşayan ilçeler (Silivri, Çatalca, Şile, Beykoz, Arnavutköy, Sarıyer) apartman az olduğu için bu çözüme uygun değil; orada çözüm şebeke yenileme. Sıralama sağlam: herhangi bir gösterge çıkarıldığında Fatih, Bağcılar ve Küçükçekmece ilk beşte kalıyor.</p>
    </section>
    <footer class="p-foot">Kaynak: İBB Açık Veri (susuzluk şikâyeti ve arıza ihbarı 2023, kesintiler Şub 2023–Şub 2024, abone sayısı, bina 2017, deprem senaryosu 2019). Yöntem <code>scripts/oncelik.py</code>.</footer>`;
  for (const b of el.querySelectorAll(".metrics button")) b.addEventListener("click", () => set({ metric: b.dataset.m }));
  for (const b of el.querySelectorAll("#ist-rank button")) {
    b.addEventListener("click", () => set({ ilce: b.dataset.ilce, selection: { kind: "ilce", ilce: b.dataset.ilce } }));
  }
  el.querySelector('#ist-rank button[aria-pressed="true"]')?.scrollIntoView({ block: "nearest" });
}

export function inspector(sel) {
  if (!IST) return null;
  const r = IST.byIlce[sel.ilce || sel.props?.ilce];
  if (!r) return null;
  const name = IST.geo.features.find((f) => f.properties.ilce === r.ilce)?.properties.name || r.ilce;
  const role = r.ilce === MAIN ? "Ana ilçe: yüksek çözünürlüklü model burada" : VALIDATION.includes(r.ilce) ? "Doğrulama ilçesi: aynı model, ek ayar yapmadan" : "";
  const b = built(r);
  const bar = (label, v) => `<div class="bar-row"><span>${label}</span><span class="bar"><i style="width:${v}%"></i></span><b>${fmt1.format(v)}</b></div>`;
  const row = (k, v) => `<dt>${k}</dt><dd>${v}</dd>`;
  return {
    body: `<div class="insp-kind">İlçe</div><h2 class="insp-title">${esc(name)}</h2><p class="insp-sub">Öncelikte ${r.rank}. sıra${role ? `. ${role}` : ""}</p>
      <div class="bars">${bar("Öncelik", r.oncelik)}${bar("Su sorunu", r.sorun)}${bar("Uygunluk", r.uygunluk)}</div>
      <dl class="facts">
        ${row("Susuzluk şikâyeti", `${fmt1.format(r.susuzluk_1000)} / 1.000 abone`)}
        ${row("Arıza ihbarı", `${fmt1.format(r.ariza_1000)} / 1.000 abone`)}
        ${row("Duyurulu kesinti", `${fmt2.format(r.kesinti_saat_1000)} saat / 1.000 abone`)}
        ${row("Basınç düşüklüğü olayı", fmt0.format(r.basinc_olay))}
        ${row("Deprem: içme suyu boru hasarı", fmt0.format(r.deprem_boru))}
        ${row("5+ katlı bina", `${fmt0.format(r.yuksek_bina)}, %${fmt0.format(100 * r.yuksek_pay)}`)}
        ${row("Abone", fmt0.format(r.abone))}
      </dl>
      ${b ? `<a class="btn-primary block" href="?d=${encodeURIComponent(b.slug)}&m=normal&s=on&h=8">${esc(name)} dijital ikizini aç</a>` : `<p class="small">Bu ilçenin dijital ikizi henüz üretilmedi: <code>.venv/bin/python -m twin.build ${esc(name)}</code></p>`}`,
  };
}

export function focusSelected() {
  if (!IST || !state.ilce) return;
  const f = IST.geo.features.find((x) => x.properties.ilce === state.ilce);
  if (!f) return;
  let x0 = 180, y0 = 90, x1 = -180, y1 = -90;
  const walk = (c) => (typeof c[0] === "number" ? ((x0 = Math.min(x0, c[0])), (y0 = Math.min(y0, c[1])), (x1 = Math.max(x1, c[0])), (y1 = Math.max(y1, c[1]))) : c.forEach(walk));
  walk(f.geometry.coordinates);
  const pad = Math.max(x1 - x0, y1 - y0) * 0.9;
  fitTo([x0 - pad, y0 - pad, x1 + pad, y1 + pad], { pitch: 0, bearing: 0, maxZoom: 12 });
}
