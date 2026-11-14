// Concept layout and the sourced requirements for an Earth rehearsal, Moon or Mars base.
import { state } from '../state.js';
import { esc, fmt, toast, BODY_LABEL } from '../util.js';
import { pct, PILLARS } from '../scoring.js';
import { closeOverlay, openOverlay } from './overlay.js';
import { basePlanMarkup, bindBasePlan } from './base-plan.js';
import { marsDelaySeconds, marsDistanceKm, nextConjunction, formatDelay, LIGHT_KM_S } from '../orbits.js';
import { tourRunning } from './tour.js';
import { corridorActive } from './corridor.js';

let docs = null;
export async function baseData() {
  if (!docs) {
    const get = (p) => fetch(p, { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json(); });
    const [base, crops] = await Promise.all([get('data/base.json'), get('data/crops.json')]);
    docs = { base, crops };
  }
  return docs;
}

const link = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a>`;
const src = (id) => { const s = docs?.base.sources[id]; return s ? `<span class="src">${link(s.url, s.label)}</span>` : ''; };
const moonDelay = () => { const d = docs.base.bodies.moon.distance_km; return [d.min / LIGHT_KM_S, d.max / LIGHT_KM_S]; };
const marsRange = () => { const d = docs.base.bodies.mars.distance_km; return [d.min / LIGHT_KM_S, d.max / LIGHT_KM_S]; };
const dateText = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
const timeText = (d) => d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

// The world the base is planned for: the target's own body, or (at an Earth site) the body of the target it is compared with.
export const planBodyOf = (place, target) => (place.body && place.body !== 'earth' ? place.body : target?.body || 'mars');

// One line for the signal delay to Earth, used in the requirements and Ask answers.
export function delayLine(body, now = new Date()) {
  if (body === 'moon') { const [a, b] = moonDelay(); return `${formatDelay(a)} to ${formatDelay(b)} each way: live calls work`; }
  const [a, b] = marsRange();
  return `${formatDelay(marsDelaySeconds(now))} each way today (${formatDelay(a)} to ${formatDelay(b)} over the years): video messages, not live calls`;
}

let request = 0;
let dialog = null;

export const baseActive = () => !!dialog;

export async function startBase({ place, target, result }) {
  if (tourRunning() || corridorActive()) { toast('Exit the tour or the Jordan corridor first (Esc).'); return; }
  stopBase();
  const run = request;
  try { await baseData(); } catch (err) { toast(`Base plan data could not load: ${err.message}`, 5000); return; }
  if (request !== run) return;

  const body = planBodyOf(place, target);
  const siteBody = place.body || 'earth';
  const location = `${BODY_LABEL[siteBody]} · ${place.name}`;
  const destination = siteBody === 'earth' && target ? `Rehearsal for ${target.name}, ${BODY_LABEL[body]}` : '';
  const familyText = body === 'moon'
    ? `The crew can schedule private video calls with family. One-way signal delay to Earth is ${moonDelay().map(formatDelay).join(' to ')}.`
    : `The crew records private video messages for family. Today the one-way signal delay to Earth is ${formatDelay(marsDelaySeconds(new Date()))}.`;
  let dispose;
  dialog = openOverlay({
    title: 'Base floor plan',
    body: basePlanMarkup({ location, destination }),
    onClose: () => { dispose?.(); dialog = null; },
  });
  dispose = bindBasePlan(dialog, { familyText, onDetails: () => openBaseDetails({ place, target, result, body }) });
}

export function stopBase() {
  request += 1;
  if (dialog) closeOverlay();
}

// ---------- plan details ----------
function problems(body, ctx) {
  const b = docs.base.bodies;
  const e = b.earth;
  const g = (x) => `${fmt(x.value, 2)} m/s² (${Math.round((x.value / e.gravity_ms2.value) * 100)} % of Earth's)`;
  const rows = body === 'moon' ? [
    ['No air', `${b.moon.pressure_text.text}.`, 'Pressurised habitat modules joined by tunnels; spacesuits outside.', 'moon-factsheet'],
    ['Heat and cold', `${b.moon.temperature_text.text}.`, 'Insulated modules; buried or shielded walls.', 'moon-factsheet'],
    ['Long nights', `${b.moon.day_length_text.text}, so most places have about two weeks of darkness.`, 'Solar arrays with energy storage. High ridges near the south pole get much longer sunlight (see the base sites in the app).', 'moon-factsheet'],
    ['Food', 'Nothing grows in lunar soil on its own.', 'Hydroponic greenhouse with LED light: water and nutrients, no soil.', 'veggie'],
    ['Water', b.moon.made_of[3].text, 'Mine ice from the shadowed craters near the base.', 'lcross'],
    ['Talking to family', `Signals take ${delayLine('moon')}.`, 'Communication room with live video calls.', 'moon-factsheet'],
    ['Isolation and stress', `${docs.base.comm.isolation.text}.`, 'Private space in the habitat, regular family contact from the communication room, and crew support. NASA already tests this on Earth in its HERA analog habitat.', 'nasa-hazards', 'nasa-hera'],
    ['Low gravity', `${g(b.moon.gravity_ms2)}.`, 'Exercise; cannot be tested on Earth.', 'moon-factsheet'],
  ] : [
    ['Thin air', `${fmt(b.mars.pressure_mbar.value, 2)} mbar, ${fmt((b.mars.pressure_mbar.value / e.pressure_mbar.value) * 100, 1)} % of Earth's air pressure; ${b.mars.air_text.text}.`, 'Pressurised habitat; the CO₂ in the air can feed the plants.', 'mars-factsheet'],
    ['Cold', `${b.mars.temperature_text.text}.`, 'Heated, insulated modules and greenhouse.', 'mars-factsheet'],
    ['Weak sunlight', `${fmt(b.mars.sunlight_wm2.value, 0)} W/m², ${Math.round((b.mars.sunlight_wm2.value / e.sunlight_wm2.value) * 100)} % of the sunlight at Earth.`, 'Larger solar arrays; LED grow lights in the greenhouse.', 'mars-factsheet'],
    ['Toxic soil', b.mars.made_of[3].text, 'Hydroponics: plants grow in water with nutrients, not in Martian soil.', 'phoenix-perchlorate'],
    ['Dust storms', b.mars.made_of[1].text, 'Dust-proof seals and stored energy for dark, dusty weeks.', 'mars-facts'],
    ['Talking to family', `Signals take ${delayLine('mars')}.`, 'Communication room for recorded video messages; plan for the solar conjunction break.', 'jpl-approx'],
    ['Isolation and stress', `${docs.base.comm.isolation.text}.`, 'Private space in the habitat, regular family contact from the communication room, and crew support. NASA already tests this on Earth in its HERA analog habitat.', 'nasa-hazards', 'nasa-hera'],
    ['Low gravity', `${g(b.mars.gravity_ms2)}.`, 'Exercise; cannot be tested on Earth.', 'mars-factsheet'],
  ];
  const head = '<tr><th>Problem</th><th>Measured</th><th>Part of the base that solves it (concept)</th></tr>';
  return `<div class="scroll-x"><table class="facts">${head}${rows.map(([p, m, s, id, sid]) => `<tr><td><b>${esc(p)}</b></td><td>${esc(m)} ${src(id)}</td><td>${esc(s)}${sid ? ` ${src(sid)}` : ''}</td></tr>`).join('')}</table></div>`;
}

