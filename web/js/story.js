// Sunum modu: jüriye adım adım anlatım. Her adım haritayı, senaryoyu ve saati ayarlar; bütün rakamlar
// o bölgenin simülasyon sonucundan gelir. Sunum kumandası (PageDown/PageUp) ve ok tuşlarıyla ilerler.
import { state, set } from "./state.js";
import { fmt0, fmt1, hh, signedPct, change, esc, $, reducedMotion } from "./format.js";
import { normalDay } from "./data.js";
import { fitTo } from "./map.js";
import * as istanbul from "./istanbul.js";
import * as leak from "./leak.js";

let D = null;
let steps = [];
export function setData(d) { D = d; }
export const active = () => state.story !== null;

const km = (m) => (m >= 1000 ? `${fmt1.format(m / 1000)} km` : `${fmt0.format(m)} m`);

async function build() {
  const s = D.summary;
  const c = s.comparison;
  const S = s.scenarios;
  const out = [];
  const peakH = S.off.hourly.inflow_m3h.indexOf(Math.max(...S.off.hourly.inflow_m3h));
  const cap = s.tank_volume_m3;
  out.push({
    title: `${s.name}: binlerce depo, tek rezervuar`,
    text: `İlçede ${fmt0.format(s.counts.buildings)} bina var; ${fmt0.format(s.counts.smart_tanks)} tanesinin bodrumunda depo ve hidrofor. Bu depolardaki su bugün dağınık ve kendi başına çalışıyor. Sanal Baraj her depoya küçük bir kit takıp hepsini tek rezervuar gibi yönetir.`,
    figure: [`${fmt0.format(cap)} m³`, "bina depolarında duran su"],
    go: { mode: "normal", sc: "off", hour: peakH }, cam: "district",
  });
  out.push({
    title: `${hh(peakH)}: herkes aynı anda su çekiyor`,
    text: `Bugün depolar şamandıralı vanayla çalışıyor: su kullanıldığı anda depo yeniden doluyor. Herkes aynı anda çektiği için şebeke tepe saatte ${fmt0.format(c.peak_inflow_m3h.off)} m³/sa taşıyor; borular ve pompalar bu tepeye göre boyutlanıyor.`,
    figure: [`${fmt0.format(c.peak_inflow_m3h.off)} m³/sa`, "tepe debisi, yapay zekâ kapalı"],
    go: { mode: "normal", sc: "off", hour: peakH }, cam: "district",
  });
  out.push({
    title: "Aynı saat, yapay zekâ açık",
    text: `Binalar depodan içiyor; orkestratör her DMA için dolumu günün sakin saatlerine yayıyor. Aynı talep saatte ${fmt0.format(c.peak_inflow_m3h.on)} m³ düzeyinde düz bir girişle karşılanıyor. Haritada bina renkleri depo doluluğu.`,
    figure: [signedPct(c.peak_inflow_m3h.pct), "tepe debisi"],
    go: { mode: "normal", sc: "on", hour: peakH }, cam: "district",
  });
  const fill = normalDay(s, "on").find((e) => e.title === "Depolar dolduruluyor");
  const fillPct = S.on.hourly.stored_m3.map((v) => (100 * v) / cap);
  if (fill) {
    const mid = (fill.from + Math.floor(((fill.to - fill.from + 24) % 24) / 2)) % 24;
    out.push({
      title: "Gece: sanal baraj doluyor",
      text: `Elektriğin ucuz olduğu saatlerde sanal baraj %${fmt0.format(fillPct[fill.from])} seviyesinden %${fmt0.format(fillPct[fill.to % 24])} seviyesine çıkıyor. Hiçbir depo %${fmt0.format(100 * (s.params?.reserve_fraction ?? 0.4))} yedeğin altına inmiyor: kesinti ve deprem için su hep hazır. Su depoda ${fmt1.format(c.water_age_h.off)} yerine ${fmt1.format(c.water_age_h.on)} saat bekliyor, daha taze.`,
      figure: [`%${fmt0.format(fillPct[fill.to % 24])}`, "sabah sanal baraj doluluğu"],
      go: { mode: "normal", sc: "on", hour: mid }, cam: "district",
    });
  }
  out.push({
    title: "Puant saatinde pompalar rahat",
    text: `Elektriğin en pahalı olduğu saatlerde şebekeye giren suyun payı %${fmt1.format(100 * c.puant_share.off)} iken %${fmt1.format(100 * c.puant_share.on)} oluyor. Günlük basma maliyeti ${fmt0.format(c.pump_tl.off)} TL'den ${fmt0.format(c.pump_tl.on)} TL'ye düşüyor. Tarife değerleri yaklaşık.`,
    figure: [signedPct(c.pump_tl.pct), "günlük basma maliyeti"],
    go: { mode: "normal", sc: "on", hour: 19 }, cam: "district",
  });
  if (S.pilot && c.leak_m3.pilot !== undefined) {
    const energy = c.pump_kwh?.pct_pilot ?? 0;
    out.push({
      title: "Kaçak için doğru kaldıraç: basınç",
      text: `Depo zamanlaması kaçağı yalnız ${signedPct(c.leak_m3.pct)} değiştirir; fazla basıncın çoğu kot farkından gelir. Binalardaki basınç sensörlerinin çizdiği harita ${s.pilot.candidates} aday vana yeri çıkarıyor. Her aday tek tek simüle ediliyor; ana bölgenin enerjisini kaçak kazancından çok artıranlar eleniyor. Seçilen ${s.pilot.prvs} vanayla basma enerjisi ${signedPct(energy)} değişiyor.` +
        (energy > 1 ? ` Bu ilçede vanalar enerjiyi artırıyor; kaçak kazancı bunu karşılıyor.` : ""),
      figure: [signedPct(c.leak_m3.pct_pilot), `kaçak, günde ${fmt0.format(c.leak_m3.off - c.leak_m3.pilot)} m³ az`],
      go: { mode: "normal", sc: "pilot", hour: 3, layers: { ...state.layers, prvs: true } }, cam: "prvs",
    });
  }
  const o = s.outage;
  if (o) {
    out.push({
      title: "Kesinti günü: su döndüğü an",
      text: `${o.dma} bölgesinde ${hh(o.start)}–${hh(o.end)} planlı çalışma. Su dönünce bütün depolar aynı anda dolmaya çalışıyor: giriş debisi ${fmt0.format(o.off.daily.refill_peak_m3h)} m³/sa ile zirve yapıyor (normal günün tepesi ${fmt0.format(o.off.daily.normal_peak_m3h)}), basınç ${fmt1.format(o.off.daily.min_pressure_after)} m seviyesine düşüyor.`,
      figure: [`${fmt1.format(o.off.daily.min_pressure_after)} m`, "dönüşte en düşük basınç, şamandıra"],
      go: { mode: "outage", sc: "off", hour: o.end }, cam: "outage",
    });
    out.push({
      title: "Orkestratörle aynı an",
      text: `Orkestratör kesintiyi önceden biliyor, depoları önceden dolduruyor. Su dönünce dolumu sıraya koyuyor: basınç ${fmt1.format(o.on.daily.min_pressure_after)} m'nin altına inmiyor. Dönüşten sonra susuz kalan yok (şamandırada ${fmt0.format(o.off.daily.unserved_after_ph)} kişi-saat).`,
      figure: [`${fmt1.format(o.on.daily.min_pressure_after)} m`, "dönüşte en düşük basınç, orkestratör"],
      go: { mode: "outage", sc: "on", hour: o.end }, cam: "outage",
    });
    out.push({
      title: "Asıl mağdur deposuz binalar",
      text: `Kesinti boyunca susuz kalanların hepsi deposuz binalarda: ${fmt0.format(o.persons_no_tank)} kişi. Depolu binalarda kimse susuz kalmıyor. Depo yaygınlaştırmak da çözümün parçası.`,
      figure: [fmt0.format(o.persons_no_tank), "kişi deposuz binada"],
      go: { mode: "outage", sc: "on", hour: Math.floor((o.start + o.end) / 2) }, cam: "outage",
    });
  }
  const q = s.quake;
  if (q && D.quake) {
    const qo = q.off.daily, qn = q.on.daily;
    const days = (m3) => (1000 * m3) / (q.drink_lpcd * q.population);
    out.push({
      title: `Deprem günü: ${hh(q.hour)}`,
      text: `İBB'nin 7,5 Mw gece senaryosu bu ilçede ${fmt0.format(q.damage_ibb)} içme suyu borusu hasarı öngörüyor: ${fmt0.format(qo.breaks)} kırık, ${fmt0.format(qo.leaks)} sızıntı. ${fmt0.format(qo.suspect_dmas)} DMA'da şebeke suyu artık şüpheli. Şamandıralı vanalar bu suyu depolara çekmeye devam ediyor: ${fmt0.format(qo.risk_tanks)} binanın deposu, ${fmt0.format(qo.risk_m3_end)} m³ su kirlenme riskinde.`,
      figure: [`${fmt0.format(qo.risk_persons)}`, "kişinin deposu kirlenme riskinde, şamandıra"],
      go: { mode: "quake", sc: "off", hour: q.hour + 1 }, cam: "quake",
    });
    out.push({
      title: "Kit depoyu mühürlüyor",
      text: `Kitteki ivmeölçer sarsıntıyı algılar algılamaz depo girişini kapatır; depodaki su şüpheli suyla karışmaz. Hasarsız bölgelerde orkestratör girişleri bir saat sonra açıp depoları tamamlıyor. Gün sonunda depolarda ${fmt0.format(qn.clean_m3_end)} m³ temiz su var (şamandırada ${fmt0.format(qo.clean_m3_end)}). Harita her ${q.kind === "mahalle" ? "mahallenin" : "bölgenin"} kaç günlük içme suyu olduğunu gösteriyor; deposuz binalara su dağıtımı bu haritayla planlanabilir.`,
      figure: [`${fmt1.format(days(qn.clean_m3_end))} gün`, `ilçenin bütün nüfusuna içme suyu, ${fmt0.format(q.drink_lpcd)} L/kişi/gün (şamandırada ${fmt1.format(days(qo.clean_m3_end))})`],
      go: { mode: "quake", sc: "on", hour: 23, layers: { ...state.layers, areas: true } }, cam: "district",
    });
  }
  if (leak.available()) {
    const L = D.leak;
    const rise = (100 * L.leak_lps * 3.6) / (L.quiet_inflow_m3h || L.events[0].inflow_base[L.hour]);
    out.push({
      title: `Gece ${String(L.hour).padStart(2, "0")}:00: bir boru sızdırıyor`,
      text: `${L.dma} bölgesinde ${fmt1.format(L.leak_lps)} L/s debili yeni bir sızıntı. DMA sayacı gece debisindeki %${fmt0.format(rise)} artıştan bunu fark eder ama yerini söyleyemez: arama ekibi bölgedeki bütün hattı dinlemek zorunda.`,
      figure: [km(L.metrics.meter.search_m), "aranacak boru, yalnız sayaçla"],
      go: { mode: "leak", sc: "off", hour: L.hour, leakEvent: 0 }, cam: "leak",
    });
    out.push({
      title: "Binalar konuşuyor",
      text: `Orkestratör şebekeyi önce susturur, sonra depoları bilinen debiyle doldurup hafifçe yükler. Her binadaki basınç sensörü sızıntının izini görür. ${L.events.length} rastgele sızıntıda aranacak hat ortalama ${km(L.metrics.dense.search_m)}; gerçek yer ${fmt0.format(L.metrics.dense.hit_rate * L.events.length)} olayda bu alanın içinde.`,
      figure: [km(L.metrics.dense.search_m), "aranacak boru, akıllı kitle"],
      go: { mode: "leak", sc: "on", hour: L.hour, leakEvent: 0 }, cam: "leak",
    });
  }
  try {
    const ist = await istanbul.ensure();
    const r = ist.byIlce[istanbul.MAIN];
    const ranked = [...ist.rows].sort((a, b) => b.susuzluk_1000 - a.susuzluk_1000);
    out.push({
      title: "Nereden başlamalı?",
      text: `İBB açık verisiyle 39 ilçeyi su sorunu ve apartman yoğunluğuna göre sıraladık. Bayrampaşa 1.000 abone başına ${fmt1.format(r.susuzluk_1000)} susuzluk şikâyetiyle öncelikli ilçeler arasında açık ara önde. Model önce burada kuruldu; Fatih, Bağcılar, Küçükçekmece ve Esenler doğrulama için.`,
      figure: [`${ranked.findIndex((x) => x.ilce === r.ilce) + 1}.`, "susuzluk şikâyetinde İstanbul sırası"],
      go: { mode: "istanbul", metric: "susuzluk_1000", ilce: istanbul.MAIN, selection: { kind: "ilce", ilce: istanbul.MAIN } }, cam: "istanbul",
    });
  } catch (_) { /* İstanbul verisi yoksa bu adım atlanır */ }
  return out;
}

