// Pitch mode. Only runs when the address has ?demo or ?shot=<name>; the normal app never loads this file.
//  ?demo        a 30-second captioned sequence for the pitch video (press Start, record the window).
//  ?demo&auto   the same, starting by itself after 2 s.
//  ?shot=<name> one fixed view for slide pictures (see SHOTS); sets <html data-shot-ready> when it is ready.
// Every number in the captions is read from the data at run time, never typed in.

import { findSite, findTarget } from '../data.js';
import { pct, PILLARS } from '../scoring.js';
import { esc } from '../util.js';
import { hideDetail } from './detail.js';
import { SOUTH_POLE_VIEW as POLE } from '../globe/globe.js';

const TEAM = 'Cosmic Cats';
const EVENT = 'NASA Space Apps Challenge 2026 · Amman, Jordan';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const CSS = `
.demo-cap { position: fixed; left: 50%; bottom: 96px; transform: translateX(-50%); z-index: 60; max-width: min(1180px, 86vw);
  background: rgba(5,8,15,.84); border-left: 4px solid #ffb547; padding: 16px 26px; color: #eef2f8; font: 600 30px/1.3 'IBM Plex Sans', 'Segoe UI', sans-serif;
  box-shadow: 0 16px 40px rgba(0,0,0,.5); opacity: 0; transition: opacity .45s ease; text-align: left; }
.demo-cap.show { opacity: 1; }
.demo-cap b { color: #ffb547; font-weight: 700; }
.demo-cap small { display: block; font: 500 19px/1.35 'IBM Plex Sans', sans-serif; color: #b9c3d6; margin-top: 6px; }
.demo-card { position: fixed; inset: 0; z-index: 70; display: grid; place-items: center; background: radial-gradient(ellipse at center, rgba(5,8,15,.55), rgba(5,8,15,.92));
  opacity: 0; transition: opacity .6s ease; pointer-events: none; text-align: center; color: #eef2f8; }
.demo-card.show { opacity: 1; }
.demo-card h1 { font: 700 86px/1 'IBM Plex Sans Condensed', 'Arial Narrow', sans-serif; letter-spacing: .14em; margin: 0 0 18px; }
.demo-card p { font: 500 34px/1.35 'IBM Plex Sans', sans-serif; margin: 0 auto; max-width: 1100px; color: #d7deea; }
.demo-card .kicker { font: 600 22px 'IBM Plex Sans Condensed', sans-serif; letter-spacing: .3em; color: #ffb547; text-transform: uppercase; margin-bottom: 22px; }
.demo-card .small { font-size: 24px; color: #9fb0c8; margin-top: 26px; }
.demo-start { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; background: rgba(5,8,15,.9); color: #eef2f8; font: 500 20px/1.5 'IBM Plex Sans', sans-serif; text-align: center; }
.demo-start button { font: 700 22px 'IBM Plex Sans', sans-serif; padding: 14px 34px; background: #ffb547; color: #111; border: 0; cursor: pointer; margin-top: 18px; }
body.demo-on .kit-bar, body.demo-on #credits { opacity: .55; }
`;

function addStyle() {
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);
  document.body.classList.add('demo-on');
}

function el(cls) {
  const d = document.createElement('div');
  d.className = cls;
  document.body.appendChild(d);
  return d;
}

let cap, card;
function caption(html) {
  if (!html) { cap.classList.remove('show'); return; }
  cap.classList.remove('show');
  setTimeout(() => { cap.innerHTML = html; cap.classList.add('show'); }, html && cap.textContent ? 250 : 0);
}
function showCard(html) {
  if (!html) { card.classList.remove('show'); return; }
  card.innerHTML = html;
  card.classList.add('show');
}

// Facts for the captions, all from the loaded data and the current ranking.
function facts(api, state) {
  const d = state.data;
  const ranked = api.ranking();
  const top = ranked[0];
  return {
    sites: d.sites.length,
    targets: d.targets.length,
    bases: d.targets.filter((t) => t.group === 'moon-base').length,
    jordan: d.sites.filter((s) => s.jordan).length,
    top,
    topPct: top ? pct(top.score) : null,
    jezero: findTarget(d, 'jezero'),
  };
}

// Same scoring settings for every run (the visitor's own settings come back at the end, as in the tour).
function defaults(api, state) {
  const saved = api.settings();
  api.closePanels();
  api.setTarget('jezero');
  api.setSettings({ mode: 'full', strict: false, earthTemp: 'air', weights: Object.fromEntries(Object.keys(state.weights).map((k) => [k, 1])), pillars: Object.fromEntries(Object.keys(state.pillars).map((k) => [k, 1])) });
  return saved;
}

