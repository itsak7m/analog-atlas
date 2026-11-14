// "Measured from orbit": what satellites measured at an Earth site or a Discover box, shown on its page.
//   Surface temperature: NASA MODIS MOD21A2 / MYD21A2 (data/lst.json, data/screening_lst.json). It is used in the
//   score only when Earth temperature is set to "Ground surface" in Tune factors.
//   Surface composition: MODIS band-29 emissivity, Sentinel-2 ratios, ASTER silica index (data/composition.json,
//   data/screening_composition.json) and, when data/emit.json exists, NASA EMIT minerals. Display only, never scored.
// Every number is read from those files; nothing here is computed except the box reading (same cut values).

import { state } from '../state.js';
import { LST_FIELD, SUN_TILT } from '../scoring.js';
import { esc, fmt } from '../util.js';

const link = (url, text) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>`;
const doiLink = (doi) => (doi ? link(`https://doi.org/${doi}`, `doi:${doi}`) : '');
// 0.998 -> "99.8%" (a share just below 1 is not rounded up to 100%).
const pctText = (share) => (share == null ? 'not measured' : `${share >= 1 ? 100 : fmt(Math.floor(share * 1000) / 10, 1)}%`);
const count = (n) => (n == null ? '?' : Number(n).toLocaleString('en'));
const yearOf = (date) => String(date || '').slice(0, 4);

// The reading cut values of data/composition.json (rules.reading): e29 below 0.88 = quartz- or sulfate-rich,
// above 0.95 = low-silica. Used here only for the boxes, which have no reading of their own.
export const E29_LOW = 0.88;
export const E29_HIGH = 0.95;
export function e29Reading(e29) {
  if (e29 == null) return null;
  if (e29 < E29_LOW) return 'quartz- or sulfate-rich surface';
  if (e29 > E29_HIGH) return 'low-silica surface (basalt-like, clay or carbonate)';
  return 'mixed';
}

// ---------- the Earth value of a factor (site and box factor tables) ----------

// The MODIS biases, as a short note (data/lst.json derivedRules).
export const MODIS_NOTE = 'MODIS: mean of 4 clear-sky passes (about 10:30, 13:30, 22:30 and 01:30), about 2–3 K warmer than a 24 h mean; day-night swing ≈ 88 % of the full daily range; coldest = coldest 8-day mean of about 01:30 values.';

// The "This site" cell of a factor row: the value, plus for the three temperatures which Earth source it uses.
export function earthCell(r) {
  const f = r.factor;
  const value = fmt(r.earth, f.digits, f.unit);
  if (r.earthFrom === 'latitude') return `${value}<div class="src" title="Computed from the site latitude: 90° − |latitude| + ${SUN_TILT.earth}° (Earth tilt), at most 90°">from latitude</div>`;
  if (!LST_FIELD[f.id] || r.earthFrom === 'kit') return value;
  const from = r.earthFrom === 'modis'
    ? `<div class="src" title="${esc(MODIS_NOTE)}">surface · MODIS 2003–2020</div>`
    : '<div class="src" title="NASA POWER (cell about 50 km): mean and swing are air 2 m above the ground (T2M, T2M_RANGE); coldest ground is the model skin temperature (TS_MIN).">' + (f.id === 'coldGround' ? 'ground' : 'air 2 m') + ' · NASA POWER 2001–2020</div>';
  return `${value}${from}${r.earth == null && r.earthWhy ? `<div class="src">${esc(r.earthWhy)}</div>` : ''}`;
}

export function targetCell(r) {
  if (r.target == null) return '<span class="src">not measured</span>';
  const { digits, unit } = r.factor;
  const basis = { air: 'air', surface: 'surface', soil: 'soil' }[r.basis];
  const info = [basis, r.window].filter(Boolean).join(' · ');
  return `${fmt(r.target, digits, unit)}${info ? `<div class="src">${esc(info)}</div>` : ''}`;
}

// One line under a factor table in surface mode (empty in air mode).
export function earthTempLine(kind = 'site') {
  if (state.earthTemp === 'matched') return '<p class="src">Air is compared with air and surface with surface. Periods and sampling differ, so temperature scores are approximate.</p>';
  if (state.earthTemp !== 'surface') return '';
  const doc = state.data.lstDoc;
  const period = doc?.period ? `${yearOf(doc.period.first)}–${yearOf(doc.period.last)}` : '2003–2020';
  const where = kind === 'box' ? 'mean of the 1 km pixels in the box' : '1 km pixel at the site';
  return `<p class="src">Temperatures (surface mode): NASA MODIS land surface temperature, Terra and Aqua, ${esc(period)}, ${esc(where)}. <span title="${esc(MODIS_NOTE)}">Mean about +2–3 K vs a 24 h mean; swing ≈ 88 % of the daily range.</span> Rain and albedo: NASA POWER.</p>`;
}

