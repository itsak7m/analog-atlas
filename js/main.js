/* global Cesium */
// Analog Atlas – app start-up and wiring between the globe, the panels and the field kit.

import { HAS_ION, ION_TOKEN, NO_3D } from './config.js';
import { openTokenSetup, setIonProblem, addressWith3D } from './ui/setup.js';
import { state, update, on } from './state.js';
import { loadData, findSite, findTarget } from './data.js';
import { Globe, BODIES, SOUTH_POLE_VIEW } from './globe/globe.js';
import { Pins } from './globe/pins.js';
import { computeRanking, renderRanking, markSelected, earthPinItems } from './ui/ranking.js';
import { renderWelcome, renderSite, renderTarget, hideDetail, focusDetail } from './ui/detail.js';
import { initTopbar, setWorld, setTarget, setBackVisible, DEFAULT_TARGET } from './ui/topbar.js';
import { openPano, openTwin, openStreet } from './ui/pano.js';
import { openTune } from './ui/tune.js';
import { openMethod } from './ui/method.js';
import { closeOverlay, overlayOpen } from './ui/overlay.js';
import { playTour, stopTour, tourRunning, focusAfterRun } from './ui/tour.js';
import { startCorridor, stopCorridor, corridorActive, corridorSiteIds } from './ui/corridor.js';
import { startBase, stopBase, baseActive } from './ui/base.js';
import { openAsk } from './ui/ask.js';
import { initKit, kit, refreshKit, feedLine, openPanel as openKitPanel, closePanel as closeKitPanel } from './kit/kit.js';
import { loadScreening, scoreBoxes, findBox } from './screening.js';
import { BoxLayer } from './globe/boxes.js';
import { initDiscover, setDiscoverTab, renderDiscover, renderDiscoverMessage, markDiscoverSelected, announceDiscover } from './ui/discover.js';
import { renderBox } from './ui/screening-detail.js';
import { $, esc, fmt, toast } from './util.js';

let globe = null;
let pins = null;
let boxes = null;     // Discover Jordan: the 10 km boxes on the globe (js/globe/boxes.js)
let discoverRun = 0;  // counts Discover on/off presses, so a slow load cannot switch Discover back on
let ranked = [];
let hudTimer = 0;
let kitPinKey = '';
let routeEntity = null;

// ---------- ranking & pins ----------
function refreshRanking() {
  const target = findTarget(state.data, state.targetId);
  ranked = computeRanking();
  renderRanking({ ranked, target, selectedId: state.selected?.kind === 'site' ? state.selected.id : null, onPick: (id) => pickSite(id), onTwins: showTwins });
}

// "Show all 19 sites" / "Show only strong twins": the list is drawn again, so keyboard focus would fall to the
// page. It goes to the first row that has just appeared (Show all), else to the button that replaced the one pressed.
function showTwins() {
  const before = new Set([...document.querySelectorAll('#rank-list .rank-row')].map((b) => b.dataset.id));
  refreshRanking();
  buildPins();
  const fresh = [...document.querySelectorAll('#rank-list .rank-row')].find((b) => !before.has(b.dataset.id));
  (fresh || $('#rank-list [data-twins]'))?.focus();
}

function buildPins() {
  if (!globe?.viewer) return;
  const target = findTarget(state.data, state.targetId);
  let items;
  if (state.world === 'earth') {
    const fair = state.discover && state.screenRanked ? new Map(state.screenRanked.sites.map((s) => [s.site.id, s])) : null;
    const selId = state.selected?.kind === 'site' ? state.selected.id : null;
    items = earthPinItems({ ranked, target, selId, fair, corridor: corridorSiteIds(), kit });
  } else {
    items = state.data.targets.filter((t) => t.body === state.world).map((t) => ({
      id: t.id,
      kind: 'target',
      name: t.name,
      lon: t.lon,
      lat: t.lat,
      pcText: t.id === state.targetId ? 'TARGET' : '',
      color: t.id === state.targetId ? '#ffb547' : '#c9d1df',
      glow: t.id === state.targetId ? 'rgba(255,181,71,.7)' : 'rgba(201,209,223,.45)',
      priority: t.id === state.targetId ? 2 : 1,
      keepLabel: t.id === state.targetId, // the TARGET label stays readable when a pin is close (south pole)
      aria: `${t.name}, ${t.mission}. Press to fly down.`,
    }));
  }
  pins.set(items, globe.ellipsoid);
  pins.setSelected(state.selected?.id || null);
  kitPinKey = kit.location ? `${kit.source}|${kit.location.lat}|${kit.location.lon}` : '';
}