function camera(step) {
  const dur = reducedMotion() ? 0 : 1600;
  const s = D.summary;
  if (step.cam === "district") fitTo(s.bbox, { duration: dur });
  else if (step.cam === "outage" && s.outage) fitTo(s.outage.bbox, { duration: dur, pitch: 50, bearing: -20 });
  else if (step.cam === "quake" && s.quake) fitTo(s.quake.bbox, { duration: dur, pitch: 45, bearing: -10 });
  else if (step.cam === "leak") fitTo(leak.bbox(), { duration: dur, pitch: 45, bearing: 8 });
  else if (step.cam === "istanbul") fitTo(istanbul.bbox(), { duration: dur, pitch: 0, bearing: 0, maxZoom: 10 });
  else if (step.cam === "prvs") {
    const top = D.prvs.features.filter((f) => f.properties.rank <= 12);
    if (!top.length) return fitTo(s.bbox, { duration: dur });
    const xs = top.map((f) => f.geometry.coordinates[0]), ys = top.map((f) => f.geometry.coordinates[1]);
    fitTo([Math.min(...xs) - 0.003, Math.min(...ys) - 0.003, Math.max(...xs) + 0.003, Math.max(...ys) + 0.003], { duration: dur, pitch: 45 });
  }
}

export async function start(i = 0) {
  steps = await build();
  document.body.classList.add("story-on");
  go(i);
}

