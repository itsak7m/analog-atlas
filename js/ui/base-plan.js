import { REDUCED_MOTION } from '../config.js';
import { esc } from '../util.js';
import { layout } from './base-plan-layout.js';

export const basePlanImage = new URL('../../textures/base/floor-plan.svg', import.meta.url).href;

const rooms = {
  habitat: { label: 'Habitat', text: 'Four stacked berths, personal storage and a fold-down workbench for the crew.' },
  greenhouse: { label: 'Greenhouse', text: 'LED-lit trays grow leafy greens in nutrient solution. Select a tray to see its crop.' },
  comm: { label: 'Communications', short: 'Comms', text: 'Three stations link the crew with Mission Control, field teams and family.' },
};

const hardware = {
  bunks: { label: 'Crew bunks', text: 'Two stacked berths on each side give four crew members a place to sleep.' },
  stowage: { label: 'Personal lockers', text: 'The crew stores clothing, equipment and personal items along the aisle.' },
  workbench: { label: 'Fold-down workbench', text: 'A small shared surface for repairs, a laptop or a meal.' },
  romaine: { label: 'Red romaine lettuce', text: 'A source of fresh greens for the crew. NASA grew red romaine in Veggie aboard the International Space Station.',
    source: 'https://ntrs.nasa.gov/citations/20240001584' },
  mizuna: { label: 'Mizuna mustard', text: 'A leafy green with a peppery taste. NASA tested how different LED light recipes affected mizuna in orbit.',
    source: 'https://ntrs.nasa.gov/citations/20240001638' },
  mission: { label: 'Mission Control link', text: 'The crew uses this console to contact the Mission Control Center (MCC) on Earth and report on base operations.' },
  surface: { label: 'Surface operations', text: 'This console tracks crew and rover activity outside and coordinates field work.' },
  family: { label: 'Family station', source: 'https://nlsp.nasa.gov/explore/api/v1/getfiles3?alias=lsda&id=IDP-LSDA_DOCUMENT-0000000000000712&type=lsda_document',
    sourceLabel: 'NASA family contact reference' },
};

const overview = { label: 'Whole base', text: 'Choose a room to zoom in and inspect what’s inside.' };
const pixelsPerMeter = 36;

export function basePlanMarkup({ location, destination }) {
  return `<div class="sheet-body base-explorer">
    <div class="base-map" aria-label="Interactive top-down base plan">
      <div class="base-map-art" aria-hidden="true"><img src="${esc(basePlanImage)}" alt="" draggable="false"></div>
      <div class="base-map-targets"></div>
      <div class="base-map-north" aria-label="North is up"><span aria-hidden="true">N</span><span aria-hidden="true">↑</span></div>
      <div class="base-map-scale" aria-hidden="true"><span></span></div>
    </div>
    <aside class="base-explorer-info">
      <div class="base-explorer-location"><span>${esc(location)}</span>${destination ? `<span>${esc(destination)}</span>` : ''}</div>
      <button type="button" class="btn small base-map-reset" data-base-reset hidden>← Whole base</button>
      <div class="base-inspection" aria-live="polite" aria-atomic="true">
        <h3></h3><p></p><a hidden target="_blank" rel="noopener"></a>
      </div>
      <button type="button" class="btn small base-explorer-details" data-base-details>Plan details</button>
    </aside>
  </div>`;
}