// Getting ready before the clock starts: Mars and Jezero on screen, Discover boxes already loaded,
// so the 30 seconds need only one change of world (Mars -> Earth).
async function prepare(api, state) {
  hideDetail();
  await api.showWorld('mars');
  await api.lookAt(findTarget(state.data, 'jezero'), 3.2e6);
  try { await (await import('../screening.js')).loadScreening(); } catch { /* Discover shows its own message */ }
}

// The Discover caption, from the scored boxes: how many boxes, their size, and the best box against the
// best hand-picked Jordan site scored the same way (both without resources).
function discoverCaption(state) {
  const scr = state.screening;
  const res = state.screenRanked;
  const km = scr?.doc?.grid?.box_m ? scr.doc.grid.box_m / 1000 : null;
  const box = res?.listed?.[0];
  const site = res?.sites?.find((x) => x.score != null);
  const head = `<b>Discover Jordan:</b> ${scr ? `${scr.boxes.length} squares${km ? ` of ${km} km` : ''}` : 'all of Jordan'}, scored with the same method`;
  if (!box || !site) return head;
  const near = Math.abs(box.pct - site.pct) <= 2; // "differences of 1–2 points are within the resolution of the data" (Discover notes)
  return `${head}<small>best square ${box.pct}%, best hand-picked site ${esc(site.site.name)} ${site.pct}% (both without resources)${near ? ': the same within the resolution of the data, so the data agrees with our pick' : ''}</small>`;
}

async function sequence(api, helpers, state) {
  const t0 = performance.now();
  const at = async (s) => { const wait = t0 + s * 1000 - performance.now(); if (wait > 0) await sleep(wait); };
  const f = facts(api, state);

  // 0–4 s: title over Mars.
  showCard(`<div><div class="kicker">${TEAM} · ${EVENT}</div><h1>ANALOG ATLAS</h1><p>Where on Earth can crews train for the Moon and Mars?</p></div>`);
  await at(3.6);
  showCard('');

  // 4–9 s: the targets (Mars, Jezero Crater on screen).
  await at(4);
  caption(`We compare Earth with <b>${f.targets} places on the Moon and Mars</b>:<small>${f.bases === 1 ? 'a Moon base site' : `${f.bases} Moon base sites`} near the south pole, NASA's proposed Mars landing zones, ice and caves, each value with its source</small>`);

  // 9–13 s: the Earth sites (the one change of world).
  await at(9);
  caption(`${f.sites} Earth sites scored on <b>${PILLARS.length} pillars</b><small>${PILLARS.map((p) => p.label.toLowerCase()).join(' · ')} (NASA, ESA and USGS open data)</small>`);
  await api.showWorld('earth');
  api.lookAt({ lat: 31.6, lon: 36.9 }, 1.9e6);

  // 13–17 s: the result.
  await at(13);
  if (f.top) {
    api.select(f.top.site.id);
    caption(`<b>#1 Earth twin of ${esc(f.jezero.name)} on Mars: ${esc(f.top.site.name)}, ${esc(f.top.site.country)} (${f.topPct}%)</b><small>the same method for every site, every number with its source</small>`);
  }

  // 17–22.5 s: Discover Jordan.
  await at(17);
  hideDetail();
  await helpers.onRankTab('discover'); // already loaded in prepare(), so this is quick
  caption(discoverCaption(state));
  api.lookAt({ lat: 31.3, lon: 36.9 }, 9.5e5);

  // 22.5–26.5 s: evidence.
  await at(22.5);
  helpers.onRankTab('sites');
  api.openTwin('harrat', 'jezero');
  caption(`What the ground is made of, seen from orbit by <b>NASA MODIS, EMIT and ESA Sentinel-2</b><small>shown next to the score, never scored · next: our ESP32 field kit</small>`);

  // 26.5–30 s: end card.
  await at(26.5);
  api.closeOverlay();
  caption('');
  showCard(`<div><div class="kicker">${EVENT}</div><h1>ANALOG ATLAS</h1><p>Real data. One method for every place. Made in Jordan.</p><p class="small">${TEAM} · open data: NASA · ESA · USGS · BGR</p></div>`);
  await at(30);
}

