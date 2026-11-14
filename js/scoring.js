// Similarity scoring for Analog Atlas.
//
// Section 6 of the brief:
//   factor score = max(0, 1 − |earth − target| / R)
//   site score   = Σ(w × factor score) ÷ Σ w      (only factors whose target value was measured)
//
// The screening score averages the available, enabled pillars. The legacy five-pillar
// calculation is kept for reproducing the project's original reference rankings.

// Mean temperature: on Earth this is NASA POWER T2M (air at 2 m). Target values are air
// (Perseverance MEDA at Jezero) or surface/ground temperatures (Moon: Diviner, Apollo 17;
// Mars orbit: Mars Climate Sounder). The Method page explains this. With opts.earthTemp = 'surface' the three
// temperature factors use NASA MODIS ground surface temperature instead (see earthSource below).
export const CLIMATE_FACTORS = [
  { id: 'meanTemp', label: 'Mean temperature', short: 'Mean temp', power: 'T2M', R: 100, unit: '°C', digits: 1 },
  { id: 'swing', label: 'Daily temperature swing', short: 'Daily swing', power: 'T2M_RANGE', R: 100, unit: '°C', digits: 1 },
  { id: 'coldGround', label: 'Coldest ground temperature', short: 'Coldest ground', power: 'TS_MIN', R: 100, unit: '°C', digits: 1 },
  { id: 'rain', label: 'Rainfall', short: 'Rainfall', power: 'PRECTOTCORR', R: 3, unit: 'mm/day', digits: 2 },
  { id: 'albedo', label: 'Surface brightness (albedo)', short: 'Albedo', power: 'ALLSKY_SRF_ALB', R: 0.5, unit: '', digits: 2 },
];

// Base-site factor, part of the climate score only for targets that have a value for it (the three permanent
// Moon base sites; every other target leaves it out, so its scores do not change). "Sun height" is the highest
// the Sun gets above a flat horizon in a year: 90° − |latitude| + axial tilt (at most 90°). Both sides use the
// same formula: the target value is in data/targets.json; the Earth value is computed from the site latitude.
// The low Sun is why high ground near the lunar poles gets long sunlight, and Earth sites near the poles have
// the most similar low Sun. R = 90° (the whole possible range) is our method choice.
export const SUN_TILT = { earth: 23.44, moon: 1.54 }; // NASA Earth fact sheet; NASA Photojournal PIA13720
export function sunHeight(lat, tilt) {
  if (lat == null || !Number.isFinite(lat) || tilt == null) return null;
  return Math.min(90, 90 - Math.abs(lat) + tilt);
}
export const EXTRA_FACTORS = [
  { id: 'sunHeight', label: 'Highest Sun in the sky (Sun height)', short: 'Sun height', power: null, R: 90, unit: '°', digits: 1 },
];
// The climate factors a target is scored on: the five NASA POWER factors, plus an extra factor when the target has it.
export const factorsFor = (target) => [...CLIMATE_FACTORS, ...EXTRA_FACTORS.filter((f) => target?.values?.[f.id])];

// Terrain pillar: median slope over a 10 km box (see data/terrain.json).
// R_SLOPE is our method choice: a 10° difference in median slope counts as "nothing alike".
export const R_SLOPE = 10;

// Geology pillar: rock families used for partial matches (our method choice, see Method & data).
export const ROCK_FAMILY = {
  basalt: 'volcanic',
  anorthosite: 'plutonic',
  granite: 'plutonic',
  sandstone: 'clastic',
  mudstone: 'clastic',
  evaporite: 'chemical',
  carbonate: 'chemical',
  'acid-sulfate': 'chemical',
  chert: 'chemical',
  impactite: 'impact',
  ice: 'ice',
};

export const ROCK_LABEL = {
  basalt: 'Basalt',
  anorthosite: 'Anorthosite',
  granite: 'Granite',
  sandstone: 'Sandstone',
  mudstone: 'Mudstone / lake mud',
  evaporite: 'Salt and sulfate (evaporite)',
  carbonate: 'Limestone / dolomite',
  'acid-sulfate': 'Iron sulfates (acidic)',
  chert: 'Chert',
  impactite: 'Impact breccia',
  ice: 'Ground ice',
};

export const PILLARS = [
  { id: 'climate', label: 'Climate' },
  { id: 'terrain', label: 'Terrain' },
  { id: 'landing', label: 'Landing zone' },
  { id: 'geology', label: 'Geology' },
  { id: 'resources', label: 'Resources' },
];

