// Türkçe sayı biçimleri ve küçük yardımcılar
export const fmt0 = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 0 });
export const fmt1 = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
export const fmt2 = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const hh = (h) => `${String(((h % 24) + 24) % 24).padStart(2, "0")}:00`;
// Türkçede yüzde işareti sayıdan önce gelir
export const pct = (v, f = fmt0) => `%${f.format(v)}`;
export const signedPct = (p, f = fmt1) => `${p > 0 ? "+" : p < 0 ? "−" : ""}%${f.format(Math.abs(p))}`;
export const change = (cur, ref) => (ref ? (100 * (cur - ref)) / ref : 0);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = (v * 1.06) / p;
  return [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((x) => x >= n) * p;
}

export const sum = (a) => a.reduce((s, x) => s + x, 0);
export const $ = (id) => document.getElementById(id);
export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Ardışık saatleri "10:00–16:00" biçiminde yazar (bitiş saati dahil değil)
export const span = (a, b) => `${hh(a)}–${hh(b)}`;