// When no site pin is on the visible side of the Earth (Malapert: its only strong twin is in Antarctica),
// turn the globe to the #1 site, so the answer is on screen. Only after the visitor changes target or world.
function frameTwins() {
  if (state.world !== 'earth' || state.view !== 'globe' || state.discover || !globe?.viewer || tourRunning() || corridorActive()) return;
  const sites = pins.items.filter((it) => it.kind === 'site');
  if (!sites.length || sites.some((it) => globe.onScreen(it.lon, it.lat))) return;
  const top = ranked.find((r) => r.score != null);
  if (top) api.lookAt(top.site);
}

// ---------- Discover Jordan (10 km screening boxes) ----------
const selectedBoxId = () => (state.selected?.kind === 'box' ? state.selected.id : null);

// Score the boxes for the current target and settings, then redraw the Top 10 and the box colours.
// Does nothing while Discover is off (the boxes are scored again when it is turned on).
function refreshDiscover() {
  if (!state.discover || !state.screening) return;
  state.screenRanked = scoreBoxes();
  boxes.setScores(state.screenRanked);
  renderDiscover({ result: state.screenRanked, target: findTarget(state.data, state.targetId), selectedId: selectedBoxId(), onPick: pickBox });
}

// The "Discover Jordan" tab: switch to Earth if needed, load the boxes once, then show the Top 10 and the boxes.
async function openDiscover() {
  if (tourRunning()) { toast('Exit the mission tour first (Esc).'); setDiscoverTab(state.discover); return; }
  if (state.discover && state.screening) return;
  stopCorridor();
  const run = ++discoverRun;
  if (state.world !== 'earth') await showWorld('earth');
  if (run !== discoverRun) return;
  update({ discover: true });
  setDiscoverTab(true);
  if (!state.screening) renderDiscover({ result: null, target: findTarget(state.data, state.targetId) });
  let screening;
  try {
    screening = await loadScreening();
  } catch (err) {
    console.warn(err);
    if (run === discoverRun) renderDiscoverMessage(err.message); // e.g. "Screening data not built: run …"
    return;
  }
  if (run !== discoverRun) return;
  state.screening = screening;
  boxes.setData(screening);
  refreshDiscover();
  buildPins(); // the site pins now show the same kind of % as the boxes
  boxes.setShown(true);
  announceDiscover(state.screenRanked);
  api.lookAt({ lat: 31.3, lon: 36.9 }, 9e5);
}

// Turn Discover off: the site list comes back, the boxes leave the globe and a selected box is closed.
// Used by the "Hand-picked sites" tab, when leaving Earth, and by api.closePanels (tour and corridor).
function closeDiscover() {
  discoverRun += 1;
  setDiscoverTab(false);
  if (!state.discover) return;
  update({ discover: false });
  state.screenRanked = null;
  boxes.setShown(false);
  boxes.setSelected(null);
  if (state.selected?.kind === 'box') {
    state.selected = null;
    pins.setSelected(null);
    hideDetail();
  }
  buildPins(); // back to the full-match % of the site list
}

function onRankTab(tab) {
  if (tab === 'discover') openDiscover();
  else closeDiscover();
}

// A box picked in the Top 10, in the table of all boxes or on the globe: show its page and look at it from 120 km.
function pickBox(id) {
  const box = findBox(id);
  if (!box) return;
  stopCorridor();
  select({ kind: 'box', id });
  announcePick(state.selected);
  api.lookAt(box, 1.2e5);
}

// N/E/S/W on a box page. Keyboard focus stays on the same direction button (renderBox keeps it there).
function stepBox(id) {
  const box = findBox(id);
  if (!box) return;
  select({ kind: 'box', id });
  $('#sr-status').textContent = `Showing ${box.name}`;
  api.lookAt(box, 1.2e5);
}