// ---------- surface temperature ----------

function lstSources(doc) {
  const p = doc?.product || {};
  const dois = (p.dois || []).map(doiLink).join(' · ');
  const lic = p.licence && typeof p.licence === 'object' ? p.licence : { name: p.licence, url: p.licenceUrl };
  return `NASA MODIS MOD21A2 (Terra) and MYD21A2 (Aqua), Collection 6.1, 8-day, 1 km${dois ? ` · ${dois}` : ''}${lic.name ? ` · ${lic.url ? link(lic.url, lic.name) : esc(lic.name)}` : ''}`;
}

const LST_FLAG_WORDS = {
  polar: 'Polar site: near the poles the sun stays up or down for days, so MODIS day and night passes are not a normal daily cycle. Mean and swing are not computed; the coldest night is kept.',
  water: 'Mostly water: more than half of the 1 km pixel is lake or sea in the MODIS land/water flag, so these values describe water (or lake ice), not ground. They are not used in the score.',
  fewClear: 'Fewer than half of the values are clear-sky: the numbers describe the clear days only.',
  partWater: 'Part water: 20–50 % of the box’s 1 km pixels are mostly water.',
  centreWater: 'The pixel at the box centre is mostly water.',
};

// Whether the surface values are in the score now (Earth temperature switch in Tune factors).
function usedLine(v) {
  if (state.earthTemp === 'matched') return 'Used for comparable surface factors when measurements are available. See the factor table.';
  if (state.earthTemp !== 'surface') return 'Not used in the score now: Earth temperature is set to Air 2 m in Tune factors.';
  if ((v.flags || []).includes('water')) return 'Not used in the score: mostly water (the three temperature factors are left out).';
  const missing = Object.values(LST_FIELD).filter((k) => v[k] == null).length;
  return missing ? 'Used in the score now where a value exists (Earth temperature: Ground surface).' : 'Used in the score now (Earth temperature: Ground surface).';
}

function lstRows(v, coldText) {
  return `<table class="facts"><tbody>
    <tr><td>Mean surface temperature</td><td class="num">${fmt(v.meanSurface_C, 1, '°C')}</td><td><span class="src">average of the 4 clear-sky passes; about 2–3 K warmer than a true 24 h mean</span></td></tr>
    <tr><td>Day-night swing</td><td class="num">${fmt(v.swingSurface_C, 1, '°C')}</td><td><span class="src">about 13:30 minus about 01:30 (Aqua); about 88 % of the full daily range</span></td></tr>
    <tr><td>Coldest 8-day night</td><td class="num">${fmt(v.coldSurface_C, 1, '°C')}</td><td><span class="src">${coldText}</span></td></tr>
    </tbody></table>`;
}

function lstSiteHTML(site) {
  const doc = state.data.lstDoc;
  if (!doc) return '';
  const v = site.lst;
  if (!v) return '<p class="src">Surface temperature: this site is not in data/lst.json.</p>';
  const period = doc.period ? `${yearOf(doc.period.first)}–${yearOf(doc.period.last)}` : '';
  const flags = (v.flags || []).map((f) => `<p class="caveat">${esc(LST_FLAG_WORDS[f] || f)}</p>`).join('');
  const cold = v.coldSurface_C == null ? 'not measured' : `the 8 days from ${esc(v.coldSurfaceStart || '?')}; an 8-day mean of about 01:30 values, so single nights get colder`;
  return `<p><b>Ground surface temperature</b> · ${esc(period)} · ${esc(Number(v.nComposites ?? 0).toLocaleString('en'))} 8-day values from Terra and Aqua, ${esc(pctText(v.validShare))} clear enough to use</p>
    ${lstRows(v, cold)}${flags}${v.note && !(v.flags || []).length ? `<p class="src">${esc(v.note)}</p>` : ''}
    <p class="src">${usedLine(v)} Source: ${lstSources(doc)}.</p>`;
}

