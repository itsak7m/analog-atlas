// "Tune the factors": one slider per factor (re-weights the score live) and the stability check.

import { state, update } from '../state.js';
import { CLIMATE_FACTORS, PILLARS, LST_FIELD, stability } from '../scoring.js';
import { esc, fmt } from '../util.js';
import { findTarget } from '../data.js';
import { openOverlay } from './overlay.js';

function slider(group, id, label, value, hint) {
  return `<div class="slider"><label for="w-${group}-${id}">${esc(label)}</label><output id="o-${group}-${id}">×${fmt(value, 1)}</output>
    <input type="range" id="w-${group}-${id}" data-group="${group}" data-id="${id}" min="0" max="2" step="0.1" value="${value}" aria-describedby="h-${group}-${id}">
    <span class="src" id="h-${group}-${id}" style="grid-column:1/-1">${esc(hint)}</span></div>`;
}

function stabilityHTML() {
  const s = state.stability;
  const target = findTarget(state.data, state.targetId);
  if (!s || s.targetId !== state.targetId || s.mode !== state.mode || !!s.strict !== state.strict || (s.earthTemp || 'air') !== state.earthTemp) {
    return `<p class="hint">Draws 1,000 random sets of weights (each from 0 to 2) and counts how often each site stays in the top 3 for ${esc(target.name)}. A strong twin stays there whatever the weights are.</p>`;
  }
  const rows = Object.entries(s.share).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([id, v]) => {
      const site = state.data.sites.find((x) => x.id === id);
      return `<li><span>${esc(site.name)} <span class="src">${esc(site.country)}</span></span><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span><span class="v">${Math.round(v * 100)}%</span></li>`;
    }).join('');
  return `<p class="hint">Share of ${s.runs.toLocaleString()} random weightings in which each site is in the top ${s.topN} (${state.mode === 'full' ? 'full analog match' : 'climate match'}${state.earthTemp === 'surface' ? ', surface temperature' : ''}, ${esc(target.name)}). Seed ${s.seed}, so the result is repeatable.</p><ul class="stab-list">${rows}</ul>`;
}

// Where a factor's Earth value comes from: NASA POWER, or MODIS for the three temperatures in surface mode.
const factorHint = (f) => `${state.earthTemp === 'surface' && LST_FIELD[f.id] ? `MODIS ${LST_FIELD[f.id]}` : `NASA POWER ${f.power}`} vs target · R = ${f.R}${f.unit ? ` ${f.unit}` : ''}`;

// The Earth temperature switch: air 2 m (NASA POWER, default) or ground surface (MODIS). Off when data/lst.json is missing.
function tempSwitch() {
  const on = !!state.data.lstDoc;
  const btn = (id, main, sub) => `<button type="button" data-temp="${id}" aria-pressed="${state.earthTemp === id}" ${on ? '' : 'disabled'}><b>${esc(main)}</b><span>${esc(sub)}</span></button>`;
  return `<div class="temp-switch"><span class="label" id="temp-label">Earth temperature</span>
      <div class="temp-toggle" role="group" aria-labelledby="temp-label">${btn('air', 'Air 2 m', 'NASA POWER (~50 km)')}${btn('surface', 'Ground surface', 'MODIS (1 km)')}</div>
      <p class="src">${on
    ? 'Ground surface is closer to how most Moon and Mars targets are measured (ground seen from orbit by LRO Diviner and Mars Climate Sounder, or the Apollo 17 probe). The reference rankings of the brief use air. Rain and albedo stay NASA POWER.'
    : 'Ground surface is off: the MODIS file data/lst.json did not load.'}</p></div>`;
}

export function openTune(onChange) {
  const climate = CLIMATE_FACTORS.map((f) => slider('w', f.id, f.label, state.weights[f.id], factorHint(f))).join('');
  const pillars = PILLARS.map((p) => slider('p', p.id, p.label, state.pillars[p.id], { climate: 'The five climate factors in this panel', terrain: 'Median slope in a 10 km box', landing: 'Largest flat zone (slope under 10°)', geology: 'Main rock type match', resources: 'Share of the target resources you can practise with' }[p.id])).join('');
  const el = openOverlay({
    title: 'Tune the factors',
    wide: false,
    body: `<div class="sheet-body">${tempSwitch()}<div class="tune-grid">
      <div><span class="label">Climate factors</span>${climate}</div>
      <div><span class="label">Pillars · full analog match only</span>${pillars}
        <p class="src">${state.mode === 'full' ? 'Full analog match is on.' : 'Switch the ranking to "Full analog match" to use the pillars.'}</p></div>
      </div>
      <label class="strict-row"><input type="checkbox" id="strict-toggle" ${state.strict ? 'checked' : ''}> <span><b>Strict data:</b> use only target values measured at the site itself. Values that are Moon-wide or Mars-wide averages, midpoints or general statements are left out (see Method &amp; data). The reference rankings of the brief use the normal values.</span></label>
      <div class="actions"><button type="button" class="btn" data-reset>Reset all to ×1</button><button type="button" class="btn primary" data-stab>Run stability check</button></div>
      <div class="section"><span class="label">Stability check</span><div id="stab-out">${stabilityHTML()}</div></div>
    </div>`,
  });
  el.addEventListener('input', (e) => {
    const r = e.target;
    if (r.type !== 'range') return;
    const v = Number(r.value);
    if (r.dataset.group === 'w') update({ weights: { ...state.weights, [r.dataset.id]: v } });
    else update({ pillars: { ...state.pillars, [r.dataset.id]: v } });
    el.querySelector(`#o-${r.dataset.group}-${r.dataset.id}`).textContent = `×${fmt(v, 1)}`;
    onChange();
  });
  el.querySelectorAll('[data-temp]').forEach((b) => b.addEventListener('click', () => {
    if (b.disabled || b.dataset.temp === state.earthTemp) return;
    update({ earthTemp: b.dataset.temp });
    el.querySelectorAll('[data-temp]').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.temp === state.earthTemp)));
    for (const f of CLIMATE_FACTORS) el.querySelector(`#h-w-${f.id}`).textContent = factorHint(f);
    el.querySelector('#stab-out').innerHTML = stabilityHTML();
    onChange();
  }));
  el.querySelector('#strict-toggle').addEventListener('change', (e) => {
    update({ strict: e.target.checked });
    el.querySelector('#stab-out').innerHTML = stabilityHTML();
    onChange();
  });
  el.querySelector('[data-reset]').addEventListener('click', () => {
    update({ weights: Object.fromEntries(CLIMATE_FACTORS.map((f) => [f.id, 1])), pillars: Object.fromEntries(PILLARS.map((p) => [p.id, 1])) });
    el.querySelectorAll('input[type=range]').forEach((r) => { r.value = 1; el.querySelector(`#o-${r.dataset.group}-${r.dataset.id}`).textContent = '×1.0'; });
    onChange();
  });
  el.querySelector('[data-stab]').addEventListener('click', () => {
    const target = findTarget(state.data, state.targetId);
    const res = stability(state.data.sites, target, { mode: state.mode, strict: state.strict, earthTemp: state.earthTemp, terrain: state.data.terrain, resources: state.data.resources });
    state.stability = { ...res, targetId: state.targetId, mode: state.mode, strict: state.strict, earthTemp: state.earthTemp };
    el.querySelector('#stab-out').innerHTML = stabilityHTML();
    onChange();
  });
}