// The Top 10 row of a box: the row of its cluster's lead box (a row shows only the lead).
function discoverRowOf(id) {
  const r = state.screenRanked?.byId.get(id);
  const lead = r && r.cluster != null ? state.screenRanked.clusters[r.cluster].lead.id : id;
  return $(`#discover-list .rank-row[data-id="${CSS.escape(lead)}"]`);
}

// ---------- detail panel ----------
function stabilityFor(id) {
  const s = state.stability;
  if (!s || s.targetId !== state.targetId || s.mode !== state.mode || !!s.strict !== state.strict || (s.earthTemp || 'air') !== state.earthTemp) return null;
  return s.share[id] ?? null;
}

function renderDetail() {
  const sel = state.selected;
  const target = findTarget(state.data, state.targetId);
  if (!sel) { renderWelcome(); return; }
  if (sel.kind === 'box') {
    const box = placeOf(sel);
    if (box) renderBox(box, target, state.screenRanked?.byId.get(sel.id));
    else renderWelcome();
  } else if (sel.kind === 'site') {
    const site = findSite(state.data, sel.id);
    const result = ranked.find((r) => r.site.id === sel.id);
    renderSite(site, target, result, { stability: stabilityFor(sel.id) });
  } else {
    const t = findTarget(state.data, sel.id);
    const twins = sel.id === state.targetId ? ranked : computeRanking(sel.id);
    renderTarget(t, twins);
  }
}

function onDetailAction(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const place = placeOf(state.selected);
  switch (action) {
    case 'close': {
      const prev = state.selected;
      state.selected = null;
      pins.setSelected(null);
      markSelected(null);
      boxes.setSelected(null);
      if (state.discover) markDiscoverSelected(null);
      hideDetail();
      focusAfterClose(prev);
      break;
    }
    case 'fly': flyToSelected(); break;
    case 'back': backToGlobe(); break;
    case 'stand': standHere(); break;
    case 'go-site': pickSite(btn.dataset.id); break;
    case 'go-box': stepBox(btn.dataset.id); break;
    case 'pano': if (place) openPano({ ...place, body: place.body || 'earth' }, btn.dataset.id); break;
    case 'street': if (place) openStreet(place); break;
    case 'twin': if (place) openTwin(place, findTarget(state.data, state.targetId)); break;
    case 'tour': if (need3D('The mission tour')) playTour(api); break;
    case 'base': if (place && state.selected?.kind !== 'box') openBase(state.selected, place); break;
    case 'brief-more': {
      const open = btn.closest('.welcome').classList.toggle('open');
      btn.setAttribute('aria-expanded', String(open));
      btn.textContent = open ? 'Less' : 'More';
      break;
    }
    default: break;
  }
}

// After the detail panel closes, give keyboard focus back to the row or pin of the place that was
// shown (else the first row of the list on show, else the target selector), so focus does not fall to the page.
// A box goes back to its Top 10 row (the row of its cluster), when it has one.
function focusAfterClose(prev) {
  const usable = (el) => el && el.tabIndex >= 0 && el.offsetParent !== null && !el.closest('[inert]')
    && getComputedStyle(el).visibility !== 'hidden';
  const row = prev?.kind === 'site' ? $(`#rank-list .rank-row[data-id="${CSS.escape(prev.id)}"]`)
    : prev?.kind === 'box' ? discoverRowOf(prev.id) : null;
  const pin = prev ? pins.items.find((it) => it.id === prev.id)?.el : null;
  const el = [row, pin, $('#discover-list .rank-row'), $('#rank-list .rank-row'), $('#target-picker')].find(usable);
  if (el) el.focus({ preventScroll: true });
}

// ---------- selection & camera ----------
// A box only counts while Discover is on (its data may be loaded, but the boxes are not shown otherwise).
function placeOf(sel) {
  if (!sel) return null;
  if (sel.kind === 'box') return state.discover ? findBox(sel.id) : null;
  return sel.kind === 'site' ? findSite(state.data, sel.id) : findTarget(state.data, sel.id);
}

