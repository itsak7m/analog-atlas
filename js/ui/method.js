// "Method & data": the formula, every value with its source, all scores in one table, credits, limits and the AI-use note.

import { state } from '../state.js';
import { CLIMATE_FACTORS, EXTRA_FACTORS, SUN_TILT, factorsFor, PILLARS, R_SLOPE, SAFE_SLOPE_DEG, RESOURCES, ROCK_FAMILY, ROCK_LABEL, climateBreakdown, pct, rankSites, scoreSite, measuredFactors, TARGET_MIN_MEASURED, STRICT_MIN_FACTORS, FULL_MIN_PILLARS } from '../scoring.js';
import { esc, fmt, fmtCoord, cellGap, CELL_GAP_LIMIT_M, STATUS_LABEL, BODY_LABEL } from '../util.js';
import { openOverlay } from './overlay.js';
import { TARGET_GROUPS } from './topbar.js';
import { computeRanking, displayRanks, gapWords, rankingBasis, basisText, TWIN_MIN_PCT, BASE_GROUP, BASE_TOP_N, baseConsensus, baseConsensusText } from './ranking.js';
import { fromOrbit } from './detail.js';
import { loadScreening, getScreening, scoreBoxes, statusText, FLAG_WORDS, SCREEN_LABEL, TOP_N } from '../screening.js';
import { exclusionsText } from './discover.js';
import { E29_LOW, E29_HIGH, s2YearRange } from './orbit.js';

// The brief's original site list (Mauna Kea removed, see the self-check text).
const ORIGINAL_SITES = ['wadi-rum', 'harrat', 'atacama', 'haughton', 'death-valley', 'dry-valleys', 'holuhraun', 'rio-tinto', 'mdrs'];
// The brief gave reference values for these four targets only. The other targets use our own sourced values.
const BRIEF_TARGETS = ['jezero', 'gale', 'southpole', 'apollo11'];
const EXPECTED = {
  jezero: { 'dry-valleys': 60, harrat: 57, atacama: 57, 'death-valley': 57, mdrs: 57, haughton: 56, 'wadi-rum': 55, 'rio-tinto': 52, holuhraun: 33 },
  southpole: { atacama: 51, harrat: 50, 'death-valley': 50, 'wadi-rum': 47 },
  apollo11: { atacama: 44, harrat: 43, 'death-valley': 43, 'wadi-rum': 40 },
};

// Long file names, DOIs and source labels may break anywhere, so the tables fit on a phone.
const WRAP = 'style="overflow-wrap:anywhere"';

const link = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label || url)}</a>`;
const nameOf = (id) => (state.data.targets.find((t) => t.id === id) || state.data.sites.find((s) => s.id === id) || { name: id }).name;
// "a", "a and b", "a, b and c" (with ";" between items when a name has a comma). The items must already be escaped.
function andList(items) {
  if (items.length < 2) return items.join('');
  const sep = items.some((x) => x.includes(',')) ? '; ' : ', ';
  return `${items.slice(0, -1).join(sep)} and ${items[items.length - 1]}`;
}
// A number exactly as it is stored in the data file, with its unit.
const exact = (v, unit) => fmt(v, (String(v).split('.')[1] || '').length, unit);

// Pillars the full match cannot use for a target because the target has no data for them
// (from scoreSite; they are the same whichever site is compared).
function targetGaps(t) {
  const d = state.data;
  return scoreSite(d.sites[0], t, { mode: 'full', terrain: d.terrain, resources: d.resources }).targetGaps || [];
}

// "3 of 5 pillars (rock type and resources not measured)", with the same words as the ranking panel.
function pillarText(t) {
  const gaps = targetGaps(t);
  return `${PILLARS.length - new Set(gaps).size} of ${PILLARS.length} pillars${gaps.length ? ` (${esc(gapWords(gaps))} not measured)` : ''}`;
}

// Targets whose largest flat zone is no larger than any Earth site's: their landing pillar is 100 % for every site.
function flatForAll() {
  const d = state.data;
  if (!d.terrain) return [];
  const zones = d.sites.filter((s) => !s.terrainExclude).map((s) => d.terrain[s.id]?.max_flat_square_km).filter((v) => v != null);
  if (!zones.length) return [];
  const smallest = Math.min(...zones);
  return d.targets.filter((t) => { const z = d.terrain[t.id]?.max_flat_square_km; return z > 0 && z <= smallest; })
    .map((t) => ({ t, zone: d.terrain[t.id].max_flat_square_km }));
}

// Measured climate factors of a target, split into those that score under 10 % at every Earth site
// (they cannot separate the sites) and the rest.
function factorSpread(t) {
  const rows = state.data.sites.map((s) => climateBreakdown(s, t).rows);
  const measured = factorsFor(t).map((f, i) => ({ f, i })).filter(({ f }) => t.values[f.id]?.value != null);
  const low = measured.filter(({ i }) => rows.every((r) => (r[i].score ?? 0) < 0.1)).map(({ f }) => f);
  return { low, rest: measured.map(({ f }) => f).filter((f) => !low.includes(f)) };
}

// Earth sites whose NASA POWER cell is far above or below the real ground (largest gap first).
function flaggedSites() {
  const d = state.data;
  return d.sites.map((s) => ({ s, q: cellGap(s, d.terrain) })).filter((x) => x.q && x.q.flagged)
    .sort((a, b) => Math.abs(b.q.gap) - Math.abs(a.q.gap));
}

const flaggedTargets = () => state.data.targets.filter((t) => measuredFactors(t) < TARGET_MIN_MEASURED);

// How a photo is offered in the app (the same words as the "Stand here" buttons).
function viewKind(p) {
  if (p.kind === 'photo') return 'Photo (not 360°)';
  const h = Number(p.haov) || 360;
  return h >= 360 ? '360° photo' : `${Math.round(h)}° panorama`;
}

// Re-run the reference rankings from the brief, in the browser, with the real data files.
function selfCheck() {
  const d = state.data;
  const rows = [];
  let ok = true;
  for (const [tid, expected] of Object.entries(EXPECTED)) {
    const target = d.targets.find((t) => t.id === tid);
    const sites = d.sites.filter((s) => ORIGINAL_SITES.includes(s.id));
    const ranked = rankSites(sites, target, { mode: 'climate' });
    for (const [sid, want] of Object.entries(expected)) {
      const got = pct(climateBreakdown(d.sites.find((s) => s.id === sid), target).score);
      const pass = got === want;
      ok = ok && pass;
      rows.push(`<tr><td>${esc(target.name)}</td><td>${esc(d.sites.find((s) => s.id === sid).name)}</td><td class="num">${want}%</td><td class="num">${got}%</td><td class="check${pass ? '' : ' fail'}">${pass ? '✓' : '✗'}</td></tr>`);
    }
    const order = ranked.map((r) => r.site.id);
    if (tid !== 'jezero') {
      const pass = ['atacama', 'harrat', 'death-valley', 'wadi-rum'].every((id, i) => order[i] === id);
      ok = ok && pass;
      rows.push(`<tr><td>${esc(target.name)}</td><td>Order of the first four</td><td>Atacama, Harrat, Death Valley, Wadi Rum</td><td>${order.slice(0, 4).map((id) => esc(d.sites.find((s) => s.id === id).name)).join(', ')}</td><td class="check${pass ? '' : ' fail'}">${pass ? '✓' : '✗'}</td></tr>`);
    }
  }
  return { ok, html: `<table class="facts"><thead><tr><th>Target</th><th>Site</th><th>Reference</th><th>This app</th><th></th></tr></thead><tbody>${rows.join('')}</tbody></table>` };
}

function groupsList() {
  const d = state.data;
  return TARGET_GROUPS.map((g) => {
    const names = d.targets.filter((t) => (t.group || t.body) === g.id).map((t) => esc(t.name));
    return names.length ? `<li><b>${esc(g.label)}</b>: ${andList(names)}</li>` : '';
  }).join('');
}

// The short answer: every target with its 3 closest Earth twins (full analog match, default settings, whatever the
// panel is set to now), how many sites reach the strong-twin line, and what to keep in mind. All computed live.
function shortAnswer() {
  const d = state.data;
  const opts = { mode: 'full', terrain: d.terrain, resources: d.resources };
  const brief = (name) => esc(name.split(' (')[0].split(',')[0]);
  const rows = TARGET_GROUPS.map((g) => {
    const targets = d.targets.filter((t) => (t.group || t.body) === g.id);
    if (!targets.length) return '';
    return `<tr><th colspan="4" style="text-align:left">${esc(g.label)}</th></tr>${targets.map((t) => {
      const ranked = rankSites(d.sites, t, opts);
      const ranks = displayRanks(ranked);
      const top = ranked.map((r, i) => ({ r, rank: ranks[i] })).filter(({ r, rank }) => r.score != null && rank <= 3)
        .map(({ r, rank }) => `${rank}. ${brief(r.site.name)} ${pct(r.score)}%${flagOf(r.site)}${r.site.jordan ? ' <span class="src">Jordan</span>' : ''}`).join('<br>');
      const strong = ranked.filter((r) => r.score != null && pct(r.score) >= TWIN_MIN_PCT).length;
      const notes = [];
      if (targetGaps(t).length) notes.push(`Uses ${pillarText(t)}.`);
      const basis = basisText(rankingBasis(ranked, { mode: 'full', pillars: {} }));
      if (basis) notes.push(esc(basis));
      if (!strong) notes.push(`No site reaches ${TWIN_MIN_PCT}%.`);
      if (measuredFactors(t) < TARGET_MIN_MEASURED) notes.push(`⚑ fewer than ${TARGET_MIN_MEASURED} of the 5 factors measured at the site itself.`);
      return `<tr><td>${esc(t.name)}</td><td>${top || '<span class="src">no score</span>'}</td><td class="num">${strong} of ${d.sites.length}</td><td class="src">${notes.join(' ')}</td></tr>`;
    }).join('')}${g.id === BASE_GROUP ? baseRow() : ''}`;
  }).join('');
  return `<p>Every target and its 3 closest Earth twins (full analog match, all weights ×1, strict data off, Earth air temperature; this table does not follow the settings of the ranking panel). Equal percentages share a rank. A match says where to test first; it is not proof.</p>
    <div class="scroll-x"><table class="facts"><thead><tr><th>Target</th><th>Closest Earth twins</th><th>Sites at ${TWIN_MIN_PCT}% or more</th><th>Read with care</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="src">⚑ after a site: its NASA POWER cell height differs from the ground by more than ${CELL_GAP_LIMIT_M} m, so its climate describes a wider area. ⚑ in the last column: the target has fewer than ${TARGET_MIN_MEASURED} of the 5 factors measured at the site itself.</p>`;
}

// ⚑ after a site name whose NASA POWER cell is far above or below the real ground.
const flagOf = (s) => (cellGap(s, state.data.terrain)?.flagged ? ' ⚑' : '');

// The extra short-answer row for the permanent Moon base locations taken together (computed by baseConsensus).
function baseRow() {
  const c = baseConsensus();
  if (!c) return '';
  const names = andList(c.targets.map((t) => esc(t.name.split(' (')[0])));
  const line = (r) => `${esc(r.site.name.split(',')[0])}${flagOf(r.site)}: ${r.ranks.map((k, i) => `#${k} (${r.pcts[i]}%)`).join(', ')}`;
  const best = c.rows[0];
  const twins = c.steady.length ? c.steady.map(line).join('<br>') : `<span class="src">none in the top ${BASE_TOP_N} for all ${c.targets.length}</span>`;
  const notes = [`Earth sites in the top ${BASE_TOP_N} for every base site (equal percentages share a rank); ranks in the order ${names}.`];
  if (best && !c.steady.includes(best)) notes.push(`Best mean rank: ${esc(best.site.name)} (${best.mean.toFixed(1)}).`);
  else if (best) notes.push(`Mean rank ${best.mean.toFixed(1)}; the next best is ${c.rows[1] ? `${esc(c.rows[1].site.name)} (${c.rows[1].mean.toFixed(1)})` : 'none'}.`);
  return `<tr><td><b>All ${c.targets.length} base sites together</b></td><td>${twins}</td><td class="num">${c.strong.length} of ${state.data.sites.length}<div class="src">for all ${c.targets.length}</div></td><td class="src">${notes.join(' ')}</td></tr>`;
}

function targetsTable() {
  const d = state.data;
  // Values are not forced onto one line, so the tables also fit on a phone.
  const show = (v, f) => (v != null ? `<span class="mono" style="white-space:nowrap">${exact(v, f.unit)}</span>` : '<span class="src">not measured</span>');
  const srcOf = (id) => { const s = id && d.sources[id]; return s ? link(s.url, s.label) : '—'; };
  return d.targets.map((t) => {
    const rows = factorsFor(t).map((f) => {
      const v = t.values[f.id] || {};
      const st = v.strict;
      return `<tr><td>${esc(f.label)}</td><td>${show(v.value, f)}</td><td ${WRAP}>${esc(v.note || '')}<div class="src">${srcOf(v.source)}</div></td>
        <td ${WRAP}>${st === undefined ? '<span class="src">same</span>' : show(st.value, f)}${st && st.note ? `<div class="src">${esc(st.note)}${st.source ? ` · ${srcOf(st.source)}` : ''}</div>` : ''}</td></tr>`;
    }).join('');
    const flag = measuredFactors(t) < TARGET_MIN_MEASURED ? ` <span title="Fewer than ${TARGET_MIN_MEASURED} of the 5 factors are measured at the site itself">⚑</span>` : '';
    const ref = BRIEF_TARGETS.includes(t.id) ? 'from the team\'s brief, checked against the source on each row' : 'our own, from the source on each row';
    return `<h4 style="margin:14px 0 4px">${esc(t.name)}${flag} <span class="body-chip ${esc(t.body)}">${esc(BODY_LABEL[t.body] || t.body)}</span> <span class="src">${fmtCoord(t.lat, t.lon)} · ${esc(t.mission)}</span></h4>
      <p class="src">Reference values: ${ref}. Full analog match: ${pillarText(t)}.</p>
      <table class="facts"><thead><tr><th>Factor</th><th>Reference value</th><th>What it is · source</th><th>Strict data</th></tr></thead><tbody>${rows}</tbody></table>`;
  }).join('');
}

function sitesTable() {
  const d = state.data;
  const rows = d.sites.map((s) => {
    const a = s.power.annual;
    const [label] = STATUS_LABEL[s.status] || [''];
    const q = cellGap(s, d.terrain);
    return `<tr><td>${esc(s.name)}<div class="src">${esc(s.country)} · ${esc(label)}</div></td><td class="num">${fmtCoord(s.lat, s.lon)}</td>
      <td class="num">${fmt(s.power.gridElevation_m, 0)}${q && q.flagged ? ' ⚑' : ''}</td><td class="num">${q ? fmt(q.ground, 0) : 'not measured'}</td><td class="num">${fmt(a.T2M, 2)}</td><td class="num">${fmt(a.T2M_RANGE, 2)}</td><td class="num">${fmt(a.TS_MIN, 2)}</td>
      <td class="num">${fmt(a.PRECTOTCORR, 2)}</td><td class="num">${fmt(a.ALLSKY_SRF_ALB, 2)}</td><td class="num">${fmt(a.RH2M, 1)}</td><td class="num">${fmt(a.ALLSKY_SFC_UV_INDEX, 2)}</td>
      <td class="num">${fmt(a.PS, 2)}</td><td>${link(s.power.rawFile, 'raw JSON')}</td><td>${s.sources.map((x) => link(x.url, x.label)).join('<br>')}</td></tr>`;
  }).join('');
  return `<div class="scroll-x"><table class="facts"><thead><tr><th>Site</th><th>Lat, lon</th><th>Cell elev. m</th><th>Ground elev. m</th><th>T2M °C</th><th>T2M_RANGE °C</th><th>TS_MIN °C</th><th>Rain mm/d</th><th>Albedo</th><th>RH %</th><th>UV index</th><th>PS kPa</th><th>NASA POWER</th><th>Why it is listed</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// Every site against every target with the current settings (the same numbers as the ranking panel).
