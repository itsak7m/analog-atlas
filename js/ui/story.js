// Story mode: a short animated story for judges and first-time visitors (about 2 minutes).
// Few words, one number per scene, real camera flights: Earth -> Jordan (Harrat al-Shaam) -> Mars (Jezero) ->
// a 3D concept base that builds itself -> food grown in water -> a message home crossing space -> the crew's mind.
// Every number is computed from the app's data when the scene is shown (match from the ranking, signal delay from
// JPL planet positions); the base layout and the drawings are our concept (SI-assisted, see README section 10).
// Keys: → next, ← back, Space pause, Esc exit.

import { state } from '../state.js';
import { $, esc, toast } from '../util.js';
import { pct, screeningDefaults } from '../scoring.js';
import { findSite, findTarget } from '../data.js';
import { REDUCED_MOTION } from '../config.js';
import { baseData, coverScreen, revealCover } from './base.js';
import { drawBase, BASE_PARTS } from '../globe/base3d.js';
import { marsDelaySeconds, formatDelay } from '../orbits.js';
import { makePixelCat } from '../../pitch/pixelcat.js';

const SITE = 'harrat';
const TARGET = 'jezero';
const MSG_MS = 6500; // the message animation on screen
const HAZARDS = ['Radiation', 'Isolation and confinement', 'Distance from Earth', 'Gravity', 'Hostile, closed places'];

let run = null;
export const storyRunning = () => !!run;

// The same settings the app opens with, so the story's numbers match the ranking panel.
const defaults = () => ({ mode: 'full', ...screeningDefaults() });

// ---------- timing helpers (pause-aware, end early on Next / Back / Exit) ----------
function wait(ms) {
  const my = run;
  return new Promise((resolve) => {
    let left = ms;
    let last = performance.now();
    const step = () => {
      if (!run || run !== my || my.jump || my.stopped) { resolve(false); return; }
      const now = performance.now();
      if (!my.paused) left -= now - last;
      last = now;
      if (left <= 0) resolve(true); else setTimeout(step, 60);
    };
    step();
  });
}
const until = (check) => new Promise((resolve) => { const step = () => (check() ? resolve() : setTimeout(step, 80)); step(); });
const limit = (promise, ms) => Promise.race([promise, new Promise((r) => setTimeout(r, ms))]);
const words = (text) => text.split(' ').map((w, i) => `<span class="w" style="--i:${i}">${esc(w)}</span>`).join(' ');

// ---------- the 3D base (separate from the Base plan button, so the two never fight) ----------
function removeBase() {
  if (run?.base) { run.base.remove(); run.base = null; }
}

// The same base, the same camera, another world: a picture of the view covers the globe while the other
// place loads under it, then opens from the base outward (see coverScreen in base.js).
async function swapBase(api, sel, place, text) {
  const o = api.globe.orbit;
  if (!o || !api.globe.viewer) return false;
  const view = { heading: o.heading, pitch: o.pitch, range: o.range };
  const cover = await coverScreen(api, text);
  try {
    removeBase();
    const h = await api.jumpTo(sel, view);
    if (h == null) return false;
    run.base = { remove: drawBase(api.globe.viewer, api.globe.ellipsoid, place, h), viewer: api.globe.viewer, at: place.id };
    await api.globe.waitForTiles(8000);
    return true;
  } finally {
    await revealCover(cover);
    api.globe.resumeOrbit();
  }
}