function select(sel) {
  if (baseActive() && (sel?.kind !== state.selected?.kind || sel?.id !== state.selected?.id)) stopBase();
  state.selected = sel;
  // A site below the strong-twin line (picked from a twin list, the tour or the corridor) gets its row and pin back.
  if (sel?.kind === 'site' && !$(`#rank-list .rank-row[data-id="${CSS.escape(sel.id)}"]`)) {
    refreshRanking();
    buildPins();
  }
  pins.setSelected(sel?.id || null);
  markSelected(sel?.kind === 'site' ? sel.id : null);
  const boxId = selectedBoxId();
  boxes.setSelected(boxId);
  if (state.discover) markDiscoverSelected(boxId);
  renderDetail();
}

// The world a selected place is on: Earth for a site or a box, the target's own body for a target.
const worldOf = (sel, place) => (sel.kind === 'target' ? place.body : 'earth');

// After the visitor picks a place: tell screen readers (#sr-status) and move keyboard focus to the panel heading.
function announcePick(sel) {
  const place = placeOf(sel);
  const status = $('#sr-status');
  if (place && status) status.textContent = `Showing ${place.name}`;
  focusDetail();
}

function pickSite(id) {
  stopCorridor();
  select({ kind: 'site', id });
  announcePick(state.selected);
  flyToSelected();
}

function pickTarget(id) {
  stopCorridor();
  if (id !== state.targetId) changeTarget(id);
  select({ kind: 'target', id });
  announcePick(state.selected);
  flyToSelected();
}

// Close-up mode: the ranking slides away, so it also leaves the Tab order (inert).
function setCloseup(on) {
  document.body.classList.toggle('closeup', on);
  $('#rank').inert = on;
}

// Leave the close-up UI before a camera move back to a far view (used by api.home and api.lookAt).
function resetCloseupUi() {
  stopBase();
  const wasCloseup = state.view !== 'globe';
  setCloseup(false);
  setBackVisible(false);
  showHud(false);
  banner('');
  update({ view: 'globe' });
  pins.setHidden(false);
  if (wasCloseup && state.selected) renderDetail(); // swap "Back to globe" for "Fly down"
}

async function flyToSelected() {
  const sel = state.selected;
  const place = placeOf(sel);
  if (!place || !need3D('Fly down')) return false;
  // Fly down where the place really is, even if another world is showing.
  const world = worldOf(sel, place);
  if (state.world !== world) await showWorld(world);
  if (!globe.viewer) return false;
  update({ view: 'flying' });
  setCloseup(true);
  setBackVisible(true);
  pins.setHidden(true);
  showHud(true);
  renderDetail();
  const ok = await globe.flyToPlace(place);
  if (!ok) return false; // interrupted by another camera move
  update({ view: 'closeup' });
  renderDetail();
  if (!globe.has3D) {
    banner(HAS_ION
      ? ($('#token-state').textContent === 'failed'
        ? '<b>Flat view:</b> 3D terrain could not load (no internet, or the token was not accepted). <button type="button" class="btn small" data-setup>Details</button>'
        : 'Loading 3D terrain… if the ground stays flat, check the internet connection.')
      : NO_3D ? '<b>Flat view:</b> 3D is off for this visit (<b>?no3d</b> in the address).'
        : '<b>Flat view:</b> 3D terrain needs a free Cesium ion token. <button type="button" class="btn small primary" data-setup>Turn on 3D</button>', 12000);
  }
  return true;
}

async function standHere() {
  const sel = state.selected;
  const place = placeOf(sel);
  if (!place || !need3D('Stand here')) return;
  const world = worldOf(sel, place);
  if (state.world !== world) await showWorld(world);
  if (!globe.viewer) return;
  update({ view: 'flying' }); // so Esc and Back to globe work during the approach
  setCloseup(true);
  setBackVisible(true);
  pins.setHidden(true);
  showHud(true);
  renderDetail();
  const move = globe.standHere(place);
  const mine = globe.flightId;
  const res = await move;
  if (!res) {
    // Interrupted, and no newer camera move owns the screen: back to the far-view panels.
    if (globe.flightId === mine && state.view === 'flying') resetCloseupUi();
    return;
  }
  pins.setHidden(true);
  update({ view: 'ground' });
  renderDetail();
  banner(globe.has3D
    ? `<b>3D terrain at eye level</b> (${res.eyeHeight} m above the ground), rendered from elevation data, not a photo. Drag to look around.`
    : `<b>Flat view at eye level</b> (${res.eyeHeight} m above the smooth globe): no 3D terrain is loaded (${NO_3D ? '3D is off for this visit' : 'it needs the Cesium ion token and internet'}), so you see the flat map picture, not the shape of the ground. Drag to look around.`, 9000);
}