// Landing-zone pillar: the largest square in the 10 km box where every grid point is under 10° (NASA's
// Artemis landing rule is "under 10°"; our slopes use a 1 km baseline). A site needs one flat zone as large
// as the one at the target; mountains elsewhere in the box do not count against it.
export const SAFE_SLOPE_DEG = 10;

// Resources pillar vocabulary (tags with sources in data/resources.json).
export const RESOURCES = {
  ice: 'Water ice or ground ice',
  shelter: 'Lava tubes, caves or pits (natural shelter)',
  regolith: 'Regolith usable as building material',
  salts: 'Salts and brines (water and chemistry)',
};

export function factorScore(earth, target, R) {
  if (earth == null || target == null || Number.isNaN(earth) || Number.isNaN(target)) return null;
  return Math.max(0, 1 - Math.abs(earth - target) / R);
}

const weightOf = (weights, id) => (weights && weights[id] != null ? weights[id] : 1);

// Earth temperature source (Tune factors). 'air' (default): NASA POWER, as in the reference rankings.
// 'surface': NASA MODIS land surface temperature at the site's 1 km pixel (data/lst.json, attached as site.lst;
// a Discover box gets the 10 km box mean from data/screening_lst.json). Rain and albedo always stay NASA POWER.
export const LST_FIELD = { meanTemp: 'meanSurface_C', swing: 'swingSurface_C', coldGround: 'coldSurface_C' };

export function screeningDefaults() {
  return {
    strict: true,
    earthTemp: 'matched',
    weights: Object.fromEntries(CLIMATE_FACTORS.map(({ id }) => [id, 1])),
    pillars: Object.fromEntries(PILLARS.map(({ id }) => [id, id === 'landing' ? 0 : 1])),
  };
}

export function referenceDefaults() {
  return { ...screeningDefaults(), strict: false, earthTemp: 'air', pillars: Object.fromEntries(PILLARS.map(({ id }) => [id, 1])) };
}

// Where the Earth value of a factor comes from: { value, from: 'power' | 'modis' | 'kit', why }.
// In surface mode a missing value, or a site whose MODIS pixel is mostly water, gives null with the reason.
export function earthSource(site, factorId, earthTemp = 'air', override = null) {
  const factor = CLIMATE_FACTORS.find((f) => f.id === factorId);
  if (override && override[factorId] != null) return { value: override[factorId], from: 'kit', why: '' };
  if (factorId === 'sunHeight') {
    const v = sunHeight(site.lat, SUN_TILT.earth);
    return { value: v, from: 'latitude', why: v == null ? 'no latitude for this place' : '' };
  }
  if (earthTemp === 'surface' && LST_FIELD[factorId]) {
    const lst = site.lst;
    if (!lst) return { value: null, from: 'modis', why: 'no MODIS surface temperature for this place' };
    const flags = lst.flags || [];
    if (flags.includes('water')) return { value: null, from: 'modis', why: 'the MODIS pixel is mostly water, so it does not measure the ground' };
    const v = lst[LST_FIELD[factorId]];
    if (v == null) return { value: null, from: 'modis', why: flags.includes('polar') ? 'polar site: MODIS day and night passes are not a daily cycle here' : 'not measured by MODIS here' };
    return { value: v, from: 'modis', why: '' };
  }
  return { value: site.power ? site.power.annual[factor.power] : null, from: 'power', why: '' };
}

// The target value for a factor. In strict mode, a value that is not a measurement at the
// site itself is replaced by its "strict" entry (often null), see data/targets.json.
export function targetValue(target, factorId, strict) {
  const tv = target.values[factorId];
  if (!tv) return { value: null, source: null, note: '' };
  if (strict && tv.strict !== undefined) return { ...tv.strict, strictApplied: true };
  return tv;
}

// In strict mode a score needs at least this many measured factors, otherwise it is "not enough data".
export const STRICT_MIN_FACTORS = 2;

// Data-quality rule for targets: how many of the 5 factors are measured at the site itself
// (the strict values; rain counts, because it is physically zero on the Moon and Mars).
// Fewer than 3 gets a ⚑ flag.
export const TARGET_MIN_MEASURED = 3;
export function measuredFactors(target) {
  return CLIMATE_FACTORS.filter((f) => targetValue(target, f.id, true).value != null).length;
}