async function ensureBase(api, live, { build }) {
  const viewer = api.globe.viewer;
  if (run.base && run.base.viewer === viewer && run.base.at === TARGET) return true;
  const target = findTarget(state.data, TARGET);
  // The base is in Jordan (the scene before): swap the world back to Mars under the same base.
  if (run.base && run.base.viewer === viewer && state.view === 'closeup') {
    return swapBase(api, { kind: 'target', id: TARGET }, target, `${findSite(state.data, SITE).name}, Earth  →  ${target.name}, Mars`);
  }
  removeBase();
  if (!viewer) return false;
  if (!(state.world === 'mars' && state.view === 'closeup' && state.selected?.id === TARGET)) {
    const ok = await api.flyTo({ kind: 'target', id: TARGET });
    if (!ok || !live()) return false;
  }
  const h = await api.globe.closeOrbit(240, -24);
  if (h == null || !live()) return false;
  const place = findTarget(state.data, TARGET);
  const remove = drawBase(api.globe.viewer, api.globe.ellipsoid, place, h, { build: true, reducedMotion: REDUCED_MOTION });
  run.base = { remove, viewer: api.globe.viewer, at: TARGET };
  if (!build) BASE_PARTS.forEach((p) => remove.reveal(p.id));
  return true;
}

// ---------- the scenes ----------
function buildScenes(api, docs) {
  const site = findSite(state.data, SITE);
  const target = findTarget(state.data, TARGET);
  const match = () => {
    const r = api.ranking();
    const i = r.findIndex((x) => x.site.id === SITE);
    return { p: i < 0 ? null : pct(r[i].score), rank: i + 1, n: r.length };
  };
  const delay = () => marsDelaySeconds(new Date());
  const hazardSrc = docs.base.sources['nasa-hazards'];

  return [
    {
      k: 'Mission', t: 'Before people live on Mars, they practise on Earth.',
      s: 'But where on Earth is the best place to practise?',
      hold: 5000,
      run: async (live) => { removeBase(); await api.showWorld('earth'); if (live()) await api.home(); },
    },
    {
      k: 'Earth · Jordan', t: 'This black lava desert is in Jordan.',
      s: `${esc(site.name)}: black basalt, the same kind of rock as large parts of Mars.`,
      hold: 4000,
      run: async () => { removeBase(); await api.flyTo({ kind: 'site', id: SITE }); },
    },
    {
      k: 'Mars · Jezero Crater', t: 'And this is Jezero Crater, on Mars.',
      s: `Where NASA's ${esc((target.mission || 'Perseverance rover').split(' (')[0])} explores.`,
      viz: () => {
        const m = match();
        if (m.p == null) return '';
        const best = m.rank === 1 ? `the closest of all ${m.n} Earth sites we compared` : `#${m.rank} of ${m.n} Earth sites we compared`;
        return `<div class="st-match"><span>Jordan</span><i class="st-link"></i><span>Mars</span><b><em data-count="${m.p}">0</em>%</b><small>match: ${esc(best)}</small></div>`;
      },
      hold: 5500,
      run: async () => { removeBase(); await api.flyTo({ kind: 'target', id: TARGET }); },
      play: (el) => countUp(el),
    },
    {
      k: 'The future', t: "Now imagine the crew's home.",
      s: 'A concept base: our idea, not built yet.',
      viz: () => `<div class="st-parts">${BASE_PARTS.map((p) => `<span data-part="${p.id}" style="--c:${p.colour}">${esc(p.label)}</span>`).join('')}</div>`,
      hold: 2500,
      run: async (live) => {
        if (!(await ensureBase(api, live, { build: true }))) return;
        for (const p of BASE_PARTS) {
          if (!live()) return;
          run.base.remove.reveal(p.id);
          $(`#story [data-part="${p.id}"]`)?.classList.add('on');
          await wait(1300);
        }
      },
    },
    {
      k: 'Back on Earth', t: 'The same base, in Jordan.',
      s: `${esc(site.name)}: where a crew can practise for Jezero first. Only the world around the base changed.`,
      hold: 5000,
      run: async (live) => {
        if (!(await ensureBase(api, live, { build: false })) || !live()) return;
        await swapBase(api, { kind: 'site', id: SITE }, site, `${target.name}, Mars  →  ${site.name}, Earth`);
      },
    },
    {
      k: 'Food', t: 'Mars soil is toxic, so they grow food in water.',
      s: 'Hydroponics: no soil at all. NASA has grown all three of these without soil.',
      viz: () => `<div class="st-farm">${docs.base.best_set.crops.map((id, i) => {
        const c = docs.base.crops[id];
        const icon = { potato: '🥔', soybean: '🌱', lettuce: '🥬' }[id] || '🌱';
        const role = { potato: 'energy', soybean: 'protein', lettuce: 'vitamins' }[id] || '';
        return `<div class="st-crop" style="--i:${i}"><div class="st-plant">${icon}</div><div class="st-water"></div><b>${esc(c.name)}</b><span>${esc(role)}</span></div>`;
      }).join('')}</div>`,
      hold: 6500,
      run: async (live) => { await ensureBase(api, live, { build: false }); },
      play: (el) => el.querySelector('.st-farm')?.classList.add('grow'),
    },
    {
      k: 'Home', t: () => `A message home takes ${Math.round(delay() / 60)} minutes.`,
      s: 'That is how long light itself needs today, so families send video messages, not calls.',
      viz: () => {
        const d = delay();
        const speed = Math.round(d / (MSG_MS / 1000));
        return `<div class="st-msg">
          <div class="st-typed"><span></span><i></i></div>
          <svg viewBox="0 0 420 96" aria-hidden="true">
            <path class="st-route" d="M52 52 Q210 -22 368 52"/>
            <circle cx="36" cy="58" r="18" class="st-mars"/><text x="36" y="94">Mars</text>
            <circle cx="384" cy="58" r="15" class="st-earth"/><text x="384" y="94">Earth</text>
            <g class="st-env"><rect x="-11" y="-8" width="22" height="16" rx="2"/><path d="M-11 -8 L0 2 L11 -8"/></g>
          </svg>
          <div class="st-clock"><b>0 min 0 s</b> of ${esc(formatDelay(d))} <small>(shown about ${speed}× faster)</small></div>
        </div>`;
      },
      hold: MSG_MS + 3500,
      run: async (live) => { await ensureBase(api, live, { build: false }); },
      play: (el) => sendMessage(el, delay()),
    },
    {
      k: 'The crew', t: 'Being far from family is hard.',
      s: `NASA lists isolation as one of the five hazards of human spaceflight. The communication room keeps the crew close to home.`,
      viz: () => `<div class="st-hazards">${HAZARDS.map((h, i) => `<span class="${i === 1 ? 'hot' : ''}" style="--i:${i}">${esc(h)}</span>`).join('')}</div>
        ${hazardSrc ? `<a class="st-src" href="${esc(hazardSrc.url)}" target="_blank" rel="noopener">Source: ${esc(hazardSrc.label)}</a>` : ''}`,
      hold: 7000,
      run: async (live) => { await ensureBase(api, live, { build: false }); },
    },
    {
      k: 'Analog Atlas', t: 'We find where to practise on Earth.',
      s: () => {
        const m = match();
        return m.rank === 1 ? `For Jezero Crater, the best place is ${esc(site.name)}, in Jordan.` : `For Jezero Crater, ${esc(site.name)} in Jordan ranks #${m.rank}.`;
      },
      end: true,
      run: async (live) => { await ensureBase(api, live, { build: false }); },
    },
  ];
}

