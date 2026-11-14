// Detail panel: one Earth site, one Moon/Mars target, or the welcome card.

import { state } from '../state.js';
import { CLIMATE_FACTORS, factorsFor, ROCK_LABEL, R_SLOPE, SAFE_SLOPE_DEG, RESOURCES, pct, targetValue, measuredFactors, TARGET_MIN_MEASURED } from '../scoring.js';
import { esc, fmt, fmtCoord, STATUS_LABEL, BODY_LABEL, cellGap, CELL_GAP_LIMIT_M } from '../util.js';
import { noScoreText, targetGapText, gapWords, strictDropsClimate, computeRanking, displayRanks, pillarStrip, pillarKey, scoreLabel, baseAllowed, isStarTarget, starPairs } from './ranking.js';
import { earthCell, targetCell, earthTempLine, orbitSiteHTML } from './orbit.js';
import { HAS_ION } from '../config.js';

export const POWER_FACTS = [
  ['T2M', 'Mean air temperature', 1, '°C'],
  ['T2M_RANGE', 'Average daily air range', 1, '°C'],
  ['T2M_MAX', 'Highest hourly air temperature', 1, '°C'],
  ['T2M_MIN', 'Lowest hourly air temperature', 1, '°C'],
  ['TS', 'Mean ground (skin) temperature', 1, '°C'],
  ['TS_MIN', 'Lowest hourly ground temperature', 1, '°C'],
  ['RH2M', 'Relative humidity', 0, '%'],
  ['PRECTOTCORR', 'Rain', 2, 'mm/day'],
  ['ALLSKY_SFC_UV_INDEX', 'UV index (all-sky mean)', 2, ''],
  ['ALLSKY_SFC_SW_DWN', 'Sunlight at the surface', 2, 'kWh/m²/day'],
  ['WS2M', 'Wind at 2 m', 1, 'm/s'],
  ['PS', 'Air pressure', 1, 'kPa'],
  ['ALLSKY_SRF_ALB', 'Surface albedo', 2, ''],
];

const panel = () => document.getElementById('detail');

// Replace the panel content. If keyboard focus was inside the panel, put it back on the
// same button (or on the heading), so a re-render does not drop focus to the page.
export function setPanel(el, html) {
  const a = document.activeElement;
  const had = a && a !== el && el.contains(a);
  const action = had && a.dataset.action;
  el.innerHTML = html;
  el.querySelector('details.more')?.addEventListener('toggle', (e) => { moreOpen = e.currentTarget.open; });
  if (!had) return;
  const same = action && [...el.querySelectorAll('[data-action]')].find((b) => b.dataset.action === action && b.dataset.id === a.dataset.id);
  (same || el.querySelector('h2.title'))?.focus({ preventScroll: true });
}

// Move keyboard focus to the panel heading, e.g. after the visitor picks a site or a target.
export function focusDetail() {
  const el = panel();
  if (!el.hidden) el.querySelector('h2.title')?.focus({ preventScroll: true });
}

export function srcLink(id) {
  const s = id && state.data.sources[id];
  return s ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>` : '';
}

// "NASA's Artemis limit" (slope under 10° for landing), linked to its source when it is in targets.json.
export function artemisLink() {
  const s = state.data.sources['artemis-landing-slope'];
  return s ? `<a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.label)}">NASA's Artemis limit</a>` : "NASA's Artemis limit";
}

function resourcesText(site, target, res) {
  const doc = state.data.resourcesDoc;
  if (!doc) return '<span class="src">not measured</span>';
  if (!res) return `<span class="src">${(state.data.resources?.[target.id] || []).length ? 'not measured at this site' : 'not measured at the target'}</span>`;
  const name = (t) => esc(RESOURCES[t] || t);
  return `${res.shared.length ? `Practise: ${res.shared.map(name).join(', ')}` : 'None of the target resources'}${res.missing.length ? `<div class="src">Not here: ${res.missing.map(name).join(', ')}</div>` : ''}`;
}

