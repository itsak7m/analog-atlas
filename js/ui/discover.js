// Discover Jordan: the tabs of the ranking panel, the Top 10 list of 10 km screening boxes, its notes
// and the "All boxes" table. The boxes are scored by js/screening.js (scoreBoxes) with the same method
// as the hand-picked sites, resources left out. Boxes never appear in the site list.

import { state } from '../state.js';
import { ROCK_LABEL, pct } from '../scoring.js';
import { $, $$, esc, fmtCoord, toast } from '../util.js';
import { findSite, findTarget } from '../data.js';
import { gapWords, noScoreText, scoreLabel, surfaceHint } from './ranking.js';
import { openOverlay, closeOverlay } from './overlay.js';
import { scoreBoxes, getScreening, statusText, notListedText, boxesCsv, FLAG_WORDS, SCREEN_LABEL } from '../screening.js';

let lastPick = null;

const shortName = (name) => String(name || '').split(',')[0].split(' (')[0];
const modeText = () => scoreLabel().toLowerCase();
const currentTarget = () => findTarget(state.data, state.targetId);

// The scoreBoxes() result for the current settings (state.screenRanked when main.js keeps it), or null before loading.
export const currentResult = () => state.screenRanked || scoreBoxes();

// The loaded data/screening_jordan.json.
export const screenDoc = () => getScreening()?.doc || state.screening?.doc || null;

// "34 km SE of Qa' al-Jafr", from the box record's nearestSite.
export function nearText(rec) {
  const n = rec && rec.nearestSite;
  if (!n || n.km == null) return '';
  const site = findSite(state.data, n.id);
  return `${Math.round(n.km)} km ${n.dir ? `${n.dir} ` : ''}of ${shortName(site ? site.name : n.id)}`;
}

// The Atlas site inside a box (containsSite is a site id, or true with nearestSite naming it).
export function containedSite(rec) {
  const c = rec && rec.containsSite;
  if (!c) return null;
  return findSite(state.data, typeof c === 'string' ? c : rec.nearestSite?.id) || null;
}

// Why a box is not listed, in plain words (row.why[0] from scoreBoxes).
export function whyWords(row) {
  const why = row && row.why && row.why[0];
  if (!why) return '';
  if (why === 'incomplete') return `no ${gapWords(row.missing || [])} data`;
  return { water: 'mostly water', site: 'holds an Atlas site', cellGap: '⚑ climate cell height differs', noScore: 'no score' }[why] || why;
}

const rockOf = (box) => (box.geology?.primary ? ROCK_LABEL[box.geology.primary] || box.geology.primary : '');

// ---------- tabs ----------

// Show the Discover list (true) or the hand-picked sites (false). Only changes the ranking panel.
export function setDiscoverTab(on) {
  $$('#rank-tabs button').forEach((b) => b.setAttribute('aria-pressed', String((b.dataset.tab === 'discover') === !!on)));
  $('#discover-panel').hidden = !on;
  $('#rank-list').hidden = !!on;
  $('#rank-hint').hidden = !!on;
  $('#discover-legend').hidden = !on;
  if (!on) setLegend(null);
  $('#rank-lead').textContent = on ? 'Top 10 boxes in Jordan for' : 'Earth twins of';
  document.body.classList.toggle('discover-on', !!on);
}

// Wire the two tabs and the "All boxes" button (call once). onTab('sites' | 'discover') decides what
// happens: switch to Earth, load the data, then setDiscoverTab(). onPick(boxId) selects a box.
export function initDiscover({ onTab, onPick } = {}) {
  if (onPick) lastPick = onPick;
  $$('#rank-tabs button').forEach((b) => b.addEventListener('click', () => {
    if (onTab) onTab(b.dataset.tab);
    else setDiscoverTab(b.dataset.tab === 'discover');
  }));
  $('#discover-all').addEventListener('click', () => openAllBoxes());
}

// ---------- the Top 10 list ----------

function hintText(target, result) {
  const base = state.mode === 'full'
    ? 'Awaiting field checks · no resources data'
    : 'Awaiting field checks · climate match';
  const first = result && result.rows[0];
  const gaps = state.mode === 'full' && first ? (first.targetGaps || []).filter((g) => g !== 'resources' && state.pillars[g] > 0) : [];
  return `${base}${gaps.length ? ` · insufficient ${gapWords(gaps)} data at the target` : ''}${state.strict ? ' · strict data' : ''}${surfaceHint()}`;
}

// The fair comparison, above the list: the best hand-picked Jordan site scored like a box (a box % leaves
// resources out, so it can only be compared with a site % that also leaves them out).
function compareHTML(result) {
  const best = result && (result.sites || []).find((s) => s.score != null);
  if (!best) return '';
  const how = state.mode === 'full' ? 'same method, no resources' : 'same climate match';
  return `<br><b>Compare:</b> ${esc(shortName(best.site.name))} <b>${best.pct}%</b> (best hand-picked Jordan site, ${how})`;
}

