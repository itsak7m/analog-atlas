// Small helpers shared by the UI modules.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// Format a number for display. Returns "not measured" for null.
export function fmt(value, digits = 1, unit = '') {
  if (value == null || Number.isNaN(value)) return 'not measured';
  const s = Number(value).toFixed(digits).replace('-', '−');
  return unit ? `${s} ${unit}`.trim() : s;
}

export function fmtCoord(lat, lon) {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(2)}° ${ns}, ${Math.abs(lon).toFixed(2)}° ${ew}`;
}

// Score colour: grey-blue (30 % or less) to amber (70 % or more). The same scale is drawn in the legend.
// The grey-blue end (#8090a8) keeps percentages readable: contrast 5.9:1 on the panel, 4.7:1 on a selected row.
const LO = [128, 144, 168];
const HI = [255, 181, 71];
export function scoreColor(score) {
  if (score == null) return `rgb(${LO[0]},${LO[1]},${LO[2]})`;
  const t = clamp((score - 0.3) / 0.4, 0, 1);
  const c = LO.map((lo, i) => Math.round(lo + (HI[i] - lo) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
export function scoreGlow(score) {
  const t = score == null ? 0 : clamp((score - 0.3) / 0.4, 0, 1);
  return `rgba(255,181,71,${(0.18 + 0.5 * t).toFixed(2)})`;
}

let toastTimer = null;
export function toast(message, ms = 3200) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

export const STATUS_LABEL = {
  'nasa-analog': ['NASA/ESA analog', 'nasa', 'NASA/ESA'],
  analog: ['Published analog', 'analog', 'Analog'],
  candidate: ['Candidate', 'candidate', 'Candidate'],
};

export const BODY_LABEL = { earth: 'Earth', moon: 'Moon', mars: 'Mars' };

// Data-quality rule: if the NASA POWER grid cell is more than 400 m higher or lower than the real
// ground at the site (from data/terrain.json), the climate values describe a wider area.
// 400 m is about 2.6 °C at the standard lapse rate of 6.5 °C per km.
export const CELL_GAP_LIMIT_M = 400;
export function cellGap(site, terrain) {
  const t = terrain && terrain[site.id];
  if (!t || !Number.isFinite(t.centre_elev_m) || !site.power) return null;
  const gap = site.power.gridElevation_m - t.centre_elev_m;
  return { gap, cell: site.power.gridElevation_m, ground: t.centre_elev_m, flagged: Math.abs(gap) > CELL_GAP_LIMIT_M };
}

// Great-circle distance on a sphere (km).
export function distanceKm(lat1, lon1, lat2, lon2, radiusKm = 6371.0088) {
  const r = Math.PI / 180;
  const dLat = (lat2 - lat1) * r;
  const dLon = (lon2 - lon1) * r;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dLon / 2) ** 2;
  return 2 * radiusKm * Math.asin(Math.sqrt(a));
}