function testSection(ctx) {
  const { place, target, result } = ctx;
  if (place.body && place.body !== 'earth') return '';
  const rows = PILLARS.map((p) => {
    const s = result?.[p.id]?.score;
    const context = p.id === 'landing' && !state.pillars.landing;
    const use = s == null ? 'no data' : context ? 'Terrain context' : s >= 0.6 ? 'Candidate for a field check' : 'Weak match';
    return `<tr><td>${esc(p.label)}</td><td class="num">${s == null ? '<span class="src">not measured</span>' : `${pct(s)} %`}</td><td>${esc(use)}</td></tr>`;
  }).join('');
  return `<h3 class="label">What a test base here can practise for ${esc(target.name)}</h3>
    <p>Screening score: ${result?.score == null ? 'unavailable' : `<b>${pct(result.score)}%</b>`}. A pillar at 60% or higher can help prioritize a field check.</p>
    <table class="facts"><thead><tr><th>Pillar</th><th>Match</th><th>Use</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="caveat">Cannot be tested anywhere on Earth: low gravity, vacuum or the thin Martian air, and space radiation.</p>`;
}

// Crew wellbeing and mission lessons (data/base.json): what was found, its source, and what the base does about it.
function table(rows, found, first = 'Topic') {
  const head = `<tr><th>${esc(first)}</th><th>${esc(found)}</th><th>What the base does (concept)</th></tr>`;
  return `<div class="scroll-x"><table class="facts">${head}${rows.map((r) => `<tr><td><b>${esc(r.topic)}</b></td><td>${esc(r.text)} ${src(r.source)}</td><td>${esc(r.base)}</td></tr>`).join('')}</table></div>`;
}

function madeOf(body) {
  const b = docs.base.bodies[body];
  return `<ul>${b.made_of.map((x) => `<li>${esc(x.text)} ${src(x.source)}</li>`).join('')}</ul>`;
}

const NUTRIENTS = [['kcal', 'Energy', 'kcal', 0], ['carbs_g', 'Carbs', 'g', 1], ['protein_g', 'Protein', 'g', 1], ['fat_g', 'Fat', 'g', 1], ['vitc_mg', 'Vitamin C', 'mg', 1]];

