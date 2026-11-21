// Küçük SVG grafik çizici: saatlik seriler, tarife/kesinti bantları, referans çizgileri, saat imleci.
// Gerçek piksel boyutunda çizer; yazılar esnemez.
import { fmt0, niceMax } from "./format.js";

const NS = "http://www.w3.org/2000/svg";

// Ardışık saatleri tek banda topla: [{from, to, cls, label}]
export function groupBands(flags, cls, labelOf = () => "") {
  const out = [];
  flags.forEach((on, i) => {
    if (!on) return;
    const last = out.at(-1);
    if (last && last.to === i && last.key === on) last.to = i + 1;
    else out.push({ from: i, to: i + 1, key: on, cls: typeof cls === "function" ? cls(on) : cls, label: labelOf(on) });
  });
  return out;
}

export function lineChart(svg, o) {
  const n = o.n || 24;
  const W = Math.max(120, Math.round(svg.clientWidth || o.width || 320));
  const H = Math.max(60, Math.round(svg.clientHeight || o.height || 120));
  const pad = { l: 40, r: 12, t: 14, b: 20, ...(o.pad || {}) };
  const all = o.series.flatMap((s) => s.values).concat((o.refs || []).map((r) => r.y)).filter(Number.isFinite);
  const yMin = o.yMin ?? 0;
  const yMax = o.yMax ?? niceMax(Math.max(...all, yMin + 1));
  const step = (W - pad.l - pad.r) / n;
  // Saatlik değer bandın ortasında durur: 0. saat [0,1) aralığının ortası
  const x = (i) => pad.l + (i + 0.5) * step;
  const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - (v - yMin) / (yMax - yMin || 1));
  const yFmt = o.yFmt || ((v) => fmt0.format(v));
  const parts = [];

  for (const b of o.bands || []) {
    const x0 = pad.l + b.from * step, x1 = pad.l + b.to * step;
    parts.push(`<rect class="band ${b.cls || ""}" x="${x0.toFixed(1)}" y="${pad.t}" width="${(x1 - x0).toFixed(1)}" height="${H - pad.t - pad.b}"/>`);
    if (b.label && x1 - x0 > 34) parts.push(`<text class="band-label ${b.cls || ""}" x="${(x0 + 4).toFixed(1)}" y="${pad.t - 4}">${b.label}</text>`);
  }
  const ticks = o.yTicks || [yMin, (yMin + yMax) / 2, yMax];
  for (const t of ticks) {
    parts.push(`<line class="grid" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t).toFixed(1)}" y2="${y(t).toFixed(1)}"/>`);
    parts.push(`<text class="axis" x="${pad.l - 6}" y="${(y(t) + 3.5).toFixed(1)}" text-anchor="end">${yFmt(t)}</text>`);
  }
  const xt = o.xTicks || (W > 520 ? [0, 3, 6, 9, 12, 15, 18, 21] : [0, 6, 12, 18]);
  for (const i of xt) {
    const label = o.xFmt ? o.xFmt(i) : String(i).padStart(2, "0");
    const xi = o.xFmt ? x(i) : pad.l + i * step;   // saatler aralık başında, sayılar noktanın altında
    parts.push(`<text class="axis" x="${xi.toFixed(1)}" y="${H - 5}" text-anchor="middle">${label}</text>`);
  }
  for (const r of o.refs || []) {
    parts.push(`<line class="ref ${r.cls || ""}" x1="${pad.l}" x2="${W - pad.r}" y1="${y(r.y).toFixed(1)}" y2="${y(r.y).toFixed(1)}"/>`);
    if (r.label) parts.push(`<text class="ref-label ${r.cls || ""}" x="${W - pad.r - 2}" y="${(y(r.y) - 4).toFixed(1)}" text-anchor="end">${r.label}</text>`);
  }
  const path = (vals) => vals.map((v, i) => (Number.isFinite(v) ? `${i && Number.isFinite(vals[i - 1]) ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}` : "")).join("");
  // Uçlarda yarım saatlik payı kapat: seri grafiği kenardan kenara doldursun
  const extend = (vals) => {
    const p = path(vals);
    const first = vals.findIndex(Number.isFinite);
    const last = vals.length - 1 - [...vals].reverse().findIndex(Number.isFinite);
    if (first !== 0 || last !== n - 1) return p;
    return `M${pad.l},${y(vals[0]).toFixed(1)}L` + p.slice(1) + `L${W - pad.r},${y(vals[n - 1]).toFixed(1)}`;
  };
  const ordered = [...o.series].sort((a, b) => (a.main ? 1 : 0) - (b.main ? 1 : 0));
  for (const s of ordered) {
    const d = extend(s.values);
    if (s.area) parts.push(`<path class="area ${s.cls}" d="${d}L${W - pad.r},${y(yMin)}L${pad.l},${y(yMin)}Z"/>`);
    parts.push(`<path class="line ${s.cls}${s.main ? " main" : ""}${s.ghost ? " ghost" : ""}" d="${d}"/>`);
  }
  if (o.cursor !== null && o.cursor !== undefined) {
    const cx = x(o.cursor);
    parts.push(`<line class="cursor" x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${pad.t - 2}" y2="${H - pad.b}"/>`);
    for (const s of o.series) {
      const v = s.values[o.cursor];
      if (!Number.isFinite(v) || s.ghost) continue;
      parts.push(`<circle class="dot ${s.cls}${s.main ? " main" : ""}" cx="${cx.toFixed(1)}" cy="${y(v).toFixed(1)}" r="${s.main ? 4 : 2.6}"/>`);
    }
    const m = o.series.find((s) => s.main);
    if (m && o.cursorLabel !== false && Number.isFinite(m.values[o.cursor])) {
      const label = (o.cursorFmt || yFmt)(m.values[o.cursor]);
      const right = cx < W - 90;
      parts.push(`<text class="cursor-label" x="${(cx + (right ? 8 : -8)).toFixed(1)}" y="${(Math.max(y(m.values[o.cursor]) - 8, pad.t + 10)).toFixed(1)}" text-anchor="${right ? "start" : "end"}">${label}</text>`);
    }
  }
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = parts.join("");
  return {
    hourAt(clientX) {
      const r = svg.getBoundingClientRect();
      const px = ((clientX - r.left) / r.width) * W;
      return Math.max(0, Math.min(n - 1, Math.floor((px - pad.l) / step)));
    },
  };
}

export function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}
