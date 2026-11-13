// Ask Atlas: questions about the project in plain words.
//  - On this computer (start.bat), with an Anthropic API key saved in anthropic_key.txt, the local server asks
//    Claude (SI) and gives it only the facts of this app (rankings, base data, sources) to answer from.
//    The key stays in the server; the browser never sees it.
//  - Everywhere else (GitHub Pages, no key, no internet) it answers from our own data with fixed rules:
//    no SI, and it says so on every answer.

import { state } from '../state.js';
import { esc, fmt, BODY_LABEL } from '../util.js';
import { pct, PILLARS } from '../scoring.js';
import { computeRanking, displayRanks } from './ranking.js';
import { openOverlay } from './overlay.js';
import { baseData, delayLine, factLines, planBodyOf } from './base.js';

const LOCAL = ['localhost', '127.0.0.1'].includes(location.hostname);
const EXAMPLES = [
  'Which Earth site is the best twin of Jezero Crater?',
  'Is potato a good crop for Mars?',
  'How long does a message to Mars take today?',
  'What is the Moon made of?',
  'Why is Harrat al-Shaam a good analog?',
  'What can a test base on Earth not test?',
];

const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, ' ');
const short = (name) => name.split(' (')[0];

function findIn(q, list) {
  const n = ` ${norm(q)} `;
  let best = null;
  for (const item of list) {
    const words = [item.name, short(item.name), ...(item.aliases || []), item.id.replace(/-/g, ' ')].map(norm).filter((w) => w.length > 3);
    for (const w of words) if (n.includes(` ${w}`) && (!best || w.length > best.len)) best = { item, len: w.length };
  }
  return best?.item || null;
}

function twinsText(t, n = 3) {
  const r = computeRanking(t.id);
  const ranks = displayRanks(r);
  const top = r.filter((x) => x.score != null).slice(0, n);
  if (!top.length) return `No Earth site has a score for ${t.name} with the current settings.`;
  return `Closest Earth twins of ${short(t.name)} (${state.mode === 'full' ? 'full analog match' : 'climate match'}): ${top.map((x) => `#${ranks[r.indexOf(x)]} ${x.site.name} ${pct(x.score)} %`).join(', ')}.`;
}

function siteText(s) {
  const hits = state.data.targets.map((t) => {
    const r = computeRanking(t.id);
    const i = r.findIndex((x) => x.site.id === s.id);
    return i < 0 || r[i].score == null ? null : { t, rank: displayRanks(r)[i], p: pct(r[i].score), r: r[i] };
  }).filter(Boolean).sort((a, b) => a.rank - b.rank || b.p - a.p).slice(0, 3);
  const best = hits[0];
  const strong = best ? PILLARS.filter((p) => (best.r[p.id]?.score ?? 0) >= 0.6).map((p) => p.label.toLowerCase()) : [];
  return `${s.name} (${s.country}): ${s.why} Our scores: ${hits.map((h) => `#${h.rank} for ${short(h.t.name)} (${h.p} %)`).join(', ')}.${strong.length ? ` Strong pillars for ${short(best.t.name)}: ${strong.join(', ')}.` : ''}`;
}