function scoreMatrix() {
  return state.data.targets.map((t) => {
    const ranked = computeRanking(t.id);
    const ranks = displayRanks(ranked);
    const bySite = new Map(ranked.map((r, i) => [r.site.id, { r, rank: ranks[i] }]));
    return { t, bySite };
  });
}

const pillarsUsed = (r) => r.pillarsUsed ?? [r.climate?.score, r.terrain?.score, r.landing?.score, r.geology?.score, r.resources?.score].filter((v) => v != null).length;
const settingsText = () => `${state.mode === 'full' ? 'Full analog match' : 'Climate match'} · strict data ${state.strict ? 'on' : 'off'} · Earth temperature ${state.earthTemp === 'surface' ? 'ground surface (MODIS)' : 'air (NASA POWER)'} · weights as set in Tune factors`;

function matrixSection() {
  const d = state.data;
  const full = state.mode === 'full';
  const cols = scoreMatrix();
  const flagged = new Set(flaggedTargets().map((t) => t.id));
  const head = cols.map(({ t }) => `<th>${esc(t.name.split(' (')[0])}${flagged.has(t.id) ? ' ⚑' : ''}</th>`).join('');
  const rows = d.sites.map((s) => {
    const q = cellGap(s, d.terrain);
    const cells = cols.map(({ bySite }) => {
      const { r, rank } = bySite.get(s.id);
      const p = pct(r.score);
      if (p == null) return '<td><span class="src">no score</span></td>';
      return `<td class="num">${rank <= 3 ? `<b>${p}%</b>` : `${p}%`}${full ? `<div class="src">${pillarsUsed(r)}/${PILLARS.length}</div>` : ''}</td>`;
    }).join('');
    return `<tr><td>${esc(s.name)}${q && q.flagged ? ' ⚑' : ''}<div class="src">${esc(s.country)}</div></td>${cells}</tr>`;
  }).join('');
  return `<p>Every Earth site against every target. Settings now: ${esc(settingsText())}. Change them in the ranking panel or in Tune factors, then open this page again. <b>Bold</b> = top 3 for that target.${full ? ` Under each score: pillars used. A site with fewer than ${FULL_MIN_PILLARS} pillars gets no score.` : ''} ⚑ = data-quality flag (see below).</p>
    <p><button type="button" class="btn small" data-action="matrix-csv">Download this table (CSV)</button></p>
    <div class="scroll-x"><table class="facts"><thead><tr><th>Site</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function downloadMatrix() {
  const d = state.data;
  const full = state.mode === 'full';
  const cols = scoreMatrix();
  const cell = (v) => { const x = String(v ?? ''); return /[",\n]/.test(x) ? `"${x.replace(/"/g, '""')}"` : x; };
  const head = ['site_id', 'site', 'country', 'cell_flag'];
  for (const { t } of cols) head.push(`${t.id}_percent`, `${t.id}_rank`, ...(full ? [`${t.id}_pillars`] : []));
  const lines = [head.map(cell).join(',')];
  for (const s of d.sites) {
    const q = cellGap(s, d.terrain);
    const row = [s.id, s.name, s.country, q && q.flagged ? 'yes' : 'no'];
    for (const { bySite } of cols) {
      const { r, rank } = bySite.get(s.id);
      const p = pct(r.score);
      row.push(p ?? '', p == null ? '' : rank, ...(full ? [pillarsUsed(r)] : []));
    }
    lines.push(row.map(cell).join(','));
  }
  const blob = new Blob([`${lines.join('\n')}\n`], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `analog-atlas-scores-${state.mode}${state.strict ? '-strict' : ''}${state.earthTemp === 'surface' ? '-surface' : ''}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function terrainSection() {
  const doc = state.data.terrainDoc;
  if (!doc) return '<p>Terrain statistics are not available yet (data/terrain.json).</p>';
  const m = doc.method || {};
  const g = m.grid;
  const sets = (m.datasets || []).map((x) => `<li>${esc(BODY_LABEL[x.body] || x.body)}: ${esc(x.name)} · ${esc(x.resolution || '')} · ${esc(x.licence || x.credit || '')} ${x.url ? link(x.url, 'link') : ''}</li>`).join('');
  const plain = g ? `<p>For each place we read the ground height at ${esc(g.n)} × ${esc(g.n)} points, ${esc(Math.round(g.spacing_m))} m apart (a ${esc(g.box_m / 1000)} km square around the pin). At each inner point we measure the slope over ${esc(g.baseline_m / 1000)} km. Elevation data:</p>` : '';
  return `${plain}<ul>${sets}</ul>
    <details><summary>Technical details (from data/terrain.json)</summary><p>${esc(m.text || '')}</p></details>
    <p>Terrain match = max(0, 1 − |median slope of the site − median slope of the target| ÷ ${R_SLOPE}°). The ${R_SLOPE}° scale is our choice: a difference of ${R_SLOPE}° or more counts as "not alike".</p>`;
}

function landingSection() {
  const d = state.data;
  const src = d.sources['artemis-landing-slope'];
  const same = flatForAll().map(({ t, zone }) => `<p>${esc(t.name)} has a largest flat zone of ${esc(zone)} km. Every Earth site with terrain data has a flat zone at least as large, so for this target the landing pillar is 100 % for all of them. It does not change their order.</p>`).join('');
  return `<p>A crew needs one flat place to land and build, not a whole flat region. In the same 10 km box we find the largest square where every grid point has a slope under ${SAFE_SLOPE_DEG}°. NASA's key Artemis landing rule is a slope under 10° measured over 100 m; our slopes use a 1 km baseline, so this is an approximation. The square's side is between 0.5 and 9.5 km (500 m steps). Landing match = min(1, site flat zone ÷ target flat zone): a site scores 1 when it offers a flat zone at least as large as the target's. Mountains elsewhere in the box do not lower this score; they are counted in the terrain pillar.</p>${src ? `<p class="src">Source of the Artemis rule: ${link(src.url, src.label)}</p>` : ''}${same}`;
}