export function climateBreakdown(site, target, weights, override, strict = false, earthTemp = 'air') {
  const rows = factorsFor(target).map((factor) => {
    const tv = targetValue(target, factor.id, strict);
    const matched = earthTemp === 'matched';
    const basis = tv.temperatureBasis;
    let excluded = '';
    if (matched && LST_FIELD[factor.id] && tv.value != null) {
      const needsSurface = factor.id === 'coldGround';
      if (basis !== 'surface' && (basis !== 'air' || needsSurface)) {
        excluded = basis === 'soil' ? 'Soil temperature requires a comparable soil measurement.' : 'No comparable target temperature for this factor.';
      }
      if (tv.screeningNote) excluded = tv.screeningNote;
    }
    const es = earthSource(site, factor.id, matched ? (basis === 'surface' ? 'surface' : 'air') : earthTemp, override);
    if (matched && es.from === 'kit' && basis === 'surface' && factor.id !== 'coldGround') {
      excluded = 'This kit value measures air temperature.';
    }
    const score = excluded ? null : factorScore(es.value, tv.value, factor.R);
    const weight = weightOf(weights, factor.id);
    return { factor, earth: es.value, earthFrom: es.from, earthWhy: es.why, target: tv.value, score, weight, source: tv.source, note: tv.note, basis, window: tv.measurementWindow, excluded, strictApplied: !!tv.strictApplied };
  });
  let num = 0;
  let den = 0;
  let used = 0;
  for (const row of rows) {
    if (row.score == null || row.weight <= 0) continue;
    num += row.weight * row.score;
    den += row.weight;
    used += 1;
  }
  const enough = !strict || rows.filter((r) => r.target != null && !r.excluded && (earthTemp !== 'matched' || r.weight > 0)).length >= STRICT_MIN_FACTORS;
  const enoughEarth = earthTemp !== 'matched' || override || used >= STRICT_MIN_FACTORS;
  return { rows, used, enough, score: den > 0 && enough && enoughEarth ? num / den : null };
}

export function geologyMatch(siteGeo, targetGeo) {
  if (!siteGeo || !targetGeo || !siteGeo.primary || !targetGeo.primary) return null;
  const sSec = siteGeo.secondary || [];
  const tSec = targetGeo.secondary || [];
  if (siteGeo.primary === targetGeo.primary) {
    return { score: 1, reason: `Same main rock: ${ROCK_LABEL[siteGeo.primary] || siteGeo.primary}` };
  }
  if (sSec.includes(targetGeo.primary) || tSec.includes(siteGeo.primary)) {
    return { score: 0.5, reason: 'The main rock of one place is also found at the other' };
  }
  const fam = ROCK_FAMILY[siteGeo.primary];
  if (fam && fam === ROCK_FAMILY[targetGeo.primary]) {
    return { score: 0.5, reason: `Same rock family (${fam})` };
  }
  return { score: 0, reason: 'Different rock types' };
}

export function landingMatch(siteTerrain, targetTerrain) {
  if (!siteTerrain || !targetTerrain) return null;
  const a = siteTerrain.max_flat_square_km;
  const b = targetTerrain.max_flat_square_km;
  if (a == null || b == null) return null;
  // A target with no flat zone at all asks for nothing, so every site with data meets it.
  return { score: b > 0 ? Math.min(1, a / b) : 1, earth: a, target: b };
}

// Share of the target's resources that crews can practise with at the Earth site.
export function resourcesMatch(siteTags, targetTags) {
  if (!targetTags || !targetTags.length || !siteTags) return null;
  const shared = targetTags.filter((t) => siteTags.includes(t));
  return { score: shared.length / targetTags.length, shared, missing: targetTags.filter((t) => !siteTags.includes(t)) };
}

export function terrainMatch(siteTerrain, targetTerrain) {
  if (!siteTerrain || !targetTerrain) return null;
  const a = siteTerrain.median_slope_deg;
  const b = targetTerrain.median_slope_deg;
  const score = factorScore(a, b, R_SLOPE);
  if (score == null) return null;
  return { score, earth: a, target: b };
}

// Minimum coverage for the legacy method and for the independent screening pillars.
export const FULL_MIN_PILLARS = 3;
export const SCREEN_MIN_PILLARS = 2;

// Pillars that are missing because one place lacks the data. `tagsMissing` is the resources rule:
// a target with no sourced tags gives nothing to compare; a site needs an entry in resources.json.
function dataGaps(place, terrainPoint, tagsMissing) {
  const gaps = [];
  if (!terrainPoint || terrainPoint.median_slope_deg == null) gaps.push('terrain');
  if (!terrainPoint || terrainPoint.max_flat_square_km == null) gaps.push('landing');
  if (!place.geology?.primary) gaps.push('geology');
  if (tagsMissing) gaps.push('resources');
  return gaps;
}

