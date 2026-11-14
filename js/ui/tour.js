// Guided mission tour (about 2 minutes): a narrated explanation with animated captions,
// counters, filling score bars and a glowing frame around the part of the screen being explained.
// Controls: Back, Pause, Next, Exit (keys: ←, Space, →, Esc). Focus starts on Pause, so Space pauses;
// on another focused tour button Space presses that button.
// Every step has a time limit, so a slow download can never make the tour hang.
// Every count, name and percentage in the narration is computed from the data when the step is shown.

import { state } from '../state.js';
import { pct, CLIMATE_FACTORS, PILLARS } from '../scoring.js';
import { $, esc, fmt, distanceKm, BODY_LABEL } from '../util.js';
import { findSite, findTarget } from '../data.js';
import { TARGET_GROUPS } from './topbar.js';
import { displayRanks, baseConsensus, baseConsensusText } from './ranking.js';
import { REDUCED_MOTION } from '../config.js';
import { SOUTH_POLE_VIEW as POLE } from '../globe/globe.js';

const JORDAN = ['harrat', 'waqf-as-suwwan', 'lisan-dead-sea', 'qa-al-jafr', 'wadi-rum'];
const AMMAN = { lat: 31.95, lon: 35.93 };

// Plain words for the target groups of the top bar (TARGET_GROUPS): [one, more than one].
const GROUP_WORDS = {
  'moon-base': ['permanent Moon base site', 'permanent Moon base sites'],
  'moon-cave': ['Moon cave shelter (lava-tube pit)', 'Moon cave shelters (lava-tube pits)'],
  'moon-ice': ['shadowed crater floor at the south pole', 'shadowed crater floors at the south pole'],
  'mars-base': ['proposed Mars human landing zone', 'proposed Mars human landing zones'],
  'mars-cave': ['Mars cave skylight', 'Mars cave skylights'],
  mars: ['Mars lander site', 'Mars lander sites'],
  'moon-ref': ['Apollo site', 'Apollo sites'],
};

// Plain words for the pillars, for "not measured" notes.
const PILLAR_WORDS = { climate: 'climate', terrain: 'ground slope', landing: 'landing zone', geology: 'rock type', resources: 'resources' };

// The tour explains the default settings, so it uses them and puts the visitor's own settings,
// target and selection (detail panel) back at the end.
const defaults = () => ({
  strict: false,
  earthTemp: 'air',
  weights: Object.fromEntries(CLIMATE_FACTORS.map((f) => [f.id, 1])),
  pillars: Object.fromEntries(PILLARS.map((p) => [p.id, 1])),
});

let run = null;

export function tourRunning() { return !!run; }

// ---------- small helpers ----------
const NUM = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const num = (n) => NUM[n] || String(n);
const cap = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const list = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
const short = (place) => place.name.split(' (')[0].split(',')[0];

function words(text) {
  return text.split(' ').map((w, i) => `<span class="w" style="--i:${i}">${esc(w)}</span>`).join(' ');
}

