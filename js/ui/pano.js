/* global pannellum */
// "Stand here" with a REAL ground-level photo (Pannellum viewer), and "Twin view":
// an Earth site and its Moon/Mars target side by side. Never shows a fake photo.

import { REDUCED_MOTION } from '../config.js';
import { esc, fmt, BODY_LABEL } from '../util.js';
import { openOverlay } from './overlay.js';
import { panoramasFor, fromOrbit, standWords } from './detail.js';

let loading = null;
function loadPannellum() {
  if (window.pannellum) return Promise.resolve();
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const css = document.createElement('link');
      css.rel = 'stylesheet';
      css.href = 'vendor/pannellum/pannellum.css';
      document.head.appendChild(css);
      const s = document.createElement('script');
      s.src = 'vendor/pannellum/pannellum.js';
      s.onload = resolve;
      s.onerror = () => reject(new Error('The 360° viewer (vendor/pannellum) could not be loaded.'));
      document.head.appendChild(s);
    });
  }
  return loading;
}

// The viewer can start before the overlay has its final size; measure again after loading, so the canvas fills
// the frame and a short band (a partial panorama) stays inside it.
const fit = (v) => { v.on('load', () => { v.resize(); v.setHfov(v.getHfov(), false); }); return v; };

const clampHfov = (h, cfg) => Math.max(cfg.minHfov, Math.min(cfg.maxHfov, h));

function viewerConfig(p) {
  const cfg = {
    type: 'equirectangular',
    panorama: p.file,
    autoLoad: true,
    showControls: true,
    showFullscreenCtrl: false,
    compass: false,
    hfov: 95,
    minHfov: 35,
    maxHfov: 115,
    backgroundColor: [0.01, 0.02, 0.04],
    autoRotate: REDUCED_MOTION ? 0 : -1.5,
    autoRotateStopDelay: 0,
  };
  // Optional start direction (degrees), chosen by looking at the photo, e.g. away from a rover deck.
  if (p.yaw != null && Number.isFinite(Number(p.yaw))) cfg.yaw = Number(p.yaw);
  const haov = Number(p.haov) || 360;
  cfg.haov = haov;
  if (haov < 360) { cfg.minYaw = -haov / 2; cfg.maxYaw = haov / 2; cfg.autoRotate = 0; }
  const vaov = Number(p.vaov) || 180;
  if (vaov < 180) {
    const off = Number(p.vOffset) || 0;
    cfg.vaov = vaov;
    cfg.vOffset = off;
    cfg.minPitch = off - vaov / 2;
    cfg.maxPitch = off + vaov / 2;
    cfg.avoidShowingBackground = true;
    cfg.hfov = Math.min(cfg.hfov, vaov * 1.6);
    cfg.minHfov = Math.min(cfg.minHfov, Math.floor(vaov * 0.6)); // a short band in a tall frame needs room to zoom in, or it shows black edges
  }
  // Optional start pitch and zoom (degrees), also view choices only, e.g. to keep a rover deck out of the first view.
  if (p.pitch != null && Number.isFinite(Number(p.pitch))) cfg.pitch = Number(p.pitch);
  if (p.hfov != null && Number.isFinite(Number(p.hfov))) cfg.hfov = clampHfov(Number(p.hfov), cfg);
  return cfg;
}