async function backToGlobe() {
  stopBase();
  update({ view: 'globe' });
  setCloseup(false);
  setBackVisible(false);
  showHud(false);
  banner('');
  if (globe.viewer) await farView();
  // A new fly-down may have started during the home flight; it owns the pins and the panel now.
  if (state.view !== 'globe') return;
  pins.setHidden(false);
  renderDetail();
}

async function showWorld(world) {
  if (state.world === world && globe.viewer) return;
  if (world !== 'earth') closeDiscover(); // the boxes are on Earth only
  update({ world });
  setWorld(world);
  resetCloseupUi();
  try {
    await globe.show(world);
  } catch (err) {
    noGlobe(err);
    return;
  }
  boxes.attach(globe.viewer); // globe.show() made a new viewer (on the Moon or Mars the layer only detaches)
  buildPins();
  // Every world opens whole, from far away (globe.show() already put the camera at the body's home view).
  // The tilted south-pole view is used only after a site visit (Back to globe) or when a pole target is chosen.
}

// Without WebGL the 3D globe cannot start. The ranking, the details and the field kit still work.
function noGlobe(err) {
  console.error(err);
  banner('<b>No 3D globe:</b> this browser could not start 3D graphics (WebGL). The ranking, the details and the field kit still work.');
}

function need3D(what) {
  if (globe.viewer) return true;
  toast(`${what} needs the 3D globe, which this browser cannot show (no WebGL).`, 5000);
  return false;
}

// Base plan (future work): the 3D concept base at a site or target, with its plan. At an Earth site the
// plan is a test base for the current target; at a target it is the base itself.
function openBase(sel, place) {
  const target = sel.kind === 'target' ? place : findTarget(state.data, state.targetId);
  const result = sel.kind === 'site' ? ranked.find((r) => r.site.id === sel.id) : null;
  startBase(api, { sel: { ...sel }, place, target, result, here: state.view === 'closeup', onAsk: (q) => openAsk(q) });
}

function toggleCorridor() {
  if (corridorActive()) { stopCorridor(); return; }
  if (tourRunning()) { toast('Exit the mission tour first (Esc).'); return; }
  if (need3D('The Jordan corridor')) startCorridor(api);
}

function changeTarget(id) {
  update({ targetId: id });
  setTarget(findTarget(state.data, id));
  refreshRanking();
  refreshDiscover();
  if (state.discover) announceDiscover(state.screenRanked);
  buildPins();
  renderDetail();
  refreshKit();
}

// After a change of mode, strict data or weights (Tune factors): the sites and, while Discover is on, the boxes.
function rescore() {
  refreshRanking();
  refreshDiscover();
  buildPins();
  renderDetail();
  refreshKit();
}

// ---------- far views ----------
// The Moon base and ice targets all sit within a few degrees of the south pole. In the whole-Moon view their
// four pins fall within about 20 px, so for these targets the far view of the Moon is the tilted south-pole view.
function poleTarget() {
  const t = findTarget(state.data, state.targetId);
  return state.world === 'moon' && /^moon-(base|ice)$/.test(t?.group || '');
}

function farView(duration) {
  const v = SOUTH_POLE_VIEW;
  return poleTarget() ? globe.lookAtPlace(v, { duration, height: globe.southPoleHeight(), pitch: v.pitch, heading: v.heading }) : globe.goHome(duration);
}

// ---------- phone layout: the ranking sheet opens as a short "peek", so the globe stays in view ----------
function setSheetOpen(open) {
  document.body.classList.toggle('rank-open', open);
  const b = $('#rank-handle');
  b.setAttribute('aria-expanded', String(open));
  b.textContent = open ? 'Show less of the list' : 'Show more of the list';
}