function counter(el) {
  // Animate every [data-count] number from 0 to its value (shown at once with reduced motion).
  el.querySelectorAll('[data-count]').forEach((n) => {
    const to = Number(n.dataset.count);
    const digits = Number(n.dataset.digits || 0);
    if (REDUCED_MOTION) { n.textContent = fmt(to, digits); return; }
    const start = performance.now();
    const dur = 1100;
    const tick = (now) => {
      if (!document.contains(n)) return;
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - (1 - t) ** 3;
      n.textContent = fmt(to * eased, digits);
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  // Fill bars after a short delay so the transition is visible.
  const fill = () => el.querySelectorAll('[data-fill]').forEach((b) => { b.style.width = `${b.dataset.fill}%`; });
  if (REDUCED_MOTION) fill(); else setTimeout(fill, 250);
}

// The top-bar button shows that the tour runs, and that pressing it now stops the tour.
export function markRunButton(sel, on, idle, running) {
  const b = $(sel);
  if (!b) return;
  b.setAttribute('aria-pressed', String(on));
  const icon = b.querySelector('[aria-hidden]');
  const txt = b.querySelector('.txt');
  if (icon) icon.textContent = on ? running[0] : idle[0];
  if (txt) txt.textContent = on ? running[1] : idle[1];
  b.title = on ? running[2] : idle[2];
}
const tourButton = (on) => markRunButton('#tour-btn', on, ['▶', 'Data tour', 'Play the 2-minute data tour'], ['■', 'Stop tour', 'Stop the mission tour (Esc)']);

function ring(selector) {
  let el = $('#tour-ring');
  const target = selector && document.querySelector(selector);
  // (offsetParent is always null for the fixed panels, so it cannot tell whether they are shown.)
  if (!target || target.hidden || !target.getClientRects().length || getComputedStyle(target).visibility === 'hidden') { if (el) el.hidden = true; return; }
  if (!el) {
    el = document.createElement('div');
    el.id = 'tour-ring';
    el.className = 'tour-ring';
    document.body.appendChild(el);
  }
  const r = target.getBoundingClientRect();
  el.hidden = false;
  Object.assign(el.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
}

// A wait that stops while paused and ends early when the user jumps to another step.
function wait(ms) {
  const my = run;
  return new Promise((resolve) => {
    let left = ms;
    let last = performance.now();
    const step = () => {
      if (!run || run !== my || my.jump) { resolve(false); return; }
      const now = performance.now();
      if (!my.paused) left -= now - last;
      last = now;
      if (left <= 0) resolve(true); else setTimeout(step, 80);
    };
    step();
  });
}

const limit = (promise, ms) => Promise.race([promise, new Promise((r) => setTimeout(r, ms))]);

// Resolves when check() is true (checked every 80 ms, like wait()).
function until(check) {
  return new Promise((resolve) => {
    const step = () => { if (check()) resolve(); else setTimeout(step, 80); };
    step();
  });
}

// "one permanent Moon base site, four proposed Mars human landing zones, …" from the target list.
function groupCounts(targets) {
  const known = new Set(TARGET_GROUPS.map((g) => g.id));
  const parts = TARGET_GROUPS.map((g) => {
    const n = targets.filter((t) => (t.group || t.body) === g.id).length;
    if (!n) return null;
    const w = GROUP_WORDS[g.id];
    return w ? `${num(n)} ${w[n === 1 ? 0 : 1]}` : `${g.label}: ${n}`;
  }).filter(Boolean);
  const other = targets.filter((t) => !known.has(t.group || t.body)).length;
  if (other) parts.push(`${num(other)} other target${other === 1 ? '' : 's'}`);
  return parts;
}

// "3 of 5 pillars: rock type and resources not measured at Malapert Massif" for one full-match ranking row.
function pillarNote(r, target) {
  const total = PILLARS.length;
  if (r.pillarsUsed == null) return '';
  if (r.pillarsUsed >= total) return `All ${total} pillars scored`;
  const gaps = (r.targetGaps || []).map((g) => PILLAR_WORDS[g] || g);
  return `${r.pillarsUsed} of ${total} pillars${gaps.length ? `: ${list(gaps)} not measured at ${short(target)}` : ''}`;
}

// ---------- the story ----------
function buildSteps(api) {
  const d = state.data;
  const jezero = findTarget(d, 'jezero');
  const apollo = findTarget(d, 'apollo17');
  const base = findTarget(d, 'malapert');
  const moreBases = d.targets.filter((t) => t.group === 'moon-base' && t.id !== base.id).map((t) => t.name.split(' (')[0]);
  const harrat = findSite(d, 'harrat');
  const jordan = JORDAN.map((id) => findSite(d, id)).filter(Boolean);
  // Ground panoramas (not the flat photos); same 360° rule as the viewer in pano.js (no haov = full circle).
  const pans = (d.panoramas?.panoramas || []).filter((p) => p.kind !== 'photo');
  const full360 = pans.filter((p) => (Number(p.haov) || 360) >= 360).length;
  const far = Math.max(...jordan.map((s) => distanceKm(AMMAN.lat, AMMAN.lon, s.lat, s.lon)));
  const years = (d.sites[0]?.power?.period || '').match(/\d{4}/g) || [];
  const use = (targetId, mode) => () => { api.setTarget(targetId); api.setMode(mode); };
  const bestJordan = () => api.ranking().find((x) => JORDAN.includes(x.site.id) && x.score != null) || null;
  // Names of the sites with the same climate match as Harrat al-Shaam (the title and text of the key finding).
  const climateTie = () => {
    const r = api.ranking();
    const p = pct(r.find((x) => x.site.id === 'harrat').score);
    return r.filter((x) => pct(x.score) === p).map((x) => x.site.name);
  };
  const twinViz = (target) => {
    const top = api.ranking()[0];
    const jo = bestJordan();
    return `<div class="viz-hero"><span>Closest Earth twin of ${esc(short(target).replace(/ site$/, ''))}</span><b>${esc(top.site.name)}</b><em><span data-count="${pct(top.score)}">0</span>%</em></div>${jo ? `<div class="viz-sub">Best in Jordan: <b>${esc(jo.site.name)}</b> ${pct(jo.score)}%</div>` : ''}`;
  };

  return [
    {
      k: 'Mission briefing', t: 'Where on Earth can crews practise for the Moon and Mars?',
      s: 'Analog Atlas compares places on Earth with sites on the Moon and Mars, using NASA measurements.',
      viz: () => `<div class="viz-stats">
        <div><b data-count="${d.sites.length}">0</b><span>Earth sites</span></div>
        <div><b data-count="${d.targets.length}">0</b><span>Moon and Mars targets</span></div>
        <div><b data-count="${pans.length}">0</b><span>real ground panoramas</span></div>
        <div><b data-count="${full360}">0</b><span>of them full 360°</span></div></div>`,
      dur: 7000,
      run: async (live) => { await api.showWorld('earth'); if (live()) await api.home(); },
    },
    {
      k: 'The targets', t: 'Moon and Mars targets, with sourced data (measured where possible)',
      s: `Orbiters, rovers, landers and astronauts measured the ground and, where known, temperature and rock type at each target: ${esc(list(groupCounts(d.targets)))}.`,
      viz: () => `<div class="viz-chips">${d.targets.map((t, i) => `<span class="chip" style="--i:${i}"><span class="body-chip ${esc(t.body)}">${esc(BODY_LABEL[t.body] || t.body)}</span> ${esc(t.name)}</span>`).join('')}</div>`,
      dur: 7000,
      run: async (live) => { await api.showWorld('mars'); if (live()) await api.lookAt(jezero, 3.5e6); },
    },
    {
      k: 'Target · Mars', t: `${jezero.name}, where Perseverance explores`,
      s: 'An ancient river delta over lava rock. These are the numbers our Earth sites are compared with:',
      viz: () => {
        const v = jezero.values;
        return `<div class="viz-stats">
          <div><b><span data-count="${v.meanTemp.value}">0</span> °C</b><span>mean air (MEDA)</span></div>
          <div><b><span data-count="${v.swing.value}">0</span> °C</b><span>daily swing</span></div>
          <div><b><span data-count="${v.coldGround.value}">0</span> °C</b><span>coldest air (MEDA)</span></div>
          <div><b><span data-count="${v.albedo.value}" data-digits="2">0</span></b><span>albedo</span></div></div>`;
      },
      dur: 10000,
      run: async () => { await api.flyTo({ kind: 'target', id: 'jezero' }); },
    },
    {
      k: 'Earth data',
      t: years.length > 1 ? `${cap(num(years[years.length - 1] - years[0] + 1))} years of NASA climate data for every Earth site` : 'NASA climate data for every Earth site',
      s: `NASA POWER gives each place its ${esc(list(CLIMATE_FACTORS.map((f) => f.label.toLowerCase())))}${years.length > 1 ? `, from ${years[0]} to ${years[years.length - 1]}` : ''}.`,
      ring: '#rank',
      before: use('jezero', 'climate'),
      dur: 8000,
      run: async (live) => { await api.showWorld('earth'); if (live()) await api.home(); },
    },
    {
      k: 'The score', t: `${cap(num(CLIMATE_FACTORS.length))} factors, one score`,
      s: `Each factor scores 1 when Earth matches the target and falls to 0 as they differ. ${esc(harrat.name)} vs ${esc(jezero.name)}:`,
      ring: '#detail',
      before: use('jezero', 'climate'),
      viz: () => {
        const r = api.ranking().find((x) => x.site.id === 'harrat');
        const rows = r.climate.rows.filter((x) => x.score != null).map((x, i) => `<div class="bar-row" style="--i:${i}"><span>${esc(x.factor.short)}</span><span class="track"><i data-fill="${Math.round(x.score * 100)}"></i></span><b data-count="${Math.round(x.score * 100)}">0</b>%</div>`).join('');
        return `<div class="viz-bars">${rows}</div><div class="viz-total">Climate match <b><span data-count="${pct(r.score)}">0</span>%</b></div>`;
      },
      dur: 10000,
      run: async () => { api.select('harrat'); },
    },
    {
      k: 'Key finding',
      t: () => (climateTie().length < 2 ? 'Climate alone is not enough' : "Climate alone can't tell the deserts apart"),
      s: () => {
        const r = api.ranking();
        const p = pct(r.find((x) => x.site.id === 'harrat').score);
        const same = climateTie();
        if (same.length < 2) return `${esc(harrat.name)}: ${p}% for ${esc(jezero.name)}. Climate says nothing about the ground, the rock or the resources, so we need more than climate.`;
        return `${esc(list(same))}: all ${p}% for ${esc(jezero.name)}. To separate them we need more than climate.`;
      },
      ring: '#rank-list',
      before: use('jezero', 'climate'),
      dur: 8000,
      run: async () => {},
    },
    {
      k: 'Full analog match', t: `Add ${list(PILLARS.filter((p) => p.id !== 'climate').map((p) => p.label.toLowerCase()))}`,
      s: `Same NASA climate, plus ground slope and the largest flat landing zone from elevation maps, the main rock type, and the resources a base needs. Now compare with the ${esc(short(apollo))}:`,
      ring: '#rank',
      before: use('apollo17', 'full'),
      viz: () => twinViz(apollo),
      dur: 9000,
      run: async (live) => { await api.showWorld('earth'); if (live()) await api.home(); },
    },
    {
      k: 'Fly down · Jordan',
      t: () => { const jo = bestJordan(); return jo ? `${jo.site.name}: Jordan’s closest twin of the ${short(apollo)}` : `Jordan and the ${short(apollo)}`; },
      s: () => esc(bestJordan()?.site.why || ''),
      before: use('apollo17', 'full'),
      dur: 11000,
      run: async () => { const jo = bestJordan(); if (jo) await api.flyTo({ kind: 'site', id: jo.site.id }); },
    },
    {
      k: 'Moon base · full match', t: `Moon base site: ${base.name}`,
      s: `${esc(base.mission)}.${moreBases.length ? ` We also score ${esc(moreBases.join(' and '))}.` : ''} The same full match for this base site:`,
      ring: '#rank',
      before: use('malapert', 'full'),
      viz: () => {
        const note = pillarNote(api.ranking()[0], base);
        // The 3 base sites as one answer (computed from the same ranking, default settings).
        const together = baseConsensusText(baseConsensus(), { short: true });
        return `${twinViz(base)}${note ? `<div class="viz-sub">${esc(note)}</div>` : ''}${together ? `<div class="viz-sub">${esc(together)}</div>` : ''}`;
      },
      dur: 10000,
      run: async (live) => { await api.showWorld('moon'); if (live()) await api.lookAt(POLE, api.globe.southPoleHeight(), { pitch: POLE.pitch, heading: POLE.heading }); }, // tilted: see SOUTH_POLE_VIEW
    },
    {
      k: 'Jordan Analog Corridor', t: 'A Moon and Mars training ground in one country',
      s: `Basalt plains with lava tubes, an impact crater, salt flats, a dry lake and red sandstone, all within ${fmt(far, 0)} km of Amman.`,
      viz: () => `<div class="viz-chips">${jordan.map((s, i) => `<span class="chip" style="--i:${i}">${esc(s.name)}</span>`).join('')}</div>`,
      dur: 9000,
      run: async (live) => {
        await api.showWorld('earth');
        await api.backToGlobe();
        if (!live()) return; // Next or Exit was pressed during the flight home
        api.showRoute(JORDAN);
        await api.lookAt({ lat: 31.0, lon: 36.4 }, 1.5e6);
      },
      after: () => api.clearRoute(),
    },
    {
      // The pair the scores support: the Jordan site that ranks highest for Jezero (full match).
      k: 'Stand here', t: 'Real photos, side by side',
      s: () => {
        const r = api.ranking();
        const twin = (bestJordan() || { site: harrat }).site;
        const i = r.findIndex((x) => x.site.id === twin.id);
        const rank = i < 0 ? '' : ` It ranks #${displayRanks(r)[i]} of ${r.length} Earth sites for ${esc(short(jezero))} (${pct(r[i].score)}%, full match).`;
        return `${esc(twin.name)} on Earth and ${esc(jezero.name)} photographed by Perseverance.${rank} Similar looks are a clue; the score uses sourced data.`;
      },
      before: use('jezero', 'full'),
      dur: 8000,
      run: async () => { api.openTwin((bestJordan() || { site: harrat }).site.id, 'jezero'); },
      after: () => api.closeOverlay(),
    },
    {
      k: 'Validity', t: 'Every number has a source',
      s: 'Method & data links every value, re-checks the reference rankings automatically, and a strict mode uses only measurements made at the site itself.',
      ring: '#method-btn',
      dur: 7000,
      run: async () => {},
    },
    {
      k: 'Analog Atlas', t: 'Places on Earth that behave like the Moon and Mars',
      s: 'NASA data · open methods · a 3D base concept · made in Jordan',
      end: true,
      dur: 6000,
      run: async () => { await api.home(); },
    },
  ];
}

// ---------- rendering ----------
function render(steps, i) {
  const st = steps[i];
  const el = $('#caption');
  // Keep keyboard focus on the same tour button when the card is redrawn.
  const focused = document.activeElement?.closest?.('#caption [data-t]')?.dataset.t;
  el.hidden = false;
  el.className = `caption tour-card${st.end ? ' end' : ''}`;
  const title = typeof st.t === 'function' ? st.t() : st.t;
  const body = typeof st.s === 'function' ? st.s() : st.s;
  el.innerHTML = `
    <div class="tc-top"><span class="k">${esc(st.k)} · ${i + 1}/${steps.length}</span></div>
    <div class="t">${words(title)}</div>
    <div class="s">${body}</div>
    ${st.viz ? `<div class="viz">${st.viz()}</div>` : ''}
    <div class="segs">${steps.map((_, j) => `<i class="${j < i ? 'done' : j === i ? 'now' : ''}" ${j === i ? `style="--d:${st.dur}ms"` : ''}></i>`).join('')}</div>
    <div class="ctl">
      <button type="button" class="btn small" data-t="back" ${i === 0 ? 'disabled' : ''}>◀ Back</button>
      <button type="button" class="btn small" data-t="pause">${run.paused ? '▶ Play' : '❚❚ Pause'}</button>
      <button type="button" class="btn small primary" data-t="next">${i === steps.length - 1 ? 'Finish' : 'Next ▶'}</button>
      <button type="button" class="btn small" data-t="exit">■ Exit</button>
    </div>`;
  el.classList.toggle('paused', run.paused);
  el.querySelectorAll('[data-t]').forEach((b) => b.addEventListener('click', () => control(b.dataset.t)));
  // On the first card, and whenever a tour button had focus, put focus on the controls.
  // Focus starts on Pause, so Space still pauses (Space on a focused button presses that button).
  if (focused || i === 0) (el.querySelector(`[data-t="${focused}"]:not([disabled])`) || el.querySelector('[data-t="pause"]')).focus({ preventScroll: true });
  counter(el);
  // The space from the card's top edge to the bottom of the window: an open Twin view stops above it.
  document.body.style.setProperty('--tour-room', `${Math.round(innerHeight - el.offsetTop + 8)}px`);
}

function control(c) {
  if (!run) return;
  if (c === 'exit') { stopTour(); return; }
  if (c === 'pause') {
    run.paused = !run.paused;
    const b = $('#caption [data-t="pause"]');
    if (b) b.textContent = run.paused ? '▶ Play' : '❚❚ Pause';
    $('#caption').classList.toggle('paused', run.paused);
    return;
  }
  if (c === 'next') { run.target = run.index + 1; run.jump = true; }
  if (c === 'back') { run.target = Math.max(0, run.index - 1); run.jump = true; }
}

function onKey(e) {
  if (!run || e.target.closest?.('input, select, textarea')) return;
  // Keys already used by the focused globe or 360° viewer (arrows turn the view) do not also move the tour.
  if (e.defaultPrevented || e.target.closest?.('canvas, .pnlm-container')) return;
  if (e.key === 'ArrowRight') { control('next'); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { control('back'); e.preventDefault(); }
  else if (e.key === ' ' && !e.target.closest?.('button, a')) { control('pause'); e.preventDefault(); }
}

export function stopTour() {
  if (!run) return;
  run.stopped = true;
  run.jump = true;
}

export async function playTour(api) {
  if (run) return;
  const saved = { ...api.settings(), targetId: state.targetId }; // mode, strict data, Earth temperature source, weights, pillars
  const detail = api.detailState(); // the selected site or target, or the welcome card, or a closed panel
  run = { index: 0, target: 0, paused: false, jump: false, stopped: false };
  document.body.classList.add('tour-on');
  tourButton(true);
  document.addEventListener('keydown', onKey);
  try {
    api.closePanels(); // also stops the Jordan corridor, so the two never run together
    api.setSettings(defaults());
    const steps = buildSteps(api);
    while (run && !run.stopped && run.index < steps.length) {
      const i = run.index;
      const st = steps[i];
      run.jump = false;
      if (st.before) st.before();
      render(steps, i);
      ring(null);
      const started = performance.now();
      // Do the step's action, but never wait for it longer than 15 s, and stop waiting at once on
      // Next, Back or Exit (the next camera move cancels the old one). live() is false from then on.
      const my = run;
      const live = () => run === my && !my.jump && !my.stopped && my.index === i;
      let done = false;
      const work = limit(st.run(live).catch((err) => console.warn('tour step', err)), 15000).then(() => { done = true; });
      await Promise.race([work, until(() => done || !live())]);
      if (run.stopped) break;
      if (!run.jump) {
        ring(st.ring);
        const elapsed = performance.now() - started;
        await wait(Math.max(2500, st.dur - elapsed));
      }
      ring(null);
      if (st.after) st.after();
      if (run.stopped) break;
      run.index = run.jump ? run.target : i + 1;
    }
  } finally {
    // Keyboard focus was on the tour card (Pause, Exit…): it must not fall to the page when the card hides.
    const hadFocus = $('#caption').contains(document.activeElement);
    ring(null);
    document.removeEventListener('keydown', onKey);
    document.body.classList.remove('tour-on');
    $('#caption').hidden = true;
    $('#caption').className = 'caption';
    api.clearRoute();
    api.closeOverlay();
    api.closeKit();
    api.setSettings({ mode: saved.mode, strict: saved.strict, earthTemp: saved.earthTemp || 'air', weights: saved.weights, pillars: saved.pillars });
    api.setTarget(saved.targetId);
    api.restoreDetail(detail); // so every redraw below shows the visitor's own selection
    // What that shows now (a selected Discover box can only come back with Discover, further down).
    const shown = { kind: state.selected?.kind || null, id: state.selected?.id || null };
    // `run` stays set until Earth is shown again, so the corridor cannot start in the middle of this.
    try { await api.showWorld('earth'); } catch (err) { console.warn('tour end', err); }
    run = null;
    tourButton(false);
    await api.backToGlobe();
    // Back to globe redraws the panel (a closed panel would reopen on the welcome card), so restore once
    // more, unless the visitor already picked something else or started a new tour during the flight home.
    const same = (state.selected?.kind || null) === shown.kind && (state.selected?.id || null) === shown.id;
    if (!run && state.view === 'globe' && same) {
      if (detail.discover && !state.discover) await api.openDiscover(); // the visitor had Discover Jordan open
      if (!run) api.restoreDetail(detail);
    }
    if (hadFocus && !run) focusAfterRun('#tour-btn');
  }
}

// After the tour or the Jordan corridor ends: focus the heading of the place still shown in the panel,
// else the top-bar button that started it. Only when focus is on the page itself (the visitor did not move it).
export function focusAfterRun(buttonSel) {
  const a = document.activeElement;
  if (a && a !== document.body && a.isConnected && a.getClientRects().length) return;
  const detail = $('#detail');
  const head = state.selected && !detail.hidden ? detail.querySelector('h2.title') : null;
  (head || $(buttonSel))?.focus({ preventScroll: true });
}
