// "Tune the factors": one slider per factor (re-weights the score live) and the stability check.

import { state, update } from '../state.js';
import { PILLARS, LST_FIELD, factorsFor, referenceDefaults, screeningDefaults, stability, targetValue } from '../scoring.js';
import { esc, fmt } from '../util.js';
import { findTarget } from '../data.js';
import { openOverlay } from './overlay.js';
import { scoreLabel, surfaceHint } from './ranking.js';

function slider(group, id, label, value, hint) {
  return `<div class="slider"><label for="w-${group}-${id}">${esc(label)}</label><output id="o-${group}-${id}">×${fmt(value, 1)}</output>
    <input type="range" id="w-${group}-${id}" data-group="${group}" data-id="${id}" min="0" max="2" step="0.1" value="${value}" aria-describedby="h-${group}-${id}">
    <span class="src" id="h-${group}-${id}" style="grid-column:1/-1">${esc(hint)}</span></div>`;
}

function stabilityHTML() {
  const s = state.stability;
  const target = findTarget(state.data, state.targetId);
  if (!s || s.targetId !== state.targetId || s.mode !== state.mode || !!s.strict !== state.strict || (s.earthTemp || 'air') !== state.earthTemp) {
    return `<p class="hint">Tests 1,000 random weightings of enabled factors for ${esc(target.name)} and counts how often each site is in the top 3.</p>`;
  }
  const rows = Object.entries(s.share).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([id, v]) => {
      const site = state.data.sites.find((x) => x.id === id);
      return `<li><span>${esc(site.name)} <span class="src">${esc(site.country)}</span></span><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span><span class="v">${Math.round(v * 100)}%</span></li>`;
    }).join('');
  return `<p class="hint">Share of ${s.runs.toLocaleString()} random weightings in which each site is in the top ${s.topN} (${scoreLabel().toLowerCase()}${esc(surfaceHint())}, ${esc(target.name)}). Disabled factors and pillars stayed off.</p><ul class="stab-list">${rows}</ul>`;
}

// Where a factor's Earth value comes from: NASA POWER, or MODIS for the three temperatures in surface mode.
function factorHint(f, target) {
  const value = targetValue(target, f.id, state.strict);
  const surface = state.earthTemp === 'surface' || (state.earthTemp === 'matched' && value.temperatureBasis === 'surface');
  const source = f.id === 'sunHeight' ? 'From latitude' : surface && LST_FIELD[f.id] ? 'NASA MODIS' : `NASA POWER ${f.power}`;
  return `${source} · R = ${f.R}${f.unit ? ` ${f.unit}` : ''}`;
}

// The Earth temperature switch: air 2 m (NASA POWER, default) or ground surface (MODIS). Off when data/lst.json is missing.
function tempSwitch() {
  const on = !!state.data.lstDoc;
  const btn = (id, main, sub) => `<button type="button" data-temp="${id}" aria-pressed="${state.earthTemp === id}" ${id === 'surface' && !on ? 'disabled' : ''}><b>${esc(main)}</b><span>${esc(sub)}</span></button>`;
  return `<div class="temp-switch"><span class="label" id="temp-label">Earth temperature</span>
      <div class="temp-toggle" role="group" aria-labelledby="temp-label">${btn('matched', 'Match measurement type', 'Screening default')}${btn('air', 'Air 2 m', 'NASA POWER · reference')}${btn('surface', 'Ground surface', 'MODIS · exploratory')}</div>
      <p class="src">Matched uses the corresponding Earth air or surface product for each target factor. The other settings are for comparison with earlier results.${on ? '' : ' MODIS site data is unavailable.'}</p></div>`;
}