export function bindBasePlan(dialog, { familyText, onDetails }) {
  const map = dialog.querySelector('.base-map');
  const art = map.querySelector('.base-map-art');
  const targets = map.querySelector('.base-map-targets');
  const scale = map.querySelector('.base-map-scale');
  const reset = dialog.querySelector('[data-base-reset]');
  const info = dialog.querySelector('.base-inspection');
  const heading = info.querySelector('h3');
  const description = info.querySelector('p');
  const source = info.querySelector('a');
  const [east, north] = layout.center;
  const [width, height] = layout.span;
  const left = east - width / 2;
  const top = north + height / 2;
  let room = null;
  let pinned = null;
  let zoomTimer;
  let hotspots = [];

  art.style.width = width * pixelsPerMeter + 'px';
  art.style.height = height * pixelsPerMeter + 'px';

  function showInfo(item) {
    const content = item || rooms[room] || overview;
    heading.textContent = content.label;
    description.textContent = content === hardware.family ? familyText : content.text;
    source.hidden = !content.source;
    if (content.source) {
      source.href = content.source;
      source.textContent = content.sourceLabel || 'NASA crop research';
    }
  }

  function project() {
    const [x, y, w, h] = layout.rooms[room] || [east, north, width, height];
    const margin = room ? 3.2 : 0;
    const fit = Math.min((map.clientWidth - 26) / (w + margin), (map.clientHeight - 34) / (h + margin));
    if (fit <= 0) return;
    const offsetX = map.clientWidth / 2 - (x - left) * fit;
    const offsetY = map.clientHeight / 2 - (top - y) * fit;
    art.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${fit / pixelsPerMeter})`;

    for (const { button, bounds: [bx, by, bw, bh] } of hotspots) {
      button.style.left = offsetX + (bx - left) * fit + 'px';
      button.style.top = offsetY + (top - by) * fit + 'px';
      button.style.width = bw * fit + 'px';
      button.style.height = bh * fit + 'px';
    }
    const meters = room ? 2 : 5;
    scale.style.width = meters * fit + 'px';
    scale.firstElementChild.textContent = meters + ' m';
  }

  function showRoom(next, animate = true) {
    const previous = room;
    room = next;
    pinned = null;
    reset.hidden = !room;
    targets.replaceChildren();
    hotspots = [];
    if (room) {
      for (const { kind, bounds } of layout.items[room]) {
        const item = hardware[kind];
        const button = document.createElement('button');
        button.className = 'base-map-item';
        button.type = 'button';
        button.setAttribute('aria-label', item.label);
        button.setAttribute('aria-pressed', 'false');
        button.innerHTML = '<span aria-hidden="true"></span>';
        button.addEventListener('pointerenter', (event) => { if (event.pointerType === 'mouse') showInfo(item); });
        button.addEventListener('pointerleave', (event) => { if (event.pointerType === 'mouse') showInfo(pinned?.item); });
        button.addEventListener('focus', () => showInfo(item));
        button.addEventListener('blur', () => showInfo(pinned?.item));
        button.addEventListener('click', () => {
          pinned?.button.setAttribute('aria-pressed', 'false');
          pinned = { item, button };
          button.setAttribute('aria-pressed', 'true');
          showInfo(item);
        });
        targets.append(button);
        hotspots.push({ button, bounds });
      }
    } else {
      for (const [id, spec] of Object.entries(rooms)) {
        const button = document.createElement('button');
        button.className = 'base-map-room';
        button.type = 'button';
        button.dataset.room = id;
        button.setAttribute('aria-label', `Zoom into ${spec.label}`);
        button.innerHTML = `<span aria-hidden="true">${esc(spec.short || spec.label)}</span>`;
        button.addEventListener('click', () => showRoom(id));
        targets.append(button);
        hotspots.push({ button, bounds: layout.rooms[id] });
      }
    }

    showInfo();
    clearTimeout(zoomTimer);
    if (animate && !REDUCED_MOTION) {
      map.classList.add('base-zooming');
      targets.inert = true;
      zoomTimer = setTimeout(() => {
        map.classList.remove('base-zooming');
        targets.inert = false;
        if (!next && previous && (document.activeElement === reset || document.activeElement === document.body)) {
          targets.querySelector(`[data-room="${previous}"]`).focus({ preventScroll: true });
        }
      }, 360);
    }
    project();
    if (next) reset.focus({ preventScroll: true });
    else if (previous && !targets.inert) targets.querySelector(`[data-room="${previous}"]`).focus({ preventScroll: true });
  }

  reset.addEventListener('click', () => showRoom(null));
  dialog.querySelector('[data-base-details]').addEventListener('click', onDetails);
  showRoom(null, false);
  const observer = new ResizeObserver(project);
  observer.observe(map);
  return () => {
    observer.disconnect();
    clearTimeout(zoomTimer);
  };
}