// One Top 10 row: the lead box of a cluster, "+N nearby" at the same %, and the nearest Atlas site.
function rowHTML(c, selectedId) {
  const r = c.lead;
  const box = r.box;
  const rock = rockOf(box);
  const more = c.nearby ?? c.members.length - 1;
  const near = nearText(r.rec);
  const where = fmtCoord(box.lat, box.lon);
  const current = selectedId != null && c.members.some((m) => m.id === selectedId);
  const coverage = state.mode === 'full' ? `${r.pillarsUsed} of ${r.pillarsEnabled} enabled pillars used` : '';
  const aria = `${c.tie ? 'Tied rank ' : 'Rank '}${c.rank}: ${near ? `${near} (${box.name})` : box.name}, ${where}${rock ? `, ${rock}` : ''}, ${r.pct} percent ${modeText()}${coverage ? `, ${coverage}` : ''}${more ? `, plus ${more} nearby ${more === 1 ? 'box' : 'boxes'} at the same percent` : ''}.`;
  const nearby = more ? `<span class="tag near" title="${more} more ${more === 1 ? 'box' : 'boxes'} next to it ${more === 1 ? 'scores' : 'score'} the same %">+${more} nearby</span>` : '';
  // Name, bar and % on the first line; the details below use the full width of the row.
  // The readable name is the nearest Atlas site and the direction ("25 km SW of Harrat al-Shaam");
  // the grid code ("Box r32 c18") means nothing to a visitor, so it is only in the tooltip (and on the box page).
  return `<li><button type="button" class="rank-row" data-id="${esc(r.id)}" aria-current="${current}" aria-label="${esc(aria)}" title="${esc(box.name)}" style="--c:${esc(r.fill.css)}">
      <span class="n">${c.tie ? '=' : ''}${c.rank}</span><span class="nm">${esc(near || box.name)}</span>
      <span class="bar" aria-hidden="true"><i style="width:${r.pct}%"></i></span><span class="pc">${r.pct}%</span>
      <span class="meta"><span class="co">${esc(where)}</span>${rock ? `<span class="tag rock">${esc(rock)}</span>` : ''}${coverage ? `<span class="tag" title="${coverage}">${r.pillarsUsed}/${r.pillarsEnabled}</span>` : ''}</span>
      ${nearby ? `<span class="meta">${nearby}</span>` : ''}
    </button></li>`;
}

// The colour legend: the stretched range of the Discover layer, or the fixed 30-70 % scale of the sites.
function setLegend(range) {
  const lo = range ? `${pct(range.lo)}%` : '30%';
  const hi = range ? `${pct(range.hi)}%` : '70%+';
  $('#legend-lo').textContent = lo;
  $('#legend-hi').textContent = hi;
  $('#legend').setAttribute('aria-label', range ? `Box colours stretched for this target, from ${lo} to ${hi}` : 'Colour scale from 30 percent to 70 percent or more');
}

// The exclusions line under the list. Mostly-water boxes are not drawn on the globe (boxFill hides them),
// so "all stay on the map" is narrowed when there are any.
export function exclusionsText(result) {
  const text = notListedText(result);
  if (!text || !result.notListed.water) return text;
  return text.replace(/ — all stay on the map$/, ' — all stay in the table and, apart from the water boxes, on the map');
}

// (The fair comparison with the best hand-picked site is above the list: compareHTML.)
function notesHTML(result) {
  const excl = exclusionsText(result) || 'Every box with a score is listed';
  return `<p>${esc(excl)}. <span title="⚑ = the NASA POWER cell is more than 400 m higher or lower than the ground at the box centre">⚑ = climate cell height differs.</span></p>
    <p>Differences of 1–2 points are within the resolution of the data.</p>`;
}

// Render the Top 10 for the current target and settings. result: a scoreBoxes() result (default: the
// current one). Returns { listed, top } (number of listed boxes, top %), or null while loading.
export function renderDiscover({ result = currentResult(), target = currentTarget(), selectedId = null, onPick } = {}) {
  if (onPick) lastPick = onPick;
  const list = $('#discover-list');
  $('#rank-target').textContent = target.name;
  $('#discover-hint').innerHTML = `${esc(hintText(target, result))}${compareHTML(result)}`;
  if (!result) {
    list.innerHTML = '<li class="msg hint">Loading the Jordan boxes…</li>';
    $('#discover-notes').innerHTML = '';
    return null;
  }
  if (result.top.length) {
    list.innerHTML = result.top.map((c) => rowHTML(c, selectedId)).join('');
  } else {
    // noScoreText speaks about sites; here the rows are boxes.
    const why = result.rows.length && result.scored === 0
      ? noScoreText(result.rows, target).replace('no site gets a score', 'no box gets a score')
      : 'No box meets the listing rules for this target. All boxes stay on the map and in the table.';
    list.innerHTML = `<li class="msg caveat">${why}</li>`;
  }
  list.querySelectorAll('.rank-row').forEach((b) => b.addEventListener('click', () => pick(b.dataset.id)));
  $('#discover-notes').innerHTML = notesHTML(result);
  setLegend(result.colourRange);
  return { listed: result.listed.length, top: result.listed.length ? result.listed[0].pct : null };
}