// ---------- HUD & banner ----------
function showHud(onOff) {
  $('#hud').hidden = !onOff;
}

function updateHud() {
  const now = performance.now();
  if (now - hudTimer < 100) return;
  hudTimer = now;
  const hud = $('#hud');
  if (hud.hidden) return;
  const c = globe.cameraInfo();
  if (!c) return;
  const alt = c.height >= 10000 ? `${fmt(c.height / 1000, 1)} km` : `${fmt(c.height, 0)} m`;
  hud.innerHTML = `<div><span>Alt</span>${alt}</div><div><span>Lat</span>${fmt(c.lat, 3)}°</div><div><span>Lon</span>${fmt(c.lon, 3)}°</div><div><span>Hdg</span>${fmt(c.heading, 0)}°</div><div><span>Pitch</span>${fmt(c.pitch, 0)}°</div><div><span>Light</span>${globe.body === 'earth' ? 'satellite photo' : 'Sun fixed 30°'}</div>`;
}

// The 3D button says what is true now: "on" while Cesium ion works, "failed" after a load error
// (the reason goes to the 3D dialog), "off" without a token or with ?no3d.
let artemisNoted = false;
function set3D(ok, why = '') {
  const on = HAS_ION && ok;
  $('#token-btn').classList.toggle('on', on);
  $('#token-btn').classList.toggle('off', !on);
  $('#token-state').textContent = on ? 'on' : HAS_ION ? 'failed' : 'off';
  setIonProblem(on ? '' : why);
}

let bannerTimer = null;
function banner(html, ms = 0) {
  const el = $('#banner');
  clearTimeout(bannerTimer);
  if (!html) { el.hidden = true; return; }
  el.innerHTML = html;
  el.hidden = false;
  if (ms) bannerTimer = setTimeout(() => { el.hidden = true; }, ms);
}

function onFrame() {
  pins.update(globe.scene, globe.ellipsoid);
  updateHud();
}

// ---------- shared actions for the tour and the corridor ----------
const api = {
  get globe() { return globe; },
  showWorld,
  // Select a site or target and fly down to it (flyToSelected switches to its world first).
  flyTo(sel) {
    select(sel);
    return flyToSelected();
  },
  // Look at a place from some height (straight down, or tilted with { pitch }). Leaves the close-up UI first, exactly like home().
  async lookAt(place, height, { pitch, heading } = {}) {
    resetCloseupUi();
    if (!globe.viewer) return false;
    return globe.lookAtPlace(place, { height, pitch, heading });
  },
  select: (id) => select({ kind: 'site', id }),
  // The visitor's selection and detail panel (a copy), so the tour can put them back when it ends.
  detailState: () => ({ selected: state.selected ? { ...state.selected } : null, hidden: $('#detail').hidden, discover: !!state.discover }),
  openDiscover, // brings Discover back after the tour, when the visitor had it open
  restoreDetail(saved) {
    const sel = saved?.selected && placeOf(saved.selected) ? saved.selected : null;
    select(sel); // with no selection this shows the welcome card
    if (!sel && saved?.hidden) hideDetail();
  },
  backToGlobe,
  openTwin: (siteId, targetId) => openTwin(findSite(state.data, siteId), findTarget(state.data, targetId)),
  closeOverlay,
  // Also turns Discover off, so the tour and the Jordan corridor show the hand-picked sites only.
  closePanels: () => { stopBase(); stopCorridor(); closeKitPanel(); closeOverlay(); closeDiscover(); },
  ranking: () => ranked,
  setTarget: (id) => { if (id !== state.targetId) changeTarget(id); },
  setMode: (mode) => {
    if (mode === state.mode) return;
    update({ mode });
    rescore();
  },
  // Scoring settings (copies), so the tour can save them, use the defaults and restore them.
  settings: () => ({ mode: state.mode, strict: state.strict, earthTemp: state.earthTemp, weights: { ...state.weights }, pillars: { ...state.pillars } }),
  // Change any of { mode, strict, earthTemp, weights, pillars } at once, then rescore.
  setSettings(patch) {
    update(patch);
    rescore();
  },
  async home() {
    resetCloseupUi();
    if (globe.viewer) await globe.goHome();
  },
  openKit: () => openKitPanel(),
  closeKit: () => closeKitPanel(),
  refreshPins: () => buildPins(),
  showRoute(ids) {
    this.clearRoute();
    if (!globe.viewer || state.world !== 'earth') return;
    const sites = ids.map((id) => findSite(state.data, id)).filter(Boolean);
    routeEntity = globe.viewer.entities.add({
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(sites.flatMap((s) => [s.lon, s.lat])),
        width: 4,
        clampToGround: true,
        material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.25, color: Cesium.Color.fromCssColorString('#ffb547') }),
      },
    });
  },
  clearRoute() {
    if (routeEntity && globe.viewer) { try { globe.viewer.entities.remove(routeEntity); } catch { /* viewer rebuilt */ } }
    routeEntity = null;
  },
};