export function stop() {
  if (!active()) return;
  document.body.classList.remove("story-on");
  $("story").hidden = true;
  set({ story: null });
}

export function next() { if (active()) go(Math.min(state.story + 1, steps.length - 1)); }
export function prev() { if (active()) go(Math.max(state.story - 1, 0)); }

function go(i) {
  const step = steps[i];
  if (!step) return;
  set({ ...step.go, story: i, playing: false, peek: false, selection: step.go.selection || null });
  if (step.go.leakEvent !== undefined) leak.syncMap();
  render();
  requestAnimationFrame(() => camera(step));
}

export function render() {
  const el = $("story");
  if (!active()) { el.hidden = true; return; }
  const i = state.story;
  const step = steps[i];
  el.hidden = false;
  el.innerHTML = `
    <div class="story-top">
      <span class="story-count">${i + 1} / ${steps.length}</span>
      <div class="story-dots" aria-hidden="true">${steps.map((_, k) => `<i class="${k === i ? "on" : k < i ? "past" : ""}"></i>`).join("")}</div>
      <button type="button" class="story-exit" data-act="exit">Sunumdan çık <kbd>Esc</kbd></button>
    </div>
    <h2 class="story-title">${esc(step.title)}</h2>
    <p class="story-text">${esc(step.text)}</p>
    <div class="story-figure"><b>${esc(step.figure[0])}</b><span>${esc(step.figure[1])}</span></div>
    <div class="story-nav">
      <button type="button" data-act="prev" ${i === 0 ? "disabled" : ""}>Önceki</button>
      <button type="button" data-act="next" class="btn-primary" ${i === steps.length - 1 ? "disabled" : ""}>Sonraki <kbd>→</kbd></button>
    </div>`;
  el.querySelector('[data-act="exit"]').addEventListener("click", stop);
  el.querySelector('[data-act="prev"]').addEventListener("click", prev);
  el.querySelector('[data-act="next"]').addEventListener("click", next);
}
