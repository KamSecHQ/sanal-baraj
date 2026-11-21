// Harita lejantı: moda göre değişir; her grup aynı zamanda katman anahtarıdır.
import { state, set, shownSc } from "./state.js";
import { fmt1, $ } from "./format.js";
import { PAL, istanbulRamp, QUAKE_DAY_STOPS } from "./map.js";

let open = window.innerWidth > 900;
let istRows = [];
export function setIstanbulRows(rows) { istRows = rows; }

const sw = (c, shape = "dot") => `<i class="lg-sw ${shape}" style="background:${c}"></i>`;
const ramp = (colors) => `<span class="lg-ramp" style="background:linear-gradient(90deg,${colors.join(",")})"></span>`;

function group(layer, title, body) {
  const on = layer ? state.layers[layer] : true;
  return `<div class="lg-group${on ? "" : " off"}">
    <div class="lg-head">${layer ? `<label><input type="checkbox" data-layer="${layer}" ${on ? "checked" : ""}> ${title}</label>` : `<span>${title}</span>`}</div>
    <div class="lg-body">${body}</div></div>`;
}

export function render() {
  const el = $("legend");
  const P = PAL[state.theme];
  const sc = shownSc();
  const pr = P.pressure;
  const pressure = group("nodes", "Düğüm basıncı, m",
    `<div class="lg-steps">${[[pr[0], "<15"], [pr[2], "15–25"], [pr[4], "25–45"], [pr[6], "45–60"], [pr[8], ">60"]].map(([c, t]) => `<span>${sw(c)}${t}</span>`).join("")}</div>`);
  let groups = [];
  if (state.mode === "istanbul") {
    const stops = istRows.length ? istanbulRamp(state.metric, istRows) : [0, 100];
    groups = [
      group(null, { oncelik: "Öncelik", sorun: "Su sorunu", uygunluk: "Uygunluk", susuzluk_1000: "Susuzluk / 1.000 abone" }[state.metric] || "",
        `${ramp(P.ist)}<div class="lg-ends"><span>${fmt1.format(stops[0])}</span><span>${fmt1.format(stops.at(-1))}</span></div>`),
      group(null, "İşaretler", `<div class="lg-list"><span>${sw(P.istMain, "line")}Ana ilçe</span><span><i class="lg-pin val"></i>Doğrulama ilçesi</span><span><i class="lg-pin"></i>Sıra (ilk 10)</span></div>`),
    ];
  } else if (state.mode === "quake") {
    const st = QUAKE_DAY_STOPS;
    groups = [
      group("buildings", "Binada temiz su", `<div class="lg-list">
        <span>${sw(P.bHigh, "sq")}Depoda temiz su</span>
        <span>${sw(P.bRisk, "sq")}Depo kirlenme riskinde</span>
        <span>${sw(P.bDry, "sq")}Deposuz, şebeke suyu şüpheli</span>
        <span>${sw(P.bNone, "sq")}Deposuz, şebeke suyu temiz</span></div>`),
      group("areas", "Temiz içme suyu, gün", `${ramp(P.quakeDays)}<div class="lg-ends"><span>${st[0]}</span><span>${st[1]}</span><span>${st[2]}</span><span>${st[3]}+</span></div>
        <p class="lg-note">Alandaki depolarda kalan temiz su, alanın bütün nüfusuna kaç günlük içme suyu</p>`),
      group(null, "Boru hasarı", `<div class="lg-list">
        <span><i class="lg-sw ring fill" style="border-color:${P.quakeBreak};background:${P.quakeBreak}"></i>Kırık</span>
        <span><i class="lg-sw ring" style="border-color:${P.quakeBreak}"></i>Sızıntı</span></div>`),
      pressure,
      group("pipes", "Borular", ""),
      group("dmas", "Şebeke suyu şüpheli DMA", `<div class="lg-list"><span>${sw(P.dmaOut, "line")}Hasarlı ya da basıncı düşen</span></div>`),
    ];
  } else if (state.mode === "leak") {
    groups = [
      group(null, "Sızıntı yeri olasılığı", `${ramp(P.leakHeat.slice(1))}<div class="lg-ends"><span>düşük</span><span>yüksek</span></div>`),
      group(null, "İşaretler", `<div class="lg-list">
        <span><i class="lg-sw ring" style="border-color:${P.prv}"></i>%90 güven alanı</span>
        <span><i class="lg-sw ring fill" style="border-color:${P.bDry};background:${P.leakTrue}"></i>Gerçek sızıntı (simülasyon)</span>
        ${sc === "on" ? `<span>${sw(P.dma)}Akıllı kitli düğüm</span>` : ""}</div>`),
      group("pipes", "Borular", ""),
    ];
  } else {
    const out = state.mode === "outage";
    const bld = out
      ? `<div class="lg-list"><span>${ramp([P.bDry, P.bLow, P.bMid, P.bHigh])}</span></div><div class="lg-ends"><span>boş</span><span>dolu</span></div>
         <div class="lg-list"><span>${sw(P.bDry, "sq")}Deposuz, kesintide susuz</span><span>${sw(P.bNone, "sq")}Deposuz</span></div>`
      : sc === "off"
        ? `<div class="lg-list"><span>${sw(P.bFull, "sq")}Depolu, şamandırayla hep dolu</span><span>${sw(P.bNone, "sq")}Deposuz</span></div>`
        : `<div class="lg-list"><span>${ramp([P.bLow, P.bMid, P.bHigh])}</span></div><div class="lg-ends"><span>%40 yedek</span><span>%100</span></div>
           <div class="lg-list"><span>${sw(P.bNone, "sq")}Deposuz</span></div>`;
    groups = [
      group("buildings", out ? "Bina deposu doluluğu" : "Akıllı depo doluluğu", bld),
      pressure,
      group("pipes", out ? "Borular" : "Boru debisi, L/s", out ? "" : `${ramp(P.pipeFlow)}<div class="lg-ends"><span>0</span><span>150+</span></div>`),
      group("dmas", out ? "Kesinti bölgesi ve girişler" : "Ölçüm bölgeleri (DMA) ve girişler", ""),
    ];
    if (!out && sc === "pilot") groups.push(group("prvs", "Önerilen basınç düşürücü vana", `<div class="lg-list"><span>${sw(P.prv)}Büyüklük: öncelik sırası</span></div>`));
  }
  el.innerHTML = `<button type="button" class="lg-toggle" aria-expanded="${open}">Lejant ve katmanlar</button><div class="lg-groups" ${open ? "" : "hidden"}>${groups.join("")}</div>`;
  el.querySelector(".lg-toggle").addEventListener("click", () => { open = !open; render(); });
  for (const cb of el.querySelectorAll("input[data-layer]")) {
    cb.addEventListener("change", () => set({ layers: { ...state.layers, [cb.dataset.layer]: cb.checked } }));
  }
}