// Extra words about the terrain numbers of a site (lake surfaces, salt flats, exclusions).
function terrainNote(site) {
  if (site.terrainExclude) return ` <b>${esc(site.terrainExclude)}</b>`;
  const t = state.data.terrain && state.data.terrain[site.id];
  if (!t) return ' Terrain data are not available for this site yet.';
  return t.notes ? ` Note: ${esc(t.notes)}.` : '';
}

export function mbar(score) {
  if (score == null) return '<span class="src">not used</span>';
  return `<span class="mbar" aria-hidden="true"><i style="width:${Math.round(score * 100)}%"></i></span>${pct(score)}%`;
}

// ---------- the short view ----------
// A panel first shows what is needed to judge a match: the score, the pillars side by side and one limit.
// Everything else (factor tables, orbit data, climate facts, caveats, sources) is one press away under
// "Full data & sources". Its open/closed state is kept while the visitor moves between places.
let moreOpen = false;
export function moreSection(html) {
  return `<details class="more"${moreOpen ? ' open' : ''}><summary>Full data &amp; sources <span class="src">every number, its source and the caveats</span></summary><div class="more-body">${html}</div></details>`;
}

// rows: [label, here, there, score]; there === null joins the two value cells. score: a 0-1 number, null
// ("not used") or the string 'context' (shown, not scored).
export function quickTable(hereName, thereName, rows) {
  const match = (s) => (s === 'context' ? '<span class="src">Context</span>' : mbar(s));
  const body = rows.map(([label, a, b, s]) => (b === null
    ? `<tr><td>${label}</td><td colspan="2">${a}</td><td class="match">${match(s)}</td></tr>`
    : `<tr><td>${label}</td><td>${a}</td><td>${b}</td><td class="match">${match(s)}</td></tr>`)).join('');
  return `<div class="section quick"><span class="label">The match in short</span>
    <table class="facts"><thead><tr><th scope="col"><span class="sr-only">Pillar</span></th><th scope="col">${esc(hereName)}</th><th scope="col">${esc(thereName)}</th><th scope="col">Match</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

export const LIMIT_LINE = '<p class="src limit">Screening from satellite and climate data, not a field visit. Every number and its source is under <b>Full data &amp; sources</b>.</p>';

export function panoramasFor(id) {
  const p = state.data.panoramas;
  const street = (state.data.streetview || {})[id] || null;
  if (!p) return { photos: [], flat: [], street, links: [], none: null };
  const all = (p.panoramas || []).filter((x) => x.target === id);
  return {
    photos: all.filter((x) => x.kind !== 'photo'),
    flat: all.filter((x) => x.kind === 'photo'),
    street,
    links: (p.linkOuts || []).filter((x) => x.target === id),
    none: (p.none || []).find((x) => x.target === id) || null,
  };
}

// True when a place has any real image (360° photo, Street View or an ordinary photo): the Twin view needs one.
export function hasImagery(id) {
  const { photos, flat, street } = panoramasFor(id);
  return !!(photos.length || flat.length || street);
}

function standButtons(id) {
  const { photos, flat, street, links } = panoramasFor(id);
  let html = '';
  let primary = true;
  const cls = () => { const c = primary ? 'btn primary' : 'btn'; primary = false; return c; };
  // Say how wide the panorama really is (same rule as the viewer: no haov means a full 360°).
  const haov = photos.length ? Number(photos[0].haov) || 360 : 0;
  if (photos.length) html += `<button type="button" class="${cls()}" data-action="pano" data-id="${esc(photos[0].id)}">Stand here · ${haov >= 360 ? '360° photo' : `${Math.round(haov)}° panorama`}</button>`;
  if (street) html += `<button type="button" class="${cls()}" data-action="street">Stand here · Street View</button>`;
  if (flat.length) html += `<button type="button" class="${cls()}" data-action="pano" data-id="${esc(flat[0].id)}">Photo</button>`;
  html += `<button type="button" class="${cls()}" data-action="stand">Stand here · 3D terrain</button>`;
  if (!street) for (const l of links) html += `<a class="btn" href="${esc(l.url)}" target="_blank" rel="noopener" title="${esc(l.note || '')}">${esc(l.label || 'Street View')} ↗</a>`;
  return html;
}

// Same rule as the Method page: a photo whose title says "from orbit" was taken by a spacecraft, not on the ground.
export const fromOrbit = (p) => /from orbit/i.test(p?.title || '');

// What "Stand here · 3D terrain" shows: real relief only when 3D is on (a token and no ?no3d) and the terrain loads.
export const standWords = () => (HAS_ION
  ? 'shows the ground at eye level, rendered from elevation data when the 3D terrain has loaded'
  : 'shows the flat map picture at eye level, because 3D terrain is off');

function photoNote(id) {
  const { photos, flat, street, none } = panoramasFor(id);
  if (photos.length || street) return '';
  if (flat.length && fromOrbit(flat[0])) return '<p class="src">No ground-level photo is available here; "Photo" shows a real photograph taken from orbit, looking down.</p>';
  if (flat.length) return '<p class="src">No 360° view exists here; "Photo" shows a real photograph of the place.</p>';
  return `<p class="caveat">No real ground-level 360° photo is available here${none ? `: ${esc(none.reason)}` : '.'} "Stand here" ${standWords()}.</p>`;
}

// The sources that name a site's rock types (data/sites_meta.json geology.sources), each with its exact quote.
function rockSources(site) {
  const gs = site.geology || {};
  const one = (x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>: “${esc(x.quote)}”${x.note ? ` (${esc(x.note)})` : ''}`;
  return `<p class="src">Rock sources: ${(gs.sources || []).map(one).join(' · ') || 'none yet'}</p>${gs.note ? `<p class="src">${esc(gs.note)}</p>` : ''}`;
}