// Offline answers: fixed rules over the app's own data. Returns { text, sources }.
async function offlineAnswer(q) {
  const { base, crops } = await baseData();
  const n = norm(q);
  const has = (...w) => w.some((x) => n.includes(x));
  const target = findIn(q, state.data.targets);
  const site = findIn(q, state.data.sites);
  const body = has('mars', 'martian') ? 'mars' : has('moon', 'lunar') ? 'moon' : null;
  if (has('potato', 'crop', 'food', 'farm', 'grow', 'hydropon', 'plant', 'eat', 'protein', 'carb', 'wheat', 'soy', 'lettuce', 'greenhouse')) {
    const c = crops.crops;
    const line = (id) => `${base.crops[id].name}: ${fmt(c[id].per100g.kcal, 0)} kcal, ${fmt(c[id].per100g.carbs_g, 1)} g carbs, ${fmt(c[id].per100g.protein_g, 1)} g protein per 100 g raw`;
    const potato = has('potato') ? ` Potato is a good choice. ${base.crops.potato.role} ${base.crops.potato.nasa.text}` : '';
    return { text: `Best low-cost set for a base greenhouse: ${base.best_set.why}${potato}\n${base.best_set.crops.map(line).join('\n')}\nPlants grow in water with nutrients (hydroponics), not in soil${body !== 'moon' ? '; Martian soil holds toxic perchlorate' : ''}.`, sources: ['USDA FoodData Central', base.sources['bpc-1996'].label] };
  }
  if (has('delay', 'signal', 'message', 'call', 'family', 'talk', 'communicat', 'radio', 'conjunction')) {
    const b = body || 'mars';
    return { text: `Signal time from ${b === 'moon' ? 'the Moon' : 'Mars'} to Earth: ${delayLine(b)}.${b === 'mars' ? ` ${base.comm.conjunction.text}` : ''}`, sources: [b === 'mars' ? 'JPL Approximate Positions of the Planets' : 'NASA Moon Fact Sheet', 'NASA Mars Fact Sheet'] };
  }
  if (has('gravity', 'vacuum', 'radiation', 'cannot', 'can t', 'not test', 'limit')) {
    return { text: 'An Earth analog cannot reproduce low gravity (Moon 16 %, Mars 38 % of Earth\'s), vacuum or the thin Martian air (under 1 % of Earth\'s pressure), or space radiation. We do not score them; every analog breaks there. Dust storms are not scored either: we have no dust data for the Earth sites.', sources: ['NASA Moon and Mars Fact Sheets', 'Method & data → Challenge criteria'] };
  }
  if (body && has('made', 'composition', 'element', 'rock', 'red', 'what is', 'soil', 'mineral', 'air', 'atmosphere')) {
    const lines = base.bodies[body].made_of.map((x) => `• ${x.text}`).join('\n');
    const extra = body === 'mars' ? `\n• Air: ${base.bodies.mars.air_text.text}, ${base.bodies.mars.pressure_mbar.value} mbar.` : `\n• ${base.bodies.moon.pressure_text.text}.`;
    return { text: `What makes the ${BODY_LABEL[body]} the ${BODY_LABEL[body]}:\n${lines}${extra}`, sources: [body === 'mars' ? 'NASA Science: Mars Facts' : 'NASA Science: Moon Composition', `NASA ${BODY_LABEL[body]} Fact Sheet`] };
  }
  if (target && !site) return { text: twinsText(target, 5), sources: ['Analog Atlas ranking (Method & data)'] };
  if (site) return { text: `${siteText(site)}${target ? `\n${twinsText(target)}` : ''}`, sources: ['Analog Atlas ranking and site sources'] };
  if (has('best', 'twin', 'analog', 'rank')) {
    const t = state.data.targets.find((x) => x.id === state.targetId);
    return { text: twinsText(t, 5), sources: ['Analog Atlas ranking (Method & data)'] };
  }
  return { text: `I answer from this app's data. Try a place (Jezero, Malapert, Harrat al-Shaam, Wadi Rum…), crops and food, the signal delay to the Moon or Mars, what the Moon or Mars is made of, or what an Earth analog cannot test.`, sources: [] };
}