function greenhouse(body) {
  const { base, crops } = docs;
  const ids = Object.keys(base.crops).filter((id) => crops.crops[id]);
  const rows = ids.map((id) => {
    const c = base.crops[id];
    const n = crops.crops[id];
    const best = base.best_set.crops.includes(id);
    return `<tr${best ? ' class="best"' : ''}><td><b>${esc(c.name)}</b>${best ? ' <span class="tag">best set</span>' : ''}<div class="src">${esc(c.role)}</div></td>
      ${NUTRIENTS.map(([k, , , d]) => `<td class="num">${n.per100g[k] == null ? '<span class="src">not measured</span>' : fmt(n.per100g[k], d)}</td>`).join('')}
      <td><span class="src">${c.nasa ? `${esc(c.nasa.text)} ${c.nasa.sources.map((s) => src(s)).join(' ')}` : '—'}</span> <span class="src">${link(n.url, `FDC ${n.fdcId}`)}</span></td></tr>`;
  }).join('');
  const light = body === 'mars'
    ? `Mars gets ${Math.round((base.bodies.mars.sunlight_wm2.value / base.bodies.earth.sunlight_wm2.value) * 100)} % of Earth's sunlight, so the greenhouse needs LED grow lights.`
    : 'A lunar night lasts about two weeks, so the greenhouse needs LED grow lights and stored energy.';
  const plate = base.best_set.crops.map((id, i) => `<label class="plate-row">${esc(base.crops[id].name)} <input type="range" min="0" max="600" step="50" value="${[400, 100, 150][i] ?? 100}" data-crop="${esc(id)}"><output>0 g</output></label>`).join('');
  return `<p><b>Why water, not soil:</b> plants grow in water with nutrients (hydroponics), so the base does not depend on the soil${body === 'mars' ? ', and Martian soil holds toxic perchlorate' : ''}. ${esc(light)}</p>
    <p><b>Best low-cost set:</b> ${esc(base.best_set.why)} ${src('bpc-1996')}</p>
    <p><b>Why not the local soil?</b> In a 2014 experiment, plants grew for 50 days in Mars and Moon soil simulants without added nutrients: best in the Mars simulant, worst in the Moon simulant. ${src('wamelink-2014')} A simulant is not the real soil${body === 'mars' ? ', and real Martian soil also holds perchlorate' : ''}, so the base starts with hydroponics.</p>
    <p><b>Nothing is waste:</b> ESA's MELiSSA project works on a closed loop, where microbes and plants turn the crew's waste and exhaled CO₂ back into oxygen, water and food. ${src('esa-melissa')}</p>
    <div class="scroll-x"><table class="facts crops"><thead><tr><th>Crop (per 100 g, raw)</th>${NUTRIENTS.map(([, l, u]) => `<th>${esc(l)} <span class="src">${esc(u)}</span></th>`).join('')}<th>Grown by NASA</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="src">Nutrients: ${link(crops.source.url, crops.source.label)} (each crop links its record). Raw food, before cooking.</p>
    <h4 class="label">Build a daily plate from the best set</h4>
    <div class="plate">${plate}</div><div class="plate-total" aria-live="polite"></div>
    <p class="src">The totals are the USDA values times the weight. They show what a plate gives, not what a person needs.</p>`;
}

function bindPlate(el) {
  const { crops } = docs.crops;
  const inputs = [...el.querySelectorAll('.plate input')];
  const total = el.querySelector('.plate-total');
  const redraw = () => {
    const sum = Object.fromEntries(NUTRIENTS.map(([k]) => [k, 0]));
    for (const i of inputs) {
      const g = Number(i.value);
      i.nextElementSibling.textContent = `${g} g`;
      for (const [k] of NUTRIENTS) sum[k] += ((crops[i.dataset.crop].per100g[k] || 0) * g) / 100;
    }
    total.innerHTML = NUTRIENTS.map(([k, l, u, d]) => `<span><b>${fmt(sum[k], k === 'kcal' ? 0 : d)}</b> ${esc(u)} ${esc(l.toLowerCase())}</span>`).join('');
  };
  inputs.forEach((i) => i.addEventListener('input', redraw));
  redraw();
}