// "What crews can test here" (data/sites.json 'tests'): tests done here, with their source, then our own proposals.
// Terrain numbers for a proposal are read from data/terrain.json, so they never go out of date.
function testsSection(site) {
  const list = site.tests || [];
  if (!list.length) return '';
  const t = !site.terrainExclude && state.data.terrain ? state.data.terrain[site.id] : null;
  const ground = (e) => (t && (e.pillar === 'terrain' || e.pillar === 'landing')
    ? ` Our data: median slope ${fmt(t.median_slope_deg, 1, '°')}, relief ${fmt(t.relief_m, 0, 'm')} in the 10 km box.${t.notes ? ` Note: ${esc(t.notes)}.` : ''}` : '');
  const link = (e) => `<a href="${esc(e.url)}" target="_blank" rel="noopener" title="${esc(`Quote: “${e.quote}”`)}">${esc(e.source)}</a>`;
  const item = (e) => (e.proposed
    ? `<li><span class="tag candidate">Our proposal</span> ${esc(e.activity)}<div class="src">Basis: ${esc(e.basis)}${ground(e)} · ${link(e)}${e.note ? ` · ${esc(e.note)}` : ''}</div></li>`
    : `<li>${esc(e.activity)}${e.year != null ? ` (${esc(e.year)})` : ''}<div class="src">${esc(e.who)} · ${link(e)}${e.note ? ` · ${esc(e.note)}` : ''}</div></li>`);
  const done = list.some((e) => !e.proposed);
  const ideas = list.some((e) => e.proposed);
  const key = [done ? `${ideas ? 'Items without a label are real tests or training' : 'Each item is a real test or training'} (each link is the source; a note says if it was near this spot rather than on it).` : 'Nothing is documented as tested here yet.',
    ideas ? '"Our proposal" is our own idea, not tested yet.' : ''].join(' ').trim();
  return `<div class="section"><span class="label">What crews can test here</span><ul class="links tests">${list.map(item).join('')}</ul>
    <p class="src">${esc(key)}</p></div>`;
}