// On screen: place, credit, licence, date and distance in plain words. How the camera position and the field of
// view were worked out (the full notes of data/panoramas.json) stays one click away under "Photo notes".
function creditRow(p, place) {
  const cover = (Number(p.haov) || 360) >= 360
    ? ((Number(p.vaov) || 180) >= 180 ? 'full 360° sphere' : `360° band, ${fmt(p.vaov, 0)}° tall`)
    : `partial view, about ${fmt(p.haov, 0)}° wide`;
  const taken = p.takenAt && /^\d{4}-\d{2}-\d{2}/.test(p.takenAt) ? `Taken ${p.takenAt.slice(0, 10)}` : p.takenAt;
  const point = place.body && place.body !== 'earth' ? 'target point' : 'site point';
  const km = p.distanceKm != null ? `camera about ${fmt(p.distanceKm, p.distanceKm < 10 ? 1 : 0)} km from our ${point}` : null;
  const where = [taken, km].filter(Boolean).join(' · ');
  const notes = [p.distanceNote ? ['Camera position', p.distanceNote] : null, p.fovNote ? ['Field of view', p.fovNote] : null].filter(Boolean);
  return `<div class="row"><span><b>${esc(place.name)}</b> · real photograph (${esc(cover)})</span>
    <span>Credit: ${esc(p.credit)} · ${p.licenceUrl ? `<a href="${esc(p.licenceUrl)}" target="_blank" rel="noopener">${esc(p.licence)}</a>` : esc(p.licence)}</span>
    ${p.sourcePage ? `<a href="${esc(p.sourcePage)}" target="_blank" rel="noopener">Source page ↗</a>` : ''}</div>
    ${where ? `<div class="row"><span>${esc(where)}</span></div>` : ''}
    ${notes.length ? `<details class="src"><summary>Photo notes: ${esc(notes.map(([k]) => k.toLowerCase()).join(' and '))}</summary>${notes.map(([k, v]) => `<p><b>${esc(k)}:</b> ${esc(v)}</p>`).join('')}</details>` : ''}`;
}

function emptyCell(place, none) {
  return `<div class="pano-empty"><div><b>No real 360° photo here</b>${esc(place.name)}: ${esc(none ? none.reason : 'no openly licensed ground-level panorama was found.')}<br><br><b style="display:inline">Stand here · 3D terrain</b> ${standWords()}.</div></div>`;
}

// Street View (Google's own keyless embed; the imagery stays © Google and its contributors).
function streetSrc(sv) {
  return `https://www.google.com/maps/embed?origin=mfe&pb=!6m7!1m6!2m2!1d${sv.lat}!2d${sv.lon}!3f${sv.heading || 0}!4f0!5f1`;
}
const streetFrame = (sv) => `<iframe class="street-frame" title="${esc(sv.label)}" src="${esc(streetSrc(sv))}" loading="lazy" allowfullscreen referrerpolicy="no-referrer-when-downgrade"></iframe>`;
const streetCredit = (sv, place) => `<div class="row"><span><b>${esc(place.name)}</b> · Google Street View (real ground-level imagery, needs internet)</span><span>${esc(sv.label)} · © Google and its contributors, shown with Google's embed</span></div>`;

// A real photograph that is not a 360° view: shown whole; click to fill the frame.
const flatFrame = (p) => `<img class="flat-photo" src="${esc(p.file)}" alt="${esc(p.title || '')}" title="Click to zoom">`;
function flatCredit(p, place) {
  const kind = fromOrbit(p) ? 'real photograph taken from orbit (not a ground view)' : 'real photograph (not a 360° view)';
  return creditRow({ ...p, haov: null }, place).replace(/real photograph \([^)]*\)/, kind);
}

// What to show for a place, best first: 360° photo, Street View, ordinary photo.
function bestView(place) {
  const v = panoramasFor(place.id);
  if (v.photos.length) return { kind: 'pano', p: v.photos[0] };
  if (v.street) return { kind: 'street', sv: v.street };
  if (v.flat.length) return { kind: 'photo', p: v.flat[0] };
  return { kind: 'none', none: v.none };
}

// One half of the Twin view. A place with Street View AND a local photo keeps the other one as 'other':
// offline the local photo comes first, because Street View needs internet.
function twinSide(place) {
  const best = bestView(place);
  const flat = panoramasFor(place.id).flat[0];
  if (best.kind !== 'street' || !flat) return { place, view: best, other: null, why: '' };
  const photo = { kind: 'photo', p: flat };
  return navigator.onLine === false ? { place, view: photo, other: best, why: 'This computer is offline, so our local photo is shown.' }
    : { place, view: best, other: photo, why: '' };
}