function lstBoxHTML(box, lstDoc) {
  if (!lstDoc) return '';
  const v = box.lst;
  if (!v) return '<p class="src">Surface temperature: this box is not in data/screening_lst.json.</p>';
  const period = lstDoc.period ? `${yearOf(lstDoc.period.first)}–${yearOf(lstDoc.period.last)}` : '';
  const flags = (v.flags || []).map((f) => `<p class="caveat">${esc(LST_FLAG_WORDS[f] || f)}</p>`).join('');
  const c = v.centre || {};
  return `<p><b>Ground surface temperature</b> · ${esc(period)} · mean of ${esc(v.nPix ?? '?')} pixels of 1 km in the box, ${esc(pctText(v.validShare))} of them valid</p>
    ${lstRows(v, 'the average of each pixel’s own coldest 8-day night (their dates differ)')}
    <p class="src">Centre pixel only: mean ${fmt(c.meanSurface_C, 1, '°C')}, swing ${fmt(c.swingSurface_C, 1, '°C')}, coldest ${fmt(c.coldSurface_C, 1, '°C')}.</p>${flags}
    <p class="src">${usedLine(v)} Source: ${lstSources(lstDoc)}.</p>`;
}

// ---------- surface composition ----------

const COMP_FLAG_LABEL = {
  vegetation: 'Plants',
  water: 'Water',
  waterNearby: 'Water nearby',
  coldSeason: 'Snow-free season only',
  vegetationUnchecked: 'Plants not checked',
  oneS2Scene: 'One Sentinel-2 picture',
  oneAsterScene: 'One ASTER picture',
  noModis: 'No MODIS value',
  noS2: 'No Sentinel-2 value',
  noAster: 'No ASTER value',
};

const READING_WORDS = {
  'quartz- or sulfate-rich surface': 'Quartz- or sulfate-rich surface: low emissivity near 8.5 µm, as quartz (sand, sandstone) and gypsum have.',
  'low-silica surface (basalt-like, clay or carbonate)': 'Low-silica surface: high emissivity near 8.5 µm, like basalt, clay or limestone.',
  mixed: 'Mixed: between the two cut values, so no clear reading.',
};
const readingText = (reading) => (READING_WORDS[reading] || `${String(reading || 'No reading').charAt(0).toUpperCase()}${String(reading || 'no reading').slice(1)}.`);

const sceneDates = (scenes) => (scenes || []).map((x) => x.date).filter(Boolean);
const sceneYears = (scenes) => [...new Set(sceneDates(scenes).map(yearOf))].sort();

// "2023–2024": the years of every Sentinel-2 scene used in data/composition.json (for the Copernicus notice).
export function s2YearRange(doc = state.data.compositionDoc) {
  const years = Object.values(doc?.places || {}).flatMap((p) => sceneYears(p?.s2?.scenes));
  if (!years.length) return '';
  const sorted = [...new Set(years)].sort();
  return sorted.length === 1 ? sorted[0] : `${sorted[0]}–${sorted[sorted.length - 1]}`;
}

function compSources(doc) {
  const by = Object.fromEntries((doc?.sources || []).map((s) => [s.id, s]));
  const item = (id, name) => (by[id] ? `${by[id].url ? link(by[id].url, name) : esc(name)}${by[id].doi ? ` · ${doiLink(by[id].doi)}` : ''}` : '');
  const years = s2YearRange(doc);
  return [item('mod21a2', 'MODIS MOD21A2 v061'), `${item('sentinel-2-l2a', 'Sentinel-2 L2A')}${years ? ` (Contains modified Copernicus Sentinel data ${esc(years)})` : ''}`, item('aster-l1t', 'ASTER L1T v003')].filter(Boolean).join(' · ');
}

