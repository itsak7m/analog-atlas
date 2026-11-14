// Top bar: world buttons, target picker (Moon | Mars menu) and the main action buttons.

import { esc, BODY_LABEL } from '../util.js';
import { measuredFactors, TARGET_MIN_MEASURED } from '../scoring.js';
import { isStarTarget } from './ranking.js';

// Groups in the target list, in this order: the Moon column first, then the Mars column. The challenge asks for
// permanent Moon base locations and Mars. 'short' is the heading inside the menu; 'label' is the full name.
// Groups with no target are not shown.
export const TARGET_GROUPS = [
  { id: 'moon-base', body: 'moon', short: 'South pole reference sites', label: 'Lunar south pole reference sites' },
  { id: 'moon-cave', body: 'moon', short: 'Cave shelter · lava-tube pit', label: 'Moon · cave shelter (lava-tube pit)' },
  { id: 'moon-ice', body: 'moon', short: 'Ice · shadowed crater floor', label: 'Moon · south-pole ice (shadowed crater floor)' },
  { id: 'moon-ref', body: 'moon', short: 'Apollo sites · reference', label: 'Moon · Apollo sites (reference)' },
  { id: 'mars-base', body: 'mars', short: 'Human landing zones · NASA 2015', label: 'Mars · proposed human landing zones (NASA, 2015)' },
  { id: 'mars-cave', body: 'mars', short: 'Cave skylight · lava-flow pit', label: 'Mars · cave skylight (lava-flow pit)' },
  { id: 'mars', body: 'mars', short: 'Lander site · measured reference', label: 'Mars · lander site (measured reference)' },
];

// Target shown when the visitor switches to a world whose targets are not selected.
export const DEFAULT_TARGET = { moon: 'malapert', mars: 'jezero' };

const BODIES = ['moon', 'mars'];
const groupOf = (t) => t.group || t.body;
const flagged = (t) => measuredFactors(t) < TARGET_MIN_MEASURED;

