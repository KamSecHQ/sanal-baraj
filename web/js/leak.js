// Sızıntı avı: gece ölçümüyle yeni bir sızıntının yerini daraltmak. Veri leak.json'dan (twin/leak.py).
import { state, set, shownSc } from "./state.js";
import { fmt0, fmt1, fmt2, esc, $ } from "./format.js";
import { setLeakFeatures } from "./map.js";

let D = null;
let built = "";
export function setData(d) { D = d; built = ""; }
export const available = () => Boolean(D && D.leak && D.leak.events && D.leak.events.length);

const SC = [
  { key: "off", label: "Yalnız DMA sayacı", desc: "Gece debisi arttı: sızıntı var. Ama nerede? Bütün bölge aranır." },
  { key: "on", label: "Akıllı kit sensörleri", desc: "Her binadaki basınç sensörü ve kontrollü yükleme arama alanını daraltır; ekip en olası adaydan başlar." },
];

const km = (m) => (m >= 1000 ? `${fmt1.format(m / 1000)} km` : `${fmt0.format(m)} m`);

// 90% güven alanı: en olasıdan başlayarak olasılığın %90'ını kapsayan adaylar
function searchSet(post, conf = 0.9) {
  const order = post.map((p, i) => [p, i]).sort((a, b) => b[0] - a[0]);
  const out = [];
  let acc = 0;
  for (const [p, i] of order) { out.push(i); acc += p; if (acc >= conf) break; }
  return out;
}

export function features() {
  const L = D.leak;
  const ev = L.events[state.leakEvent] || L.events[0];
  const post = ev.post.dense;
  const max = Math.max(...post);
  const set90 = searchSet(post);
  const rank = new Map(set90.map((i, r) => [i, r + 1]));
  const f = [];
  L.nodes.forEach((ll, i) => {
    f.push({ type: "Feature", geometry: { type: "Point", coordinates: ll },
      properties: { k: "cand", pa: post[i] / max, po: 0.32, p: post[i] } });
  });
  for (const i of L.sensor_idx.dense) {
    f.push({ type: "Feature", geometry: { type: "Point", coordinates: L.nodes[i] }, properties: { k: "sensor" } });
  }
  for (const i of set90) {
    f.push({ type: "Feature", geometry: { type: "Point", coordinates: L.nodes[i] },
      properties: { k: "guess", r: rank.get(i), pa: post[i], id: L.ids[i], len: L.len_m[i], i } });
  }
  f.push({ type: "Feature", geometry: { type: "Point", coordinates: L.nodes[ev.true] }, properties: { k: "true" } });
  return { type: "FeatureCollection", features: f };
}

export function syncMap() {
  if (!available()) return;
  setLeakFeatures(features());
}

