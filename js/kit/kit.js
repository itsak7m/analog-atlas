// ESP32 field kit: live readings over USB (or a clearly labelled simulation), charts,
// a "this spot right now" comparison with the target, the kit location, and the 24-hour log.

import { state, emit } from '../state.js';
import { climateBreakdown, pct } from '../scoring.js';
import { $, esc, fmt, fmtCoord, toast, clamp, CELL_GAP_LIMIT_M } from '../util.js';
import { findTarget } from '../data.js';
import { SerialKit, serialSupported } from './serial.js';
import { drawChart } from './chart.js';

const HISTORY_MS = 15 * 60 * 1000;    // charts show the last 15 minutes
const DAY_MS = 24 * 3600 * 1000;      // the log is cut into 24-hour windows, starting at its first timed row
const FULL_DAY_MS = 20 * 3600 * 1000; // a window counts as a full day with at least 20 hours of data...
const MAX_GAP_MS = 3600 * 1000;       // ...and no gap longer than 1 hour
const TIME_RESEND_MS = 5000;          // send TIME again at most once every 5 s
const ALB_MIN_LUX = 1000;             // albedo needs daylight on the UP sensor...
const ALB_MIN_SUN_DEG = 20;           // ...and the sun 20° or more above the horizon (low sun: angle errors dominate)
const ALB_MEDIAN_MS = 60 * 1000;      // albedo is shown as the median of the last minute
const SURF_SHARE = 0.9;               // coldest ground from the infrared sensor when it covers 90 % of the rows
const K_MIN = 0.5;
const K_MAX = 2;
// Ground elevation at the default point: Copernicus DEM GLO-90 (the DEM behind data/terrain.json), tile
// Copernicus_DSM_COG_30_N31_00_E035_00_DEM from the AWS open-data copy (s3 bucket copernicus-dem-90m),
// pixel centred at 31.95° N, 35.93° E: 829.2 m. Read on 2026-10-10.
const DEFAULT_LOCATION = {
  lat: 31.95, lon: 35.93, label: 'Amman (city centre)', source: 'default', powerFile: 'data/raw/power/amman.json',
  elev: 829, elevSource: 'Copernicus DEM GLO-90',
};
const STORE_KEY = 'analog-atlas-kit-location';
const K_KEY = 'analog-atlas-kit-albedo-k';
const KIT_BANNER = '# Analog Atlas field kit - firmware';
const BASE_BANNER = '# base station ready';
const CSV_COLS = ['unix', 'est_unix', 'boot', 'ms', 'air', 'rh', 'p', 'uv', 'ground', 'surf', 'lux_up', 'lux_down'];
const LIMIT_TEXT = /^[<>]\d+(\.\d+)?$/; // "<1.0" (UV below range) or ">121557" (light sensor saturated)

export const kit = {
  source: 'sim',      // 'usb' while a device is connected, otherwise 'sim'
  viaBase: false,     // true when the USB device is the ESP-NOW base station
  connectedAt: 0,     // when the USB port was opened (ms)
  latest: null,
  history: [],
  status: null,
  messages: [],
  location: null,
  powerHere: null,    // NASA POWER climatology for the kit location
  albK: 1,            // light sensor pair calibration factor k (1 = not calibrated)
  log: null,          // { raw, rows, starts, from }
};

let serial = null;
let simTimer = null;
let dump = null;      // lines collected during LOG DUMP
let lastTimeSent = 0;
let pendingLog = null; // a LOG command waiting for the status line that confirms it

const minOf = (a) => a.reduce((m, v) => (v < m ? v : m), Infinity);
const maxOf = (a) => a.reduce((m, v) => (v > m ? v : m), -Infinity);
const validUnix = (v) => Number.isFinite(v) && v > 1e9;
const shortTime = (t) => new Date(t).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });

// ---------- readings ----------
function normalize(obj, simulated) {
  const r = { t: Date.now(), sim: simulated };
  for (const k of ['air', 'rh', 'p', 'uv', 'uv_mv', 'ground', 'surf', 'amb', 'lux_up', 'lux_down', 'rssi']) {
    if (Number.isFinite(obj[k])) r[k] = obj[k];
  }
  if (obj.sat_up) r.satUp = true;
  if (obj.sat_down) r.satDown = true;
  if (obj.via) r.via = obj.via;
  if (!Number.isFinite(r.uv) && Number.isFinite(obj.uv_lt)) r.uvBelow = obj.uv_lt; // too dark to measure UV
  albedoOf(r);
  return r;
}