// ---------- start ----------
async function main() {
  if (HAS_ION) Cesium.Ion.defaultAccessToken = ION_TOKEN;
  state.data = await loadData();
  // Measured ground height at a pin (data/terrain.json centre elevation), only where the terrain box is
  // centred on the pin itself (some boxes, such as Mistastin's, are moved off the pin on purpose).
  const knownGroundHeight = (body, lon, lat) => {
    const p = Object.values(state.data.terrain || {}).find((t) => t.body === body && Math.abs(t.lat - lat) < 0.005 && Math.abs(t.lon - lon) < 0.005);
    return p && Number.isFinite(p.centre_elev_m) ? p.centre_elev_m : null;
  };

  pins = new Pins($('#pins'), (item) => {
    if (item.kind === 'kit') openKitPanel();
    else if (item.kind === 'site') pickSite(item.id);
    else pickTarget(item.id);
  }, () => [$('#credits'), $('#rank'), $('#detail')]); // pin labels avoid the map credits and the side panels / bottom sheet
  boxes = new BoxLayer({ onPick: (id) => pickBox(id) });
  globe = new Globe({
    container: 'globe',
    knownHeight: knownGroundHeight,
    creditContainer: $('#credits'),
    onFrame,
    onStatus: (s) => {
      if (s.body !== state.world) return;
      if (s.ion === false) {
        set3D(false, `Cesium ion did not answer (no internet?) or did not accept the token (${s.error}).`);
        banner(`<b>No 3D terrain:</b> Cesium ion did not answer (no internet?) or did not accept the token. The globe still works with NASA pictures, without 3D. Check the token and its <b>Allowed URLs</b> (http://localhost:8080 and http://127.0.0.1:8080) with the <b>3D</b> button, or open the app with <a href="${esc(addressWith3D(false))}">?no3d</a>.`, 12000);
      } else if (s.tiles === false) {
        set3D(false, `the 3D terrain of the ${BODIES[s.body].name} did not load (${s.error}).`);
        banner(`3D terrain for the ${BODIES[s.body].name} could not load. Showing NASA image mosaics instead.`, 9000);
      } else if (s.terrain || s.tiles) set3D(true);
      else if (s.artemis === false && !artemisNoted) {
        artemisNoted = true; // once per visit
        banner(`NASA's Artemis III candidate landing regions are not shown: Cesium ion did not send them (${s.status === 404 ? 'error 404: the data set is not available to this account' : s.status ? `error ${s.status}` : esc(s.error)}).`, 9000);
      } else if (s.artemis) banner('<b>Orange areas:</b> NASA Artemis III candidate landing regions near the south pole.', 9000);
    },
  });
  window.__atlas = { globe, state, kit, kitFeed: feedLine };

  initTopbar({
    targets: state.data.targets,
    onWorld: async (w) => {
      stopCorridor();
      const shown = showWorld(w);
      const cur = findTarget(state.data, state.targetId);
      if (DEFAULT_TARGET[w] && cur.body !== w) changeTarget(DEFAULT_TARGET[w]);
      await shown;
      frameTwins();
    },
    onTarget: (id) => {
      // A target on the other body (Mars chosen while the Moon shows): show its world and its TARGET pin.
      const t = findTarget(state.data, id);
      const before = poleTarget();
      const switching = t && state.world !== 'earth' && t.body !== state.world; // showWorld then frames the view itself
      if (switching) { stopCorridor(); showWorld(t.body); }
      changeTarget(id);
      // On the Moon's far view, a south-pole target turns the camera to the pole (and Apollo back to the whole Moon).
      if (!switching && state.world === 'moon' && state.view === 'globe' && globe.viewer && poleTarget() !== before) farView();
      frameTwins();
    },
  });
  setTarget(findTarget(state.data, state.targetId));
  document.querySelectorAll('.mode-toggle button').forEach((b) => b.addEventListener('click', () => {
    update({ mode: b.dataset.mode });
    rescore();
  }));
  $('#detail').addEventListener('click', onDetailAction);
  // The button hides itself, so keyboard focus moves on: to the heading of the place in the panel, else the target picker.
  $('#back-btn').addEventListener('click', async () => {
    const hadFocus = document.activeElement === $('#back-btn');
    stopCorridor();
    await backToGlobe();
    if (hadFocus && state.view === 'globe') focusAfterRun('#target-picker');
  });
  $('#tour-btn').addEventListener('click', () => (tourRunning() ? stopTour() : need3D('The mission tour') && playTour(api)));
  $('#corridor-btn').addEventListener('click', toggleCorridor);
  $('#method-btn').addEventListener('click', openMethod);
  $('#ask-btn').addEventListener('click', () => openAsk());
  set3D(true);
  $('#token-btn').addEventListener('click', openTokenSetup);
  $('#banner').addEventListener('click', (e) => { if (e.target.closest('[data-setup]')) openTokenSetup(); });
  $('#target-body').addEventListener('click', () => select({ kind: 'target', id: state.targetId }));
  $('#tune-btn').addEventListener('click', () => openTune(rescore));
  $('#rank-handle').addEventListener('click', () => setSheetOpen(!document.body.classList.contains('rank-open')));
  initDiscover({ onTab: onRankTab, onPick: pickBox });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || overlayOpen()) return;
    if (tourRunning()) { stopTour(); return; }
    if (corridorActive()) { stopCorridor(); backToGlobe(); return; } // the same as the corridor's Exit button
    if (baseActive()) { backToGlobe(); return; } // the same as Exit base
    if (!$('#kit-panel').hidden) { closeKitPanel(); return; }
    if (state.view !== 'globe') backToGlobe();
  });
  on('kit', () => {
    const key = kit.location ? `${kit.source}|${kit.location.lat}|${kit.location.lon}` : '';
    if (key !== kitPinKey && state.world === 'earth') buildPins();
  });

  refreshRanking();
  await initKit();
  try {
    await globe.show('earth');
  } catch (err) {
    // No WebGL (an old or locked-down browser): keep the ranking and details usable.
    renderWelcome();
    $('#loading').classList.add('done');
    noGlobe(err);
    return;
  }
  boxes.attach(globe.viewer);
  buildPins();
  renderWelcome();
  $('#loading').classList.add('done');
  if (NO_3D) banner(`<b>3D is off for this visit</b> (<b>?no3d</b> in the address): the globe shows NASA pictures without 3D terrain and works without internet. <a href="${esc(addressWith3D(true))}">Turn 3D back on</a>`, 12000);
  else if (!HAS_ION) banner('3D terrain is off: the globe works, but close-ups are flat. <button type="button" class="btn small primary" data-setup>Turn on 3D</button>', 12000);
  // Pitch mode (?demo for the 30-second video, ?shot=<name> for slide pictures): loaded only when asked for.
  if (/[?&](demo|shot)\b/.test(location.search)) {
    const { runDemo } = await import('./ui/demo.js');
    runDemo(api, { onRankTab: (tab) => (tab === 'discover' ? openDiscover() : closeDiscover()) }, state);
  }
}

main().catch((err) => {
  console.error(err);
  $('#loading').innerHTML = `<div class="box">Could not start<small>${esc(err.message)}<br>Run start.bat and open http://localhost:8080</small></div>`;
});