// "Twin of": the targets where this site is in the top 3, scored live with the ranking's own code and the
// current settings (the bold cells of the Method & data matrix). Each row makes that target the comparison.
function twinOfSection(site) {
  const modeText = scoreLabel().toLowerCase();
  const hits = state.data.targets.map((t) => {
    const ranked = computeRanking(t.id);
    const ranks = displayRanks(ranked);
    const i = ranked.findIndex((r) => r.site.id === site.id);
    if (i < 0 || ranked[i].score == null || ranks[i] > 3) return null;
    return { t, rank: ranks[i], tie: ranks.filter((x) => x === ranks[i]).length > 1, score: ranked[i].score };
  }).filter(Boolean).sort((a, b) => a.rank - b.rank || b.score - a.score);
  const n = state.data.sites.length;
  const row = ({ t, rank, tie, score }) => {
    const inner = `<span>${esc(t.name)} <span class="src">${esc(BODY_LABEL[t.body])}${t.id === state.targetId ? ' · compared now' : ''}</span></span>
      <span class="tw-r"><span class="rk">${tie ? '=' : '#'}${rank}</span><span class="pc">${pct(score)}%</span></span>`;
    const aria = `${tie ? 'Tied rank' : 'Rank'} ${rank} of ${n} for ${t.name}, ${pct(score)} percent.`;
    return t.id === state.targetId
      ? `<li><div class="tw-now" role="group" aria-label="${esc(`${aria} This is the target compared now.`)}">${inner}</div></li>`
      : `<li><button type="button" data-action="go-target" data-id="${esc(t.id)}" aria-label="${esc(`${aria} Compare with this target.`)}">${inner}</button></li>`;
  };
  const list = hits.length ? `<ul class="twins">${hits.map(row).join('')}</ul>` : '';
  const note = hits.length
    ? `Targets where this site is in the top 3 of ${n} (${modeText}, settings as now).${hits.some((h) => h.t.id !== state.targetId) ? ' Click one to compare with it.' : ''}`
    : `Not in the top 3 for any target (${modeText}, settings as now).`;
  return `<div class="section"><span class="label">Twin of</span>${list}<p class="src">${esc(note)}</p></div>`;
}

// "Twin of" rows change the target through the top bar's own list, the same path as the target picker.
let twinOfWired = false;
function wireTwinOf(el) {
  if (twinOfWired) return;
  twinOfWired = true;
  el.addEventListener('click', (e) => {
    const b = e.target.closest('[data-action="go-target"]');
    const select = document.getElementById('target-select');
    if (!b || !select || select.value === b.dataset.id) return;
    select.value = b.dataset.id;
    select.dispatchEvent(new Event('change'));
  });
}