function compSiteHTML(site) {
  const doc = state.data.compositionDoc;
  const c = doc && doc.places ? doc.places[site.id] : null;
  if (!doc) return '';
  if (!c) return '<p class="src">Surface composition: this site is not in data/composition.json.</p>';
  const m = c.modis;
  const s2 = c.s2;
  const a = c.aster;
  const flags = c.flags || [];
  const why = (id) => (flags.find((f) => f.id === id) || {}).why;
  const rows = [];
  rows.push(`<tr><td>Emissivity at 8.5 µm (MODIS e29)</td><td class="num">${m && m.e29 != null ? fmt(m.e29, 3) : 'not measured'}</td><td><span class="src">${m ? `${esc(count(m.n))} pixel samples · ${esc(m.years || '')}; how well the ground gives off heat at 8.5 µm: low = quartz or sulfate, high = basalt-like, clay or carbonate` : esc(why('noModis') || '')}</span></td></tr>`);
  if (s2) {
    const dates = sceneDates(s2.scenes);
    rows.push(`<tr><td>Iron (red ÷ blue, Sentinel-2)</td><td class="num">${fmt(s2.feRatio, 2)}</td><td><span class="src">higher = redder, more rust-coloured (iron oxide) ground</span></td></tr>`);
    rows.push(`<tr><td>Clay, carbonate, sulfate (1.6 ÷ 2.2 µm)</td><td class="num">${fmt(s2.swirRatio, 2)}</td><td><span class="src">higher = more of these minerals</span></td></tr>`);
    rows.push(`<tr><td>Brightness (Sentinel-2)</td><td class="num">${fmt(s2.brightness, 2)}</td><td><span class="src">0–1; dark basalt is low, salt and sand are high · ${dates.length} ${dates.length === 1 ? 'picture' : 'pictures'}: ${esc(dates.join(', '))}</span></td></tr>`);
  } else {
    rows.push(`<tr><td>Sentinel-2 ratios</td><td class="num">not measured</td><td><span class="src">${esc(why('noS2') || '')}</span></td></tr>`);
  }
  if (a) {
    const years = sceneYears(a.scenes);
    rows.push(`<tr><td>Silica index (ASTER)</td><td class="num">${fmt(a.silicaIndex, 3)}</td><td><span class="src"><b>relative only</b> (not corrected for the air): ${a.rank != null ? `${esc(a.rank)} of ${esc(a.of)} sites, 1 = most silica` : ''} · ${(a.scenes || []).length} ${(a.scenes || []).length === 1 ? 'picture' : 'pictures'}${years.length ? `, ${esc(years[0])}${years.length > 1 ? `–${esc(years[years.length - 1])}` : ''}` : ''}</span></td></tr>`);
  } else {
    rows.push(`<tr><td>Silica index (ASTER)</td><td class="num">not measured</td><td><span class="src">${esc(why('noAster') || '')}</span></td></tr>`);
  }
  const shown = flags.filter((f) => !['noModis', 'noS2', 'noAster'].includes(f.id));
  const flagList = shown.length ? `<ul class="links">${shown.map((f) => `<li><b>${esc(COMP_FLAG_LABEL[f.id] || f.id)}</b>: ${esc(f.why || '')}</li>`).join('')}</ul>` : '';
  const jc = c.jordanCheck;
  const check = jc && jc.verdict ? `<p class="${jc.verdict === 'agrees' ? 'src' : 'caveat'}"><b>Check against the rock map (${esc(jc.rock || '')}): ${esc(jc.verdict)}.</b> ${esc(String(jc.reason || '').replace(/^\w+:\s*/, '').replace(/^./, (c) => c.toUpperCase()))}</p>` : '';
  return `<p><b>Surface composition</b> · ${esc(readingText(c.reading))}</p>
    <table class="facts"><tbody>${rows.join('')}</tbody></table>${flagList}${check}
    <p class="src">The reading comes from MODIS e29 only (below ${E29_LOW} or above ${E29_HIGH}); we set those cut values while looking at these same sites, so it is an illustration, not an independent test. It describes the top millimetre of the ground and never names a rock. Sources: ${compSources(doc)}.</p>`;
}

function compBoxHTML(box, compDoc) {
  if (!compDoc) return '';
  const v = compDoc.boxes ? compDoc.boxes[box.id] : null;
  if (!v || v.e29 == null) return '<p class="src">Surface composition: no MODIS e29 value for this box.</p>';
  const rock = box.geology?.primary;
  const r = rock && compDoc.byRock ? compDoc.byRock[rock] : null;
  const years = Array.isArray(compDoc.years) ? compDoc.years.join('–') : '';
  const wet = (box.lst?.flags || []).some((f) => f === 'water' || f === 'partWater');
  return `<p><b>Surface composition</b> · ${esc(readingText(e29Reading(v.e29)))}</p>
    <table class="facts"><tbody><tr><td>Emissivity at 8.5 µm (MODIS e29)</td><td class="num">${fmt(v.e29, 3)}</td><td><span class="src">${esc(count(v.n))} pixel samples · ${esc(years)}; box mean</span></td></tr>
    ${r ? `<tr><td>Boxes mapped as ${esc(rock)}</td><td class="num">${fmt(r.median, 3)}</td><td><span class="src">median of ${esc(r.boxes)} boxes (10–90 %: ${fmt(r.p10, 3)}–${fmt(r.p90, 3)})</span></td></tr>` : ''}</tbody></table>
    ${wet ? '<p class="caveat">Part of this box is water, which raises e29: read it with care.</p>' : ''}
    <p class="src">Reading by the same cut values as the sites (below ${E29_LOW} or above ${E29_HIGH}); boxes have no Sentinel-2 check for plants or water. Source: MODIS MOD21A2 v061${compDoc.source?.doi ? ` · ${doiLink(compDoc.source.doi)}` : ''}.</p>`;
}