// Full analog match: weighted mean of the pillars that could be computed.
export function scoreSite(site, target, opts = {}) {
  const climate = climateBreakdown(site, target, opts.weights, opts.override, opts.strict, opts.earthTemp || 'air');
  if (opts.mode !== 'full') {
    return { score: climate.score, climate, terrain: null, geology: null };
  }
  // A site can opt out of the terrain pillar when its box is mostly water (see terrainExclude in sites_meta.json).
  const usableTerrain = opts.terrain && !site.terrainExclude;
  const terrain = usableTerrain ? terrainMatch(opts.terrain[site.id], opts.terrain[target.id]) : null;
  const landing = usableTerrain ? landingMatch(opts.terrain[site.id], opts.terrain[target.id]) : null;
  const geology = geologyMatch(site.geology, target.geology);
  const siteTags = opts.resources ? opts.resources[site.id] : null;
  const targetTags = opts.resources ? opts.resources[target.id] : null;
  const res = opts.resources ? resourcesMatch(siteTags, targetTags) : null;
  const parts = [
    ['climate', climate.score],
    ['terrain', terrain ? terrain.score : null],
    ['landing', landing ? landing.score : null],
    ['geology', geology ? geology.score : null],
    ['resources', res ? res.score : null],
  ];
  let num = 0;
  let den = 0;
  for (const [id, value] of parts) {
    const w = weightOf(opts.pillars, id);
    if (value == null || w <= 0) continue;
    num += w * value;
    den += w;
  }
  const active = parts.filter(([id]) => weightOf(opts.pillars, id) > 0);
  const pillarsUsed = active.filter(([, value]) => value != null).length;
  const minPillars = weightOf(opts.pillars, 'landing') > 0 ? FULL_MIN_PILLARS : SCREEN_MIN_PILLARS;
  // Only list a gap for a pillar that really is missing.
  const unused = (ids) => ids.filter((id) => parts.find((p) => p[0] === id)[1] == null);
  const targetGaps = unused(dataGaps(target, opts.terrain ? opts.terrain[target.id] : null, !targetTags || !targetTags.length));
  const siteGaps = unused(dataGaps(site, usableTerrain ? opts.terrain[site.id] : null, !siteTags));
  if (opts.earthTemp === 'matched' && climate.score == null) {
    (climate.enough ? siteGaps : targetGaps).push('climate');
  }
  const few = pillarsUsed < minPillars;
  return {
    score: den > 0 && !few ? num / den : null,
    reason: few ? 'few-pillars' : null,
    pillarsUsed,
    pillarsEnabled: active.length,
    minPillars,
    targetGaps,
    siteGaps,
    climate,
    terrain,
    landing,
    geology,
    resources: res,
  };
}

// Sort sites by score (highest first). Ties keep a stable alphabetical order.
export function rankSites(sites, target, opts = {}) {
  const ranked = sites.map((site) => ({ site, ...scoreSite(site, target, opts) }));
  ranked.sort((a, b) => {
    if (a.score == null && b.score == null) return a.site.name.localeCompare(b.site.name);
    if (a.score == null) return 1;
    if (b.score == null) return -1;
    if (b.score !== a.score) return b.score - a.score;
    return a.site.name.localeCompare(b.site.name);
  });
  ranked.forEach((r, i) => { r.rank = i + 1; });
  return ranked;
}

export const pct = (score) => (score == null ? null : Math.round(score * 100));

// Small seeded random generator so the stability check gives the same answer every time.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Stability check: draw random weights (each between 0 and 2) many times and
// count how often each site stays in the top N. A robust twin stays there
// whatever the weights are.
export function stability(sites, target, opts = {}, { runs = 1000, topN = 3, seed = 2026 } = {}) {
  const rand = mulberry32(seed);
  const extra = factorsFor(target).filter((f) => !CLIMATE_FACTORS.includes(f));
  const counts = Object.fromEntries(sites.map((s) => [s.id, 0]));
  for (let i = 0; i < runs; i++) {
    const weights = {};
    for (const f of CLIMATE_FACTORS) weights[f.id] = rand() * 2 * Number(weightOf(opts.weights, f.id) > 0);
    const pillars = {};
    for (const p of PILLARS) pillars[p.id] = rand() * 2 * Number(weightOf(opts.pillars, p.id) > 0);
    // Extra factors are drawn last, and only for targets that use them, so other targets get the same draws as before.
    for (const f of extra) weights[f.id] = rand() * 2 * Number(weightOf(opts.weights, f.id) > 0);
    const ranked = rankSites(sites, target, { ...opts, weights, pillars });
    for (const r of ranked.slice(0, topN)) if (r.score != null) counts[r.site.id] += 1;
  }
  const out = {};
  for (const id of Object.keys(counts)) out[id] = counts[id] / runs;
  return { runs, topN, seed, share: out };
}