// Sun height above the horizon in degrees (NOAA "General Solar Position Calculations").
export function sunElevationDeg(lat, lon, t) {
  const d = new Date(t);
  const day = Math.floor((t - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400e3);
  const hour = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
  const g = ((2 * Math.PI) / 365) * (day + (hour - 12) / 24);
  const eqt = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
    + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const ha = ((hour * 60 + eqt + 4 * lon) / 4 - 180) * (Math.PI / 180);
  const la = lat * (Math.PI / 180);
  const cosZ = Math.sin(la) * Math.sin(decl) + Math.cos(la) * Math.cos(decl) * Math.cos(ha);
  return 90 - Math.acos(clamp(cosZ, -1, 1)) * (180 / Math.PI);
}

// Albedo = reflected / incoming light, with the pair calibration factor k (PROTOCOL.md section 9).
// k is applied to real readings only (the simulation has a perfect sensor pair).
// When albedo cannot be measured, r.albWhy says why.
function albedoOf(r) {
  delete r.alb;
  delete r.albWhy;
  const sun = kit.location ? sunElevationDeg(kit.location.lat, kit.location.lon, r.t) : null;
  if (r.satUp) r.albWhy = 'UP sensor saturated: add a diffuser';
  else if (r.satDown) r.albWhy = 'DOWN sensor saturated: add a diffuser';
  else if (!Number.isFinite(r.lux_up)) r.albWhy = 'UP sensor missing';
  else if (!Number.isFinite(r.lux_down)) r.albWhy = 'DOWN sensor missing';
  else if (r.lux_up <= ALB_MIN_LUX) r.albWhy = 'needs daylight';
  else if (sun != null && sun < ALB_MIN_SUN_DEG) r.albWhy = `sun too low (${Math.round(sun)}°)`;
  else r.alb = (r.lux_down * (r.sim ? 1 : kit.albK)) / r.lux_up;
}

// The albedo used now: the median of the last minute, so a single reading cannot make it jump.
function albedoNow() {
  const L = kit.latest;
  if (!L) return { value: null, why: 'not measured' };
  if (!Number.isFinite(L.alb)) return { value: null, why: L.albWhy || 'not measured' };
  const vals = kit.history.filter((r) => r.t >= L.t - ALB_MEDIAN_MS && Number.isFinite(r.alb)).map((r) => r.alb).sort((a, b) => a - b);
  const m = vals.length >> 1;
  return { value: vals.length % 2 ? vals[m] : (vals[m - 1] + vals[m]) / 2, n: vals.length };
}

function push(reading) {
  kit.latest = reading;
  kit.history.push(reading);
  const cutoff = Date.now() - HISTORY_MS;
  while (kit.history.length && kit.history[0].t < cutoff) kit.history.shift();
  if (!$('#kit-panel').hidden) renderLive();
  emit('kit', kit);
}

function addMessage(text) {
  kit.messages.push({ t: Date.now(), text });
  if (kit.messages.length > 30) kit.messages.shift();
  if (!$('#kit-panel').hidden) renderMessages();
}

function onLine(line) {
  if (line.startsWith('#')) {
    if (line.startsWith('#LOG BEGIN')) { dump = []; return; }
    if (line.startsWith('#LOG END')) { finishDump(); return; }
    if (line.startsWith(BASE_BANNER)) setViaBase();
    if (line.startsWith(KIT_BANNER)) resendTime(); // the kit has just restarted and lost its clock
    addMessage(line.slice(1).trim());
    return;
  }
  if (dump && !line.startsWith('{')) { dump.push(line); return; }
  let obj;
  try { obj = JSON.parse(line); } catch { return; } // ignore garbled lines
  if (!obj || typeof obj !== 'object') return;
  if (obj.via === 'espnow') setViaBase();
  if (obj.status && typeof obj.status === 'object') { onStatus(obj.status, obj.via); return; }
  if (obj.info && typeof obj.info === 'object') { kit.status = { ...(kit.status || {}), ...obj.info }; return; }
  if (obj.base) { // reply from the ESP-NOW base station, not a reading
    setViaBase();
    addMessage(`Base station: ${JSON.stringify(obj.base)}`);
    return;
  }
  if (!Number.isFinite(obj.t)) return; // every kit data line has "t": anything else is not a kit reading
  push(normalize(obj, false));
}

function onStatus(status, via) {
  kit.status = status;
  if (status.time === false && via !== 'espnow') resendTime();
  if (pendingLog && pendingLog.check(status)) {
    clearTimeout(pendingLog.timer);
    toast(pendingLog.okText);
    pendingLog = null;
  }
  if (!$('#kit-panel').hidden) renderStatus();
}

// PROTOCOL.md section 1: after a restart the kit has no clock, so send TIME again.
// Not through the base station (it does not pass TIME on), and at most once every 5 s.
function resendTime() {
  if (kit.source !== 'usb' || kit.viaBase || Date.now() - lastTimeSent < TIME_RESEND_MS) return;
  lastTimeSent = Date.now();
  send(`TIME ${Math.floor(Date.now() / 1000)}`);
}

function setViaBase() {
  if (kit.viaBase || kit.source !== 'usb') return;
  kit.viaBase = true;
  if (!$('#kit-panel').hidden) renderPanel();
}

// ---------- simulation (when no device is connected) ----------
function simulate() {
  const P = kit.powerHere;
  if (!P) return;
  const now = Date.now();
  const m = new Date(now).getUTCMonth();
  const mon = (k) => P.monthly[k][m] ?? P.annual[k];
  const solarHour = (((now / 3600e3) % 24) + kit.location.lon / 15 + 24) % 24;
  const daily = Math.cos((2 * Math.PI * (solarHour - 15)) / 24);
  const sun = Math.max(0, Math.sin((Math.PI * (solarHour - 6)) / 12));
  const n = (a) => (Math.random() - 0.5) * a;
  const up = 90000 * sun * (0.95 + n(0.04));
  const uv = mon('ALLSKY_SFC_UV_INDEX') * 2.5 * sun + n(0.1);
  push(normalize({
    air: mon('T2M') + (mon('T2M_RANGE') / 2) * daily + n(0.3),
    rh: clamp(mon('RH2M') - 12 * daily + n(1), 3, 100),
    p: P.annual.PS + n(0.04),
    ...(uv >= 1 ? { uv } : { uv_lt: 1.0 }), // like the real kit: below UV index 1.0 only "< 1.0" is known
    ground: mon('TS') + mon('T2M_RANGE') * 0.3 * Math.cos((2 * Math.PI * (solarHour - 17)) / 24) + n(0.1),
    surf: mon('TS') + mon('T2M_RANGE') * 0.9 * Math.cos((2 * Math.PI * (solarHour - 13.5)) / 24) + n(0.4),
    lux_up: up,
    lux_down: up * mon('ALLSKY_SRF_ALB') * (1 + n(0.04)),
  }, true));
}

function startSim() {
  stopSim();
  kit.source = 'sim';
  kit.history = [];
  simulate();
  simTimer = setInterval(simulate, 1000);
}

function stopSim() {
  clearInterval(simTimer);
  simTimer = null;
}

// ---------- USB ----------
async function connect() {
  if (!serialSupported()) {
    toast('USB needs Chrome or Edge on a computer, opened at http://localhost:8080.', 5000);
    return;
  }
  serial = serial || new SerialKit({ onLine, onState });
  try {
    await serial.connect();
  } catch (err) {
    if (err && err.name !== 'NotFoundError') toast(`Could not open the port: ${err.message}`, 5000);
  }
}

function onState(s, err) {
  if (s === 'connected') {
    stopSim();
    kit.source = 'usb';
    kit.viaBase = false;
    kit.history = [];
    kit.latest = null;
    kit.connectedAt = Date.now();
    lastTimeSent = 0;
    toast('Field kit connected');
  } else if (s === 'error') {
    console.warn('serial error', err);
    toast(`USB problem: ${err?.message || err}. Still listening for data.`, 5000);
  } else {
    // disconnected or unplugged
    kit.viaBase = false;
    dump = null;
    clearTimeout(pendingLog?.timer);
    pendingLog = null;
    toast(s === 'unplugged' ? 'Field kit unplugged. Back to simulation.' : 'Field kit disconnected. Back to simulation.');
    startSim();
  }
  if (!$('#kit-panel').hidden) renderPanel();
  emit('kit', kit);
}

const send = (cmd) => serial && serial.connected && serial.send(cmd);

// Sends a LOG command and reports success only when a status line confirms it.
function logCommand(cmd, check, okText) {
  send(cmd);
  clearTimeout(pendingLog?.timer);
  const timer = setTimeout(() => {
    pendingLog = null;
    toast('The kit did not confirm. See "Messages from the kit" below.', 5000);
  }, 5000);
  pendingLog = { check, okText, timer };
  toast('Sent to the kit…');
}

// ---------- the loaded log: 24-hour windows ----------
// Cuts the timed log rows into 24-hour windows, starting at the first row with a known time.
// A window is a full day when its air readings cover at least 20 h with no gap longer than 1 h.
export function dayWindows(rows) {
  const timed = rows.filter((r) => Number.isFinite(r.t));
  if (!timed.length) return [];
  const t0 = timed[0].t;
  const wins = [];
  for (const r of timed) {
    const k = Math.floor((r.t - t0) / DAY_MS);
    if (!wins[k]) wins[k] = { start: t0 + k * DAY_MS, rows: [] };
    wins[k].rows.push(r);
  }
  return wins.filter(Boolean).map((w) => {
    const air = w.rows.filter((r) => Number.isFinite(r.air));
    let gap = 0;
    for (let i = 1; i < air.length; i++) gap = Math.max(gap, air[i].t - air[i - 1].t);
    const span = air.length > 1 ? air[air.length - 1].t - air[0].t : 0;
    const temps = air.map((r) => r.air);
    return {
      ...w,
      span,
      gap,
      full: span >= FULL_DAY_MS && gap <= MAX_GAP_MS,
      mean: temps.length ? temps.reduce((a, b) => a + b, 0) / temps.length : null,
      range: temps.length ? maxOf(temps) - minOf(temps) : null,
      month: new Date(w.start + DAY_MS / 2).getMonth(),
    };
  });
}

// Daily swing and coldest ground from the full 24-hour windows of the loaded log.
function logSummary() {
  const full = dayWindows(kit.log?.rows || []).filter((w) => w.full);
  if (!full.length) return { swing: null, cold: null };
  const swing = full.reduce((a, w) => a + w.range, 0) / full.length;
  const rows = full.flatMap((w) => w.rows);
  const surf = rows.map((r) => r.surf).filter(Number.isFinite);
  const soil = rows.map((r) => r.ground).filter(Number.isFinite);
  // The target value is a surface (skin) temperature. A soil probe reads warmer at night, so it is
  // only used when the infrared sensor is missing for more than 10 % of the rows, and then labelled.
  let cold = null;
  if (surf.length && surf.length >= SURF_SHARE * rows.length) cold = { value: minOf(surf), from: 'infrared surface' };
  else if (soil.length) cold = { value: minOf(soil), from: 'soil probe, warmer than the surface at night' };
  else if (surf.length) cold = { value: minOf(surf), from: 'infrared surface, with gaps' };
  return { swing, cold };
}

export function liveInputs() {
  const L = kit.latest;
  const inputs = {};
  if (!L) return inputs;
  if (Number.isFinite(L.air)) inputs.meanTemp = L.air;
  const alb = albedoNow();
  if (alb.value != null) inputs.albedo = alb.value;
  const log = logSummary();
  if (log.swing != null) inputs.swing = log.swing;
  if (log.cold && (state.earthTemp !== 'matched' || log.cold.from.startsWith('infrared surface'))) inputs.coldGround = log.cold.value;
  return inputs;
}

export function liveScore(target) {
  const inputs = liveInputs();
  const pseudoSite = { power: { annual: {} } };
  const res = climateBreakdown(pseudoSite, target, state.weights, inputs, state.strict, state.earthTemp === 'matched' ? 'matched' : 'air');
  const used = res.rows.filter((r) => r.score != null).length;
  return { ...res, used, inputs };
}

// ---------- panel ----------
// [key, label, unit, digits, colour, smallest y-range shown]. The smallest range is for display only: it keeps
// sensor noise of a few tenths from filling the whole chart height.
const CHARTS = [
  ['air', 'Air temperature', '°C', 1, '#5ce1e6', 2],
  ['surf', 'Surface (infrared)', '°C', 1, '#ffb547', 2],
  ['ground', 'Soil probe', '°C', 1, '#ff8a65', 2],
  ['rh', 'Humidity', '%', 0, '#74b9ff', 5],
  ['uv', 'UV index', '', 1, '#c792ea', 1],
  ['alb', 'Albedo', '', 2, '#c9d1df', 0.05],
];

function renderPanel() {
  const el = $('#kit-panel');
  const live = kit.source === 'usb';
  const logOk = live && !kit.viaBase;
  const supported = serialSupported();
  el.innerHTML = `
    <div class="kp-head">
      <h2 class="label">ESP32 field kit</h2>
      <span class="kit-state ${live ? 'live' : 'sim'}">${live ? 'Live' : 'Simulated'}</span>
      <div class="spacer"></div>
      ${live ? '<button type="button" class="btn small" data-kit="disconnect">Disconnect</button>'
        : `<button type="button" class="btn small primary" data-kit="connect" ${supported ? '' : 'disabled'}>Connect kit (USB)</button>`}
      <button type="button" class="btn small" data-kit="close" aria-label="Close field kit panel">✕</button>
    </div>
    <p class="hint" id="kp-status"></p>
    ${supported ? '' : '<p class="caveat">USB connection needs Chrome or Edge on a computer, with the app opened at http://localhost:8080.</p>'}
    ${live ? '' : '<p class="caveat">No device connected. These values are <b>simulated</b> from NASA POWER monthly averages for the kit location, with a daily cycle. They are not measurements.</p>'}
    <div class="kp-charts">${CHARTS.map(([k, label]) => `<canvas data-chart="${k}" aria-label="${esc(label)} chart${live ? '' : ', simulated values'}" role="img"></canvas>`).join('')}</div>
    <div class="section"><span class="label">This spot right now vs the target</span><div id="kp-live"></div>
      <form id="kp-k" class="kp-form">
        <label>Albedo calibration k <input name="k" type="number" step="0.001" min="${K_MIN}" max="${K_MAX}" value="${kit.albK}" required></label>
        <button type="submit" class="btn small">Save k</button>
      </form>
      <p class="src">${kit.albK === 1 ? 'k = 1: <b>not calibrated</b>.' : `k = ${esc(kit.albK)}.`} k is the UP/DOWN ratio of the two light sensors side by side, both facing up (WIRING.md, test 4). Albedo = down × k / up, for real kit readings.</p>
    </div>
    <div class="section"><span class="label">Kit location</span>
      <div id="kp-loc"></div>
      <div class="actions" style="margin-top:6px">
        <button type="button" class="btn small" data-kit="geo">Use this computer's location</button>
        <button type="button" class="btn small" data-kit="manual">Type coordinates</button>
      </div>
      <p class="src">A location you set is sent to NASA POWER (power.larc.nasa.gov), rounded to about 1 km, to get its climate averages.</p>
      <form id="kp-manual" class="kp-form" hidden>
        <label>Latitude <input name="lat" type="number" step="0.0001" min="-90" max="90" required></label>
        <label>Longitude <input name="lon" type="number" step="0.0001" min="-180" max="180" required></label>
        <label>Elevation (m, optional) <input name="elev" type="number" step="1" min="-500" max="9000" placeholder="from a map or GPS"></label>
        <label>Name <input name="label" type="text" maxlength="40" placeholder="e.g. University roof"></label>
        <button type="submit" class="btn small primary">Save</button>
      </form>
    </div>
    <div class="section"><span class="label">24-hour log</span>
      <p class="hint">The kit can record one reading per minute in its own memory, even on a power bank. Then read it here and compare each 24-hour window with NASA POWER.</p>
      ${kit.viaBase ? '<p class="caveat">Connected through the base station: logging commands only work on the kit\'s own USB port (WIRING.md, section 8).</p>' : ''}
      <div class="actions" style="margin-top:6px">
        <button type="button" class="btn small" data-kit="log-start" ${logOk ? '' : 'disabled'}>Start logging (60 s)</button>
        <button type="button" class="btn small" data-kit="log-stop" ${logOk ? '' : 'disabled'}>Stop</button>
        <button type="button" class="btn small" data-kit="log-dump" ${logOk ? '' : 'disabled'}>Read log from kit</button>
        <button type="button" class="btn small" data-kit="log-clear" ${logOk ? '' : 'disabled'}>Erase kit log</button>
        <button type="button" class="btn small" data-kit="import">Import CSV file</button>
        <input id="kp-file" type="file" accept=".csv,text/csv" hidden>
        <button type="button" class="btn small" data-kit="log-save" ${kit.log ? '' : 'disabled'}>Save log as CSV</button>
      </div>
      <div id="kp-log"></div>
    </div>
    <div class="section"><span class="label">Messages from the kit</span><ul class="kp-msgs" id="kp-msgs"></ul></div>`;
  renderStatus();
  renderLocation();
  renderLive();
  renderLog();
  renderMessages();
}

function renderStatus() {
  const el = $('#kp-status');
  if (!el) return;
  if (kit.source !== 'usb') { el.textContent = 'Not connected.'; return; }
  const s = kit.status || {};
  const bits = [s.fw ? `firmware ${s.fw}` : null, s.bme ? `air sensor ${s.bme}` : null,
    s.log != null ? (s.log ? `logging every ${s.interval || 60} s (${s.rows ?? 0} rows)` : 'not logging') : null,
    s.time != null ? (s.time ? 'clock set' : 'clock not set') : null,
    kit.viaBase ? `through the base station, radio link ${kit.latest?.rssi ?? ''} dBm` : 'USB'].filter(Boolean);
  el.textContent = `Connected · ${bits.join(' · ')}`;
}

// NASA POWER cell elevation vs the ground at the kit location: the same 400 m rule as for the sites.
function cellCheck() {
  const cell = kit.powerHere?.cellElev;
  if (!Number.isFinite(cell)) return null;
  const ground = kit.location?.elev;
  if (!Number.isFinite(ground)) return { cell, ground: null };
  const gap = cell - ground;
  return { cell, ground, gap, flagged: Math.abs(gap) > CELL_GAP_LIMIT_M };
}

// The ⚑ warning text (or '' when the rule does not apply).
function cellFlagText(q) {
  if (!q || !q.flagged) return '';
  return `⚑ Data quality: the NASA POWER grid cell sits at ${fmt(q.cell, 0)} m, but the ground here is at ${fmt(q.ground, 0)} m, so the cell is ${fmt(Math.abs(q.gap), 0)} m ${q.gap > 0 ? 'higher' : 'lower'} (our limit is ${CELL_GAP_LIMIT_M} m). Expect a working kit to read ${q.gap < 0 ? 'cooler, with lower pressure,' : 'warmer, with higher pressure,'} than this cell's averages. The numbers are not corrected.`;
}

function renderLocation() {
  const el = $('#kp-loc');
  if (!el) return;
  const L = kit.location;
  const q = cellCheck();
  const from = L.source === 'default' ? 'default, set your own' : L.source === 'browser' ? 'from this computer, about 1 km' : 'typed by hand';
  const ground = !q ? '' : q.ground == null ? 'ground here not measured (type it with the coordinates)'
    : `ground here ${fmt(q.ground, 0, 'm')} (${L.elevSource ? esc(L.elevSource) : 'typed by hand'})`;
  el.innerHTML = `<p>${esc(L.label)} · ${fmtCoord(L.lat, L.lon)} <span class="src">(${from})</span></p>
    ${q ? `<p class="src">NASA POWER cell elevation ${fmt(q.cell, 0, 'm')} · ${ground}</p>` : ''}
    ${q?.flagged ? `<p class="caveat">${cellFlagText(q)}</p>` : ''}`;
}

function renderLive() {
  const panel = $('#kit-panel');
  if (!panel || panel.hidden) return;
  const sim = kit.source !== 'usb';
  for (const [key, label, unit, digits, color, minSpan] of CHARTS) {
    const c = panel.querySelector(`canvas[data-chart="${key}"]`);
    if (c) drawChart(c, kit.history.map((r) => ({ t: r.t, v: r[key] })), { label, unit, digits, minSpan, color: sim ? '#ffb547' : color, note: sim ? 'Simulated' : '' });
  }
  const target = findTarget(state.data, state.targetId);
  const s = liveScore(target);
  const alb = albedoNow();
  const log = logSummary();
  const kText = kit.source === 'usb' ? ` × k ${kit.albK}${kit.albK === 1 ? ' (not calibrated)' : ''}` : '';
  const unitOf = (f) => f.unit;
  const rows = s.rows.map((r) => {
    const f = r.factor;
    const why = {
      meanTemp: 'air now',
      albedo: `down/up light${kText}${alb.n ? `, median of ${alb.n} readings in 1 min` : ''}`,
      swing: 'from the loaded log',
      coldGround: log.cold ? `log minimum, ${log.cold.from}` : 'log minimum',
      rain: 'not measured by the kit',
    }[f.id];
    const missing = f.id === 'coldGround' && log.cold ? 'surface measurement needed' : f.id === 'swing' || f.id === 'coldGround' ? 'needs a full 24 h log window' : f.id === 'albedo' ? alb.why : 'not measured';
    return `<tr><td>${esc(f.short)} <span class="src">${esc(why)}</span></td>
      <td class="num">${r.earth == null ? `<span class="src">${esc(missing)}</span>` : fmt(r.earth, f.digits, unitOf(f))}</td>
      <td class="num">${r.target == null ? '<span class="src">not measured</span>' : fmt(r.target, f.digits, unitOf(f))}</td>
      <td class="match">${r.excluded ? `<span title="${esc(r.excluded)}">Not scored</span>` : r.score == null ? '—' : `${pct(r.score)}%`}</td></tr>`;
  }).join('');
  $('#kp-live').innerHTML = `
    <table class="facts"><thead><tr><th>Factor</th><th>${kit.source === 'usb' ? 'Kit now' : 'Simulated now'}</th><th>${esc(target.name.split(' (')[0])}</th><th>Match</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="src">${s.score == null ? 'No comparable snapshot score yet.' : `${sim ? 'Simulated' : 'Live'} snapshot score: <b>${pct(s.score)}%</b> from ${s.used} factors.`} The snapshot covers a different time window from the site rankings.${sim && kit.log ? ' Daily swing and the ground reading use the imported log when available.' : ''}</p>`;
}

function renderMessages() {
  const el = $('#kp-msgs');
  if (!el) return;
  el.innerHTML = kit.messages.length
    ? kit.messages.slice(-12).reverse().map((m) => `<li><span class="src">${new Date(m.t).toLocaleTimeString()}</span> ${esc(m.text)}</li>`).join('')
    : '<li class="src">No messages yet.</li>';
}

// ---------- log (device memory or CSV file) ----------
export function parseCsv(text) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith('#') && !l.startsWith('{'));
  if (!lines.length) return [];
  const header = lines[0].split(',').map((h) => h.trim().toLowerCase());
  if (!header.includes('air')) throw new Error('This file has no "air" column. Use a log saved by the kit or by this app.');
  return lines.slice(1).map((line) => {
    const cells = line.split(',');
    const row = {};
    header.forEach((h, i) => {
      if (!CSV_COLS.includes(h)) return; // unknown columns are ignored
      const cell = (cells[i] ?? '').trim();
      const v = cell === '' ? null : Number(cell);
      row[h] = Number.isFinite(v) ? v : null;
      if (row[h] == null && LIMIT_TEXT.test(cell)) { // keep "<1.0" and ">121557": limits, not values
        row.limits = row.limits || {};
        row.limits[h] = cell;
      }
    });
    return row;
  });
}