function comm(body) {
  const now = new Date();
  const { base } = docs;
  if (body === 'moon') {
    const [a, b] = moonDelay();
    return `<p>The Moon is ${fmt(base.bodies.moon.distance_km.min / 1000, 1)} to ${fmt(base.bodies.moon.distance_km.max / 1000, 1)} thousand km away, so a radio signal takes <b>${formatDelay(a)} to ${formatDelay(b)}</b> each way. ${src('moon-factsheet')} Live video calls with family work, with a short pause.</p>${sender('moon', (a + b) / 2)}`;
  }
  const d = marsDelaySeconds(now);
  const [a, b] = marsRange();
  const conj = nextConjunction(now);
  return `<p>Today Mars is <b>${fmt(marsDistanceKm(now) / 1e6, 1)} million km</b> from Earth, so a signal takes <b>${formatDelay(d)}</b> each way (computed for ${esc(dateText(now))} from ${link(base.sources['jpl-approx'].url, 'JPL planet positions')}). Over the years it is ${formatDelay(a)} to ${formatDelay(b)} ${src('mars-factsheet')}. A question and its answer take at least ${formatDelay(2 * d)}, so families send <b>recorded video messages</b>, like voice notes, not live calls.</p>
    <p>${esc(base.comm.conjunction.text)} ${src('conjunction-2023')}${conj ? ` Next solar conjunction (computed): <b>about ${esc(dateText(conj.date))}</b>.` : ''}</p>${sender('mars', d)}`;
}

function sender(body, delay) {
  return `<h4 class="label">Send a message home</h4>
    <div class="sender" data-delay="${delay}" data-body="${body}">
      <input type="text" maxlength="140" placeholder="Hi mum, the potatoes are growing!" aria-label="Message to your family">
      <label class="src"><input type="checkbox" checked data-fast> demo speed (×60)</label>
      <button type="button" class="btn small primary" data-send>Send</button>
      <div class="sender-track"><i></i></div><div class="sender-log src" aria-live="polite"></div></div>`;
}

function bindSender(el) {
  const box = el.querySelector('.sender');
  if (!box) return;
  const delay = Number(box.dataset.delay);
  const bar = box.querySelector('.sender-track i');
  const log = box.querySelector('.sender-log');
  let timer = null;
  box.querySelector('[data-send]').addEventListener('click', () => {
    const text = box.querySelector('input[type="text"]').value.trim() || box.querySelector('input[type="text"]').placeholder;
    const fast = box.querySelector('[data-fast]').checked;
    const ms = (delay * 1000) / (fast ? 60 : 1);
    const sent = new Date();
    const arrive = new Date(sent.getTime() + delay * 1000);
    const reply = new Date(sent.getTime() + 2 * delay * 1000);
    cancelAnimationFrame(timer);
    const t0 = performance.now();
    const step = () => {
      const f = Math.min(1, (performance.now() - t0) / ms);
      bar.style.width = `${f * 100}%`;
      if (f < 1) timer = requestAnimationFrame(step);
      else log.innerHTML = `“${esc(text)}” has reached Earth. Earliest reply back at the base: <b>${esc(timeText(reply))}</b>.`;
    };
    log.innerHTML = `Sent ${esc(timeText(sent))} · travelling at the speed of light · arrives on Earth ${esc(timeText(arrive))}${fast ? ' (shown 60 times faster)' : ''}.`;
    step();
  });
}

export async function openBaseDetails(ctx) {
  try { await baseData(); } catch (err) { toast(`Base plan data could not load: ${err.message}`, 5000); return; }
  const { place, body } = ctx;
  const test = !place.body || place.body === 'earth';
  const name = BODY_LABEL[body];
  const html = `<div class="sheet-body method base-plan">
    <p class="caveat">Concept layout for future work. The requirements below use cited measurements and calculations.</p>
    ${test ? testSection(ctx) : ''}
    <h3 class="label">${esc(name)}: problems and the part of the base that solves each</h3>${problems(body, ctx)}
    <h3 class="label">What makes ${esc(name)} ${esc(name)}</h3>${madeOf(body)}
    <h3 class="label">Hydroponic greenhouse</h3>${greenhouse(body)}
    <h3 class="label">Communication room</h3>${comm(body)}
    <h3 class="label">Crew wellbeing: the human side</h3>${table(docs.base.crew, 'What research found')}
    <h3 class="label">Lessons from past missions: why rehearse on Earth first</h3>${table(docs.base.lessons, 'What happened', 'Mission')}
    
  </div>`;
  const el = openOverlay({ title: `Base plan · ${test ? `test base at ${place.name}` : `${name} base at ${place.name}`}`, body: html });
  bindPlate(el);
  bindSender(el);
}

// For the Ask panel: the facts it may use, as plain text lines with their sources.
export function factLines(body) {
  const b = docs.base.bodies[body];
  const s = docs.base.sources;
  const lines = [];
  for (const [k, v] of Object.entries(b)) {
    if (k === 'made_of') continue;
    const val = v.text || (v.value != null ? `${v.value}` : v.min != null ? `${v.min}-${v.max} km` : '');
    lines.push(`${body} ${k}: ${val} [${s[v.source]?.label}]`);
  }
  for (const x of b.made_of) lines.push(`${body}: ${x.text} [${s[x.source]?.label}]`);
  return lines;
}
