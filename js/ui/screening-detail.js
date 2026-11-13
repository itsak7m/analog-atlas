// Detail panel for one 10 km screening box of Discover Jordan (design 4.4).
// The same layout as a site page, plus the screening label, the box's rank, its neighbours, caveats,
// the hand-picked Jordan sites for comparison and where every number comes from.
// Not shown for boxes: Twin view, panoramas and "What crews can test here".

import { state } from '../state.js';
import { ROCK_LABEL, R_SLOPE, SAFE_SLOPE_DEG, pct } from '../scoring.js';
import { esc, fmt, fmtCoord, BODY_LABEL, CELL_GAP_LIMIT_M, distanceKm, scoreColor } from '../util.js';
import { noScoreText, gapWords, strictDropsClimate } from './ranking.js';
import { setPanel, mbar, POWER_FACTS, srcLink, artemisLink } from './detail.js';
import { currentResult, screenDoc, nearText, containedSite, whyWords } from './discover.js';
import { findBox, neighbours, siteScoreNoResources, getScreening, SCREEN_LABEL } from '../screening.js';
import { earthCell, earthTempLine, orbitBoxHTML } from './orbit.js';

const shortName = (name) => String(name || '').split(',')[0].split(' (')[0];
const link = (url, text) => (url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));
const fileName = (path) => String(path).split('/').pop();
const latText = (v) => `${Math.abs(v)} ${v >= 0 ? 'N' : 'S'}`;
const lonText = (v) => `${Math.abs(v)} ${v >= 0 ? 'E' : 'W'}`;

// ---------- neighbour buttons ----------
const DIRS = [['N', 'North', '▲'], ['E', 'East', '▶'], ['S', 'South', '▼'], ['W', 'West', '◀']];

// N/E/S/W go to the next box in Jordan in that direction (neighbourBox skips cells outside Jordan).
function navHTML(box) {
  const next = neighbours(box);
  const btns = DIRS.map(([d, word, arrow]) => {
    const n = next[d];
    if (!n) return `<button type="button" class="btn small" data-dir="${d}" disabled aria-label="${word}: no more boxes in Jordan"><span aria-hidden="true">${arrow}</span> ${d}</button>`;
    const km = Math.round(distanceKm(box.lat, box.lon, n.lat, n.lon));
    return `<button type="button" class="btn small" data-action="go-box" data-id="${esc(n.id)}" data-dir="${d}" aria-label="${esc(`${word}: ${n.name}${km > 12 ? `, ${km} km away` : ''}`)}"><span aria-hidden="true">${arrow}</span> ${d}</button>`;
  }).join('');
  return `<div class="box-nav" role="group" aria-label="Next box"><span class="src">Next box</span>${btns}</div>`;
}

// ---------- climate source line ----------
// "NASA POWER regional, MERRA-2 cell 30.5 N 36.25 E (about 55 × 59 km, 937 m); albedo 1° CERES cell 30.5 N 36.5 E"
function climateSource(box, doc) {
  const { merra, syn } = box.power?.cells || {};
  const files = pathsOf(doc.climate?.rawFiles);
  let text = link(files.find((f) => /manifest/i.test(f)) || files[0], 'NASA POWER regional');
  if (merra) {
    const ns = distanceKm(merra.s, merra.lon, merra.n, merra.lon);
    const ew = distanceKm(merra.lat, merra.w, merra.lat, merra.e);
    const size = [ns, ew].every(Number.isFinite) ? ` (about ${Math.round(ns)} × ${Math.round(ew)} km, ${fmt(merra.elev_m, 0, 'm')})` : ` (${fmt(merra.elev_m, 0, 'm')})`;
    text += `, MERRA-2 cell ${esc(latText(merra.lat))} ${esc(lonText(merra.lon))}${size}`;
  }
  if (syn) text += `; albedo 1° CERES cell ${esc(latText(syn.lat))} ${esc(lonText(syn.lon))}`;
  return text;
}