export function renderSite(site, target, result, extra = {}) {
  const el = panel();
  el.hidden = false;
  wireTwinOf(el);
  document.body.classList.add('sheet-detail');
  const [statusText, statusCls] = STATUS_LABEL[site.status] || ['', ''];
  const p = site.power;
  const score = result.score;
  const modeText = scoreLabel().toLowerCase();
  const rows = result.climate.rows.map((r) => {
    const f = r.factor;
    return `<tr>
      <td>${esc(f.short)}${r.weight !== 1 ? ` <span class="src">×${r.weight.toFixed(1)}</span>` : ''}</td>
      <td class="num">${earthCell(r)}</td>
      <td class="num">${targetCell(r)}</td>
      <td class="match">${r.excluded ? `<span class="src" title="${esc(r.excluded)}">Not scored</span>` : mbar(r.score)}</td></tr>`;
  }).join('');
  const targetSources = [...new Set(result.climate.rows.map((r) => r.source).filter(Boolean))].map(srcLink).join(' · ');

  // Terrain values are read directly, so each side still shows when the other side has no data.
  const terrain = state.data.terrain || {};
  const st = (!site.terrainExclude && terrain[site.id]) || {};
  const tt = terrain[target.id] || {};
  const notComputed = '<span class="src">not computed</span>';
  const slope = (x) => (x.median_slope_deg != null ? fmt(x.median_slope_deg, 1, '°') : notComputed);
  const flat = (x) => (x.max_flat_square_km != null ? `${fmt(x.max_flat_square_km, 1)} km` : notComputed);
  const rockOf = (x) => (x.geology?.primary ? esc(ROCK_LABEL[x.geology.primary] || x.geology.primary) : '<span class="src">not measured</span>');
  const climateRow = ['Climate', `<span class="src">${result.climate.used} comparable factors: temperature, rain${state.mode === 'full' ? '' : ', albedo'}…</span>`, null, strictDropsClimate(result) ? null : result.climate.score];
  const quick = quickTable(site.name.split(',')[0], target.name.split(' (')[0], state.mode === 'full' ? [
    climateRow,
    ['Ground slope', slope(st), slope(tt), result.terrain ? result.terrain.score : null],
    ['Main rock', rockOf(site), rockOf(target), result.geology ? result.geology.score : null],
    ['Resources', resourcesText(site, target, result.resources), null, result.resources ? result.resources.score : null],
  ] : [climateRow]);

  let pillars = '';
  if (state.mode === 'full') {
    const t = result.terrain;
    const g = result.geology;
    pillars = `<div class="section"><span class="label">Terrain and geology</span>
      <table class="facts"><thead><tr><th>Pillar</th><th>${esc(site.name.split(',')[0])}</th><th>${esc(target.name.split(' (')[0])}</th><th>Match</th></tr></thead><tbody>
      <tr><td>Climate</td><td colspan="2" class="src">${result.climate.used} comparable factors</td><td class="match">${mbar(result.climate.score)}</td></tr>
      <tr><td>Median slope</td><td class="num">${slope(st)}</td><td class="num">${slope(tt)}</td><td class="match">${mbar(t ? t.score : null)}</td></tr>
      <tr><td>Largest flat zone (&lt;${SAFE_SLOPE_DEG}°)</td><td class="num">${flat(st)}</td><td class="num">${flat(tt)}</td><td class="match">${state.pillars.landing > 0 ? mbar(result.landing?.score) : '<span class="src">Context</span>'}</td></tr>
      <tr><td>Main rock</td><td>${site.geology?.primary ? esc(ROCK_LABEL[site.geology.primary] || site.geology.primary) + (site.geology.unsourced?.includes(site.geology.primary) ? ' <span class="src">(no source yet)</span>' : '') : '<span class="src">not measured</span>'}</td><td>${target.geology?.primary ? esc(ROCK_LABEL[target.geology.primary] || target.geology.primary) : '<span class="src">not measured</span>'}</td><td class="match">${mbar(g ? g.score : null)}</td></tr>
      <tr><td>Resources</td><td colspan="2">${resourcesText(site, target, result.resources)}</td><td class="match">${mbar(result.resources ? result.resources.score : null)}</td></tr>
      </tbody></table>
      <p class="src">${g ? esc(g.reason) + '. ' : ''}Slopes are estimated over 1 km on a 500 m grid. A ${R_SLOPE}° difference scores 0. The flat-zone estimate uses that same grid. ${artemisLink()} uses 100 m slopes.${terrainNote(site)}</p>
      ${rockSources(site)}</div>`;
  }

  const facts = POWER_FACTS.map(([key, label, digits, unit]) => `<tr><td>${esc(label)}</td><td class="num">${fmt(p.annual[key], digits, unit)}</td></tr>`).join('');
  const sources = site.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a></li>`).join('');
  const q = cellGap(site, state.data.terrain);
  const gapNote = q && q.flagged
    ? `<p class="caveat">⚑ Data quality: the NASA POWER grid cell sits at ${fmt(q.cell, 0)} m, but the ground here is at ${fmt(q.ground, 0)} m (${fmt(Math.abs(q.gap), 0)} m ${q.gap > 0 ? 'higher' : 'lower'}; our limit is ${CELL_GAP_LIMIT_M} m). The climate values describe the wider area, so read this site's climate score with care.</p>` : '';
  const caveats = gapNote + (site.caveats || []).map((c) => `<p class="caveat">${esc(c)}</p>`).join('');
  const stab = extra.stability != null
    ? `<div class="stab">Stays in the top 3 in ${Math.round(extra.stability * 100)}% of 1,000 random weightings</div>` : '';
  const inCloseup = state.view !== 'globe'; // also during the fly-down, so Back to globe shows

  // Full match: how many pillars this site really uses, and which have no data (on either side).
  const missing = gapWords([...(strictDropsClimate(result) ? ['climate'] : []), ...(result.targetGaps || []), ...(result.siteGaps || [])]);
  const gapText = state.mode === 'full' && score != null && result.pillarsUsed != null
    ? `${result.pillarsUsed} of ${result.pillarsEnabled} enabled pillars used${missing ? ` · insufficient ${missing} data` : ''}` : '';
  setPanel(el, `
    <button type="button" class="btn small close" data-action="close" aria-label="Close details" title="Back to results">←</button>
    <div class="kicker"><span class="tag ${esc(statusCls)}">${esc(statusText)}</span>${site.jordan ? '<span class="tag jo">Jordan</span>' : ''}<span class="body-chip earth">Earth</span></div>
    <h2 class="title" tabindex="-1">${esc(site.name)}</h2>
    <p class="where">${esc(site.country)} · ${fmtCoord(site.lat, site.lon)} · ${esc(site.terrain)}</p>
    <div class="scorebox"><span class="big">${score == null ? '<small>no score</small>' : `${pct(score)}<small>%</small>`}</span>
      <span class="of">${esc(modeText)} with<br><b>${esc(target.name)}</b> · ${esc(BODY_LABEL[target.body])}${gapText ? `<br>${esc(gapText)}` : ''}${stab}</span></div>
    ${score == null ? `<p class="caveat">${noScoreText([result], target)}</p>` : ''}
    <div class="actions" style="margin-top:0">
      ${inCloseup ? '<button type="button" class="btn" data-action="back">Back to globe</button>' : '<button type="button" class="btn primary" data-action="fly">Fly down</button>'}
      ${standButtons(site.id)}
      ${hasImagery(site.id) || hasImagery(target.id) ? '<button type="button" class="btn" data-action="twin">Twin view</button>' : ''}
      ${baseAllowed({ kind: 'site', id: site.id }, target.id) ? '<button type="button" class="btn primary" data-action="base" title="A test base here for the starred target: floor plan, crops, communications">⭐ Explore base plan</button>' : ''}
    </div>
    ${baseAllowed({ kind: 'site', id: site.id }, target.id) ? `<p class="star-note">⭐ Strongest Earth match on the ${esc(BODY_LABEL[target.body])}: the one pair we plan a base for.</p>` : ''}
    ${quick}
    ${site.why ? `<p class="why">${esc(site.why)}</p>` : ''}
    ${LIMIT_LINE}
    ${moreSection(`${photoNote(site.id)}
    ${twinOfSection(site)}
    <div class="section"><span class="label">Factor by factor</span>
      <table class="facts"><thead><tr><th>Factor</th><th>This site</th><th>${esc(target.name.split(' (')[0].split(',')[0])}</th><th>Match</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="src">Earth: <a href="${esc(p.rawFile)}" target="_blank">NASA POWER ${esc(p.period.match(/\(([^)]+)\)/)?.[1] || '2001–2020')}</a> (grid cell about 50 km, elevation ${fmt(p.gridElevation_m, 0, 'm')}). Target: ${targetSources}</p>
      ${earthTempLine('site')}
    </div>
    ${pillars}
    ${orbitSiteHTML(site)}
    <div class="section"><span class="label">Sources and caveats</span><ul class="links">${sources}</ul>${caveats}</div>
    ${testsSection(site)}
    <div class="section"><span class="label">Climate facts · NASA POWER</span>
      <table class="facts"><tbody>${facts}</tbody></table>
      <p class="src">Highest/lowest values are the extreme hourly values in 2001–2020; the others are 20-year averages.</p></div>`)}`);
}