function geologySection() {
  const fams = {};
  for (const [rock, fam] of Object.entries(ROCK_FAMILY)) (fams[fam] = fams[fam] || []).push(ROCK_LABEL[rock] || rock);
  // Rock sources of the Earth sites (geology.sources / geology.unsourced in data/sites_meta.json), counted live.
  const sites = state.data.sites;
  const igme = sites.filter((s) => (s.geology?.sources || []).some((x) => /IGME5000/.test(x.label || ''))).length;
  const noMain = sites.filter((s) => (s.geology?.unsourced || []).includes(s.geology?.primary)).map((s) => esc(s.name));
  return `<p>Each place has a main rock type and, where relevant, other rock types found there (data/sites_meta.json and data/targets.json). Each target names the source of its rock type. Each Earth site lists the sources that name its rock types, with an exact quote (geology.sources in data/sites_meta.json)${igme ? `; for ${igme} sites one of them is the IGME5000 map unit at the site point` : ''}.${noMain.length ? ` For ${noMain.length} of the ${sites.length} sites the main rock has no source yet, and the data says so ("Rock type source still to be added"): ${andList(noMain)}.` : ''}</p>
    <ul><li><b>1.0</b>: same main rock (for example basalt at Harrat al-Shaam and mare basalt at Apollo 11).</li>
    <li><b>0.5</b>: the main rock of one place is also found at the other, or both main rocks are in the same family.</li>
    <li><b>0</b>: different rock types.</li></ul>
    <p>Families: ${Object.entries(fams).map(([f, list]) => `<b>${esc(f)}</b> (${list.map(esc).join(', ')})`).join('; ')}. These match levels are a method choice, not a measurement. A target whose rock type is not known has no geology pillar.</p>`;
}