export function bbox() {
  const L = D.leak;
  const xs = L.nodes.map((n) => n[0]), ys = L.nodes.map((n) => n[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

export function render() {
  const el = $("panel");
  if (state.mode !== "leak") return;
  if (!available()) {
    el.innerHTML = `<section class="p-sec"><h2 class="p-h">Sızıntı avı</h2><p class="small">Bu bölgenin verisinde sızıntı avı yok. Yeniden üretin: <code>.venv/bin/python -m twin.build ${esc(D?.summary?.ilce || "İlçe")}</code></p></section>`;
    return;
  }
  const L = D.leak;
  const sc = shownSc();
  const key = `${sc}|${state.leakEvent}|${state.peek}`;
  if (key === built) return;
  built = key;
  const ev = L.events[state.leakEvent];
  // Orkestratör ölçüm için dolumu durdurunca sayaçtaki taban debi düşer, sızıntının payı büyür
  const base = L.quiet_inflow_m3h || ev.inflow_base[L.hour];
  const rise = (100 * L.leak_lps * 3.6) / base;
  const M = L.metrics, Q = L.quiet || {};
  const dense = sc === "on";
  const searchNow = dense ? ev.search_m.dense : L.dma_pipe_m;
  const pipeTotal = L.dma_pipe_m;

  el.innerHTML = `
    <section class="p-sec">
      <h2 class="p-h">${esc(L.dma)} · gece ${String(L.hour).padStart(2, "0")}:00</h2>
      <p class="lead">Bölgede yeni bir sızıntı: ${fmt1.format(L.leak_lps)} L/s. ${L.quiet_inflow_m3h ? `Orkestratör dolumu durdurunca bölgeye giren su saatte ${fmt0.format(base)} m³'e iner; sızıntı bunu %${fmt0.format(rise)} artırır ve sayaç fark eder.` : `DMA sayacı gece debisindeki %${fmt0.format(rise)} artıştan bunu fark eder.`} Sorun, yerini bulmak.</p>
    </section>
    <section class="p-sec">
      <div class="scen-list" role="radiogroup" aria-label="Sensör düzeni">${SC.map((x, i) => `
        <button type="button" role="radio" class="scen-opt ${x.key}" data-sc="${x.key}" aria-checked="${x.key === sc}">
          <kbd class="scen-key">${i + 1}</kbd><span class="scen-name">${x.label}</span><span class="scen-desc">${x.desc}</span>
        </button>`).join("")}</div>
    </section>
    <section class="p-sec">
      <h2 class="p-h">Sızıntı olayı <span class="p-h-aside">simülasyonda rastgele yer</span></h2>
      <div class="events" role="group" aria-label="Olay">${L.events.map((_, i) => `<button type="button" data-ev="${i}" aria-pressed="${i === state.leakEvent}">${i + 1}</button>`).join("")}</div>
    </section>
    <section class="p-sec verdict ${dense ? "on" : "off"}">
      <span class="verdict-k">Kazılacak alan</span>
      <span class="verdict-v">${km(searchNow)}</span>
      <span class="verdict-u">boru; bölgedeki hat ${km(pipeTotal)}, payı %${fmt0.format((100 * searchNow) / pipeTotal)}</span>
      ${dense ? `<dl class="facts">
        <dt>Gerçek yer</dt><dd>${ev.hit.dense ? `%90 alanın içinde, ${ev.rank.dense}. aday` : `alanın dışında (${ev.rank.dense}. aday)`}</dd>
        <dt>En olası aday</dt><dd>gerçek yere ${fmt0.format(ev.error_m.dense)} m</dd>
        <dt>Basınç izi</dt><dd>en çok ${fmt2.format(ev.drop_m)} m düşüş</dd>
      </dl>` : `<p class="small">Sayaç yalnız bölgeye girenle çıkanı görür; arama ekibi bütün hattı dinlemek zorunda.</p>`}
    </section>
    <section class="p-sec">
      <h2 class="p-h">${L.events.length} olayın ortalaması</h2>
      <div class="ledger-wrap"><table class="ledger">
        <thead><tr><th></th><th class="${!dense ? "active" : ""}">Sayaç</th><th>${L.sensors.sparse} kaydedici</th><th class="${dense ? "active" : ""}">Akıllı kit</th></tr></thead>
        <tbody>
          <tr><th scope="row">Arama alanı<span>boru</span></th><td class="${!dense ? "active" : ""}">${km(M.meter.search_m)}</td><td>${km(M.sparse.search_m)}</td><td class="${dense ? "active" : ""}">${km(M.dense.search_m)}</td></tr>
          <tr><th scope="row">Bölgenin<span>%</span></th><td class="${!dense ? "active" : ""}">100</td><td>${fmt0.format(100 * M.sparse.search_share)}</td><td class="${dense ? "active" : ""}">${fmt0.format(100 * M.dense.search_share)}</td></tr>
          <tr><th scope="row">Gerçek yer alanda<span>olay</span></th><td class="${!dense ? "active" : ""}">${L.events.length}/${L.events.length}</td><td>${fmt0.format(M.sparse.hit_rate * L.events.length)}/${L.events.length}</td><td class="${dense ? "active" : ""}">${fmt0.format(M.dense.hit_rate * L.events.length)}/${L.events.length}</td></tr>
        </tbody>
      </table></div>
      <p class="small">Ölçümü orkestratör yönetir: önce akıllı depoların dolumunu durdurup şebekeyi sessizleştirir, sonra depoları bilinen debiyle doldurarak şebekeyi kontrollü yükler (+${fmt0.format(L.excite_m3h)} m³/sa). Yük kaybı debiyle büyüdüğü için sızıntının basınç izi büyür.${Q.dense ? ` Yüklemesiz ölçümde kitle arama alanı ${km(Q.dense.search_m)} olurdu.` : ""}</p>
      <p class="small">Varsayımlar (tahmin): gece talebi düğüm başına ±%${fmt0.format(100 * (L.demand_noise ?? 0.1))} sapar, sensör 15 dakikalık ortalamada ±${fmt2.format(L.sensor_noise_m ?? 0.05)} m hata yapar; ölçülen toplam gürültü ${fmt2.format(L.sigma_m)} m. %${fmt0.format(100 * (L.confidence ?? 0.9))} güven alanı. Kaydediciler en uzak nokta yerleşimiyle.</p>
    </section>
    <footer class="p-foot">Sentetik şebeke ve simülasyon. Sızıntı yeri olasılığı en büyük olabilirlik ile hesaplanır; yöntem <code>twin/leak.py</code> içinde.</footer>`;
  for (const b of el.querySelectorAll(".scen-opt")) b.addEventListener("click", () => set({ sc: b.dataset.sc, peek: false }));
  for (const b of el.querySelectorAll(".events button")) b.addEventListener("click", () => { set({ leakEvent: Number(b.dataset.ev), selection: null }); syncMap(); });
}

export function inspector(sel) {
  const L = D?.leak;
  if (!L) return null;
  const f = sel.props;
  const ev = L.events[state.leakEvent];
  const i = Number(f.i);
  const R = 6371000, toRad = Math.PI / 180;
  const [a, b] = [L.nodes[i], L.nodes[ev.true]];
  const dist = 2 * R * Math.asin(Math.sqrt(Math.sin(((b[1] - a[1]) * toRad) / 2) ** 2 + Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(((b[0] - a[0]) * toRad) / 2) ** 2));
  return {
    body: `<div class="insp-kind">Sızıntı adayı</div><h2 class="insp-title">${f.r}. sırada</h2><p class="insp-sub">Düğüm ${esc(f.id)}</p>
      <dl class="facts"><dt>Olasılık</dt><dd>%${fmt1.format(100 * f.pa)}</dd><dt>Bağlı boru</dt><dd>${fmt0.format(f.len)} m</dd>
      <dt>Gerçek sızıntıya</dt><dd>${fmt0.format(dist)} m</dd></dl>
      <p class="small">Saha ekibi aramaya en olası adaydan başlar; dinleme cihazıyla bu düğüme bağlı hatlar taranır.</p>`,
  };
}