// Before a slide picture: wait for the 3D tiles (Moon, Mars) to replace the flat mosaic, then for every
// picture of the view to load (at most about 40 s), so a half-loaded globe is never captured.
async function loaded(api) {
  const g = api.globe;
  if (!g?.viewer) return;
  await Promise.race([g.tilesReady, sleep(20000)]);
  await g.settled(20000);
}

// Fixed views for slide pictures.
// Jordan from 1,900 km. On a phone (the layout of css/app.css under 860 px) the detail sheet covers the lower half,
// so the camera looks about 5° further south and the selected Jordan pin lands in the map area above the sheet.
const jordanView = () => ({ lat: matchMedia('(max-width: 860px)').matches ? 26.6 : 31.6, lon: 36.9 });
const SHOTS = {
  async home(api) { await api.showWorld('earth'); await api.home(); },
  async mars(api, h, state) { await api.showWorld('mars'); await api.lookAt(findTarget(state.data, 'jezero'), 3.2e6); },
  // The lunar south pole is seen tilted from the Mons Mouton side (see SOUTH_POLE_VIEW in globe.js): the darker
  // polar square of the 3D tiles and the 0°/180° mosaic seam then lie near the horizon, not in the middle.
  async moon(api) { api.setTarget('malapert'); await api.showWorld('moon'); await api.lookAt(POLE, api.globe.southPoleHeight(), { pitch: POLE.pitch, heading: POLE.heading }); },
  async ranking(api) { await api.showWorld('earth'); await api.lookAt(jordanView(), 1.9e6); const r = api.ranking()[0]; if (r) api.select(r.site.id); },
  async orbit(api, h, state) {
    await api.showWorld('earth');
    await api.lookAt(findSite(state.data, 'wadi-rum'), 1.2e6);
    api.select('wadi-rum');
    await sleep(600);
    document.querySelector('#detail .orbit')?.scrollIntoView({ block: 'start' });
  },
  async discover(api, h) { await api.showWorld('earth'); hideDetail(); await h.onRankTab('discover'); await api.lookAt({ lat: 31.3, lon: 36.9 }, 9.5e5); },
  // &site=<id>&target=<id> picks another pair, e.g. to check the photo of every place (default: Harrat and Jezero).
  async twin(api) { const q = new URLSearchParams(location.search); await api.showWorld('earth'); api.openTwin(q.get('site') || 'harrat', q.get('target') || 'jezero'); },
  async moonbase(api) { api.setTarget('malapert'); await api.showWorld('moon'); await api.lookAt(POLE, 4e5, { pitch: -24, heading: POLE.heading }); },
  async marsclose(api, h, state) { await api.showWorld('mars'); await api.lookAt(findTarget(state.data, 'jezero'), 1.5e6); },
  async caves(api) { api.setTarget('arsia-skylight'); await api.showWorld('earth'); await api.lookAt(jordanView(), 1.9e6); const r = api.ranking()[0]; if (r) api.select(r.site.id); },
};

export async function runDemo(api, helpers, state) {
  const params = new URLSearchParams(location.search);
  addStyle();
  cap = el('demo-cap');
  card = el('demo-card');
  const shot = params.get('shot');
  // &clean hides the side panels and the kit bar; &nopins also hides the pins (pictures without numbers).
  if (params.has('clean')) { const st = document.createElement('style'); st.textContent = '#rank, #detail, .kit-bar, #kit-bar, #hud, #banner, #toast, .topbar { display: none !important; }' + (params.has('nopins') ? ' #pins { display: none !important; }' : ''); document.head.appendChild(st); }
  if (shot) {
    defaults(api, state);
    hideDetail();
    if (SHOTS[shot]) await SHOTS[shot](api, helpers, state);
    await sleep(2500);
    await loaded(api);
    document.documentElement.dataset.shotReady = shot;
    return;
  }
  const saved = defaults(api, state);
  await prepare(api, state);
  const go = async () => {
    try { await sequence(api, helpers, state); } finally { api.setSettings(saved); }
  };
  if (params.has('auto')) { await sleep(2500); return go(); }
  const start = el('demo-start');
  start.innerHTML = `<div><b>Pitch video mode (30 seconds)</b><br>1. Press F11 for full screen.  2. Start recording (Win + Alt + R).  3. Press Start.<br><button type="button">Start</button></div>`;
  start.querySelector('button').addEventListener('click', async () => {
    start.remove();
    await sleep(1200);
    go();
  });
}
