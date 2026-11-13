/* global Cesium */
// Pins are HTML buttons laid over the 3D globe: crisp text, keyboard focus and
// screen-reader names come for free. A label goes to the right of its pin, or to
// the left, below or above it when the right side runs off the screen, covers a
// blocker (the map credits) or overlaps a more important label (below and above,
// it may slide sideways to stay on screen: narrow phones). With no room at all it
// is hidden (hover or focus a pin to see its name).

const scratch = new Cesium.Cartesian2();
const toWindow = Cesium.SceneTransforms.worldToWindowCoordinates || Cesium.SceneTransforms.wgs84ToWindowCoordinates;

export class Pins {
  // blockers: optional function returning elements that labels should not cover, such as the map credits and
  // the panels (read five times a second; hidden ones are skipped).
  constructor(layer, onPick, blockers = () => []) {
    this.layer = layer;
    this.onPick = onPick;
    this.blockers = blockers;
    this.blockRects = [];
    this.blockTime = 0;
    this.items = [];
    this.hidden = false;
    this.selectedId = null;
  }

  // items: [{ id, kind: 'site'|'target'|'kit', name, lon, lat, score, pcText, color, glow, aria, priority, keepLabel }]
  // keepLabel: the label always shows, like the selected pin's (the current TARGET, the #1 Earth site).
  set(items, ellipsoid) {
    this.layer.replaceChildren();
    this.items = items.map((item) => {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = `pin ${item.kind}`;
      el.style.setProperty('--c', item.color || '#ffb547');
      if (item.glow) el.style.setProperty('--glow', item.glow);
      el.setAttribute('aria-label', item.aria || item.name);
      el.innerHTML = `<span class="dot"></span><span class="lbl"><span class="nm"></span>${item.pcText ? '<span class="pc"></span>' : ''}</span>`;
      el.querySelector('.nm').textContent = item.name;
      if (item.pcText) el.querySelector('.pc').textContent = item.pcText;
      el.style.opacity = '0';
      if (item.keepLabel) el.style.zIndex = '1'; // drawn over a neighbour's dot
      el.tabIndex = -1; // invisible until update() finds it on the near side of the globe
      el.addEventListener('click', () => this.onPick(item));
      this.layer.appendChild(el);
      const cart = Cesium.Cartesian3.fromDegrees(item.lon, item.lat, item.height || 0, ellipsoid);
      // Rough label size, used to stop labels from overlapping.
      const labelWidth = 26 + 7.2 * (item.name.length + (item.pcText ? item.pcText.length + 1 : 0));
      return { ...item, el, cart, labelWidth, x: null, y: null, shown: false };
    });
    this.setSelected(this.selectedId);
  }

  setSelected(id) {
    this.selectedId = id;
    for (const it of this.items) it.el.classList.toggle('selected', it.id === id);
  }

  setHidden(hidden) {
    this.hidden = hidden;
    this.layer.style.visibility = hidden ? 'hidden' : 'visible';
  }

  // Called after every frame.
  update(scene, ellipsoid) {
    if (this.hidden || !this.items.length) return;
    const occluder = new Cesium.EllipsoidalOccluder(ellipsoid, scene.camera.positionWC);
    const w = scene.canvas.clientWidth;
    const h = scene.canvas.clientHeight;
    const visible = [];
    for (const it of this.items) {
      let pos = null;
      if (occluder.isPointVisible(it.cart)) pos = toWindow(scene, it.cart, scratch);
      // Behind the globe or outside the window: hidden, and out of the Tab order.
      if (pos && (pos.x < -5 || pos.y < -5 || pos.x > w + 5 || pos.y > h + 5)) pos = null;
      if (!pos) {
        if (it.shown) { it.el.style.opacity = '0'; it.el.tabIndex = -1; it.shown = false; }
        continue;
      }
      visible.push({ it, x: pos.x, y: pos.y });
    }
    // Most important first: the selected pin, then the pins that keep their label (the #1 site, the TARGET), then by
    // priority (score; a live field kit high, a simulated one last).
    visible.sort((a, b) => (b.it.id === this.selectedId) - (a.it.id === this.selectedId) || !!b.it.keepLabel - !!a.it.keepLabel
      || (b.it.priority || 0) - (a.it.priority || 0));
    const taken = visible.map((v) => ({ x0: v.x - 7, y0: v.y - 7, x1: v.x + 7, y1: v.y + 7 }));
    const now = performance.now();
    if (now - this.blockTime > 200) {
      this.blockTime = now;
      this.blockRects = this.blockers().filter((el) => el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden').map((el) => {
        const r = el.getBoundingClientRect();
        return { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom };
      }).filter((r) => r.x1 > r.x0 && r.y1 > r.y0);
    }
    const hit = (rect, r) => !(rect.x1 < r.x0 || rect.x0 > r.x1 || rect.y1 < r.y0 || rect.y0 > r.y1);
    const labels = [];
    for (const v of visible) {
      const { it } = v;
      if (!it.shown) { it.el.style.opacity = '1'; it.el.tabIndex = 0; it.shown = true; }
      if (it.x === null || Math.abs(it.x - v.x) > 0.3 || Math.abs(it.y - v.y) > 0.3) {
        it.el.style.transform = `translate3d(${(v.x - 5).toFixed(1)}px, ${(v.y - 5).toFixed(1)}px, 0)`;
        it.x = v.x; it.y = v.y;
      }
      const lw = it.labelWidth;
      const right = { x0: v.x + 9, y0: v.y - 11, x1: v.x + 12 + lw, y1: v.y + 11, side: '' };
      const left = { x0: v.x - 12 - lw, y0: v.y - 11, x1: v.x - 9, y1: v.y + 11, side: 'left' };
      const bx = Math.max(2, Math.min(w - 2 - lw, v.x - lw / 2)); // under or over the pin, kept on screen
      const below = { x0: bx, y0: v.y + 9, x1: bx + lw, y1: v.y + 31, side: 'below' };
      const above = { x0: bx, y0: v.y - 31, x1: bx + lw, y1: v.y - 9, side: 'above' };
      const free = (rect, dots = true) => rect.x0 >= 2 && rect.x1 <= w - 2
        && !labels.some((r) => hit(rect, r)) && !this.blockRects.some((r) => hit(rect, r))
        && !(dots && taken.some((r) => r.x0 !== v.x - 7 && hit(rect, r)));
      const must = it.id === this.selectedId || it.keepLabel; // shown even when nothing is free
      // A label that must show may cover a neighbour's dot (it is drawn on top), but not the credits;
      // as a last resort it keeps the right side unless that side runs off the screen.
      const spots = [right, left, below, above];
      const spot = spots.find((r) => free(r)) || (must ? (spots.find((r) => free(r, false)) || (right.x1 <= w - 2 ? right : left.x0 >= 2 ? left : below)) : null);
      it.el.classList.toggle('nolabel', !spot);
      for (const side of ['left', 'below', 'above']) it.el.classList.toggle(side, spot?.side === side);
      if (spot && (spot.side === 'below' || spot.side === 'above')) it.el.style.setProperty('--lx', `${(spot.x0 - (v.x - 5)).toFixed(0)}px`);
      if (spot) labels.push(spot);
    }
  }
}