// Nearest row by kit timer (ms) in a list sorted by ms.
function nearest(list, ms) {
  if (!list || !list.length) return null;
  let lo = 0;
  let hi = list.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (list[mid].ms <= ms) lo = mid; else hi = mid;
  }
  return Math.abs(list[lo].ms - ms) <= Math.abs(list[hi].ms - ms) ? list[lo] : list[hi];
}

// Gives every log row a time r.t (ms since 1970) and says where it came from (r.how),
// following PROTOCOL.md section 7:
//   'clock'   the kit clock (unix column) of that row;
//   'boot'    another row of the same boot has a kit-clock time: unix_ref + (ms - ms_ref);
//   'typed'   the start time the user typed for that boot: start + ms;
//   'file'    a time this app rebuilt earlier and saved in the est_unix column;
//   'unknown' none of these: r.t = null. A time is never invented.
export function timeRows(raw, starts = {}) {
  const refs = new Map();
  for (const r of raw) {
    if (!validUnix(r.unix) || !Number.isFinite(r.ms) || r.boot == null) continue;
    if (!refs.has(r.boot)) refs.set(r.boot, []);
    refs.get(r.boot).push(r);
  }
  for (const list of refs.values()) list.sort((a, b) => a.ms - b.ms);
  const rows = raw.map((r) => {
    if (validUnix(r.unix)) return { ...r, t: r.unix * 1000, how: 'clock' };
    const ref = Number.isFinite(r.ms) ? nearest(refs.get(r.boot), r.ms) : null;
    if (ref) return { ...r, t: ref.unix * 1000 + (r.ms - ref.ms), how: 'boot' };
    if (Number.isFinite(starts[r.boot]) && Number.isFinite(r.ms)) return { ...r, t: starts[r.boot] + r.ms, how: 'typed' };
    if (validUnix(r.est_unix)) return { ...r, t: r.est_unix * 1000, how: 'file' };
    return { ...r, t: null, how: 'unknown' };
  });
  rows.sort((a, b) => (a.t == null || b.t == null ? (a.t == null) - (b.t == null) : a.t - b.t));
  return rows;
}