// A message in place of the list, e.g. NOT_BUILT from js/screening.js when the data file is missing.
export function renderDiscoverMessage(text) {
  $('#discover-list').innerHTML = `<li class="msg caveat">${esc(text)}</li>`;
  $('#discover-notes').innerHTML = '';
}

// Mark the row whose cluster holds this box (or none).
export function markDiscoverSelected(id) {
  const result = currentResult();
  const row = result && id ? result.byId.get(id) : null;
  const leadId = row && row.cluster != null ? result.clusters[row.cluster].lead.id : id;
  $$('#discover-list .rank-row').forEach((b) => b.setAttribute('aria-current', String(b.dataset.id === leadId)));
  const el = leadId ? document.querySelector(`#discover-list .rank-row[data-id="${CSS.escape(leadId)}"]`) : null;
  if (el) el.scrollIntoView({ block: 'nearest' });
}

// #sr-status: "Discover on: 756 boxes ranked for Jezero Crater; top 89 %".
export function announceDiscover(result = currentResult()) {
  const el = $('#sr-status');
  if (el && result) el.textContent = statusText(result);
}

function pick(id) {
  if (lastPick) lastPick(id);
}

// ---------- "All boxes" table with CSV download ----------

export function openAllBoxes() {
  const result = currentResult();
  if (!result) { toast('The Jordan boxes are not loaded yet.'); return; }
  const target = result.target;
  const rows = result.rows.map((r) => {
    const flags = r.flags.map((f) => FLAG_WORDS[f] || f).join(', ');
    return `<tr${r.eligible ? '' : ' class="off"'}><td class="num">${r.rank == null ? '—' : `${r.tie ? '=' : ''}${r.rank}`}</td>
      <td><span class="sw" aria-hidden="true" style="background:${esc(r.fill.css)};opacity:${Number(r.fill.alpha) || 0}"></span> <button type="button" class="linkish" data-id="${esc(r.id)}">${esc(r.box.name)}</button></td>
      <td class="num">${r.pct == null ? '<span class="src">no score</span>' : `${r.pct}%`}</td>
      <td class="num">${esc(fmtCoord(r.box.lat, r.box.lon))}</td><td>${esc(rockOf(r.box)) || '<span class="src">not mapped</span>'}</td>
      <td>${esc(flags)}</td><td>${r.eligible ? 'yes' : `no · ${esc(whyWords(r))}`}</td></tr>`;
  }).join('');
  const settings = `${modeText()}${state.strict ? ', strict data' : ''}${state.earthTemp === 'surface' ? ', surface temperature (MODIS)' : ''}`;
  const el = openOverlay({
    title: `All ${result.rows.length} boxes in Jordan · ${target.name}`,
    badge: '<span class="tag screen">Screening</span>',
    body: `<div class="sheet-body">
      <p class="screen-label">${esc(screenDoc()?.label || SCREEN_LABEL)}</p>
      <p class="hint">Every 10 km box, scored with the same method as the hand-picked sites (${esc(settings)}; no resources data). Rank counts listed boxes only; boxes with the same % share a rank (=). Faded rows are not listed (the last column says why); they stay in this table and, apart from the mostly-water boxes, on the map. Press a box name to open it.</p>
      <p><button type="button" class="btn small" data-action="boxes-csv">Download this table (CSV)</button></p>
      <div class="boxes-wrap"><table class="facts boxes"><thead><tr><th>Rank</th><th>Box</th><th>Match</th><th>Centre</th><th>Main rock</th><th>Flags</th><th>Listed</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`,
  });
  el.querySelector('[data-action="boxes-csv"]').addEventListener('click', () => downloadBoxes(result));
  el.querySelector('tbody').addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-id]');
    if (!b) return;
    closeOverlay();
    pick(b.dataset.id);
  });
}

function downloadBoxes(result) {
  const blob = new Blob([`${boxesCsv(result)}\r\n`], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `analog-atlas-jordan-boxes-${result.targetId}-${result.mode}${result.strict ? '-strict' : ''}${result.earthTemp === 'surface' ? '-surface' : ''}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
