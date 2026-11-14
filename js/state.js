// One shared state object plus a tiny event bus.

import { screeningDefaults } from './scoring.js';

export const state = {
  world: 'earth',            // which body the globe shows: earth | moon | mars
  targetId: 'jezero',        // the Moon/Mars site Earth places are compared with
  mode: 'full',              // climate match | screening score
  ...screeningDefaults(),
  selected: null,            // { kind: 'site' | 'target' | 'box', id } (a box only while Discover is on)
  view: 'globe',             // globe | flying | closeup | ground
  data: null,                // { sites, targets, sources, panoramas, terrain, assets }
  discover: false,           // true while the ranking panel shows "Discover Jordan" (10 km screening boxes)
  screening: null,           // the Jordan screening data from loadScreening() in screening.js, once loaded
  screenRanked: null,        // scoreBoxes() for the current settings while Discover is on, else null
};

const listeners = new Map();

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event).delete(fn);
}

export function emit(event, payload) {
  const set = listeners.get(event);
  if (set) for (const fn of [...set]) fn(payload);
}

// Change state and tell everyone which keys changed.
export function update(patch) {
  Object.assign(state, patch);
  emit('change', patch);
}