// Returns false (and keeps the old log) when there are no rows.
function setLog(raw, from) {
  if (!raw.length) return false;
  kit.log = { raw, from, starts: {}, rows: timeRows(raw, {}) };
  refreshLog();
  return true;
}

function refreshLog() {
  const save = $('[data-kit="log-save"]');
  if (save) save.disabled = !kit.log;
  renderLog();
  renderLive();
  emit('kit', kit);
}

function finishDump() {
  const lines = dump || [];
  dump = null;
  try {
    const raw = parseCsv(lines.join('\n'));
    if (setLog(raw, 'kit memory')) toast(`Read ${raw.length} rows from the kit.`);
    else toast('The kit log is empty.');
  } catch (err) {
    toast(err.message, 5000);
  }
}

// One summary per boot (power-on) of the kit: rows, kit timer, largest gap, where the times come from.
function bootSummary(rows) {
  const boots = new Map();
  for (const r of rows) {
    if (r.boot == null) continue;
    if (!boots.has(r.boot)) boots.set(r.boot, []);
    boots.get(r.boot).push(r);
  }
  return [...boots].map(([boot, list]) => {
    const ms = list.map((r) => r.ms).filter(Number.isFinite).sort((a, b) => a - b);
    let gap = 0;
    for (let i = 1; i < ms.length; i++) gap = Math.max(gap, ms[i] - ms[i - 1]);
    const hows = new Set(list.map((r) => r.how));
    return { boot, n: list.length, first: ms[0], last: ms[ms.length - 1], gap, hows, canType: ms.length > 0 && !hows.has('clock') && !hows.has('boot') };
  }).sort((a, b) => a.boot - b.boot);
}