function resourcesSection() {
  const doc = state.data.resourcesDoc;
  const vocab = Object.entries(RESOURCES).map(([k, v]) => `<b>${esc(k)}</b> (${esc(v)})`).join(', ');
  if (!doc) return `<p>Resource tags are not available yet (data/resources.json). Vocabulary: ${vocab}.</p>`;
  const rows = Object.entries(doc.places).map(([id, p]) => {
    const place = state.data.sites.find((s) => s.id === id) || state.data.targets.find((t) => t.id === id);
    const tags = Object.entries(p.tags).map(([tag, src]) => `${esc(tag)} ${src.url ? link(src.url, '↗') : ''}`).join(', ');
    return `<tr><td>${esc(place ? place.name : id)}</td><td>${tags || `— <span class="src">${esc(p.note || '')}</span>`}</td></tr>`;
  }).join('');
  return `<p>Which resources for a permanent base a target offers, and which of them crews can practise with at an Earth site. Vocabulary: ${vocab}.${doc.rules?.regolith ? ` Rule for the regolith tag: ${esc(doc.rules.regolith)}` : ''} Each tag has a source. Resources match = share of the target's tags that the site also has. A site with no sourced tag scores 0 (we searched and found no source). A target with no sourced tag has no resources pillar. The tags are a classification with sources, not a measurement.</p>
    <table class="facts"><thead><tr><th>Place</th><th>Tags (source)</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// ---------- Discover Jordan: 10 km screening boxes (data/screening_jordan.json) ----------
// The file loads on demand, so these parts are filled in when it is ready. Every number is read from the
// file or counted in it, so the text stays true after a rebuild.

const num = (v) => esc(Number(v).toLocaleString('en'));

// The middle value of the number of boxes per MERRA-2 cell.
function boxesPerCell(doc) {
  const per = {};
  for (const b of doc.boxes) per[b.climate.merra] = (per[b.climate.merra] || 0) + 1;
  const counts = Object.values(per).sort((a, b) => a - b);
  return (counts[(counts.length - 1) >> 1] + counts[counts.length >> 1]) / 2;
}

// Main rocks the map gives the boxes ("Limestone / dolomite (590 boxes)"), and the rock types it never gives:
// those that no map unit in the rock table has as its main rock with high or medium certainty
// (a rock that is only not dominant in any box today, such as chert, is not in that list).
function boxRocks(doc) {
  const counts = doc.counts?.primaryRock || {};
  const found = Object.keys(counts).filter((r) => r !== 'none');
  const possible = new Set(Object.values(doc.geology?.units || {}).filter((u) => u.primary && u.certainty !== 'low').map((u) => u.primary));
  return {
    found: found.map((r) => `${esc(ROCK_LABEL[r] || r)} (${num(counts[r])})`),
    none: counts.none || 0,
    never: Object.keys(ROCK_LABEL).filter((r) => !found.includes(r) && !possible.has(r)).map((r) => esc((ROCK_LABEL[r] || r).toLowerCase())),
  };
}

// The Top 10 status for the current settings, e.g. "Discover on: 760 boxes ranked for Jezero Crater; top 89 %".
function screeningNow() {
  const result = scoreBoxes();
  if (!result) return '';
  const best = (result.sites || []).find((s) => s.score != null);
  const same = state.mode === 'full' ? 'scored the same way, without resources' : 'climate match';
  return `<p>Now (${esc(settingsText())}): ${esc(statusText(result).replace(/^Discover on: /, ''))}. ${esc(exclusionsText(result))}.${best ? ` Best hand-picked Jordan site, ${esc(same)}: ${esc(best.site.name)} ${esc(best.pct)}%.` : ''}</p>`;
}

function screeningSection(doc) {
  const g = doc.grid || {};
  const c = doc.counts || {};
  const f = c.flags || {};
  const ck = doc.checks || {};
  const cl = doc.climate || {};
  const t = doc.terrain || {};
  const geo = doc.geology || {};
  const b = doc.boundary || {};
  const kept = doc.boxes.length;
  const rocks = boxRocks(doc);
  const allFlat = doc.boxes.filter((x) => !x.terrainExclude && x.terrain?.pct_lt_10 === 100).length;
  const checks = Object.values(ck);
  const result = (name) => esc(ck[name]?.result || 'not recorded');
  const flagRows = Object.keys(FLAG_WORDS).map((k) => `<tr><td>${esc(FLAG_WORDS[k])}</td><td ${WRAP}>${esc(doc.flagRules?.[k] || '')}</td><td class="num">${num(f[k] || 0)}</td></tr>`).join('');
  return `<p>Discover Jordan covers Jordan with ${num(kept)} boxes of 10 km and scores each box against the chosen target with the same formula as the hand-picked sites. It checks the hand-picked Jordan sites against the whole country and shows the places that the data says are worth a closer look. With the default settings, for most targets the best boxes are on the same Harrat basalt plain as a hand-picked site, or close to one of our sites, and score at most 2 points above the best hand-picked Jordan site, which is within the resolution of the data: the data confirms the hand-picked sites. Every box carries the label <b>"${esc(doc.label || SCREEN_LABEL)}"</b>. Boxes are never added to the site list and have no pins: open them with the <b>Discover Jordan</b> tab of the ranking panel, on the globe, or in the table of all boxes.</p>
    <p><b>The grid.</b> The south-west corner is ${esc(g.south)}° N, ${esc(g.west)}° E. A row is ${esc(g.dlat)}° of latitude (10 km) and a column ${esc(g.dlon)}° of longitude (10 km at ${esc(g.lonStepLat)}° N): ${num(g.nrows)} rows × ${num(g.ncols)} columns = ${num(g.gridBoxes)} boxes. A box is kept when its centre is inside Jordan's polygon from ${b.url ? link(b.url, `${b.source || 'Natural Earth'} ${b.version || ''}`.trim()) : esc(b.source || 'Natural Earth')}: ${num(kept)} boxes, of which ${num(f.border || 0)} cross the border.${b.note ? ` Boundary: ${esc(b.note)}` : ''} Coverage check: ${result('coverage')}.</p>
    <p><b>Climate.</b> ${cl.api ? link(cl.api, 'NASA POWER regional') : 'NASA POWER regional'} ${esc(cl.apiVersion || '')}: each box takes the NASA POWER cells that hold its centre, the same rule the POWER point API uses for the sites. That is ${num(c.merraCells)} MERRA-2 cells (0.5° × 0.625°: temperature, rain, humidity, wind, pressure) and ${num(c.synCells)} CERES SYN1deg cells (1° × 1°: sunlight, UV and albedo). A typical MERRA-2 cell holds ${num(boxesPerCell(doc))} boxes (the median), so the climate is blocky: neighbouring boxes often have the same climate. Check: the cells of the 5 Jordan sites and Amman equal the project's own point files (${result('climateControls')}). NASA labels the regional product "${esc(cl.periodLabel || '')}", but its values are the 2001–2020 numbers: ${esc(cl.periodValidated || '')}. The build stops if they ever differ.</p>
    <p><b>Terrain.</b> ${num((t.tiles || []).length)} Copernicus DEM GLO-90 tiles (about 90 m), read from the AWS open-data copy with Open-Meteo's own pixel rule, so a box gets the same pixels as the sites (the Open-Meteo API is not called). 441 samples per box on the same 500 m grid, with the same statistics as data/terrain.json. Check: for the 5 Jordan sites the result equals data/terrain.json exactly (${result('terrainControls')}). ${num(f.water || 0)} boxes are mostly water (Dead Sea): they get no terrain or landing score. ${num(f.partWater || 0)} are part water. Terrain separates the plateau only a little: ${num(allFlat)} of ${num(kept)} boxes have every slope under 10°.</p>
    <p><b>Geology.</b> ${geo.doi ? link(geo.doi, 'IGME5000') : 'IGME5000'} (BGR), a map at ${esc(geo.scale || '1:5,000,000')}, read at 25 points per box (5 × 5, 2 km apart). ${link('data/screening_rockmap_igme5000.json', 'A rock table')} gives each map unit a rock type of this app and a certainty (high, medium or low). The main rock of a box is the rock of the unit under most of its 25 points. A unit with low certainty gives no rock type: its guess is shown on the box page but not scored. Other units under at least 5 of the 25 points add their rock as another rock found there, unless their certainty is low. Main rock of the boxes: ${andList(rocks.found)}; no rock type: ${num(rocks.none)}. At this scale the map cannot show small or special rock bodies, so ${andList(rocks.never)} can never be the main rock of a box. Rock table status: ${esc(geo.rockTableReview || 'not recorded')}</p>
    <p><b>Score.</b> scoreSite() from js/scoring.js, unchanged, with the same weights (Tune factors applies to the boxes too). Boxes have no resources data, so that pillar is left out, and the resources slider has no effect on them. Leaving a pillar out changes a score, so a box % can only be compared with a site % that also leaves resources out: every box page shows the Jordan sites scored that way.</p>
    <p><b>Top ${TOP_N}.</b> A box is listed only when it has a score, is not mostly water, does not hold a hand-picked site (that site has its own page), has no ⚑ (its NASA POWER cell is not more than ${CELL_GAP_LIMIT_M} m higher or lower than the ground at its centre), and has data for every pillar the target has, apart from resources (a missing pillar is left out of the average, which can raise a score). Order: the shown %, then fewer flags, then a larger share of the box in its main rock unit, then a smaller cell height gap, then the box id. Touching boxes (8 neighbours) with the same % are one row ("+N nearby"). Rows with the same % share a rank (=3); a box page gives the box's own rank among all listed boxes and its Top ${TOP_N} row. Differences of 1–2 points are within the resolution of the data. Boxes that are not listed stay in the table of all boxes and on the map (faded); only the mostly-water boxes are not drawn. Box colours are stretched for each target: grey-blue is the 5th percentile of the listed boxes and amber the best listed box (at least 4 points apart); the legend shows both numbers. With the fixed 30–70 % scale of the sites, most targets would colour almost every box alike.</p>
    ${screeningNow()}
    <table class="facts"><thead><tr><th>Flag</th><th>Rule</th><th>Boxes</th></tr></thead><tbody>${flagRows}</tbody></table>
    <p><b>What it cannot do.</b></p>
    <ul><li>No box has resources data, so Discover cannot look for shelter (lava tubes), ice or salts.</li>
      <li>Rock types the map cannot show (above) cannot be discovered, nor can analogs that depend on them.</li>
      <li>Climate: no microclimate below the size of a NASA POWER cell, and visible seams follow the cell edges. ${num(f.cellGap || 0)} boxes have a ⚑ and ${num(f.climateCellMostlyOutside || 0)} take their climate from a cell that lies mostly outside Jordan.</li>
      <li>Not assessed: access, protected or military areas, border zones and landmines. The elevation model is a surface model, so buildings raise the slopes in towns.</li>
      <li>The ranking is within Jordan only. "Found by data" still rests on our choices: the grid, the weights, the R values of the formula and the listing rules.</li></ul>
    <details><summary>Exact rules (from data/screening_jordan.json)</summary>
      <p>${esc(g.inclusion || '')}</p><p>${esc(cl.rule || '')}</p><p>${esc(t.pixelRule || '')}</p><p>${esc(t.waterRule || '')}</p><p>${esc(geo.sampling || '')}</p>
      <p>${esc(geo.dominant || '')}; ${esc(geo.primaryRule || '')}; ${esc(geo.secondaryRule || '')}; ${esc(geo.nullRule || '')}.</p></details>
    <p class="src">Built by scripts/build_screening.py on ${esc(doc.generated || '')}; ${num(checks.filter((x) => x.ok).length)} of ${num(checks.length)} build checks passed. Sources, licences and notices: see Credits. Files: see Data files.</p>`;
}

function screeningCredits(doc) {
  const items = (doc.sources || []).map((s) => `<li>${s.url ? link(s.url, s.label || s.id) : esc(s.label || s.id)}${s.version ? ` · ${esc(s.version)}` : ''}${s.accessed ? ` · accessed ${esc(s.accessed)}` : ''}${s.licence ? ` · ${s.licenceUrl ? link(s.licenceUrl, s.licence) : esc(s.licence)}` : ''}
    ${s.credit ? `<div class="src" ${WRAP}>${esc(s.credit)}</div>` : ''}${s.notice && s.notice !== s.credit ? `<div class="src" ${WRAP}>${esc(s.notice)}</div>` : ''}</li>`).join('');
  return `Discover Jordan boxes (${link('data/screening_jordan.json')}, label "${esc(doc.label || SCREEN_LABEL)}"):<ul>${items}</ul>`;
}

// Fill the Discover Jordan parts of the Method page (now if the file is loaded, else once it is).
function fillScreening(el) {
  const put = (screening, err) => {
    if (!el.isConnected) return;
    const section = el.querySelector('[data-screening="section"]');
    const credits = el.querySelector('[data-screening="credits"]');
    if (screening) {
      section.innerHTML = screeningSection(screening.doc);
      credits.innerHTML = screeningCredits(screening.doc);
      return;
    }
    section.innerHTML = `<p class="caveat">${esc(err.message)}</p>`;
    credits.innerHTML = `Discover Jordan boxes: ${esc(err.message)}. Their sources, licences and notices are also in ${link('data/raw/screening/README.txt', 'data/raw/screening/README.txt')}.`;
  };
  const ready = getScreening();
  if (ready) put(ready);
  else loadScreening().then((s) => put(s), (err) => put(null, err));
}

// ---------- Surface temperature (MODIS, data/lst.json) and surface composition (data/composition.json) ----------

const doiUrl = (doi) => `https://doi.org/${doi}`;
const doiLinks = (dois) => (dois || []).map((x) => link(doiUrl(x), `doi:${x}`)).join(' · ');
const yearsOf = (period) => (period ? `${String(period.first).slice(0, 4)}–${String(period.last).slice(0, 4)}` : '');

// What kind of temperature a target value is, from its source (the note next to each value says the same):
// the Moon has no air; Mars Climate Sounder and the soil probes see the ground; MEDA, the REMS daily range and
// Phoenix's weather station see the air; the Mars fact sheet does not say.
const AIR_SOURCES = ['meda-press', 'meda-blog', 'phoenix-weather'];
const GROUND_SOURCES = ['mcs-surface-temps', 'rems-humidity-albedo'];
function tempKind(t, factorId) {
  const v = t.values[factorId];
  if (!v || v.value == null) return null;
  if (t.body === 'moon') return 'surface';
  if (GROUND_SOURCES.includes(v.source)) return 'surface';
  if (AIR_SOURCES.includes(v.source)) return 'air';
  if (v.source === 'rems-temps') return factorId === 'coldGround' ? 'surface' : 'air';
  if (v.source === 'mars-factsheet') return 'not stated';
  return 'see note';
}

// Top 3 of every target with air and with ground-surface temperature (full analog match, default weights).
function surfaceVsAirTable() {
  const d = state.data;
  const opts = { mode: 'full', terrain: d.terrain, resources: d.resources };
  // Every site whose displayed % puts it in the top 3 (equal percentages share a rank, so a tie at 3rd adds rows).
  const top = (t, earthTemp) => {
    const ranked = rankSites(d.sites, t, { ...opts, earthTemp });
    const ranks = displayRanks(ranked);
    return ranked.map((r, i) => ({ r, rank: ranks[i] })).filter(({ r, rank }) => r.score != null && rank <= 3)
      .map(({ r, rank }) => `${rank}. ${esc(r.site.name.split(',')[0].split(' (')[0])} ${pct(r.score)}%`).join('<br>') || '<span class="src">no score</span>';
  };
  const rows = d.targets.map((t) => {
    const kinds = ['meanTemp', 'swing', 'coldGround'].map((id) => {
      const k = tempKind(t, id);
      return k ? `<span title="${esc(t.values[id].note || '')}">${esc(k)}</span>` : '—';
    }).join(' · ');
    return `<tr data-target="${esc(t.id)}"><td>${esc(t.name)}<div class="src">${kinds}</div></td><td>${top(t, 'air')}</td><td>${top(t, 'surface')}</td></tr>`;
  }).join('');
  return `<div class="scroll-x"><table class="facts"><thead><tr><th>Target<div class="src">its mean · swing · coldest values are</div></th><th>Top 3 · air (reference)</th><th>Top 3 · ground surface</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function lstSection() {
  const doc = state.data.lstDoc;
  if (!doc) return '<p>Surface temperature is off: data/lst.json did not load.</p>';
  const r = doc.derivedRules || {};
  const sites = state.data.sites;
  const flagged = (f) => sites.filter((s) => (s.lst?.flags || []).includes(f)).map((s) => esc(s.name));
  const missing = sites.filter((s) => !s.lst).map((s) => esc(s.name));
  const polar = flagged('polar');
  const water = flagged('water');
  return `<p>NASA's MODIS cameras on the Terra and Aqua satellites measure the temperature of the ground surface itself (its "skin"), not the air. We use ${link(doiUrl('10.5067/MODIS/MOD21A2.061'), 'MOD21A2')} (Terra) and ${link(doiUrl('10.5067/MODIS/MYD21A2.061'), 'MYD21A2')} (Aqua), Collection ${esc(doc.product?.collection || '6.1')}: 8-day values at 1 km, every 8-day value of ${esc(yearsOf(doc.period))}, at the 1 km pixel that holds each site. Only clear-sky values with an estimated error of 2 K or less are used (exact QC rule below).</p>
    <ul><li><b>Mean surface temperature</b>: the average of the four passes (about 10:30, 13:30, 22:30 and 01:30 local time). It is not a 24-hour mean: these times are about 2–3 K warmer than the true daily mean.</li>
      <li><b>Day-night swing</b>: Aqua's about 13:30 value minus its about 01:30 value. It catches about 88 % of the full daily range, so the real range is a little larger.</li>
      <li><b>Coldest 8-day night</b>: the coldest 8-day mean of Aqua's about 01:30 values. Single nights get several K colder.</li>
      <li><b>Polar sites</b> (${andList(polar) || 'none'}): inside the polar circles the sun stays up or down for days, so day and night passes are not a daily cycle. Mean and swing are left empty; the coldest night is kept (in the polar night every pass is a night pass). In surface mode their climate match then rests on fewer factors, which can raise it: read polar scores with care.</li>
      <li><b>Water</b> (${andList(water) || 'none'}): when more than half of the 1 km pixel is lake or sea, the values describe water, not ground. In surface mode the three temperature factors are left out for that site ("not measured", with the reason).</li>
      ${missing.length ? `<li>Not in the file: ${andList(missing)}.</li>` : ''}</ul>
    <p><b>The switch.</b> In <b>Tune factors</b>, "Earth temperature" chooses where the Earth side of the three temperature factors comes from: <b>Air 2 m · NASA POWER</b> (cell about 50 km; the default, and what the reference rankings of the brief use) or <b>Ground surface · MODIS</b> (1 km). Rain and albedo always stay NASA POWER. In air mode the coldest-ground factor is already NASA POWER's model ground temperature (TS_MIN). The Discover Jordan boxes switch too: each box uses the mean of its 1 km MODIS pixels (data/screening_lst.json). The ranking shows "· surface temperature (MODIS)" while it is on.</p>
    <p><b>Why it helps.</b> Most Moon and Mars target values are ground temperatures (the Moon has no air; LRO Diviner, Mars Climate Sounder and the Apollo 17 heat-flow probe measured the surface), while Perseverance's MEDA, Curiosity's REMS (daily range) and Phoenix's weather station measured the air. Under each target below: what its mean, swing and coldest values are (point at a word to read the source note).</p>
    ${surfaceVsAirTable()}
    <p class="src">Top 3: full analog match, all weights ×1, strict data off. Equal percentages share a rank, so a tie can list more than 3 sites.</p>
    <details><summary>Exact rules (from data/lst.json)</summary><p>${esc(doc.qcRule || '')}</p><p>${esc(r.meanSurface_C || '')}</p><p>${esc(r.swingSurface_C || '')}</p><p>${esc(r.coldSurface_C || '')}</p><p>${esc(r.flags?.polar || '')}</p><p>${esc(r.flags?.water || '')}</p></details>`;
}

function compositionSection() {
  const doc = state.data.compositionDoc;
  if (!doc) return '<p>Surface composition is not available: data/composition.json did not load.</p>';
  const ru = doc.rules || {};
  const s2 = ru.s2 || {};
  const sample = doc.sample || {};
  const rows = Object.entries(doc.places).map(([id, p]) => {
    const flags = (p.flags || []).map((f) => esc(f.id)).join(', ');
    const jc = p.jordanCheck ? `${esc(p.jordanCheck.rock)}: <b>${esc(p.jordanCheck.verdict)}</b>` : '';
    return `<tr><td>${esc(nameOf(id))}</td><td class="num">${p.modis?.e29 != null ? fmt(p.modis.e29, 3) : '—'}</td><td>${esc(p.reading || '')}</td><td class="num">${p.aster?.silicaIndex != null ? fmt(p.aster.silicaIndex, 3) : '—'}</td><td>${flags}</td><td>${jc}</td></tr>`;
  }).join('');
  return `<p>Each site page and Discover box page has a card <b>Measured from orbit</b>. Besides the surface temperature above, it shows what the top of the ground is made of, as measured by satellites. <b>Display only: these indicators are never used in any score or ranking.</b></p>
    <ul><li><b>MODIS emissivity e29</b> (8.55 µm, Terra MOD21A2, ${esc(sample.modis || '')}): quartz and sulfate (gypsum) give off less heat at this wavelength, so a low e29 means a quartz- or sulfate-rich surface and a high e29 basalt-like rock, clay or carbonate. Site value: a 3 × 3 pixel window (about 2.8 km); boxes: all 1 km pixels in the box.</li>
      <li><b>Sentinel-2</b> (${esc((sample.s2Dates || []).join(' to '))}, up to 3 clear pictures, 60 m around the site): iron ratio red ÷ blue (rust-coloured iron oxides), 1.6 ÷ 2.2 µm ratio (clay, carbonate and sulfate), brightness, and a plant check (NDVI above 0.3 = not interpreted).</li>
      <li><b>ASTER silica index</b> (${esc((sample.asterYears || []).join('–'))}, 90 m, about 450 m around the site): more silica gives a larger index. Not corrected for the air, so it is <b>relative only</b>: compare sites with each other, not with laboratory values.</li>
      <li><b>NASA EMIT minerals</b> (when data/emit.json is present): the most common mineral match in a 300 m window over up to 5 clear passes, and in how many passes it agrees. Discover boxes show the match in a 1 km window at the box centre from the clearest pass (data/screening_emit.json).</li></ul>
    <p><b>Reading.</b> From MODIS e29 only: below ${E29_LOW} = "quartz- or sulfate-rich surface", above ${E29_HIGH} = "low-silica surface (basalt-like, clay or carbonate)", otherwise "mixed"; not interpreted where Sentinel-2 sees plants or open water. The cut values are ours. We looked at these same 19 sites when we set them, so the readings and the Jordan checks are illustrations, not independent tests. A reading describes the top fraction of a millimetre and never names a rock. For the 5 Jordan sites the reading is compared with the rock type on our map (agrees, partly or differs, with the reason).</p>
    <div class="scroll-x"><table class="facts"><thead><tr><th>Site</th><th>e29</th><th>Reading</th><th>ASTER silica (relative)</th><th>Flags</th><th>Jordan check</th></tr></thead><tbody>${rows}</tbody></table></div>
    <details><summary>Exact rules (from data/composition.json)</summary><p>${esc(ru.modis || '')}</p><p>${esc(s2.feRatio || '')} ${esc(s2.swirRatio || '')} ${esc(s2.brightness || '')} ${esc(s2.ndvi || '')}</p><p>${esc(s2.method || '')}</p><p>${esc(ru.aster || '')}</p><p>${esc(ru.reading || '')}</p><p>${esc(ru.thresholds || '')}</p><p>${esc(ru.jordanCheck || '')}</p></details>`;
}

// Credits for the satellite data of the "Measured from orbit" card. Licence wording checked on 2026-10-10 against
// the pages the data files link: the LP DAAC policy URL redirects to NASA Earthdata's data use guidance (CC0 for
// NASA-led missions); the ASTER L1T catalog page says "openly shared, without restriction"; the Sentinel legal
// notice asks for "Contains modified Copernicus Sentinel data [Year]".
function orbitCredits() {
  const d = state.data;
  const items = [];
  const earthdata = 'https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance';
  if (d.lstDoc) {
    const p = d.lstDoc.product || {};
    items.push(`<li>Surface temperature: NASA MODIS MOD21A2 and MYD21A2 v061 (NASA LP DAAC), via Microsoft Planetary Computer · ${doiLinks(p.dois)} · ${link(earthdata, 'CC0 (NASA Earthdata data use guidance)')}${(p.citation || []).map((c) => `<div class="src" ${WRAP}>${esc(c)}</div>`).join('')}</li>`);
  }
  if (d.compositionDoc) {
    const by = Object.fromEntries((d.compositionDoc.sources || []).map((x) => [x.id, x]));
    const years = s2YearRange(d.compositionDoc);
    if (by.mod21a2) items.push(`<li>Emissivity: MODIS MOD21A2 v061 band 29 · ${doiLinks([by.mod21a2.doi])} · ${link(earthdata, 'CC0 (NASA Earthdata data use guidance)')}<div class="src" ${WRAP}>${esc(by.mod21a2.credit || '')}</div></li>`);
    if (by['sentinel-2-l2a']) items.push(`<li>Sentinel-2 L2A (${link(by['sentinel-2-l2a'].url, 'Earth Search on AWS Open Data')}) · ${doiLinks([by['sentinel-2-l2a'].doi])} · ${link('https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice', 'Copernicus Sentinel data legal notice (free, full and open)')}<div class="src">Contains modified Copernicus Sentinel data ${esc(years)}</div></li>`);
    if (by['aster-l1t']) items.push(`<li>ASTER L1T v003 (NASA/METI/AIST/Japan Spacesystems and U.S./Japan ASTER Science Team; NASA LP DAAC), via Microsoft Planetary Computer · ${doiLinks([by['aster-l1t'].doi])} · ${link('https://www.earthdata.nasa.gov/data/catalog/lpcloud-ast-l1t-003', 'openly shared without restriction (EOSDIS Data Use and Citation Guidance)')}<div class="src" ${WRAP}>${esc(by['aster-l1t'].credit || '')}</div></li>`);
  }
  if (d.emitDoc) {
    const p = d.emitDoc.product || {};
    items.push(`<li>Minerals: NASA EMIT L2B minerals and L2A masks (NASA LP DAAC) · ${doiLinks(p.dois)} · ${link(p.licenceUrl || earthdata, 'CC0 (NASA Earthdata data use guidance)')}</li>`);
  }
  return items.join('');
}

// Honest limits. Lists and counts are computed from the data files, so they stay true when the data changes.
function limitsList() {
  const d = state.data;
  const items = ['Climate alone barely separates desert sites (several tie within 1 %). That is why terrain, geology and field measurements matter.',
    'Mean temperature and daily swing compare Earth air (NASA POWER T2M and T2M_RANGE, 2 m above the ground) with surface or ground temperatures on the Moon and at the Mars targets measured from orbit (see "How the score works"). At Jezero the coldest value is air too (MEDA). The Ground surface switch in Tune factors uses MODIS surface temperature instead: clear-sky only, its mean is about 2–3 K warmer than a 24 h mean and its swing catches about 88 % of the daily range.',
    'Gravity, vacuum, radiation and the thin Martian air cannot be reproduced anywhere on Earth, so they are not scored and every analog breaks there. Dust storms are not scored either: we have no dust measurement for the Earth sites.',
    'Base plan is a concept for future work: the layout of the base is ours, not a design. Its numbers (Moon and Mars facts, crop nutrients, signal delay) come from data/base.json and data/crops.json, each with a source, or are computed from them.',
    'The surface composition indicators (MODIS emissivity, Sentinel-2, ASTER, EMIT) are display only. Their reading cut values were set while looking at the same sites, so they illustrate rather than test.'];
  const thin = d.targets.filter((t) => targetGaps(t).length).map((t) => `${esc(t.name)}: ${pillarText(t)}`);
  if (thin.length) items.push(`Some targets have no data for whole pillars, so their full analog match uses fewer pillars. ${thin.join('; ')}.`);
  const lower = (f) => esc(EXTRA_FACTORS.includes(f) ? f.short : f.label.toLowerCase());
  for (const { t } of flatForAll()) {
    const { low, rest } = factorSpread(t);
    // Rock type and resources only count when the target has data for them.
    const gaps = targetGaps(t);
    const other = [['geology', 'rock type'], ['resources', 'resources']].filter(([id]) => !gaps.includes(id)).map(([, word]) => word);
    items.push(`For ${esc(t.name)} the landing pillar is 100 % for every site with terrain data (see "Landing-zone pillar")${low.length ? `, and ${andList(low.map(lower))} score under 10 % at every site` : ''}. So in the full analog match its ranking comes down to ${andList([...rest.map(lower), 'slope', ...other])}.`);
  }
  const full = { mode: 'full', terrain: d.terrain, resources: d.resources };
  const brief = (name) => esc(name.split(' (')[0].split(',')[0]);
  // Permanent Moon base sites: pillars used, and the best climate match at any Earth site (default weights, air).
  const bases = d.targets.filter((t) => t.group === 'moon-base');
  if (bases.length) {
    const used = [...new Set(bases.map(pillarText))].join(' / ');
    const best = Math.max(...bases.flatMap((t) => d.sites.map((s) => climateBreakdown(s, t).score ?? 0)));
    // Climate factors that still separate the sites for at least one base site (the others score under 10 % everywhere).
    const spread = bases.map(factorSpread);
    const rest = [...new Set(spread.flatMap((x) => x.rest))];
    const low = [...new Set(spread.flatMap((x) => x.low))].filter((f) => !rest.includes(f));
    items.push(`Permanent Moon base sites: ${andList(bases.map((t) => esc(t.name)))}. Their full match uses ${used}, and their climate match is ${pct(best)} % or less at every Earth site${low.length ? ` (${andList(low.map(lower))} score under 10 % everywhere)` : ''}, so their rankings come down to ${andList(['slope', 'the flat landing zone', ...rest.map(lower)])}. NASA's other Artemis III candidate regions (for example Haworth, Nobile Rim and Slater Plain) are not scored: we found no NASA or USGS point for them. The app draws the Artemis III regions on the Moon only when Cesium ion sends them; for our token it answered "not found" (error 404) on 14 October 2026.`);
    if (bases.some((t) => (t.facts || []).some((f) => f.source === 'lola-illumination'))) {
      items.push(`The LOLA sunlit share, Earth visibility and distance to permanent shadow of the base sites are shown as facts but not scored: every Earth site in our list has the Sun up 50.5–51.7 % of the year (standard sunrise equation, scripts/check_scores.py), so the share would not separate them; Earth visibility has no Earth counterpart; and permanent shadow is where ice can stay, not detected ice. The scored stand-in is Sun height (see "How the score works").`);
    }
  }
  // Terrain and landing zone come from the same slope grid: for the flattest targets many sites score high on both.
  if (d.terrain) {
    const zone = Math.max(...d.targets.map((t) => d.terrain[t.id]?.max_flat_square_km ?? 0));
    const flat = d.targets.filter((t) => d.terrain[t.id]?.max_flat_square_km === zone);
    const both = [...new Set(flat.map((t) => rankSites(d.sites, t, full).filter((r) => r.terrain && r.landing?.score === 1 && r.terrain.score >= 0.8).length))];
    const withTerrain = d.sites.filter((s) => !s.terrainExclude && d.terrain[s.id]).length;
    const jz = d.targets.find((t) => t.id === 'jezero');
    // Landing weight 0: the top 3 for Jezero, plus any site that ties the 3rd one (same %, shared rank).
    const nl = jz ? rankSites(d.sites, jz, { ...full, pillars: { landing: 0 } }).filter((r) => r.score != null) : [];
    const noLanding = nl.filter((r) => nl.length > 2 && pct(r.score) >= pct(nl[2].score)).map((r) => `${brief(r.site.name)} (${pct(r.score)} %)`);
    if (flat.length) items.push(`Terrain and landing zone both come from the same slope grid. For the flattest targets (largest flat zone ${esc(zone)} km: ${andList(flat.map((t) => brief(t.name)))}), ${both.length === 1 ? both[0] : `${Math.min(...both)}–${Math.max(...both)}`} of the ${withTerrain} sites with terrain data get 100 % on landing and at least 80 % on terrain, so flat ground counts in two of the five pillars.${noLanding.length ? ` With the landing weight set to 0, the top of the list for ${esc(jz.name)} becomes ${andList(noLanding)}.` : ''} The Stability check shows how often each site stays in the top 3 when the weights change.`);
  }
  // McMurdo Dry Valleys: its terrain box is steep, so it ranks low for the flat Mars ice targets.
  const dv = d.sites.find((s) => s.id === 'dry-valleys');
  const dvT = d.terrain?.['dry-valleys'];
  const iceMars = d.targets.filter((t) => t.body === 'mars' && (d.resources?.[t.id] || []).includes('ice'));
  if (dv && dvT && iceMars.length) {
    const ranks = iceMars.map((t) => { const r = rankSites(d.sites, t, full); return displayRanks(r)[r.findIndex((x) => x.site.id === dv.id)]; });
    items.push(`${esc(dv.name)}: the 10 km terrain box around our point is mostly steep ground (median slope ${fmt(dvT.median_slope_deg, 2)}°, largest flat zone ${fmt(dvT.max_flat_square_km, 1)} km). Against the flat Mars ice targets (${andList(iceMars.map((t) => brief(t.name)))}) it ranks ${Math.min(...ranks) === Math.max(...ranks) ? Math.min(...ranks) : `${Math.min(...ranks)}–${Math.max(...ranks)}`} of ${d.sites.length}: the terrain and landing pillars describe the steep ground in the box, not the flat valley floors, and no point on a valley floor has been measured.`);
  }
  const sp = d.targets.find((t) => t.id === 'southpole');
  if (sp) items.push(`${esc(sp.name)}: the pin is a permanently shadowed crater floor, but its reference values from the brief are general figures (sunlit polar rims for the mean temperature, shadowed craters in general for the coldest ground, the whole Moon for albedo). Strict data uses only values measured at the pin.`);
  const weak = flaggedTargets().map((t) => esc(t.name));
  if (weak.length) items.push(`Targets with ⚑ (${andList(weak)}) have fewer than ${TARGET_MIN_MEASURED} of the 5 factors measured at the site itself. Their other reference values are Moon-wide or Mars-wide figures or general statements.`);
  items.push('Some target values are approximate: Gale\'s mean temperature uses the Mars global mean until a Gale-specific value is sourced; swing and albedo for Gale are midpoints of measured ranges.');
  const gaps = flaggedSites().map(({ s, q }) => `${esc(s.name)} (${fmt(Math.abs(q.gap), 0)} m)`);
  items.push(`NASA POWER cells are about 50 km wide: small places (a crater floor, a cave, the Dead Sea shore) have their own microclimate, and a cell's average height can be far from the site's. Gaps over ${CELL_GAP_LIMIT_M} m today: ${andList(gaps) || 'none'} (⚑ in the ranking). The field kit's NASA POWER cell for Amman is at 164 m (data/raw/power/amman.json), far below the city (700–1100 m, firmware/PROTOCOL.md), so a kit in the city should read cooler than that cell. The kit panel shows this with a ⚑ (the same ${CELL_GAP_LIMIT_M} m rule).`);
  const noted = d.sites.filter((s) => (s.caveats || []).length).map((s) => esc(s.name));
  if (noted.length) items.push(`These sites have a note about their data, shown on the site's page: ${andList(noted)}.`);
  items.push('The Earth sites come from published analog research plus our own proposals (marked Candidate). They were chosen first and then scored, so this is not a search of the whole Earth.');
  items.push('Discover Jordan searches Jordan only, with 10 km boxes. Every box is a screening candidate: found by data, not field-checked, and not checked for access, protected or military areas, border zones or landmines.');
  items.push('Discover Jordan boxes have no resources data, so that pillar is left out and a box % can only be compared with a site % that also leaves resources out. The 1:5 million geology map cannot show small rock bodies, and many boxes share one NASA POWER cell, so neighbouring boxes often have the same climate. See "Discover Jordan" above.');
  for (const s of d.sites.filter((x) => x.terrainExclude)) items.push(`${esc(s.name)} has no terrain or landing-zone score. ${esc(s.terrainExclude)}`);
  items.push('Geology is a match level we assign by hand (1, 0.5 or 0), not a measurement. Resource tags come from published sources, which often describe a whole region rather than the exact pin; each tag links its source.');
  items.push('Earth values are 20-year averages or 20-year extremes; target values come from missions with different durations and instruments.');
  const step = d.terrainDoc?.method?.grid?.spacing_m;
  items.push(`Slope depends on the grid size; we use the same ${step ? esc(Math.round(step)) : '500'} m grid on all three worlds, but the elevation data underneath is sharper on Earth than on the Moon and Mars.`);
  items.push('Lighting is a display choice: the far view puts the Sun at 13:00 local time over Jordan; Earth close-ups show the satellite photos as taken (no extra day/night shading); on the Moon and Mars close-ups use a fixed Sun 30° above the horizon. Around the lunar south pole the 3D Moon has a darker, less sharp square and a straight seam (the 0°/180° line of the mosaic): both are in the Cesium Moon imagery itself (photos taken in low sunlight), not added by the app, so the Moon base view looks at the pole from the side.');
  const pano = d.panoramas?.panoramas || [];
  const views = pano.filter((p) => p.kind !== 'photo');
  const partial = views.filter((p) => (Number(p.haov) || 360) < 360).map((p) => Math.round(Number(p.haov)));
  const orbit = pano.filter((p) => p.kind === 'photo' && fromOrbit(p)).map((p) => esc(nameOf(p.target)));
  if (views.length) items.push(`Of the ${views.length} panoramas, ${views.length - partial.length} are full 360° views${partial.length ? `; the other ${partial.length} are partial views (${Math.min(...partial)}–${Math.max(...partial)}° wide), and their button gives the width` : ''}.`);
  items.push(`Only "Stand here · 3D terrain" is rendered from elevation data. "360° photo", "panorama", "Photo" and "Street View" all show real photographs${orbit.length ? ` (for ${andList(orbit)}, "Photo" shows a photo taken from orbit, not from the ground)` : ''}. Street View needs internet.`);
  items.push('The field kit is a prototype. Without a connected kit or a loaded log, its values are simulated, and they are always labelled "Simulated".');
  return `<ul>${items.map((x) => `<li>${x}</li>`).join('')}</ul>`;
}