function countUp(el) {
  el.querySelectorAll('[data-count]').forEach((n) => {
    const to = Number(n.dataset.count);
    if (REDUCED_MOTION) { n.textContent = String(to); return; }
    const t0 = performance.now();
    const tick = (now) => {
      if (!n.isConnected) return;
      const t = Math.min(1, (now - t0) / 1400);
      n.textContent = String(Math.round(to * (1 - (1 - t) ** 3)));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  el.querySelector('.st-match')?.classList.add('go');
}

// The message is typed, then flies from Mars to Earth while the clock counts the real delay (sped up).
function sendMessage(el, delaySec) {
  const box = el.querySelector('.st-msg');
  if (!box) return;
  const text = 'Hi Mum, the potatoes are growing!';
  const typed = box.querySelector('.st-typed span');
  const route = box.querySelector('.st-route');
  const env = box.querySelector('.st-env');
  const clock = box.querySelector('.st-clock b');
  const len = route.getTotalLength();
  const typeMs = REDUCED_MOTION ? 0 : 1400;
  const t0 = performance.now();
  const place = (f) => { const p = route.getPointAtLength(len * f); env.setAttribute('transform', `translate(${p.x} ${p.y})`); };
  place(0);
  const tick = (now) => {
    if (!box.isConnected) return;
    const dt = now - t0;
    typed.textContent = text.slice(0, Math.ceil(text.length * Math.min(1, typeMs ? dt / typeMs : 1)));
    const f = REDUCED_MOTION ? 1 : Math.max(0, Math.min(1, (dt - typeMs) / MSG_MS));
    place(f);
    route.style.strokeDashoffset = String(len * (1 - f));
    const s = Math.round(delaySec * f);
    clock.textContent = f >= 1 ? 'Delivered ✓' : `${Math.floor(s / 60)} min ${s % 60} s`;
    if (f >= 1) { box.classList.add('done'); return; }
    requestAnimationFrame(tick);
  };
  route.style.strokeDasharray = String(len);
  requestAnimationFrame(tick);
}

// ---------- the card ----------
let catStop = null;
function startCat(canvas) {
  const g = canvas.getContext('2d');
  const { pixelCat } = makePixelCat(g, canvas.width);
  const t0 = performance.now();
  let raf = 0;
  const draw = (now) => {
    g.clearRect(0, 0, canvas.width, canvas.height);
    pixelCat(62, 76, 3, (now - t0) / 1000, { walk: !run?.paused && !REDUCED_MOTION });
    raf = requestAnimationFrame(draw);
  };
  raf = requestAnimationFrame(draw);
  catStop = () => cancelAnimationFrame(raf);
}

function createCard() {
  let el = $('#story');
  if (!el) {
    el = document.createElement('section');
    el.id = 'story';
    el.className = 'story';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
  }
  el.innerHTML = `<div class="st-cat"><canvas width="126" height="80" aria-hidden="true"></canvas><small>SI-assisted drawing</small></div>
    <div class="st-main"><div class="st-body"></div>
      <div class="st-segs"></div>
      <div class="st-ctl">
        <button type="button" class="btn small" data-s="back">◀</button>
        <button type="button" class="btn small" data-s="pause">❚❚</button>
        <button type="button" class="btn small" data-s="next">▶</button>
        <button type="button" class="btn small" data-s="exit">■ Exit</button>
      </div></div>`;
  el.hidden = false;
  el.querySelectorAll('[data-s]').forEach((b) => b.addEventListener('click', () => control(b.dataset.s)));
  startCat(el.querySelector('canvas'));
  return el;
}

function render(scenes, i) {
  const sc = scenes[i];
  const el = $('#story');
  const title = typeof sc.t === 'function' ? sc.t() : sc.t;
  const body = typeof sc.s === 'function' ? sc.s() : sc.s;
  el.classList.toggle('end', !!sc.end);
  el.querySelector('.st-body').innerHTML = `<div class="st-k">${esc(sc.k)}</div>
    <div class="st-t">${words(title)}</div>
    <div class="st-s">${body}</div>
    ${sc.viz ? `<div class="st-viz">${sc.viz()}</div>` : ''}
    ${sc.end ? `<div class="st-end"><button type="button" class="btn primary" data-s="data">Show the data</button>
      <button type="button" class="btn" data-s="again">↺ Play again</button></div>` : ''}`;
  el.querySelectorAll('.st-end [data-s]').forEach((b) => b.addEventListener('click', () => control(b.dataset.s)));
  el.querySelector('.st-segs').innerHTML = scenes.map((_, j) => `<i class="${j < i ? 'done' : j === i ? 'now' : ''}"></i>`).join('');
  el.querySelector('[data-s="back"]').disabled = i === 0;
  el.querySelector('[data-s="next"]').disabled = !!sc.end;
}

function control(c) {
  if (!run) return;
  if (c === 'exit') { run.stopped = true; run.jump = true; return; }
  if (c === 'data') { run.after = 'data'; run.stopped = true; run.jump = true; return; }
  if (c === 'again') { run.target = 0; run.jump = true; return; }
  if (c === 'pause') {
    run.paused = !run.paused;
    const b = $('#story [data-s="pause"]');
    if (b) b.textContent = run.paused ? '▶︎ Play' : '❚❚';
    $('#story').classList.toggle('paused', run.paused);
    return;
  }
  if (c === 'next') { run.target = run.index + 1; run.jump = true; }
  if (c === 'back') { run.target = Math.max(0, run.index - 1); run.jump = true; }
}

function onKey(e) {
  if (!run || e.target.closest?.('input, select, textarea')) return;
  if (e.key === 'ArrowRight') { control('next'); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { control('back'); e.preventDefault(); }
  else if (e.key === ' ' && !e.target.closest?.('button, a')) { control('pause'); e.preventDefault(); }
}

export function stopStory() {
  if (!run) return;
  run.stopped = true;
  run.jump = true;
}

export async function playStory(api) {
  if (run) return;
  let docs;
  try { docs = await baseData(); } catch (err) { toast(`The story could not load its data: ${err.message}`, 5000); return; }
  const saved = { ...api.settings(), targetId: state.targetId };
  const detail = api.detailState();
  run = { index: 0, target: 0, paused: false, jump: false, stopped: false, base: null, after: null };
  document.body.classList.add('story-on');
  $('#story-btn')?.setAttribute('aria-pressed', 'true');
  document.addEventListener('keydown', onKey);
  try {
    api.closePanels();
    api.setSettings(defaults());
    api.setTarget(TARGET);
    const scenes = buildScenes(api, docs);
    createCard().querySelector('[data-s="pause"]').focus({ preventScroll: true });
    while (run && !run.stopped && run.index < scenes.length) {
      const i = run.index;
      const sc = scenes[i];
      run.jump = false;
      render(scenes, i);
      const my = run;
      const live = () => run === my && !my.jump && !my.stopped && my.index === i;
      let done = false;
      const work = limit(sc.run(live).catch((err) => console.warn('story scene', err)), 25000).then(() => { done = true; });
      await Promise.race([work, until(() => done || !live())]);
      if (run.stopped) break;
      if (!run.jump) {
        const el = $('#story');
        el.classList.add('ready');
        sc.play?.(el);
        const seg = el.querySelector('.st-segs i.now');
        if (seg && sc.hold) seg.style.setProperty('--d', `${sc.hold}ms`);
        if (sc.end) await until(() => !live()); else await wait(sc.hold);
        el.classList.remove('ready');
      }
      if (run.stopped) break;
      run.index = run.jump ? run.target : i + 1;
    }
  } finally {
    const after = run?.after;
    removeBase();
    catStop?.();
    document.removeEventListener('keydown', onKey);
    const el = $('#story');
    if (el) { el.hidden = true; el.innerHTML = ''; }
    document.body.classList.remove('story-on');
    $('#story-btn')?.setAttribute('aria-pressed', 'false');
    api.setSettings({ mode: saved.mode, strict: saved.strict, earthTemp: saved.earthTemp || 'air', weights: saved.weights, pillars: saved.pillars });
    try { await api.showWorld('earth'); } catch (err) { console.warn('story end', err); }
    run = null;
    if (after === 'data') {
      // Carry on in the full app: Jezero's ranking, with Harrat al-Shaam open in the panel.
      api.setSettings(defaults());
      api.setTarget(TARGET);
      await api.backToGlobe();
      api.select(SITE);
    } else {
      api.setTarget(saved.targetId);
      await api.backToGlobe();
      api.restoreDetail(detail);
    }
    $('#story-btn')?.focus({ preventScroll: true });
  }
}