// Raw files named in the data file: a path, a list of paths or an object of them (any depth).
function pathsOf(x) {
  if (!x) return [];
  if (typeof x === 'string') return [x];
  if (Array.isArray(x)) return x.flatMap(pathsOf);
  if (typeof x === 'object') return x.path || x.file ? [x.path || x.file] : Object.values(x).flatMap(pathsOf);
  return [];
}

// ---------- terrain and geology ----------
function shareText(share) {
  if (share == null) return '';
  return share > 1 ? `${share} of 25 points` : `${Math.round(share * 100)}% of the box`;
}

function rockCell(box, rec, doc) {
  const g = rec.geology || {};
  const u = g.unit != null ? (doc.geology?.units || {})[g.unit] : null;
  const main = box.geology?.primary
    ? esc(ROCK_LABEL[box.geology.primary] || box.geology.primary)
    : `<span class="src">${g.inferred ? `not used (low certainty; the map suggests ${esc(ROCK_LABEL[g.inferred] || g.inferred)})` : 'not mapped'}</span>`;
  const petro = [].concat(u?.petrography || []).filter(Boolean).join(', '); // empty for the water unit
  const unit = g.unit != null
    ? `<div class="src">IGME5000 unit ${esc(g.unit)}${petro ? `: ${esc(petro)}` : ''}${u?.age ? ` · ${esc(u.age)}` : ''}${g.share != null ? ` · ${esc(shareText(g.share))}` : ''}${g.certainty ? ` · certainty ${esc(g.certainty)}` : ''}</div>` : '';
  const why = !box.geology?.primary && g.why ? `<div class="src">${esc(g.why)}</div>` : '';
  return main + unit + why;
}

function terrainNote(rec) {
  if (rec.terrainExclude) return ` <b>${esc(rec.terrainExclude)}</b>`;
  return rec.terrain?.notes ? ` Note: ${esc(rec.terrain.notes)}.` : '';
}

function pillarsSection(box, rec, target, row, doc) {
  if (state.mode !== 'full') return '';
  const bt = (!rec.terrainExclude && rec.terrain) || {};
  const tt = (state.data.terrain || {})[target.id] || {};
  const notComputed = '<span class="src">not computed</span>';
  const slope = (x) => (x.median_slope_deg != null ? fmt(x.median_slope_deg, 1, '°') : notComputed);
  const flat = (x) => (x.max_flat_square_km != null ? `${fmt(x.max_flat_square_km, 1)} km` : notComputed);
  const g = row.geology;
  return `<div class="section"><span class="label">Terrain and geology</span>
    <table class="facts"><thead><tr><th>Pillar</th><th>This box</th><th>${esc(shortName(target.name))}</th><th>Match</th></tr></thead><tbody>
    <tr><td>Median slope</td><td class="num">${slope(bt)}</td><td class="num">${slope(tt)}</td><td class="match">${mbar(row.terrain ? row.terrain.score : null)}</td></tr>
    <tr><td>Largest flat zone (&lt;${SAFE_SLOPE_DEG}°)</td><td class="num">${flat(bt)}</td><td class="num">${flat(tt)}</td><td class="match">${mbar(row.landing ? row.landing.score : null)}</td></tr>
    <tr><td>Main rock</td><td>${rockCell(box, rec, doc)}</td><td>${target.geology?.primary ? esc(ROCK_LABEL[target.geology.primary] || target.geology.primary) : '<span class="src">not measured</span>'}</td><td class="match">${mbar(g ? g.score : null)}</td></tr>
    <tr><td>Resources</td><td colspan="2"><span class="src">not available for screening boxes (pillar left out)</span></td><td class="match">${mbar(null)}</td></tr>
    </tbody></table>
    <p class="src">${g ? `${esc(g.reason)}. ` : ''}Slope: 10 km box, 500 m grid, the same method as the sites; a ${R_SLOPE}° difference scores 0. Largest flat zone: side of the biggest square in the box where all ground is under ${SAFE_SLOPE_DEG}° (${artemisLink()}); a zone as large as the target's scores 1.${terrainNote(rec)}</p></div>`;
}

