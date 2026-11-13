/* global Cesium */
// Jordan Analog Corridor: the Jordanian sites as one story, joined by a route line on the globe.

import { state } from '../state.js';
import { $, esc, fmt, distanceKm, toast } from '../util.js';
import { findSite } from '../data.js';
import { pct } from '../scoring.js';
import { tourRunning, markRunButton, focusAfterRun } from './tour.js';
import { computeRanking, displayRanks } from './ranking.js';
import { shortName } from './topbar.js';

const ORDER = ['harrat', 'waqf-as-suwwan', 'lisan-dead-sea', 'qa-al-jafr', 'wadi-rum'];
const AMMAN = { lat: 31.95, lon: 35.93 };
const ROLE = {
  harrat: 'Moon and Mars · basalt plains and lava tubes (natural shelter)',
  'waqf-as-suwwan': 'Moon and Mars · impact crater',
  'lisan-dead-sea': 'Mars · salt flats and brine',
  'qa-al-jafr': 'Mars · dry lake bed (playa)',
  'wadi-rum': 'Mars · red sandstone desert',
};

let active = null;

export function corridorActive() { return !!active; }

// The corridor sites get a pin while it runs, even below the strong-twin line (Wadi Rum for Jezero).
export const corridorSiteIds = () => (active ? ORDER : []);

const corridorButton = (on) => markRunButton('#corridor-btn', on, ['◆', 'Jordan', 'Jordan Analog Corridor'], ['■', 'Stop', 'Stop the Jordan Analog Corridor (Esc)']);

// "#2 of 19 for Malapert Massif (46%)": the target(s) where this site ranks best, with the current settings.
// The role above is the role in the literature; this line is what our own scores say.
function bestRank(site) {
  const hits = state.data.targets.map((t) => {
    const r = computeRanking(t.id);
    const i = r.findIndex((x) => x.site.id === site.id);
    return i < 0 || r[i].score == null ? null : { t, rank: displayRanks(r)[i], p: pct(r[i].score), n: r.length };
  }).filter(Boolean);
  if (!hits.length) return '';
  const top = Math.min(...hits.map((h) => h.rank));
  const best = hits.filter((h) => h.rank === top).sort((a, b) => b.p - a.p).slice(0, 3);
  const list = best.map((h) => `${esc(shortName(h.t.name))} (${h.p}%)`).join(', ');
  return `Our scores (${state.mode === 'full' ? 'full match' : 'climate match'}): best rank #${top} of ${best[0].n}, for ${list}.`;
}

export async function startCorridor(api) {
  if (active) return;
  // The tour and the corridor share the caption, so only one of them runs at a time.
  if (tourRunning()) { toast('Exit the mission tour first (Esc).'); return; }
  const sites = ORDER.map((id) => findSite(state.data, id)).filter(Boolean);
  if (!sites.length) return;
  api.closePanels();
  await api.showWorld('earth');
  if (active || tourRunning()) return; // started again, or the tour began, while the globe was switching
  const viewer = api.globe.viewer;
  const route = viewer.entities.add({
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(sites.flatMap((s) => [s.lon, s.lat])),
      width: 4,
      clampToGround: true,
      material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: Cesium.Color.fromCssColorString('#ffb547') }),
    },
  });
  active = { sites, index: -1, route, viewer, api };
  document.body.classList.add('touring');
  corridorButton(true);
  api.refreshPins();
  show(-1);
}

function show(index) {
  const { sites, api } = active;
  active.index = index;
  const el = $('#caption');
  el.hidden = false;
  const far = Math.max(...sites.map((s) => distanceKm(AMMAN.lat, AMMAN.lon, s.lat, s.lon)));
  const ctl = (extra = '') => `<div class="ctl">
      <button type="button" class="btn small" data-c="prev" ${index < 0 ? 'disabled' : ''}>◀ Back</button>
      <button type="button" class="btn small primary" data-c="next">${index >= sites.length - 1 ? 'Finish' : 'Next ▶'}</button>${extra}
      <button type="button" class="btn small" data-c="exit">Exit</button></div>`;
  if (index < 0) {
    el.innerHTML = `<div class="k">Jordan Analog Corridor</div><div class="t">${sites.length} Moon and Mars analogs in one small country</div>
      <div class="s">Basalt plains with lava tubes, an impact crater, salt flats, a dry lake and a red sandstone desert. All lie within ${fmt(far, 0)} km of Amman (straight-line distance).</div>${ctl()}`;
    api.lookAt({ lat: 31.0, lon: 36.4 }, 1.6e6);
  } else {
    const s = sites[index];
    const d = distanceKm(AMMAN.lat, AMMAN.lon, s.lat, s.lon);
    el.innerHTML = `<div class="k">Jordan Analog Corridor · ${index + 1}/${sites.length} · ${esc(ROLE[s.id] || '')}</div><div class="t">${esc(s.name)}</div>
      <div class="s">${esc(s.why)} <span class="src">${fmt(d, 0)} km from Amman · ${s.status === 'candidate' ? 'candidate analog (our proposal)' : 'documented analog'}</span></div>
      <div class="s src">${bestRank(s)}</div>
      ${ctl(`<button type="button" class="btn small" data-c="fly">Fly down</button>`)}`;
    api.select(s.id);
    api.lookAt(s, 2.6e5);
  }
  el.querySelectorAll('[data-c]').forEach((b) => b.addEventListener('click', () => onCtl(b.dataset.c)));
  el.querySelector('[data-c="next"]').focus();
}

function onCtl(c) {
  if (!active) return;
  const { sites, api } = active;
  if (c === 'exit' || (c === 'next' && active.index >= sites.length - 1)) { stopCorridor(); api.backToGlobe(); return; }
  if (c === 'next') show(active.index + 1);
  if (c === 'prev') show(active.index - 1);
  if (c === 'fly') {
    const s = sites[active.index];
    stopCorridor();
    api.flyTo({ kind: 'site', id: s.id });
  }
}

export function stopCorridor() {
  if (!active) return;
  const { api } = active;
  const hadFocus = $('#caption').contains(document.activeElement); // Next, Back or Exit on the card that hides now
  try { active.viewer.entities.remove(active.route); } catch { /* viewer may be gone */ }
  active = null;
  document.body.classList.remove('touring');
  corridorButton(false);
  $('#caption').hidden = true;
  api.refreshPins();
  if (hadFocus) { document.activeElement?.blur?.(); focusAfterRun('#corridor-btn'); }
}