// The criteria of the challenge statement, and how Analog Atlas answers each one (also in README section 3).
function challengeCriteria() {
  const rows = [
    ['Geology', 'Covered', 'Geology pillar: the main rock type of each site against the target (same rock 1, same family 0.5, else 0), every rock with a published source.'],
    ['Mineral presence', 'Covered', 'Resources pillar: sourced tags such as ice, salts and lava-tube shelter. Surface composition from orbit (EMIT minerals, ASTER and MODIS emissivity, Sentinel-2) is shown on each site page, display only.'],
    ['Temperature', 'Covered', 'Climate pillar: mean temperature, daily swing and coldest ground (NASA POWER on Earth; LRO Diviner, Mars Climate Sounder, MEDA, REMS, Phoenix on the targets). MODIS ground surface temperature as a switch. The ESP32 field kit measures air, ground and soil on site.'],
    ['Illumination', 'Partly', 'Scored: albedo, and for the three Moon base sites the highest Sun in the sky. Shown but not scored: LRO LOLA sunlit share, Earth in view and distance to permanent shadow at the base sites, because no Earth site has polar-Moon light (every site has the Sun up about half the time).'],
    ['Volcanic terrain', 'Covered', 'Basalt sites (for example Harrat al-Shaam, Craters of the Moon, Holuhraun) are scored against volcanic targets: the Arsia Mons skylight, the Mare Tranquillitatis pit, Apollo 11 and Apollo 17.'],
    ['Underground environments', 'Covered', 'Two cave targets (the Mare Tranquillitatis pit on the Moon, the Arsia Mons skylight on Mars). Lava tubes on Earth earn the "shelter" resource. Nobody has measured inside these caves, so their values describe the surface around the opening.'],
    ['Dust storms', 'Not scored', 'We have no dust-storm measurement for the Earth sites, so dust is not a factor. It appears only in the target notes (for example the UV drop during a dust storm measured by Perseverance).'],
    ['A place to test equipment for a base', 'Covered', 'Landing-zone pillar (largest flat square in a 10 km box), "Stand here" in 3D, the ESP32 field kit for a test day at the site, and Base plan: a 3D concept test base that lists what the site can practise for the chosen target (future work).'],
    ['Topography', 'Covered', 'Terrain pillar: slope statistics over a 10 km box on the same 500 m grid on all three worlds (Copernicus DEM, LRO LOLA, MGS MOLA).'],
    ['Gravity, radiation, vacuum', 'Cannot be reproduced', 'No place on Earth has low gravity, vacuum or Moon or Mars radiation, and Mars air pressure is under 1 % of Earth’s. They are not scored for any site; every analog breaks here. Gravity maps (GRAIL) are therefore not used.'],
    ['Where it works, how well, where it does not', 'Covered', 'Every result gives a %, the score of each pillar, the weak pillars, a ⚑ when data is weak, and the Limits list.'],
    ['Search Earth for unrecognised analogs', 'Partly', 'Discover Jordan scores all of Jordan in 886 boxes of 10 km with the same method. It is a screening of Jordan only, not of the whole Earth, and no box is field-checked yet.'],
  ].map(([a, b, c]) => `<tr><td>${esc(a)}</td><td><b>${esc(b)}</b></td><td>${esc(c)}</td></tr>`).join('');
  return `<p>The challenge asks where an analog works, how well, and where it does not. This is how each criterion is handled.</p>
    <div class="scroll-x"><table class="facts"><thead><tr><th>Challenge criterion</th><th>Status</th><th>How Analog Atlas handles it</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// The resources listed on the challenge page (Resources tab, read on 13 November 2026), and what we really use.
function challengeResources() {
  const rows = [
    ['NASA Earthdata Search', 'Yes, its catalog: EMIT minerals found through NASA CMR (the search behind Earthdata Search) with an Earthdata Login; MODIS surface temperature (NASA LP DAAC) read from the Microsoft Planetary Computer copy'],
    ['NASA Worldview', 'Its image service: the Earth globe uses NASA GIBS, the service Worldview runs on (Blue Marble, Black Marble)'],
    ['NASA PDS', 'Yes: LROC NAC mosaics, LOLA illumination maps, Diviner polar temperatures, MGS TES albedo, Mars cave catalog MGC3'],
    ['NASA LRO (LROC, LOLA, Diviner, LEND, Mini-RF)', 'Yes: LOLA elevation (through NASA Solar System Treks) and illumination, LROC photos, Diviner temperatures. LEND and Mini-RF data are not used'],
    ['NASA LRO Diviner Lunar Data', 'Yes: temperatures of the 3 base sites and the Shackleton crater floor'],
    ['CSA RADARSAT Constellation, RADARSAT-1, SAR Python tutorial', 'No'],
    ['ESA Copernicus Data Space Ecosystem', 'The same data by another route: Copernicus DEM GLO-90 (through Open-Meteo and the AWS copy) and Sentinel-2 (through Microsoft Planetary Computer)'],
    ['ESA Open Science Catalog', 'No'],
    ['JAXA G-Portal', 'No'],
  ].map(([a, b]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join('');
  return `<p>The challenge page lists these resources. What we use, and how. Earth climate comes from NASA POWER, which is not on the list.</p>
    <div class="scroll-x"><table class="facts"><thead><tr><th>Challenge resource</th><th>How Analog Atlas uses it</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function dataFiles() {
  const d = state.data;
  const opt = (path, present) => (present ? link(path) : esc(path));
  return `<ul><li>${link('data/sites.json')} (built by scripts/build_data.py from ${link('data/sites_meta.json')} and the raw NASA POWER responses in data/raw/power/, downloaded by scripts/fetch_power.py)</li>
      <li>${link('data/targets.json')} (Moon and Mars values with all their sources) · ${link('data/power_parameters.json')} (official NASA POWER definitions)</li>
      <li>${link('data/diviner_malapert.json')} (LRO Diviner temperatures, made by scripts/extract_diviner.py; raw windows in data/raw/diviner/) · ${link('data/illumination.json')} (LRO LOLA sunlight, Earth-in-view and permanent-shadow values at the base-site pins, made by scripts/extract_illumination.py; 5 × 5 windows and sources in ${link('data/raw/illumination/README.txt', 'data/raw/illumination/')}) · ${link('data/raw/mars_ez_research.json')} (Mars landing-zone research; extraction scripts in data/raw/mars_ez_extract/)</li>
      <li>${opt('data/terrain.json', d.terrainDoc)} (made by scripts/compute_terrain.py from ${link('data/terrain_points.json')}) · ${opt('data/resources.json', d.resourcesDoc)}</li>
      <li>${opt('data/panoramas.json', d.panoramas)} · ${link('data/streetview.json')} · ${opt('data/assets.json', d.assets)} (every downloaded file with its licence and any changes we made)</li>
      <li>data/raw/removed/: files of the removed sites (Mauna Kea and the Al-Fahda cave), kept so the removal can be checked (${link('data/raw/removed/README.txt', 'README.txt')})</li>
      <li>${link('data/screening_jordan.json')} (Discover Jordan: every 10 km box, built by scripts/build_screening.py) · ${link('data/screening_rockmap_igme5000.json')} (IGME5000 map unit to rock type) · data/raw/screening/: the raw files every box number comes from (${link('data/raw/screening/README.txt', 'README.txt')})</li>
      <li>Rebuild the boxes, in this order: <code>python -I scripts/screening_grid.py</code>, <code>screening_power.py</code>, <code>screening_terrain.py</code>, <code>screening_geology.py</code>, <code>build_screening.py</code>. The big downloads stay outside the project, in a cache folder.</li>
      <li>${opt('data/lst.json', d.lstDoc)} and ${link('data/screening_lst.json')} (MODIS surface temperature of the sites and the boxes, built by scripts/fetch_lst.py; ${link('data/raw/lst/README.txt', 'data/raw/lst/README.txt')}) · ${opt('data/composition.json', d.compositionDoc)} and ${link('data/screening_composition.json')} (surface composition, built by scripts/fetch_composition.py; ${link('data/raw/composition/README.txt', 'data/raw/composition/README.txt')})${d.emitDoc ? ` · ${link('data/emit.json')} (NASA EMIT minerals, built by scripts/fetch_emit.py)` : ''}</li>
      <li>${link('data/base.json')} (Base plan: Moon and Mars facts, crops, communication room, each with its source) · ${link('data/crops.json')} (USDA FoodData Central nutrients, built by scripts/fetch_crops.py from the raw records in data/raw/crops/) · signal delay and solar conjunction: js/orbits.js (JPL approximate planet positions)</li>
      <li>Check the scores without a browser: <code>python -I scripts/check_scores.py</code></li></ul>`;
}

function creditsSection() {
  const d = state.data;
  const pano = d.panoramas?.panoramas || [];
  const assets = d.assets?.files || [];
  const changesOf = (file) => (assets.find((a) => a.path === file) || {}).processing;
  const panoRows = pano.map((p) => {
    const changes = changesOf(p.file);
    return `<tr><td>${esc(p.title || p.id)}<div class="src">${esc(viewKind(p))} · ${esc(nameOf(p.target))}</div></td><td ${WRAP}>${esc(p.credit)}</td><td>${p.licenceUrl ? link(p.licenceUrl, p.licence) : esc(p.licence)}</td><td ${WRAP}>${p.sourcePage ? link(p.sourcePage, 'source') : ''}${changes ? `<div class="src">Changes: ${esc(changes)}</div>` : ''}</td></tr>`;
  }).join('');
  const texRows = assets.filter((a) => a.path && a.path.startsWith('textures/')).map((a) => `<tr><td ${WRAP}>${esc(a.path)}</td><td ${WRAP}>${esc(a.credit || '')}</td><td>${a.licenceUrl ? link(a.licenceUrl, a.licence) : esc(a.licence || '')}</td><td ${WRAP}>${a.sourcePage ? link(a.sourcePage, 'source') : a.sourceUrl ? link(a.sourceUrl, 'source') : ''}${a.processing ? `<div class="src">${esc(a.processing)}</div>` : ''}</td></tr>`).join('');
  const street = Object.entries(d.streetview || {}).map(([id, sv]) => `${esc(nameOf(id))}: ${esc(sv.label)}`);
  const linkOuts = (d.panoramas?.linkOuts || []).map((l) => `${link(l.url, l.label)}`);
  return `<ul>
      <li>3D engine: ${link('https://cesium.com/platform/cesiumjs/', 'CesiumJS 1.145')} (Apache 2.0). 3D data streamed from ${link('https://cesium.com/platform/cesium-ion/', 'Cesium ion')}: Cesium World Terrain, Bing Maps Aerial imagery, Cesium Moon (LOLA, Kaguya and LROC data, NASA and USGS Astrogeology) and Cesium Mars (MOLA, HRSC, Viking, CTX and HiRISE data, NASA and USGS Astrogeology). On-screen credits are shown bottom right.</li>
      <li>Earth far view: NASA Blue Marble Next Generation and NASA Black Marble (VIIRS 2016), from ${link('https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api', 'NASA GIBS')}.</li>
      <li>Moon and Mars without 3D: ${link('https://trek.nasa.gov/', 'NASA Solar System Treks')} mosaics (LRO WAC, NASA/GSFC/Arizona State University; Viking MDIM 2.1, NASA/JPL/USGS).</li>
      <li>360° viewer: ${link('https://pannellum.org/', 'Pannellum')} (${link('vendor/pannellum/LICENSE', 'MIT')}). Fonts: ${link('https://github.com/IBM/plex', 'IBM Plex')} (${link('vendor/fonts/OFL.txt', 'SIL Open Font License 1.1')}), stored in vendor/fonts so they work offline.</li>
      ${street.length ? `<li>"Stand here · Street View": Google Street View, shown with Google's own keyless Maps embed. The imagery stays © Google and its contributors and is never copied into this app. It needs internet. Places: ${street.join(' · ')}.</li>` : ''}
      ${linkOuts.length ? `<li>Links that open Google Maps (↗, Google's imagery, link only): ${linkOuts.join(' · ')}.</li>` : ''}
      ${orbitCredits()}
      <li data-screening="credits">Discover Jordan boxes: loading their sources…</li>
    </ul>
    ${panoRows ? `<h4>Photos and panoramas</h4><table class="facts"><thead><tr><th>Photo</th><th>Credit</th><th>Licence</th><th>Source and changes</th></tr></thead><tbody>${panoRows}</tbody></table>` : ''}
    ${texRows ? `<h4>Offline globe pictures</h4><table class="facts"><thead><tr><th>File</th><th>Credit</th><th>Licence</th><th>Source</th></tr></thead><tbody>${texRows}</tbody></table>` : ''}`;
}

export function openMethod() {
  const d = state.data;
  const check = selfCheck();
  const factorRows = CLIMATE_FACTORS.map((f) => `<tr><td>${esc(f.label)}</td><td><b>${esc(f.power)}</b><div class="src">${esc(d.powerDefs?.[f.power]?.definition || '')}</div></td><td class="num">${f.R} ${esc(f.unit)}</td></tr>`).join('');
  // Extra factors (today only Sun height): computed from the latitude, used only by targets that have a value for it.
  const srcLink = (id) => { const s = d.sources?.[id]; return s ? link(s.url, s.label) : ''; };
  const users = (f) => d.targets.filter((t) => t.values[f.id]?.value != null).map((t) => esc(t.name.split(' (')[0]));
  const extraRows = EXTRA_FACTORS.map((f) => `<tr><td>${esc(f.label)}<div class="src">only for ${andList(users(f)) || 'no target'}</div></td><td><b>computed from latitude</b><div class="src">The highest the Sun gets above a flat horizon in a year: 90° − |latitude| + axial tilt, at most 90°. The same formula on both sides: Earth tilt ${SUN_TILT.earth}° (${srcLink('earth-factsheet')}), Moon tilt ${SUN_TILT.moon}° (${srcLink('moon-tilt')}). A low Sun is why high ground near the lunar south pole gets long sunlight; Earth sites near the poles have the lowest Sun.</div></td><td class="num">${f.R} ${esc(f.unit)}</td></tr>`).join('');
  const brief = BRIEF_TARGETS.map((id) => esc(nameOf(id)));
  // The brief called the Shackleton target "Lunar South Pole"; its reference values are unchanged.
  const briefName = ` The brief calls ${esc(nameOf('southpole'))} the "Lunar South Pole".`;
  const rechecked = Object.keys(EXPECTED).map((id) => esc(nameOf(id)));
  const own = d.targets.filter((t) => !BRIEF_TARGETS.includes(t.id)).map((t) => esc(t.name));
  const gaps = flaggedSites().map(({ s, q }) => `${esc(s.name)} (cell ${fmt(Math.abs(q.gap), 0)} m ${q.gap > 0 ? 'higher' : 'lower'})`);
  const body = `<div class="sheet-body method">
    <h3 class="label">The short answer</h3>${shortAnswer()}
    <h3 class="label">How the score works</h3>
    <p>For each factor whose target value was measured:</p>
    <p><span class="formula">factor score = max(0, 1 − |Earth value − target value| ÷ R)<br>climate match = Σ(weight × factor score) ÷ Σ weight</span></p>
    <p>Weights start at 1 and can be changed with <b>Tune factors</b>. A factor with no measured target value is left out (shown as "not measured").</p>
    <table class="facts"><thead><tr><th>Factor</th><th>Earth value (NASA POWER, official definition)</th><th>R</th></tr></thead><tbody>${factorRows}${extraRows}
      <tr><td>Rainfall target</td><td colspan="2">0 on the Moon and Mars: no liquid rain.</td></tr></tbody></table>
    <p class="src">NASA POWER climatology API v2.10, community RE, January 2001 – December 2020, grid cells about 50 km (weather 0.5° × 0.625°, sunlight values 1° × 1°). "Maximum" and "minimum" are the extreme hourly values in that period; the other values are averages.</p>
    <p><b>Mean temperature</b>: on Earth this is NASA POWER T2M, the air 2 m above the ground. On a target it is what was measured there. The Moon has no air, so Moon values are surface temperatures. On Mars, Perseverance measured the air at Jezero, while values measured from orbit (Mars Climate Sounder) are ground temperatures. The note next to each target value says which. Earth air and target ground are not the same thing, so treat this factor as approximate. The <b>Earth temperature</b> switch in Tune factors can use measured ground surface temperature instead (see "Surface temperature (MODIS)" below).</p>
    <p><b>Full analog match</b> = weighted average of five pillars: climate (above), terrain, landing zone, geology and resources (below). Default pillar weights are 1. A pillar that cannot be computed is left out: either the target has no data for it (for example a target whose rock type is not known) or the site has none (for example a site whose 10 km box is mostly lake). The ranking shows how many pillars were used (for example 4/5). A site needs at least ${FULL_MIN_PILLARS} of the ${PILLARS.length} pillars to get a full score; with fewer it gets no score ("not enough data"), so no rank rests on one or two pillars.</p>
    <p><b>Strong twins.</b> The ranking first lists, and pins on the globe, only the sites at 50 % or more (the line is our choice). <b>Show all</b> opens every site; the ranks always count all of them. When no site reaches 50 %, the panel says so, because that is a result too.</p>
    <h3 class="label">Self-check: reference rankings from the brief</h3>
    <p class="src">The brief also listed Mauna Kea (32 % for Jezero). We removed it: its NASA POWER grid cell is at 636 m, but the site point near the summit is at 4,169 m (Copernicus DEM). That gap of 3,533 m is far above our ${CELL_GAP_LIMIT_M} m ⚑ limit, so the cell's climate (mean air 20.9 °C) describes much lower ground, not the summit. Its files are kept in data/raw/removed/ (see ${link('data/raw/removed/README.txt', 'README.txt')}). All other reference values are unchanged.</p>
    <p>${check.ok ? '<span class="check">✓ All reference values are reproduced from the real data files.</span>' : '<span class="check fail">✗ Some reference values differ – see the table.</span>'}</p>
    ${check.html}
    <h3 class="label">Targets on the Moon and Mars</h3>
    <p>The target list has these groups:</p><ul>${groupsList()}</ul>
    <p>The brief gave reference values for four targets only: ${andList(brief)}.${briefName} For them the <b>reference value</b> is the brief's value (the self-check above re-runs the brief's rankings for ${andList(rechecked)}). For ${andList(own)}, the reference value is our own, from the source shown on each row. We checked every target value against its source (the dates are in data/targets.json).</p>
    <p>Where a reference value is not a measurement at the site itself (a Moon-wide or Mars-wide average, a midpoint of a range, or a general statement), the <b>strict data</b> column shows what measurements at the site support. Switch on <b>Strict data</b> in Tune factors to rank with those values. In strict mode a target needs at least ${STRICT_MIN_FACTORS} measured factors to get a climate score; in the full analog match its other pillars are still used.</p>
    <p><b>Cave targets.</b> The Mare Tranquillitatis pit (Moon) and the Arsia Mons skylight (Mars) are openings into probable lava-tube caves, proposed as natural shelters for a base. Nobody has measured inside them, so their scored climate values are the measured ground surface around the opening (LRO Diviner on the Moon, Mars Climate Sounder and TES on Mars). The model result of about 17 °C inside the Moon cave is shown as a fact, never scored. What makes them cave analogs is the shelter tag, basalt and terrain, so Earth sites with documented lava caves (Harrat al-Shaam, Craters of the Moon) can score the resources pillar.</p>
    ${targetsTable()}
    <h3 class="label">Earth sites (NASA POWER annual values)</h3>${sitesTable()}
    <h3 class="label">All sites against all targets</h3>${matrixSection()}
    <h3 class="label">Data-quality flag ⚑</h3>
    <p>For every Earth site we compare the elevation of its NASA POWER grid cell with the real ground elevation at the site (Copernicus DEM, data/terrain.json). If they differ by more than ${CELL_GAP_LIMIT_M} m (about ${fmt(CELL_GAP_LIMIT_M * 6.5 / 1000, 1)} °C at the standard lapse rate of 6.5 °C per km), the site gets a ⚑ in the ranking and a warning on its page: its climate values describe a wider area. Flagged sites stay in the ranking. Today: ${andList(gaps) || 'none'}. Mauna Kea, from the brief's list, had a gap far above this limit, so we removed it (see the self-check above).</p>
    <p>Targets get a ⚑ when fewer than ${TARGET_MIN_MEASURED} of the 5 factors are measured at the site itself (counting rain, which is physically zero on the Moon and Mars). Today: ${andList(flaggedTargets().map((t) => esc(t.name))) || 'none'}.</p>
    <h3 class="label">Surface temperature (MODIS)</h3>${lstSection()}
    <h3 class="label">Measured from orbit: surface composition</h3>${compositionSection()}
    <h3 class="label">Terrain pillar</h3>${terrainSection()}
    <h3 class="label">Landing-zone pillar</h3>${landingSection()}
    <h3 class="label">Geology pillar</h3>${geologySection()}
    <h3 class="label">Resources pillar</h3>${resourcesSection()}
    <h3 class="label">Stability check</h3>
    <p>Draws 1,000 random sets of weights (each between 0 and 2, fixed seed 2026) and counts how often each site stays in the top 3. It shows which twins are robust and which depend on our weight choices.</p>
    <h3 class="label">Discover Jordan: 10 km screening boxes</h3>
    <div data-screening="section"><p class="hint">Loading data/screening_jordan.json…</p></div>
    <h3 class="label">ESP32 field kit</h3>
    <ul><li>BME280: air temperature, humidity and pressure. Air temperature is compared with the target's mean temperature, and in the log table with NASA POWER T2M for the same month. Humidity and pressure are shown but not scored.</li>
      <li>MLX90614: ground surface temperature by infrared, the same principle as Curiosity's REMS and Perseverance's MEDA ground sensors. The lowest value in a log is compared with the target's coldest ground temperature.</li>
      <li>DS18B20: soil temperature with a probe ("Soil probe" in the kit bar; used for the coldest ground only when the infrared sensor is missing in more than 1 of 10 log readings, and then labelled, because a probe reads warmer than the surface at night). GUVA-S12SD: UV index (≈ output voltage ÷ 0.1 V), shown only: UV is not a score factor.</li>
      <li>Two BH1750 light sensors, one facing up and one down: albedo = reflected ÷ incoming light, only in daylight, compared with the target albedo. Visible light only, so it is an approximation.</li>
      <li><b>Snapshot score</b>: the same formula with the kit's values: air temperature and albedo now, daily swing and coldest ground once a 24-hour log is loaded. The kit does not measure rain. It is a single moment, not a 20-year average, so it is shown separately from the ranking. With a connected kit the panel calls it "Live snapshot score"; without one, "Simulated snapshot score".</li>
      <li><b>Log table</b>: the kit's daily mean air temperature and daily range next to NASA POWER T2M and T2M_RANGE for the same month at the kit location, to check that the kit gives realistic numbers.</li>
      <li><b>Simulated</b>: without a device the app shows simulated values made from NASA POWER monthly averages for the kit location plus a daily cycle. They are always labelled "Simulated".</li></ul>
    <h3 class="label">Limits</h3>${limitsList()}
    <h3 class="label">Challenge criteria</h3>${challengeCriteria()}
    <h3 class="label">Challenge resources used</h3>${challengeResources()}
    <h3 class="label">Data files</h3>${dataFiles()}
    <h3 class="label">Credits</h3>${creditsSection()}
    <h3 class="label">Use of Super Intelligence (SI)</h3>
    <p>SI tool used: Claude (Anthropic), a large language model. The code (app, scripts, tests, firmware) and the research notes were written with its help and reviewed by the team. The data is not SI-generated: every number comes from the cited data files or sources, not from the SI. The drawings, slide backgrounds and promo-video music were made by code written with Claude and carry an "SI-assisted" mark. Ask Atlas uses Claude at run time only on our computer with an API key, and marks those answers "Claude (SI)"; otherwise it answers with fixed rules over our data ("no SI"). See README section 10.</p>
  </div>`;
  const el = openOverlay({ title: 'Method & data', body });
  el.querySelector('[data-action="matrix-csv"]')?.addEventListener('click', downloadMatrix);
  fillScreening(el);
}