const HOW_TEXT = { clock: 'kit clock', boot: 'kit clock + kit timer', typed: 'start time you typed', file: 'estimated earlier (est_unix)', unknown: 'unknown' };
// No-break spaces: a narrow table cell wraps only between the two times.
const hm = (ms) => (Number.isFinite(ms) ? `${Math.floor(ms / 3600e3)}\u00a0h\u00a0${String(Math.floor(ms / 60e3) % 60).padStart(2, '0')}\u00a0min` : '—');

// Value for a datetime-local input (local time of this computer, with seconds).
function localInputValue(t) {
  if (!Number.isFinite(t)) return '';
  const d = new Date(t);
  const p = (v) => String(v).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function renderBoots(L) {
  const boots = bootSummary(L.rows);
  if (!boots.length) return '';
  // The kit timer cell may wrap and the start-time forms sit below the table, so it fits a phone screen.
  const rows = boots.map((b) => `<tr><td>${esc(b.boot)}</td><td class="num">${b.n}</td>
    <td>${hm(b.first)} → ${hm(b.last)}</td><td class="num">${b.gap ? `${fmt(b.gap / 60e3, 0)} min` : '—'}</td>
    <td>${esc([...b.hows].map((h) => HOW_TEXT[h]).join(', '))}</td></tr>`).join('');
  const forms = boots.filter((b) => b.canType).map((b) => `
    <form class="kp-form" data-boot="${esc(b.boot)}"><label>Boot ${esc(b.boot)} started at <input name="start" type="datetime-local" step="1" required value="${localInputValue(L.starts[b.boot])}"></label>
      <button type="submit" class="btn small">Use</button></form>`).join('');
  return `<table class="facts"><thead><tr><th>Boot</th><th>Rows</th><th>Kit timer</th><th>Largest gap</th><th>Time from</th></tr></thead><tbody>${rows}</tbody></table>${forms}
    <p class="src">Kit timer = time since that power-on. A boot without the kit clock needs the time it started (WIRING.md, section 10, option B); until then its rows have no time and are left out of the windows.</p>`;
}

function renderLog() {
  const el = $('#kp-log');
  if (!el) return;
  const L = kit.log;
  if (!L) { el.innerHTML = '<p class="src">No log loaded.</p>'; return; }
  const timed = L.rows.filter((r) => r.t != null);
  const n = {};
  for (const r of L.rows) n[r.how] = (n[r.how] || 0) + 1;
  const notes = [
    n.boot ? `${n.boot} rows timed from the kit clock of the same boot and the kit timer` : '',
    n.typed ? `${n.typed} rows timed from a start time you typed` : '',
    n.file ? `${n.file} rows with times estimated earlier (est_unix column)` : '',
    n.unknown ? `<b>${n.unknown} rows with time unknown</b>` : '',
  ].filter(Boolean);
  const wins = dayWindows(L.rows);
  const P = kit.powerHere;
  const q = cellCheck();
  const monthName = (m) => ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][m];
  const table = wins.map((w) => {
    const pMean = P ? P.monthly.T2M[w.month] : null;
    const pRange = P ? P.monthly.T2M_RANGE[w.month] : null;
    const last = w.rows[w.rows.length - 1];
    return `<tr><td>${esc(shortTime(w.rows[0].t))} → ${esc(shortTime(last.t))}${w.full ? '' : ` <span class="src">(partial: ${fmt(w.span / 3600e3, 1)} h${w.gap > MAX_GAP_MS ? `, gap ${fmt(w.gap / 3600e3, 1)} h` : ''})</span>`}</td>
      <td class="num">${w.full ? fmt(w.mean, 1, '°C') : '—'}</td><td class="num">${fmt(pMean, 1, '°C')}</td>
      <td class="num">${w.full ? fmt(w.range, 1, '°C') : '—'}</td><td class="num">${fmt(pRange, 1, '°C')}</td></tr>`;
  }).join('');
  el.innerHTML = `
    <p class="src">${L.rows.length} rows from ${esc(L.from)}${timed.length ? ` · ${new Date(timed[0].t).toLocaleString()} → ${new Date(timed[timed.length - 1].t).toLocaleString()}` : ' · no row has a known time yet'}${notes.length ? ` · ${notes.join(' · ')}. Times that did not come from the kit clock are estimates; "Save log as CSV" keeps them apart in the est_unix column.` : ''}</p>
    ${renderBoots(L)}
    ${wins.length ? `<table class="facts"><thead><tr><th>24-hour window</th><th>Mean air (kit)</th><th>NASA POWER mean</th><th>Daily range (kit)</th><th>NASA POWER range</th></tr></thead><tbody>${table}</tbody></table>` : ''}
    <p class="src">Each window is 24 hours from the first timed row. It counts as a full day with at least 20 hours of data and no gap over 1 hour; partial windows are not compared, because their mean leans to the hours they cover. NASA POWER: 2001–2020 average for the same month at the kit location (${P ? esc(P.label) : 'not loaded'}${q ? `, cell elevation ${fmt(q.cell, 0, 'm')}` : ''}). One day of weather can differ from a 20-year average; the comparison checks that the kit gives realistic numbers.${wins.length ? ` Month: ${monthName(wins[0].month)}.` : ''}</p>
    ${q?.flagged ? `<p class="caveat">${cellFlagText(q)}</p>` : ''}`;
}