// ---------- NASA EMIT minerals (only when data/emit.json exists; its layout is read defensively) ----------

function emitGroup(label, g) {
  if (!g || typeof g !== 'object' || !g.mineral) return '';
  const strength = g.strength === 'weak' ? ' · weak signal' : g.strength ? ` · ${esc(g.strength)} signal` : '';
  return `<tr><td>${esc(label)}</td><td>${esc(g.mineral)}${g.class ? ` <span class="src">(${esc(g.class)})</span>` : ''}</td><td><span class="src">${g.agree ? `${esc(String(g.agree).replace(/granules?/, 'passes'))} agree` : ''}${strength}</span></td></tr>`;
}

function emitSiteHTML(site) {
  const doc = state.data.emitDoc;
  const place = doc && doc.places ? doc.places[site.id] : null;
  const s = place && typeof place === 'object' ? place.summary : null;
  if (!s || typeof s !== 'object') return '';
  const rows = emitGroup('Iron-oxide group (1 µm)', s.g1) + emitGroup('Clay, carbonate, sulfate group (2 µm)', s.g2);
  if (!rows) return '';
  const dois = (doc.product?.dois || []).map(doiLink).join(' · ');
  return `<p><b>Minerals · NASA EMIT</b>${s.granulesUsed != null ? ` · ${esc(s.granulesUsed)} clear ${s.granulesUsed === 1 ? 'pass' : 'passes'} from the Space Station` : ''}</p>
    <table class="facts"><tbody>${rows}</tbody></table>
    <p class="src">The most common mineral match in a 300 m window, and in how many passes it was the most common. A match is not an amount. Source: NASA EMIT L2B minerals, 60 m${dois ? ` · ${dois}` : ''}.</p>`;
}

// A box's EMIT row is a compact array; doc.fields names its columns (e.g. g1Mineral, g1Above2Sigma, granule).
function emitBoxHTML(box, doc) {
  const row = doc && doc.boxes ? doc.boxes[box.id] : null;
  if (!Array.isArray(row)) return '';
  const v = Object.fromEntries(doc.fields.map((f, i) => [f, row[i]]));
  const grp = (label, m, share, sig) => (m ? `<tr><td>${esc(label)}</td><td>${esc(m)}</td><td><span class="src">${share != null ? `${Math.round(share * 100)} % of the window` : ''}${sig != null && sig < 0.5 ? ' · weak signal' : ''}</span></td></tr>` : '');
  const rows = grp('Iron-oxide group (1 µm)', v.g1Mineral, v.g1Share, v.g1Above2Sigma) + grp('Clay, carbonate, sulfate group (2 µm)', v.g2Mineral, v.g2Share, v.g2Above2Sigma);
  if (!rows) return '<p><b>Minerals · NASA EMIT</b> · no clear mineral match at the box centre</p>';
  const g = Array.isArray(doc.granules) ? doc.granules[v.granule] : null;
  const date = Array.isArray(g) ? g[1] : '';
  return `<p><b>Minerals · NASA EMIT</b>${date ? ` · pass of ${esc(date)}` : ''}</p>
    <table class="facts"><tbody>${rows}</tbody></table>
    <p class="src">Most common mineral match in a 1 km window at the box centre, from the clearest pass. A match is not an amount. Source: NASA EMIT L2B minerals, 60 m (see the site pages for the DOIs).</p>`;
}

// ---------- the cards ----------

export function orbitSiteHTML(site) {
  const parts = [lstSiteHTML(site), compSiteHTML(site), emitSiteHTML(site)].filter(Boolean);
  if (!parts.length) return '';
  const comp = state.data.compositionDoc || state.data.emitDoc;
  return `<div class="section orbit"><span class="label">Measured from orbit</span>${parts.join('')}
    ${comp ? '<p class="src"><b>Display only: not used in the score</b> (surface composition and minerals).</p>' : ''}</div>`;
}

// screening: the prepared Discover data (prepareScreening in js/screening.js), with lstDoc and compDoc.
export function orbitBoxHTML(box, screening) {
  const parts = [lstBoxHTML(box, screening?.lstDoc), compBoxHTML(box, screening?.compDoc), emitBoxHTML(box, screening?.emitDoc)].filter(Boolean);
  if (!parts.length) return '';
  return `<div class="section orbit"><span class="label">Measured from orbit</span>${parts.join('')}
    ${screening?.compDoc || screening?.emitDoc ? '<p class="src"><b>Display only: not used in the score</b> (surface composition and minerals).</p>' : ''}</div>`;
}