export function openTune(onChange) {
  const target = findTarget(state.data, state.targetId);
  const factors = factorsFor(target);
  const climate = factors.map((f) => slider('w', f.id, f.label, state.weights[f.id] ?? 1, factorHint(f, target))).join('');
  const pillars = PILLARS.map((p) => slider('p', p.id, p.label, state.pillars[p.id], { climate: 'Comparable environmental factors', terrain: 'Median slope in a 10 km box', landing: 'Flat zone, from the same slope grid as terrain. Off by default.', geology: 'Main rock type match', resources: 'Share of the target resources you can practise with' }[p.id])).join('');
  const el = openOverlay({
    title: 'Tune the factors',
    wide: false,
    body: `<div class="sheet-body"><label class="score-mode">Ranking by <select id="score-mode"><option value="full" ${state.mode === 'full' ? 'selected' : ''}>Screening score</option><option value="climate" ${state.mode === 'climate' ? 'selected' : ''}>Climate only</option></select></label>
      <div><span class="label">Pillars · screening score</span>${pillars}
        ${state.mode === 'climate' ? '<p class="src">Switch to Screening score to apply pillar weights.</p>' : ''}</div>
      <details class="more"><summary>Advanced <span class="src">climate factor weights, Earth temperature, strict data</span></summary><div class="more-body">
      ${tempSwitch()}
      <div><span class="label">Climate factors</span>${climate}</div>
      <label class="strict-row"><input type="checkbox" id="strict-toggle" ${state.strict ? 'checked' : ''}> <span><b>Strict data:</b> use only target values measured at the site itself. Values that are Moon-wide or Mars-wide averages, midpoints or general statements are left out (see Method &amp; data). The reference rankings of the brief use the normal values.</span></label>
      </div></details>
      <div class="actions"><button type="button" class="btn" data-preset="screening">Screening defaults</button><button type="button" class="btn" data-preset="reference">Reference settings</button><button type="button" class="btn primary" data-stab>Run stability check</button></div>
      <div class="section"><span class="label">Stability check</span><div id="stab-out">${stabilityHTML()}</div></div>
    </div>`,
  });
  const changed = () => {
    state.stability = null;
    el.querySelector('#stab-out').innerHTML = stabilityHTML();
    onChange();
  };
  const syncTemp = () => {
    el.querySelectorAll('[data-temp]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.temp === state.earthTemp)));
    for (const f of factors) el.querySelector(`#h-w-${f.id}`).textContent = factorHint(f, target);
  };
  el.querySelector('#score-mode').addEventListener('change', (e) => { update({ mode: e.target.value }); changed(); });
  el.addEventListener('input', (e) => {
    const r = e.target;
    if (r.type !== 'range') return;
    const v = Number(r.value);
    if (r.dataset.group === 'w') update({ weights: { ...state.weights, [r.dataset.id]: v } });
    else update({ pillars: { ...state.pillars, [r.dataset.id]: v } });
    el.querySelector(`#o-${r.dataset.group}-${r.dataset.id}`).textContent = `×${fmt(v, 1)}`;
    changed();
  });
  el.querySelectorAll('[data-temp]').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled || b.dataset.temp === state.earthTemp) return;
    update({ earthTemp: b.dataset.temp });
    syncTemp();
    changed();
  }));
  el.querySelector('#strict-toggle').addEventListener('change', (e) => {
    update({ strict: e.target.checked });
    syncTemp();
    changed();
  });
  el.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => {
    update(b.dataset.preset === 'reference' ? referenceDefaults() : screeningDefaults());
    el.querySelector('#strict-toggle').checked = state.strict;
    syncTemp();
    for (const r of el.querySelectorAll('input[type=range]')) {
      const values = r.dataset.group === 'w' ? state.weights : state.pillars;
      r.value = values[r.dataset.id] ?? 1;
      el.querySelector(`#o-${r.dataset.group}-${r.dataset.id}`).textContent = `×${fmt(Number(r.value), 1)}`;
    }
    changed();
  }));
  el.querySelector('[data-stab]').addEventListener('click', () => {
    const res = stability(state.data.sites, target, { mode: state.mode, strict: state.strict, earthTemp: state.earthTemp, weights: state.weights, pillars: state.pillars, terrain: state.data.terrain, resources: state.data.resources });
    state.stability = { ...res, targetId: state.targetId, mode: state.mode, strict: state.strict, earthTemp: state.earthTemp };
    el.querySelector('#stab-out').innerHTML = stabilityHTML();
    onChange();
  });
}