// The menu repeats the group, so a name's own group in brackets is dropped ("Malapert Massif (south pole)" ->
// "Malapert Massif"). Brackets with a nickname in quotes stay ("Arsia Mons cave skylight ('Jeanne')").
export const shortName = (name) => name.replace(/\s*\((?![^)]*['"])[^)]*\)\s*$/, '');

let menu, picker, select, chooseTarget, targetBody;

function optionHTML(t) {
  const flag = flagged(t) ? '<span class="fl" title="Fewer than 3 of the 5 factors are measured at the site itself">⚑</span>' : '';
  const star = isStarTarget(t.id) ? '<span class="star" title="Strongest Jordan match on this world: the base is planned here">⭐</span>' : '';
  return `<button type="button" class="tm-opt" role="option" aria-selected="false" data-id="${esc(t.id)}">${flag}<span>${esc(shortName(t.name))}</span>${star}</button>`;
}

function buildMenu(targets) {
  const known = new Set(TARGET_GROUPS.map((g) => g.id));
  return BODIES.map((body) => {
    const groups = TARGET_GROUPS.filter((g) => g.body === body).map((g) => {
      const items = targets.filter((t) => groupOf(t) === g.id);
      return items.length ? `<div class="tm-group" role="group" aria-label="${esc(g.label)}"><div class="tm-glabel" aria-hidden="true">${esc(g.short)}</div>${items.map(optionHTML).join('')}</div>` : '';
    }).join('');
    // A target with an unknown group still appears (at the end of its world), so it can never vanish from the list.
    const rest = targets.filter((t) => t.body === body && !known.has(groupOf(t)));
    const other = rest.length ? `<div class="tm-group" role="group" aria-label="Other targets"><div class="tm-glabel" aria-hidden="true">Other</div>${rest.map(optionHTML).join('')}</div>` : '';
    return groups || other ? `<div class="tm-col" data-planet="${body}" hidden>${groups}${other}</div>` : '';
  }).join('');
}

const options = () => [...menu.querySelectorAll('.tm-col:not([hidden]) .tm-opt')];

function showTargets(body) {
  menu.querySelectorAll('[data-target-world]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.targetWorld === body)));
  menu.querySelectorAll('.tm-col').forEach((col) => { col.hidden = col.dataset.planet !== body; });
  menu.querySelector('.target-options').scrollTop = 0;
}

function openMenu() {
  menu.hidden = false;
  showTargets(targetBody);
  picker.setAttribute('aria-expanded', 'true');
  menu.parentElement.classList.add('choosing-target');
  menu.querySelector('[data-target-close]').focus();
  document.addEventListener('pointerdown', outside, true);
}

function closeMenu(focusPicker = true) {
  if (menu.hidden) return;
  menu.hidden = true;
  menu.parentElement.classList.remove('choosing-target');
  picker.setAttribute('aria-expanded', 'false');
  document.removeEventListener('pointerdown', outside, true);
  if (focusPicker) picker.focus();
}

function outside(e) {
  if (!menu.contains(e.target) && !picker.contains(e.target)) closeMenu(false);
}

function onMenuKey(e) {
  const list = options();
  const i = list.indexOf(document.activeElement);
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); return; }
  const move = { ArrowDown: 1, ArrowUp: -1, Home: -Infinity, End: Infinity }[e.key];
  if (move === undefined) return;
  e.preventDefault();
  const next = move === -Infinity ? 0 : move === Infinity ? list.length - 1 : Math.min(list.length - 1, Math.max(0, i + move));
  list[next]?.focus();
}

export function initTopbar({ targets, onWorld, onTarget }) {
  document.querySelectorAll('#worlds button').forEach((b) => b.addEventListener('click', () => onWorld(b.dataset.world)));
  chooseTarget = onTarget;
  // The hidden <select> keeps the same list for scripts and tests; visitors use the picker.
  select = document.getElementById('target-select');
  select.innerHTML = targets.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
  select.addEventListener('change', () => onTarget(select.value));
  picker = document.getElementById('target-picker');
  menu = document.getElementById('target-menu');
  menu.querySelector('.target-options').innerHTML = buildMenu(targets);
  picker.addEventListener('click', () => (menu.hidden ? openMenu() : closeMenu()));
  picker.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown' && menu.hidden) { e.preventDefault(); openMenu(); } });
  menu.addEventListener('keydown', onMenuKey);
  menu.addEventListener('click', (e) => {
    if (e.target.closest('[data-target-close]')) { closeMenu(); return; }
    const world = e.target.closest('[data-target-world]');
    if (world) { showTargets(world.dataset.targetWorld); return; }
    const opt = e.target.closest('.tm-opt');
    if (!opt) return;
    closeMenu();
    if (opt.getAttribute('aria-selected') !== 'true') chooseTarget(opt.dataset.id);
  });
  menu.addEventListener('focusout', (e) => { if (e.relatedTarget && !menu.contains(e.relatedTarget)) closeMenu(false); });
}

export function setWorld(world) {
  document.querySelectorAll('#worlds button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.world === world)));
}

export function setTarget(target) {
  targetBody = target.body;
  if (menu && !menu.hidden) closeMenu(false);
  if (select) select.value = target.id;
  if (picker) {
    picker.querySelector('.tp-name').textContent = `${flagged(target) ? '⚑ ' : ''}${shortName(target.name)}${isStarTarget(target.id) ? ' ⭐' : ''}`;
    picker.title = target.name;
    picker.setAttribute('aria-label', `Compare with: ${target.name}, ${BODY_LABEL[target.body]}. Open the list of places.`);
    menu.querySelectorAll('.tm-opt').forEach((o) => o.setAttribute('aria-selected', String(o.dataset.id === target.id)));
  }
  const chip = document.getElementById('target-body');
  chip.textContent = `${BODY_LABEL[target.body]} ⓘ`;
  chip.className = `body-chip ${target.body}`;
  // The name starts with the visible text, so voice control ("click Moon") still works.
  chip.setAttribute('aria-label', `${BODY_LABEL[target.body]}: show the data of ${target.name} and its closest Earth twins`);
}

export function setBackVisible(visible) {
  document.getElementById('back-btn').hidden = !visible;
}