// ---------- caveats ----------
function caveatsHTML(box, rec, row) {
  const out = [];
  const flags = rec.flags || [];
  const q = row && row.gap;
  if (q && q.flagged) {
    out.push(`⚑ Data quality: the NASA POWER grid cell sits at ${fmt(q.cell, 0)} m, but the ground at the box centre is at ${fmt(q.ground, 0)} m (${fmt(Math.abs(q.gap), 0)} m ${q.gap > 0 ? 'higher' : 'lower'}; our limit is ${CELL_GAP_LIMIT_M} m). The climate values describe the wider area, so this box is left out of the Top 10. It stays ${flags.includes('water') ? 'in the table (mostly-water boxes are not drawn on the map)' : 'on the map and in the table'}.`);
  }
  if (flags.includes('water') || rec.terrainExclude) out.push(`${rec.terrainExclude ? esc(String(rec.terrainExclude).replace(/\.\s*$/, '')) : 'Water: most of this box is water'}. Terrain and landing zone are not scored here, and the box is not drawn on the map.`);
  else if (flags.includes('partWater')) out.push(`Part water: about ${fmt(rec.terrain?.water_pct, 0)}% of the box is lake or sea surface, which counts as flat ground.`);
  if (flags.includes('border')) {
    const share = typeof rec.inJordan === 'number' && rec.inJordan <= 1 ? `about ${Math.round(rec.inJordan * 100)}% of the box is inside the indicative boundary, and ` : '';
    out.push(`Border box: ${share}its centre is ${fmt(rec.borderKm, 1)} km from the border (Natural Earth, an indicative boundary).`);
  }
  const merra = box.power?.cells?.merra;
  if (flags.includes('climateCellMostlyOutside')) {
    out.push(`The NASA POWER cell of this box lies mostly outside Jordan${merra && typeof merra.inJordan === 'number' ? ` (${Math.round(merra.inJordan * 100)}% inside)` : ''}, so its climate mixes in neighbouring land or sea.`);
  }
  const straddles = rec.climate?.straddles || [];
  if (straddles.length || flags.includes('straddlesCellEdge')) {
    const which = straddles.map((s) => (s === 'syn' ? '1° albedo' : 'MERRA-2')).join(' and ');
    out.push(`The box crosses the edge of a NASA POWER ${which ? `${which} ` : ''}cell; its climate comes from the cell that holds the box centre.`);
  }
  // Full match against a target with a rock type: the geology pillar drops out of the average, which can raise the %.
  const noRock = row && row.score != null && (row.missing || []).includes('geology') ? ' Without a rock type its % uses fewer pillars, which can raise it, so this box is not listed for this target.' : '';
  if (flags.includes('lowCertaintyGeology')) out.push(`Rock type: the 1:5 million map gives this unit low certainty, so it is not used in the score.${noRock}`);
  else if (flags.includes('noGeology') && !flags.includes('water')) out.push(`Rock type: no rock type is mapped here${rec.geology?.why ? ` (${esc(String(rec.geology.why).replace(/\s*\(([^)]*)\)/, ': $1'))})` : ''}.${noRock}`);
  const site = containedSite(rec);
  if (rec.containsSite) out.push(`This box holds an Atlas site${site ? ` (${esc(site.name)})` : ''}, so it is not listed. See that site's own page.`);
  out.push('The elevation model is a surface model: buildings raise the slopes in towns.');
  out.push('Not checked for access, protection or safety. This is a screening result, not a field visit.');
  return out.map((c) => `<p class="caveat">${c}</p>`).join('');
}

// ---------- comparison with the hand-picked Jordan sites ----------
function comparable(target, result) {
  if (result && result.target?.id === target.id && result.sites) return result.sites;
  const d = state.data;
  const opts = { mode: state.mode, strict: state.strict, earthTemp: state.earthTemp, weights: state.weights, pillars: state.pillars, terrain: d.terrain, resources: d.resources };
  return d.sites.filter((s) => s.jordan).map((site) => {
    const res = siteScoreNoResources(site, target, opts);
    return { site, ...res, pct: pct(res.score) };
  }).sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
}