export function renderTarget(target, twins, extra = {}) {
  const el = panel();
  el.hidden = false;
  document.body.classList.add('sheet-detail');
  const rows = factorsFor(target).map((f) => {
    const v = targetValue(target, f.id, state.strict);
    const digits = f.id === 'albedo' ? 2 : Number.isInteger(v.value) ? 0 : 1;
    return `<tr><td>${esc(f.short)}${v.strictApplied ? ' <span class="tag">strict</span>' : ''}</td><td class="num">${v.value != null ? fmt(v.value, digits, f.unit) : '<span class="src">not measured</span>'}</td>
      <td><span class="src">${esc(v.note || '')} ${v.source ? srcLink(v.source) : ''}</span></td></tr>`;
  }).join('');
  const facts = (target.facts || []).map((x) => `<tr><td>${esc(x.label)}</td><td>${esc(x.text)} <span class="src">${srcLink(x.source)}</span></td></tr>`).join('');
  // Only sites with a score can be twins; if none has one, say why instead.
  const scored = twins.filter((r) => r.score != null).slice(0, 3);
  const twinList = scored.length
    ? `<ul class="twins">${scored.map((r) => `<li><button type="button" data-action="go-site" data-id="${esc(r.site.id)}"><span>${esc(r.site.name)} <span class="src">${esc(r.site.country)}</span></span><span class="tw-r">${state.mode === 'full' ? pillarStrip(r) : ''}<span class="pc">${pct(r.score)}%</span></span></button></li>`).join('')}</ul>`
    : `<p class="caveat">${noScoreText(twins, target)}</p>`;
  const gapText = targetGapText(twins, target);
  const measured = measuredFactors(target);
  const inCloseup = state.view !== 'globe'; // also during the fly-down, so Back to globe shows
  setPanel(el, `
    <button type="button" class="btn small close" data-action="close" aria-label="Close details" title="Back to results">←</button>
    <div class="kicker"><span class="label">Target site</span><span class="body-chip ${esc(target.body)}">${esc(BODY_LABEL[target.body])}</span></div>
    <h2 class="title" tabindex="-1">${esc(target.name)}</h2>
    <p class="where">${esc(target.mission)} · ${fmtCoord(target.lat, target.lon)}</p>
    <div class="actions" style="margin-top:0">
      ${inCloseup ? '<button type="button" class="btn" data-action="back">Back to globe</button>' : '<button type="button" class="btn primary" data-action="fly">Fly down</button>'}
      ${standButtons(target.id)}
      ${isStarTarget(target.id) ? '<button type="button" class="btn primary" data-action="base" title="A base here: floor plan, crops, communications">⭐ Explore base plan</button>' : ''}
    </div>
    ${isStarTarget(target.id) ? `<p class="star-note">⭐ Its closest Earth twin is the strongest match of any ${esc(BODY_LABEL[target.body])} target (default screening score), so this is where we plan the base.</p>` : `<p class="src">The base plan is available only at the starred ⭐ target of each world: ${Object.values(starPairs()).map((s) => esc(state.data.targets.find((t) => t.id === s.targetId)?.name || s.targetId)).join(' and ')}.</p>`}
    <div class="section"><span class="label">Closest Earth twins</span>${twinList}
      <p class="src">${scoreLabel()}${gapText ? ` · ${esc(gapText)}` : ''}.${scored.length ? ' Click a twin to fly there on Earth.' : ''}${scored.length && state.mode === 'full' ? ` ${pillarKey().join(' = ')}.` : ''}</p></div>
    ${measured < TARGET_MIN_MEASURED ? `<p class="caveat">⚑ Only ${measured} of the ${CLIMATE_FACTORS.length} original climate factors ${measured === 1 ? 'has' : 'have'} site-level data. See the factor sources under Full data &amp; sources.</p>` : ''}
    ${moreSection(`${photoNote(target.id)}
    <div class="section"><span class="label">Environment used in the score${state.strict ? ' · strict data' : ''}</span>
      <table class="facts"><tbody>${rows}</tbody></table></div>
    <div class="section"><span class="label">More measured facts</span><table class="facts"><tbody>${facts}</tbody></table></div>`)}`);
}

export function hideDetail() {
  panel().hidden = true;
  document.body.classList.remove('sheet-detail');
}