// The facts sent to Claude with a question: compact text, only from the app.
async function contextFor(q) {
  await baseData();
  const t = state.data.targets.find((x) => x.id === state.targetId);
  const asked = findIn(q, state.data.targets) || t;
  const lines = [
    `Project: Analog Atlas (NASA Space Apps 2026, team Cosmic Cats, Amman). It ranks ${state.data.sites.length} Earth sites against ${state.data.targets.length} Moon and Mars targets on five pillars (climate, terrain, landing zone, geology, resources) with real, sourced data; a missing value is "not measured".`,
    twinsText(asked, 5),
  ];
  if (asked.id !== t.id) lines.push(twinsText(t, 3));
  const site = findIn(q, state.data.sites) || (state.selected?.kind === 'site' ? state.data.sites.find((s) => s.id === state.selected.id) : null);
  if (site) lines.push(siteText(site));
  const body = planBodyOf(site || asked, asked);
  lines.push(...factLines('moon'), ...factLines('mars'));
  lines.push(`Signal delay now: Moon ${delayLine('moon')}; Mars ${delayLine('mars')}.`);
  const { base, crops } = await baseData();
  for (const [id, c] of Object.entries(crops.crops)) lines.push(`Crop ${base.crops[id]?.name || id} per 100 g raw (USDA FDC ${c.fdcId}): ${Object.entries(c.per100g).map(([k, v]) => `${k} ${v}`).join(', ')}. ${base.crops[id]?.nasa?.text || ''}`);
  lines.push(`Best low-cost greenhouse set: ${base.best_set.why}`);
  lines.push('Earth analogs cannot reproduce low gravity, vacuum, thin Martian air or radiation; dust storms are not scored (no dust data for Earth sites).');
  lines.push(`The question is mainly about the ${BODY_LABEL[body]}.`);
  return lines.join('\n');
}

// Asked once per visit: does the local server have a key and the SDK? (No key: no request, no error.)
let claudeReady = null;
const hasClaude = async () => {
  if (!LOCAL) return false;
  if (claudeReady == null) claudeReady = fetch('/api/ask-status', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : {})).then((j) => !!j.claude).catch(() => false);
  return claudeReady;
};

async function askClaude(q) {
  if (!(await hasClaude())) return null;
  try {
    const res = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: q, context: await contextFor(q) }) });
    if (!res.ok) return null; // no key, no SDK, no internet: the offline answer takes over
    const j = await res.json();
    return j.answer ? { text: j.answer, model: j.model } : null;
  } catch { return null; }
}

let history = [];

export function openAsk(prefill = '') {
  const body = `<div class="sheet-body ask">
    <p class="src">${LOCAL ? 'On this computer: answers by Claude (SI) when an Anthropic API key is set up (README), from this app\'s facts only. Otherwise' : 'On this website'} answers come from our own data with fixed rules (no SI). Check every number in the app.</p>
    <div class="ask-log" aria-live="polite"></div>
    <div class="ask-ex">${EXAMPLES.map((x) => `<button type="button" class="btn small" data-ex>${esc(x)}</button>`).join('')}</div>
    <form class="ask-form"><input type="text" maxlength="400" placeholder="Ask about a place, the base, crops, the Moon or Mars…" aria-label="Your question"><button type="submit" class="btn primary">Ask</button></form>
  </div>`;
  const el = openOverlay({ title: 'Ask Atlas', body, wide: false });
  const log = el.querySelector('.ask-log');
  const input = el.querySelector('input');
  const draw = () => {
    log.innerHTML = history.map((m) => (m.q ? `<div class="ask-q">${esc(m.q)}</div>`
      : `<div class="ask-a">${esc(m.text).replace(/\n/g, '<br>')}<div class="src">${m.model ? `Claude (SI), ${esc(m.model)}, from this app's facts · check the numbers in the app` : m.pending ? 'Thinking…' : `From our data, fixed rules (no SI)${m.sources?.length ? ` · ${esc(m.sources.join(' · '))}` : ''}`}</div></div>`)).join('');
    log.scrollTop = log.scrollHeight;
  };
  const ask = async (q) => {
    q = q.trim();
    if (!q) return;
    history.push({ q });
    const a = { text: '', pending: true };
    history.push(a);
    draw();
    const claude = await askClaude(q);
    Object.assign(a, claude || (await offlineAnswer(q)), { pending: false });
    draw();
  };
  el.querySelector('.ask-form').addEventListener('submit', (e) => { e.preventDefault(); const q = input.value; input.value = ''; ask(q); });
  el.querySelectorAll('[data-ex]').forEach((b) => b.addEventListener('click', () => ask(b.textContent)));
  draw();
  if (prefill) ask(prefill); else input.focus();
}

export { offlineAnswer }; // for the tests