function compareHTML(rec, target, result, row) {
  const rows = comparable(target, result);
  if (!rows.length) return '';
  const same = new Set(rec.sameUnitAs || []);
  const items = rows.map((r) => `<li><button type="button" data-action="go-site" data-id="${esc(r.site.id)}" style="--c:${scoreColor(r.score)}"><span>${esc(r.site.name)}${same.has(r.site.id) ? ' <span class="src">same mapped rock unit</span>' : ''}</span><span class="pc">${r.score == null ? 'no score' : `${pct(r.score)}%`}</span></button></li>`).join('');
  const names = rows.filter((r) => same.has(r.site.id)).map((r) => shortName(r.site.name));
  // A box that lacks a pillar the target has (e.g. no rock type) is scored on fewer pillars than the sites.
  const fewer = state.mode === 'full' && row && row.score != null && row.missing && row.missing.length ? gapWords(row.missing) : '';
  const fair = row && row.score != null && !fewer;
  const note = state.mode === 'full'
    ? `Scored without the resources pillar, like the boxes${fair ? ', so these numbers can be compared with this box' : ''}. The site list includes resources, so it can show other numbers.${fewer ? ` This box has no ${fewer} data, so its % uses fewer pillars than these sites and cannot be compared with them one to one.` : ''}`
    : 'Climate match, the same as the site list.';
  return `<div class="section"><span class="label">For comparison · hand-picked Jordan sites</span><ul class="compare-sites">${items}</ul>
    <p class="src">${esc(note)}${names.length ? ` Same mapped rock unit (IGME5000) as ${esc(names.join(', '))}.` : ''}</p></div>`;
}

// ---------- where the numbers come from ----------

// The Copernicus DEM tiles under this box, when the file lists them ([{ name, url }] or { name: url }).
function tilesFor(doc, box) {
  const tiles = doc.terrain?.tiles;
  if (!tiles || typeof tiles !== 'object') return [];
  const list = Array.isArray(tiles) ? tiles : Object.entries(tiles).map(([name, t]) => ({ name, ...(typeof t === 'object' ? t : { url: t }) }));
  const b = box.bounds || { s: box.lat, n: box.lat, w: box.lon, e: box.lon };
  const pad = (v, n) => String(Math.abs(v)).padStart(n, '0');
  const keys = new Set();
  for (const lat of [b.s, b.n - 1e-9]) {
    for (const lon of [b.w, b.e - 1e-9]) {
      const a = Math.floor(lat);
      const o = Math.floor(lon);
      keys.add(`${a >= 0 ? 'N' : 'S'}${pad(a, 2)}_00_${o >= 0 ? 'E' : 'W'}${pad(o, 3)}_00`);
    }
  }
  return list.filter((t) => [...keys].some((k) => String(t.name || '').includes(k)));
}