// navigator.onLine can say "online" on a network without internet. This asks for the same embed address the
// frame loads (no new site is contacted) and says false when Google cannot be reached within a few seconds.
async function streetReachable(sv, ms = 6000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    await fetch(streetSrc(sv), { mode: 'no-cors', cache: 'no-store', signal: ctl.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function wireFlat(root) {
  root.querySelectorAll('.flat-photo').forEach((img) => img.addEventListener('click', () => img.classList.toggle('fill')));
}

export async function openPano(place, panoId) {
  const v = panoramasFor(place.id);
  const p = [...v.photos, ...v.flat].find((x) => x.id === panoId) || v.photos[0] || v.flat[0];
  if (!p) return;
  const flat = p.kind === 'photo';
  let viewer = null;
  const world = place.body || 'earth';
  const el = openOverlay({
    title: `${flat ? 'Photo' : 'Stand here'} · ${place.name}`,
    badge: `<span class="tag nasa">Real photo</span><span class="body-chip ${esc(world)}">${esc(BODY_LABEL[world])}</span>`,
    body: `<div class="pano-wrap"><div class="pano-cell" id="pano-a">${flat ? flatFrame(p) : ''}</div></div><div class="pano-credit">${flat ? flatCredit(p, place) : creditRow(p, place)}<div class="row src">${flat ? 'Click the photo to zoom.' : 'Drag to look around · scroll or pinch to zoom.'}</div></div>`,
    onClose: () => { try { viewer?.destroy(); } catch { /* ignore */ } },
  });
  if (flat) { wireFlat(el); return; }
  try {
    await loadPannellum();
    if (!el.isConnected) return; // closed while the viewer was loading
    viewer = fit(pannellum.viewer(el.querySelector('#pano-a'), viewerConfig(p)));
  } catch (err) {
    el.querySelector('#pano-a').innerHTML = `<div class="pano-empty"><div><b>Viewer error</b>${esc(err.message)}</div></div>`;
  }
}

export function openStreet(place) {
  const sv = panoramasFor(place.id).street;
  if (!sv) return;
  openOverlay({
    title: `Stand here · ${place.name}`,
    badge: '<span class="tag nasa">Street View</span><span class="body-chip earth">Earth</span>',
    body: `<div class="pano-wrap"><div class="pano-cell">${streetFrame(sv)}</div></div><div class="pano-credit">${streetCredit(sv, place)}<div class="row src">Drag to look around. Needs internet.</div></div>`,
  });
}

// Earth site (left) next to its Moon/Mars target (right). 360° views can be linked so both turn together.
export async function openTwin(site, target) {
  const sides = { a: twinSide(site), b: twinSide({ ...target }) };
  const a = sides.a.view;
  const b = sides.b.view;
  const chip = (place) => `<span class="body-chip ${esc(place.body || 'earth')} tag-body">${esc(BODY_LABEL[place.body || 'earth'])}</span>`;
  const cell = (view, place) => {
    if (view.kind === 'street') return streetFrame(view.sv);
    if (view.kind === 'photo') return flatFrame(view.p);
    if (view.kind === 'none') return emptyCell(place, view.none);
    return '';
  };
  const credit = (view, place) => (view.kind === 'pano' ? creditRow(view.p, place)
    : view.kind === 'photo' ? flatCredit(view.p, place)
      : view.kind === 'street' ? streetCredit(view.sv, place) : '');
  // The credit of one side, plus the button that swaps Street View and the local photo (when it has both).
  const sideCredit = (s, key) => `${credit(s.view, s.place)}${s.other ? `<div class="row"><span>${s.why ? `${esc(s.why)} ` : ''}<button type="button" class="linkish" data-swap="${key}">${s.other.kind === 'street' ? 'Show Street View instead (needs internet)' : 'Show our local photo instead'}</button></span></div>` : ''}`;
  // A photo from orbit looks straight down, so it has no horizon to compare.
  const hint = () => {
    const n = [sides.a.view, sides.b.view].filter((v) => v.kind === 'photo' && fromOrbit(v.p)).length;
    return n ? `${n === 2 ? 'Both images are photos' : 'One image is a photo'} taken from orbit, looking straight down, so compare rock colour and texture.`
      : 'Look for similar rock colour, texture and horizon.';
  };
  const viewers = [];
  let raf = 0;
  // Linking only works when both sides are 360° viewers.
  const canLink = a.kind === 'pano' && b.kind === 'pano';
  const el = openOverlay({
    title: `Twin view · ${site.name} ↔ ${target.name}`,
    badge: canLink ? '<label class="btn small" style="cursor:pointer"><input type="checkbox" id="twin-link" checked style="accent-color:#ffb547"> Link views</label>' : '',
    body: `<div class="pano-wrap two">
        <div class="pano-cell${a.kind === 'street' ? ' street' : ''}" id="twin-a">${chip(site)}${cell(a, site)}</div>
        <div class="pano-cell${b.kind === 'street' ? ' street' : ''}" id="twin-b">${chip(target)}${cell(b, target)}</div>
      </div>
      <div class="pano-credit"><div id="twin-credit-a">${sideCredit(sides.a, 'a')}</div><div id="twin-credit-b">${sideCredit(sides.b, 'b')}</div>
        <div class="row src" id="twin-hint">Real imagery only. ${hint()} Similar looks are a clue, not proof: the score uses sourced data.</div></div>`,
    onClose: () => { cancelAnimationFrame(raf); viewers.forEach((v) => { try { v.destroy(); } catch { /* ignore */ } }); },
  });
  wireFlat(el);
  // Street View <-> local photo, in one half (never a 360° viewer, so the linked views are not affected).
  const swap = (key, why = '') => {
    const s = sides[key];
    if (!s.other) return;
    [s.view, s.other] = [s.other, s.view];
    s.why = why;
    const c = el.querySelector(`#twin-${key}`);
    c.classList.toggle('street', s.view.kind === 'street');
    c.innerHTML = chip(s.place) + cell(s.view, s.place);
    wireFlat(c);
    el.querySelector(`#twin-credit-${key}`).innerHTML = sideCredit(s, key);
    el.querySelector('#twin-hint').innerHTML = `Real imagery only. ${hint()} Similar looks are a clue, not proof: the score uses sourced data.`;
  };
  el.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-swap]');
    if (btn) { swap(btn.dataset.swap); el.querySelector(`[data-swap="${btn.dataset.swap}"]`)?.focus(); }
  });
  // When Google cannot be reached, fall back to the local photo instead of a browser error page.
  for (const key of ['a', 'b']) {
    const s = sides[key];
    if (s.view.kind !== 'street' || !s.other) continue;
    streetReachable(s.view.sv).then((ok) => {
      if (!ok && el.isConnected && sides[key].view.kind === 'street') swap(key, 'Street View could not be reached, so our local photo is shown.');
    });
  }
  try {
    await loadPannellum();
    if (!el.isConnected) return; // closed while the viewer was loading
    if (a.kind === 'pano') viewers.push(fit(pannellum.viewer(el.querySelector('#twin-a'), { ...viewerConfig(a.p), autoRotate: 0 })));
    if (b.kind === 'pano') viewers.push(fit(pannellum.viewer(el.querySelector('#twin-b'), { ...viewerConfig(b.p), autoRotate: 0 })));
  } catch (err) {
    el.querySelector('.pano-wrap').insertAdjacentHTML('beforeend', `<div class="pano-empty"><div><b>Viewer error</b>${esc(err.message)}</div></div>`);
    return;
  }
  if (!canLink || viewers.length < 2) return;
  // Link: when one view turns, turn the other by the same amount.
  const last = viewers.map((v) => v.getYaw());
  const link = el.querySelector('#twin-link');
  const step = () => {
    raf = requestAnimationFrame(step);
    const yaws = viewers.map((v) => v.getYaw());
    const moved = yaws.map((y, i) => Math.abs(y - last[i]) > 0.01);
    if (link.checked && moved[0] !== moved[1]) {
      const src = moved[0] ? 0 : 1;
      const dst = 1 - src;
      const delta = yaws[src] - last[src];
      viewers[dst].setYaw(viewers[dst].getYaw() + delta, false);
      yaws[dst] = viewers[dst].getYaw();
    }
    yaws.forEach((y, i) => { last[i] = y; });
  };
  raf = requestAnimationFrame(step);
}