// CSV with the kit-clock time (unix) and the app's estimated time (est_unix) in separate columns.
function csvCell(r, c) {
  if (c === 'unix') return validUnix(r.unix) ? r.unix : '';
  if (c === 'est_unix') return r.how !== 'clock' && Number.isFinite(r.t) ? Math.round(r.t / 1000) : '';
  if (Number.isFinite(r[c])) return r[c];
  return r.limits?.[c] || '';
}

// The CSV text of log rows: what "Save log as CSV" writes and parseCsv reads back.
export function logCsv(rows) {
  const lines = [CSV_COLS.join(',')].concat(rows.map((r) => CSV_COLS.map((c) => csvCell(r, c)).join(',')));
  return `${lines.join('\n')}\n`;
}

function saveCsv() {
  if (!kit.log) return;
  const blob = new Blob([logCsv(kit.log.rows)], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `analog-atlas-log-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ---------- location & NASA POWER for it ----------
async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Loads the NASA POWER climatology for a location into kit.powerHere. Returns true on success.
async function loadPowerFor(loc) {
  const lat = loc.lat.toFixed(2);
  const lon = loc.lon.toFixed(2);
  const key = `analog-atlas-power-${lat}-${lon}`;
  try {
    let doc = null;
    if (loc.powerFile) {
      doc = await fetchJson(loc.powerFile);
    } else {
      try { doc = JSON.parse(localStorage.getItem(key) || 'null'); } catch { doc = null; }
      if (!doc?.properties?.parameter) {
        const url = `https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=T2M,T2M_RANGE,RH2M,PS,TS,ALLSKY_SFC_UV_INDEX,ALLSKY_SRF_ALB&community=RE&longitude=${lon}&latitude=${lat}&format=JSON`;
        doc = await fetchJson(url);
        if (doc?.properties?.parameter) {
          try { localStorage.setItem(key, JSON.stringify(doc)); } catch { /* storage may be blocked */ }
        }
      }
    }
    const params = doc?.properties?.parameter;
    if (!params) throw new Error('the answer has no NASA POWER values');
    const fill = doc.header?.fill_value ?? -999;
    const val = (v) => (Number.isFinite(v) && v !== fill ? v : null);
    const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
    const elev = doc.geometry?.coordinates?.[2];
    kit.powerHere = {
      label: loc.label,
      cellElev: Number.isFinite(elev) ? elev : null, // elevation of the NASA POWER grid cell (m)
      annual: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, val(v.ANN)])),
      monthly: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, months.map((m) => val(v[m]))])),
    };
    return true;
  } catch (err) {
    console.warn('NASA POWER for the kit location failed', err);
    return false;
  }
}

async function setLocation(loc) {
  if (!(await loadPowerFor(loc))) {
    toast(`NASA POWER is not available for that point right now. The kit location stays ${kit.location.label}.`, 5000);
    return;
  }
  kit.location = loc;
  try { localStorage.setItem(STORE_KEY, JSON.stringify(loc)); } catch { /* storage may be blocked */ }
  for (const r of kit.history) albedoOf(r); // the sun height depends on the location
  renderLocation();
  renderLog();
  renderLive();
  emit('kit', kit);
}

// A saved location from localStorage, checked field by field.
function savedLocation() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch { s = null; }
  if (!s || !Number.isFinite(s.lat) || !Number.isFinite(s.lon) || Math.abs(s.lat) > 90 || Math.abs(s.lon) > 180) return null;
  const loc = { lat: s.lat, lon: s.lon, label: String(s.label || 'Kit location').slice(0, 40), source: s.source === 'browser' ? 'browser' : 'manual' };
  if (Number.isFinite(s.elev)) loc.elev = s.elev;
  return loc;
}

function savedK() {
  try {
    const v = Number(localStorage.getItem(K_KEY));
    return v >= K_MIN && v <= K_MAX ? v : 1;
  } catch {
    return 1;
  }
}

function setK(k) {
  kit.albK = k;
  try { localStorage.setItem(K_KEY, String(k)); } catch { /* storage may be blocked: k is kept until the page reloads */ }
  for (const r of kit.history) albedoOf(r);
  toast(k === 1 ? 'Albedo calibration k = 1 (not calibrated).' : `Albedo calibration k = ${k} saved.`);
  renderPanel();
}

// ---------- panel events ----------
function onPanelClick(e) {
  const b = e.target.closest('[data-kit]');
  if (!b) return;
  const a = b.dataset.kit;
  if (a === 'close') { closePanel(); return; }
  if (a === 'connect') { connect(); return; }
  if (a === 'disconnect') { serial?.disconnect(); return; }
  if (a === 'log-start') { logCommand('LOG START 60', (s) => s.log === true && s.interval === 60, 'Logging started: one reading per minute.'); return; }
  if (a === 'log-stop') { logCommand('LOG STOP', (s) => s.log === false, 'Logging stopped.'); return; }
  if (a === 'log-dump') { send('LOG DUMP'); toast('Reading the log from the kit…'); return; }
  if (a === 'log-clear') {
    if (window.confirm('Erase the log stored on the kit? This cannot be undone.')) logCommand('LOG CLEAR', (s) => s.rows === 0, 'The kit log is erased.');
    return;
  }
  if (a === 'log-save') { saveCsv(); return; }
  if (a === 'import') { $('#kp-file').click(); return; } // a button, so the keyboard reaches it (the file input stays hidden)
  if (a === 'manual') { const f = $('#kp-manual'); f.hidden = !f.hidden; return; }
  if (a === 'geo') {
    if (!navigator.geolocation) { toast('This browser cannot give a location.'); return; }
    navigator.geolocation.getCurrentPosition(
      // 2 decimals (about 1 km): the NASA POWER grid is 0.5° × 0.625°, so more precision adds nothing.
      (p) => setLocation({ lat: +p.coords.latitude.toFixed(2), lon: +p.coords.longitude.toFixed(2), label: 'This computer', source: 'browser' }),
      (err) => toast(`Location not available: ${err.message}`, 5000),
      { enableHighAccuracy: false, timeout: 15000 },
    );
  }
}

function onManualSubmit(form) {
  const f = new FormData(form);
  const lat = Number(f.get('lat'));
  const lon = Number(f.get('lon'));
  const elevText = String(f.get('elev') || '').trim();
  const elev = elevText === '' ? null : Number(elevText);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) { toast('Please type a valid latitude and longitude.'); return; }
  if (elev != null && !Number.isFinite(elev)) { toast('Please type the elevation in metres, or leave it empty.'); return; }
  const loc = { lat, lon, label: String(f.get('label') || 'Kit location').slice(0, 40), source: 'manual' };
  if (elev != null) loc.elev = elev;
  setLocation(loc);
}

function onKSubmit(form) {
  const k = Number(new FormData(form).get('k'));
  if (!Number.isFinite(k) || k < K_MIN || k > K_MAX) { toast(`Please type k between ${K_MIN} and ${K_MAX} (1 = not calibrated).`); return; }
  setK(k);
}

// The user typed when a boot without the kit clock started (WIRING.md section 10, option B).
function onBootStart(form) {
  if (!kit.log) return;
  const boot = Number(form.dataset.boot);
  const start = new Date(String(new FormData(form).get('start') || '')).getTime(); // local time of this computer
  if (!Number.isFinite(start)) { toast('Please type the date and time when that boot started.'); return; }
  kit.log.starts[boot] = start;
  kit.log.rows = timeRows(kit.log.raw, kit.log.starts);
  refreshLog();
  toast(`Boot ${boot}: times rebuilt from the start time you typed.`);
}

export function openPanel() {
  const el = $('#kit-panel');
  el.hidden = false;
  renderPanel();
  $('#kit-btn').setAttribute('aria-expanded', 'true');
  el.querySelector('[data-kit="close"]').focus({ preventScroll: true });
}

export function closePanel() {
  const el = $('#kit-panel');
  const hadFocus = el.contains(document.activeElement);
  el.hidden = true;
  $('#kit-btn').setAttribute('aria-expanded', 'false');
  if (hadFocus) $('#more-btn').focus();
}

export function togglePanel() {
  if ($('#kit-panel').hidden) openPanel(); else closePanel();
}

// For testing the parser from the browser console without hardware:
//   __atlas.kitFeed('{"t":1000,"air":21.5,"rh":40,"lux_up":52000,"lux_down":15000}')
export function feedLine(line) { onLine(line); }

export function refreshKit() {
  if (!$('#kit-panel').hidden) renderLive();
}

export async function initKit() {
  kit.albK = savedK();
  kit.location = savedLocation() || DEFAULT_LOCATION;
  if (!(await loadPowerFor(kit.location)) && kit.location !== DEFAULT_LOCATION) {
    // Fall back to the bundled Amman file so the simulation still works offline.
    // The saved location stays in storage and is tried again next time.
    kit.location = DEFAULT_LOCATION;
    await loadPowerFor(kit.location);
    toast('NASA POWER could not be reached for your saved kit location, so the kit uses Amman for now.', 6000);
  }
  const panel = $('#kit-panel');
  panel.addEventListener('click', onPanelClick);
  panel.addEventListener('submit', (e) => {
    e.preventDefault();
    if (e.target.id === 'kp-manual') onManualSubmit(e.target);
    else if (e.target.id === 'kp-k') onKSubmit(e.target);
    else if (e.target.dataset.boot != null) onBootStart(e.target);
  });
  panel.addEventListener('change', async (e) => {
    if (e.target.id !== 'kp-file' || !e.target.files[0]) return;
    try {
      if (!setLog(parseCsv(await e.target.files[0].text()), e.target.files[0].name)) toast('The file has no log rows.');
    } catch (err) {
      toast(err.message, 5000);
    }
    e.target.value = '';
  });
  $('#kit-btn').addEventListener('click', togglePanel);
  if (navigator.serial) {
    navigator.serial.addEventListener('connect', () => toast('A USB device was plugged in. Press "Connect kit (USB)".'));
  }
  startSim();
}