function provenanceHTML(doc, box, rec) {
  const items = [];
  const c = doc.climate || {};
  const climateFiles = pathsOf(c.rawFiles);
  // Keep the merra/ or syn1deg/ folder in the name: both folders hold an ALLSKY_SRF_ALB.json.
  items.push(`Climate: ${climateFiles.length ? climateFiles.map((f) => link(f, String(f).replace(/^.*\/power\//, ''))).join(' · ') : 'NASA POWER regional'}${c.periodValidated ? `<span class="notice">${esc(c.periodValidated)}${c.periodLabel ? `. NASA labels the product: ${esc(c.periodLabel)}` : ''}</span>` : ''}`);
  const t = doc.terrain || {};
  const tiles = tilesFor(doc, box);
  const tileFile = typeof t.tiles === 'string' ? t.tiles : null;
  items.push(`Terrain: ${t.rawFile ? link(t.rawFile, fileName(t.rawFile)) : 'DEM samples'} (${esc(rec.terrain?.n_samples ?? 441)} samples for this box)${tiles.length ? ` · DEM ${tiles.length === 1 ? 'tile' : 'tiles'} ${tiles.map((x) => link(x.url, x.name)).join(', ')}` : ''}${tileFile ? ` · ${link(tileFile, fileName(tileFile))}` : ''}${t.dataset ? `<span class="notice">${esc(t.dataset)}${t.method ? ` · ${esc(t.method)}` : ''}</span>` : ''}`);
  const g = doc.geology || {};
  const doi = g.doi || g.DOI || null;
  const doiUrl = doi ? (String(doi).startsWith('http') ? doi : `https://doi.org/${doi}`) : null;
  items.push(`Geology: ${esc(g.citation || 'IGME5000')}${doiUrl ? ` · ${link(doiUrl, doiUrl.replace(/^https?:\/\//, ''))}` : ''}${g.rawFile ? ` · ${link(g.rawFile, fileName(g.rawFile))}` : ''}${g.sampling ? `<span class="notice">${esc(g.sampling)}</span>` : ''}`);
  const b = doc.boundary || {};
  if (b.source || b.url) items.push(`Boundary: ${link(b.url, b.source || 'Natural Earth')}${b.version ? ` ${esc(b.version)}` : ''}, an indicative boundary`);
  const sources = (doc.sources || []).map((s) => `<li>${link(s.url, s.label || s.id)}${s.version ? ` · ${esc(s.version)}` : ''}${s.accessed ? ` · accessed ${esc(s.accessed)}` : ''}${s.licence ? ` · ${link(s.licenceUrl, s.licence)}` : ''}${s.credit ? `<span class="notice">${esc(s.credit)}</span>` : ''}${s.notice && s.notice !== s.credit ? `<span class="notice">${esc(s.notice)}</span>` : ''}</li>`).join('');
  return `<div class="section"><span class="label">Where the numbers come from</span><ul class="links prov">${items.map((x) => `<li>${x}</li>`).join('')}</ul></div>
    ${sources ? `<div class="section"><span class="label">Sources, licences and notices</span><ul class="links prov">${sources}</ul></div>` : ''}`;
}

// ---------- the panel ----------

// Under the %: "4 of 5 pillars (no resources data)" and "rank =3 of 756 listed boxes" (or why it is not listed).
function scoreLines(row, result) {
  const lines = [];
  if (state.mode === 'full' && row.score != null && row.pillarsUsed != null) {
    const others = gapWords([...(strictDropsClimate(row) ? ['climate'] : []), ...(row.targetGaps || []).filter((g) => g !== 'resources'), ...(row.missing || [])]);
    lines.push(`${row.pillarsUsed} ${row.pillarsUsed === 1 ? 'pillar' : 'pillars'} (no resources data${others ? `; no data for ${others}` : ''})`);
  }
  if (row.eligible && row.rank != null) {
    // The Top 10 numbers its rows (clusters), so name the row too: "rank =24 of 760 listed boxes · Top 10 row =4".
    const c = result && row.cluster != null ? result.clusters[row.cluster] : null;
    const topRow = c && result.top.includes(c) ? ` · Top 10 row ${c.tie ? '=' : ''}${c.rank}` : '';
    lines.push(`rank ${row.tie ? '=' : ''}${row.rank} of ${result ? result.listed.length : '?'} listed boxes${topRow}`);
  } else if (row.why && row.why.length) {
    lines.push(`not in the list: ${row.why.map((w) => whyWords({ ...row, why: [w] })).join('; ')}`);
  }
  return lines.map((l) => `<br>${esc(l)}`).join('');
}

// Render one box. box: a box shaped like a site (boxToSite in js/screening.js) or its id;
// row: its row from scoreBoxes() (the scoreSite result plus rank, why, gap, …), found by id when omitted.
export function renderBox(box, target, row) {
  if (typeof box === 'string') box = findBox(box);
  if (!box) return;
  const result = currentResult();
  row = row || (result && result.byId.get(box.id)) || null;
  const el = document.getElementById('detail');
  const doc = screenDoc() || {};
  const rec = box.screen || {};
  el.hidden = false;
  document.body.classList.add('sheet-detail');
  const score = row ? row.score : null;
  const modeText = state.mode === 'full' ? 'full analog match' : 'climate match';
  const inCloseup = state.view !== 'globe';
  const holds = containedSite(rec);
  const near = nearText(rec);
  const title = near || box.name; // same name as in the Top 10 list

  const factors = row ? row.climate.rows.map((r) => {
    const f = r.factor;
    return `<tr>
      <td>${esc(f.short)}${r.weight !== 1 ? ` <span class="src">×${r.weight.toFixed(1)}</span>` : ''}</td>
      <td class="num">${earthCell(r)}</td>
      <td class="num">${r.target == null ? '<span class="src">not measured</span>' : fmt(r.target, f.digits, f.unit)}</td>
      <td class="match">${mbar(r.score)}</td></tr>`;
  }).join('') : '';
  const targetSources = row ? [...new Set(row.climate.rows.map((r) => r.source).filter(Boolean))].map(srcLink).join(' · ') : '';
  const annual = box.power?.annual || {};
  const facts = POWER_FACTS.map(([key, label, digits, unit]) => `<tr><td>${esc(label)}</td><td class="num">${fmt(annual[key], digits, unit)}</td></tr>`).join('');

  // Stepping with N/E/S/W keeps focus on the same direction button, so the keyboard can walk the grid.
  const focusDir = el.contains(document.activeElement) ? document.activeElement.dataset.dir : null;
  setPanel(el, `
    <button type="button" class="btn small close" data-action="close" aria-label="Close details">✕</button>
    <div class="kicker"><span class="tag screen">Screening box</span><span class="tag jo">Jordan</span><span class="body-chip earth">Earth</span></div>
    <h2 class="title" tabindex="-1">${esc(title)}</h2>
    <p class="where">${near ? `${esc(box.name)} · ` : ''}${esc(fmtCoord(box.lat, box.lon))} · 10 km box${holds ? ` · holds ${esc(shortName(holds.name))}` : ''}</p>
    <p class="screen-label">${esc(doc.label || SCREEN_LABEL)}</p>
    <div class="scorebox"><span class="big">${score == null ? '<small>no score</small>' : `${pct(score)}<small>%</small>`}</span>
      <span class="of">${esc(modeText)} with<br><b>${esc(target.name)}</b> · ${esc(BODY_LABEL[target.body])}${row ? scoreLines(row, result) : ''}</span></div>
    ${score == null && row ? `<p class="caveat">${noScoreText([row], target).replace('no site gets a score', 'no box gets a score')}</p>` : ''}
    <div class="actions" style="margin-top:0">
      ${inCloseup ? '<button type="button" class="btn" data-action="back">Back to globe</button>' : '<button type="button" class="btn primary" data-action="fly">Fly down</button>'}
      <button type="button" class="btn" data-action="stand">Stand here · 3D terrain</button>
    </div>
    ${navHTML(box)}
    ${row ? `<div class="section"><span class="label">Factor by factor</span>
      <table class="facts"><thead><tr><th>Factor</th><th>This box</th><th>${esc(shortName(target.name))}</th><th>Match</th></tr></thead><tbody>${factors}</tbody></table>
      <p class="src">Earth: ${climateSource(box, doc)}. Target: ${targetSources}</p>
      ${earthTempLine('box')}
    </div>` : ''}
    ${row ? pillarsSection(box, rec, target, row, doc) : ''}
    ${orbitBoxHTML(box, getScreening())}
    <div class="section"><span class="label">Caveats</span>${caveatsHTML(box, rec, row)}</div>
    ${compareHTML(rec, target, result, row)}
    <div class="section"><span class="label">Climate facts · NASA POWER</span>
      <table class="facts"><tbody>${facts}</tbody></table>
      <p class="src">For the whole climate cell, not only this box. Highest/lowest values are the extreme hourly values in 2001–2020; the others are 20-year averages.</p></div>
    ${provenanceHTML(doc, box, rec)}`);
  if (focusDir) {
    const b = el.querySelector(`[data-dir="${focusDir}"]:not([disabled])`);
    if (b) b.focus({ preventScroll: true });
  }
}
