// Discover Jordan: about 886 boxes of 10 km over Jordan, scored against the chosen Moon/Mars target with
// exactly the same formula as the hand-picked sites (scoreSite from scoring.js, unchanged).
//
// The data file data/screening_jordan.json is built offline (python -I scripts/build_screening.py) and
// loaded only when the visitor first opens "Discover Jordan". Boxes are never added to state.data.sites.
//
// Main exports (see the design, section 3):
//   loadScreening()             fetch + prepare the file once (memoised); a 404 gives NOT_BUILT. Also loads the
//                               optional MODIS files data/screening_lst.json and data/screening_composition.json
//   prepareScreening(doc, lst)  the same without fetching (tests); lst = data/screening_lst.json or null
//   boxToSite(rec, doc)         one box record shaped like a site (with .lst, the box's MODIS surface temperature)
//   terrainAll(screening, data) site/target terrain plus box terrain, built once
//   scoreBoxes(opts)            every box scored, sorted, ranked and clustered (cached per settings)
//   boxFill(score, eligible)    colour and opacity of a box on the globe
//   siteScoreNoResources(...)   a site's score with the resources pillar left out (comparable with a box)

import { state } from './state.js';
import { scoreSite, pct } from './scoring.js';
import { scoreColor, cellGap } from './util.js';
import { findTarget } from './data.js';
import { displayRanks } from './ui/ranking.js';

export const SCREEN_LABEL = 'Screening candidate — found by data, not field-checked';
export const SCREENING_URL = 'data/screening_jordan.json';
export const SCREENING_LST_URL = 'data/screening_lst.json';
export const SCREENING_COMPOSITION_URL = 'data/screening_composition.json';
export const SCREENING_EMIT_URL = 'data/screening_emit.json';
export const NOT_BUILT = 'Screening data not built: run python -I scripts/build_screening.py';
export const TOP_N = 10;

// Grid of the design (section 0), used when the file does not carry its own constants.
// Row 0 is the southern row, col 0 the western column.
export const GRID = { south: 29.18, west: 34.95, dlat: 0.0899320363724538, dlon: 0.10522795946422789, nrows: 47, ncols: 42 };

// Box flags (section 2.3) in plain words. 'water' and 'cellGap' keep a box out of the list by themselves;
// every other flag is "soft" and only counts in the tie-break.
export const FLAG_WORDS = {
  border: 'border box',
  cellGap: '⚑ climate cell height differs',
  climateCellMostlyOutside: 'climate cell mostly outside Jordan',
  straddlesCellEdge: 'crosses a POWER cell edge',
  partWater: 'part water',
  water: 'mostly water',
  lowCertaintyGeology: 'low-certainty geology',
  noGeology: 'no mapped rock',
};
export const FLAGS = Object.keys(FLAG_WORDS);
const HARD_FLAGS = ['water', 'cellGap'];

// Why a box is not in the list, in the order they are checked (the first one counts in notListed).
export const NOT_LISTED = ['water', 'site', 'cellGap', 'incomplete', 'noScore'];

// Globe opacity: listed, scored but not listed, no score.
export const FILL_ALPHA = { listed: 0.55, faded: 0.22, none: 0.12 };

let loading = null; // { url, promise }
let current = null; // the prepared screening data, once loaded

// ---------- loading ----------

// Load data/screening_jordan.json once. A failed load is forgotten, so the next press tries again.
// The MODIS files are optional: without them the boxes have no surface temperature (shown "not measured").
export function loadScreening(url = SCREENING_URL) {
  if (!loading || loading.url !== url) {
    const extras = url === SCREENING_URL ? Promise.all([optionalJSON(SCREENING_LST_URL), optionalJSON(SCREENING_COMPOSITION_URL), optionalJSON(SCREENING_EMIT_URL)]) : Promise.resolve([null, null, null]);
    const promise = Promise.all([fetchScreening(url), extras]).then(([doc, [lstDoc, compDoc, emitDoc]]) => {
      current = prepareScreening(doc, lstDoc, compDoc, emitDoc);
      return current;
    });
    promise.catch(() => { if (loading && loading.promise === promise) loading = null; });
    loading = { url, promise };
  }
  return loading.promise;
}

async function fetchScreening(url) {
  let res;
  try {
    res = await fetch(url, { cache: 'no-cache' });
  } catch (err) {
    throw new Error(`Screening data could not load (${err.message})`);
  }
  if (res.status === 404) {
    const err = new Error(NOT_BUILT);
    err.code = 'not-built';
    throw err;
  }
  if (!res.ok) throw new Error(`Screening data could not load: HTTP ${res.status}`);
  try {
    return await res.json();
  } catch (err) {
    throw new Error(`Screening data is not valid JSON (${err.message})`);
  }
}

// An optional data file: null when it is missing or not valid JSON.
async function optionalJSON(url) {
  try {
    const res = await fetch(url, { cache: 'no-cache' });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

// The loaded screening data, or null before the first successful load.
export const getScreening = () => current;

const cellKey = (row, col) => `${row},${col}`;
const firstNumber = (...values) => values.find((v) => Number.isFinite(v));

// Grid constants from the file (doc.grid or doc.grid.constants), else the design values.
export function gridOf(doc) {
  const g = (doc && doc.grid && (doc.grid.constants || doc.grid)) || {};
  return {
    south: firstNumber(g.south, GRID.south),
    west: firstNumber(g.west, GRID.west),
    dlat: firstNumber(g.dlat, GRID.dlat),
    dlon: firstNumber(g.dlon, GRID.dlon),
    nrows: firstNumber(g.nrows, GRID.nrows),
    ncols: firstNumber(g.ncols, GRID.ncols),
  };
}

// Box edges in degrees: from the record when it has them, else from the grid constants (never from the rounded centre).
export function boxBounds(rec, grid = GRID) {
  if ([rec.s, rec.n, rec.w, rec.e].every(Number.isFinite)) return { s: rec.s, n: rec.n, w: rec.w, e: rec.e };
  return {
    s: grid.south + rec.row * grid.dlat,
    n: grid.south + (rec.row + 1) * grid.dlat,
    w: grid.west + rec.col * grid.dlon,
    e: grid.west + (rec.col + 1) * grid.dlon,
  };
}

export const boxName = (row, col) => `Box r${row} c${col}`;

const cellOf = (cells, key) => (key && cells[key] ? { key, ...cells[key] } : null);

// One box record shaped like a site, so scoreSite, cellGap and the detail helpers work on it unchanged.
// The MERRA-2 cell gives the climate and the grid elevation; the 1° SYN1deg cell gives the solar values
// (albedo), as the POWER point API does for the sites. lstDoc (data/screening_lst.json) gives the box's MODIS
// land surface temperature (box mean over its 1 km pixels), used when Earth temperature is set to "Ground surface".
export function boxToSite(rec, doc = current && current.doc, grid = gridOf(doc), lstDoc = current && current.lstDoc) {
  const cells = (doc && doc.climate && doc.climate.cells) || {};
  const merra = cellOf(cells, rec.climate && rec.climate.merra);
  const syn = cellOf(cells, rec.climate && rec.climate.syn);
  return {
    id: rec.id,
    kind: 'box',
    name: boxName(rec.row, rec.col),
    country: 'Jordan',
    jordan: true,
    status: 'screening',
    lat: rec.lat,
    lon: rec.lon,
    bounds: boxBounds(rec, grid),
    row: rec.row,
    col: rec.col,
    power: merra ? { annual: { ...merra.annual, ...(syn ? syn.annual : {}) }, gridElevation_m: merra.elev_m, cells: { merra, syn } } : null,
    geology: { primary: (rec.geology && rec.geology.primary) || null, secondary: (rec.geology && rec.geology.secondary) || [] },
    terrainExclude: rec.terrainExclude || null,
    lst: (lstDoc && lstDoc.boxes && lstDoc.boxes[rec.id]) || null,
    screen: rec,
  };
}

// Turn the file into lookups. Used by loadScreening; tests can call it with a document directly.
// lstDoc and compDoc are the optional MODIS files (surface temperature, band-29 emissivity), or null.
export function prepareScreening(doc, lstDoc = null, compDoc = null, emitDoc = null) {
  if (!doc || !Array.isArray(doc.boxes)) throw new Error('Screening data has no boxes');
  if (doc.label !== SCREEN_LABEL) console.warn('screening_jordan.json: unexpected label', doc.label);
  const grid = gridOf(doc);
  const lst = lstDoc && lstDoc.boxes && typeof lstDoc.boxes === 'object' ? lstDoc : null;
  const boxes = doc.boxes.map((rec) => boxToSite(rec, doc, grid, lst));
  const terrainById = {};
  for (const box of boxes) if (box.screen.terrain) terrainById[box.id] = box.screen.terrain;
  const rows = boxes.map((b) => b.row);
  const cols = boxes.map((b) => b.col);
  return {
    doc,
    lstDoc: lst,
    compDoc: compDoc && compDoc.boxes && typeof compDoc.boxes === 'object' ? compDoc : null,
    emitDoc: emitDoc && emitDoc.boxes && Array.isArray(emitDoc.fields) ? emitDoc : null, // NASA EMIT minerals per box (display only)
    label: SCREEN_LABEL,
    grid,
    boxes,
    byId: new Map(boxes.map((b) => [b.id, b])),
    byCell: new Map(boxes.map((b) => [cellKey(b.row, b.col), b])),
    extent: { row0: Math.min(...rows), row1: Math.max(...rows), col0: Math.min(...cols), col1: Math.max(...cols) },
    terrainById,
    terrain: null,     // terrainAll, built once
    terrainBase: null, // the site terrain map it was built from
    cache: new Map(),  // scoreBoxes results by settings
    cacheData: null,
  };
}

export const findBox = (id, screening = current) => (screening && screening.byId.get(id)) || null;
export const isBoxId = (id, screening = current) => typeof id === 'string' && !!screening && screening.byId.has(id);

// The next box to the north, east, south or west, skipping grid cells outside Jordan; null at the edge.
const STEP = { N: [1, 0], S: [-1, 0], E: [0, 1], W: [0, -1] };
export function neighbourBox(box, dir, screening = current) {
  const step = STEP[dir];
  if (!box || !step || !screening) return null;
  const { row0, row1, col0, col1 } = screening.extent;
  for (let r = box.row + step[0], c = box.col + step[1]; r >= row0 && r <= row1 && c >= col0 && c <= col1; r += step[0], c += step[1]) {
    const next = screening.byCell.get(cellKey(r, c));
    if (next) return next;
  }
  return null;
}

export const neighbours = (box, screening = current) => Object.fromEntries(Object.keys(STEP).map((d) => [d, neighbourBox(box, d, screening)]));

// ---------- scoring ----------

// Site and target terrain plus box terrain in one map (box ids start with "jo-", so they never collide).
export function terrainAll(screening = current, data = state.data) {
  const base = (data && data.terrain) || null;
  if (!screening) return base;
  if (!screening.terrain || screening.terrainBase !== base) {
    screening.terrain = Object.assign({}, base, screening.terrainById);
    screening.terrainBase = base;
  }
  return screening.terrain;
}

const weightOf = (weights, id) => (weights && weights[id] != null ? weights[id] : 1);
const sortedPairs = (obj) => Object.keys(obj || {}).sort().map((k) => [k, obj[k]]);

function settingsOf(opts) {
  return {
    targetId: opts.targetId ?? state.targetId,
    mode: opts.mode ?? state.mode,
    strict: !!(opts.strict ?? state.strict),
    earthTemp: opts.earthTemp ?? state.earthTemp ?? 'air',
    weights: opts.weights ?? state.weights,
    pillars: opts.pillars ?? state.pillars,
  };
}

export const cacheKey = (s) => JSON.stringify([s.targetId, s.mode, s.strict, s.earthTemp || 'air', sortedPairs(s.weights), sortedPairs(s.pillars)]);

// Colour stretch for the Discover layer. Most boxes of a target often sit in a narrow band (e.g. 40-41 %
// for Malapert, 70 %+ for Jezero), so one fixed 30-70 % scale would paint them all alike. range = {lo, hi}
// (0-1): lo maps to the grey-blue end and hi to the amber end of the same pin colour scale. The legend
// shows lo and hi, so the colours stay readable as numbers.
export function stretchScore(score, range) {
  if (score == null || !range) return score;
  return 0.3 + 0.4 * (score - range.lo) / (range.hi - range.lo);
}

// Colour range of a scoreBoxes() result: 5th percentile to the best listed box (all scored boxes when none
// is listed), at least 4 points wide.
export function colourRange(rows) {
  const pool = rows.filter((r) => r.eligible && r.score != null);
  const vals = (pool.length ? pool : rows.filter((r) => r.score != null && !r.flags.includes('water'))).map((r) => r.score).sort((a, b) => a - b);
  if (!vals.length) return null;
  let lo = vals[Math.floor(0.05 * (vals.length - 1))];
  let hi = vals[vals.length - 1];
  if (hi - lo < 0.04) { const mid = (hi + lo) / 2; lo = mid - 0.02; hi = mid + 0.02; }
  return { lo, hi };
}

// Colour of a box on the globe: scoreColor() of the stretched score (or of the score itself without a range);
// water boxes are hidden.
export function boxFill(score, eligible = false, water = false, range = null) {
  const css = scoreColor(stretchScore(score, range));
  if (water) return { css, alpha: 0, show: false };
  if (score == null) return { css, alpha: FILL_ALPHA.none, show: true };
  return { css, alpha: eligible ? FILL_ALPHA.listed : FILL_ALPHA.faded, show: true };
}

// A site's score with the resources pillar left out: the only fair comparison with a box %.
export function siteScoreNoResources(site, target, opts = {}) {
  return scoreSite(site, target, { ...opts, pillars: { ...(opts.pillars || {}), resources: 0 } });
}

// Pillars the box lacks although the target has them and their weight is above ×0
// (resources never counts: no box has resources data).
function missingPillars(res, s) {
  if (s.mode !== 'full') return [];
  const targetGaps = res.targetGaps || [];
  return (res.siteGaps || []).filter((g) => g !== 'resources' && !targetGaps.includes(g) && weightOf(s.pillars, g) > 0);
}

function notListedReasons(row) {
  const why = [];
  if (row.flags.includes('water')) why.push('water');
  if (row.rec.containsSite) why.push('site');
  if (row.gap && row.gap.flagged) why.push('cellGap');
  if (row.missing.length) why.push('incomplete');
  if (row.score == null) why.push('noScore');
  return why;
}

function boxRow(box, target, scoreOpts, s) {
  const res = scoreSite(box, target, scoreOpts);
  const rec = box.screen;
  const flags = rec.flags || [];
  const row = {
    id: box.id,
    box,
    site: box,
    rec,
    ...res,
    pct: pct(res.score),
    gap: cellGap(box, scoreOpts.terrain),
    flags,
    softFlags: flags.filter((f) => !HARD_FLAGS.includes(f)).length,
    share: rec.geology && Number.isFinite(rec.geology.share) ? rec.geology.share : null,
    missing: missingPillars(res, s),
    rank: null,
    tie: false,
    cluster: null,
  };
  row.why = notListedReasons(row);
  row.eligible = row.why.length === 0;
  return row;
}

const absGap = (row) => (row.gap ? Math.abs(row.gap.gap) : Infinity);

// Order of the boxes: higher % first (the whole % that is shown), then fewer soft flags, then a larger
// share of the main rock unit, then a smaller climate-cell height gap, then the id. Boxes without a score go last.
export function compareRows(a, b) {
  if ((a.pct == null) !== (b.pct == null)) return a.pct == null ? 1 : -1;
  return ((b.pct ?? 0) - (a.pct ?? 0))
    || (a.softFlags - b.softFlags)
    || ((b.share ?? -1) - (a.share ?? -1))
    || (absGap(a) - absGap(b) || 0)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

// Listed boxes with the same shown % share a rank ("=3"), exactly like the site ranking.
function rankRows(items) {
  const ranks = displayRanks(items);
  const counts = ranks.reduce((m, r) => m.set(r, (m.get(r) || 0) + 1), new Map());
  items.forEach((item, i) => { item.rank = ranks[i]; item.tie = counts.get(ranks[i]) > 1; });
}

const NEIGHBOURS_8 = [[-1, -1], [-1, 0], [-1, 1], [0, -1], [0, 1], [1, -1], [1, 0], [1, 1]];

// Clusters: listed boxes that touch (8 neighbours) and show the same %. The lead is the first box in the order.
function findClusters(listed) {
  const at = new Map(listed.map((r) => [cellKey(r.box.row, r.box.col), r]));
  const order = new Map(listed.map((r, i) => [r.id, i]));
  const clusters = [];
  for (const lead of listed) {
    if (lead.cluster != null) continue;
    const index = clusters.length;
    const members = [];
    const stack = [lead];
    lead.cluster = index;
    while (stack.length) {
      const r = stack.pop();
      members.push(r);
      for (const [dr, dc] of NEIGHBOURS_8) {
        const n = at.get(cellKey(r.box.row + dr, r.box.col + dc));
        if (n && n.cluster == null && n.pct === lead.pct) { n.cluster = index; stack.push(n); }
      }
    }
    members.sort((a, b) => order.get(a.id) - order.get(b.id));
    clusters.push({ index, pct: lead.pct, score: lead.score, lead, members, size: members.length, nearby: members.length - 1 });
  }
  rankRows(clusters);
  return clusters;
}

function countNotListed(rows) {
  const out = Object.fromEntries(NOT_LISTED.map((k) => [k, 0]));
  for (const r of rows) if (r.why.length) out[r.why[0]] += 1;
  return out;
}

// The five Jordan sites scored without resources, best first.
function comparableSites(data, target, scoreOpts) {
  const rows = data.sites.filter((s) => s.jordan).map((site) => {
    const res = siteScoreNoResources(site, target, scoreOpts);
    return { site, ...res, pct: pct(res.score) };
  });
  return rows.sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || a.site.name.localeCompare(b.site.name));
}

function computeBoxes(screening, data, s, key) {
  const target = findTarget(data, s.targetId);
  if (!target) throw new Error(`Unknown target: ${s.targetId}`);
  const scoreOpts = { mode: s.mode, strict: s.strict, earthTemp: s.earthTemp, weights: s.weights, pillars: { ...s.pillars, resources: 0 }, terrain: terrainAll(screening, data), resources: data.resources };
  const rows = screening.boxes.map((box) => boxRow(box, target, scoreOpts, s));
  const range = colourRange(rows);
  rows.forEach((r) => { r.fill = boxFill(r.score, r.eligible, r.flags.includes('water'), range); });
  rows.sort(compareRows);
  const listed = rows.filter((r) => r.eligible);
  rankRows(listed);
  const clusters = findClusters(listed);
  return {
    key,
    targetId: target.id,
    target,
    mode: s.mode,
    strict: s.strict,
    earthTemp: s.earthTemp,
    rows,
    colourRange: range,
    byId: new Map(rows.map((r) => [r.id, r])),
    listed,
    clusters,
    top: clusters.slice(0, TOP_N),
    notListed: countNotListed(rows),
    scored: rows.filter((r) => r.score != null).length,
    sites: comparableSites(data, target, scoreOpts),
  };
}

const CACHE_MAX = 24;

// Score every box against a target. Settings default to the app state; opts can override any of
// { targetId, mode, strict, earthTemp, weights, pillars }, plus { screening, data } for tests.
// Results are cached per (target, mode, strict, earthTemp, weights, pillars). Returns null before the data is loaded.
export function scoreBoxes(opts = {}) {
  const screening = opts.screening || current;
  const data = opts.data || state.data;
  if (!screening || !data) return null;
  const s = settingsOf(opts);
  const key = cacheKey(s);
  if (screening.cacheData !== data) {
    screening.cache.clear();
    screening.cacheData = data;
  }
  let result = screening.cache.get(key);
  if (!result) {
    result = computeBoxes(screening, data, s, key);
    screening.cache.set(key, result);
    if (screening.cache.size > CACHE_MAX) screening.cache.delete(screening.cache.keys().next().value);
  }
  return result;
}

// ---------- small text helpers ----------

const shortName = (target) => target.name.split(' (')[0].split(',')[0];

// For #sr-status, e.g. "Discover on: 756 boxes ranked for Jezero Crater; top 89 %".
export function statusText(result) {
  if (!result) return '';
  const top = result.listed[0];
  return `Discover on: ${result.listed.length} boxes ranked for ${shortName(result.target)}${top ? `; top ${top.pct} %` : ''}`;
}

// e.g. "Not listed: 5 hold an Atlas site · 71 ⚑ · 41 no mapped rock · 9 water — all stay on the map".
export function notListedText(result) {
  if (!result) return '';
  const n = result.notListed;
  const incomplete = result.rows.filter((r) => r.why[0] === 'incomplete');
  const onlyRock = incomplete.every((r) => r.missing.length === 1 && r.missing[0] === 'geology');
  const parts = [
    n.site ? `${n.site} hold an Atlas site` : '',
    n.cellGap ? `${n.cellGap} ⚑` : '',
    n.incomplete ? `${n.incomplete} ${onlyRock ? 'no mapped rock' : 'incomplete data'}` : '',
    n.water ? `${n.water} water` : '',
    n.noScore ? `${n.noScore} no score` : '',
  ].filter(Boolean);
  return parts.length ? `Not listed: ${parts.join(' · ')} — all stay on the map` : '';
}

const csvCell = (v) => {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// Every box as CSV (rank only for listed boxes), in the same order as result.rows.
// A shared rank goes in its own "tied" column: a cell such as "=3" would open as a formula in a spreadsheet.
export function boxesCsv(result) {
  const head = ['rank', 'tied', 'id', 'name', 'lat', 'lon', 'percent', 'listed', 'not_listed_because', 'flags', 'merra_cell', 'syn_cell', 'main_rock', 'igme_unit', 'cell_gap_m'];
  const lines = result.rows.map((r) => [
    r.rank ?? '',
    r.rank != null && r.tie ? 'yes' : '',
    r.id,
    r.box.name,
    r.box.lat,
    r.box.lon,
    r.pct ?? '',
    r.eligible ? 'yes' : 'no',
    r.why.join(' '),
    r.flags.join(' '),
    r.box.power && r.box.power.cells.merra ? r.box.power.cells.merra.key : '',
    r.box.power && r.box.power.cells.syn ? r.box.power.cells.syn.key : '',
    r.box.geology.primary || '',
    r.rec.geology ? r.rec.geology.unit ?? '' : '',
    r.gap ? Math.round(r.gap.gap) : '',
  ].map(csvCell).join(','));
  return [head.join(','), ...lines].join('\r\n');
}
