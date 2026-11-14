/* global Cesium */
// Discover Jordan on the 3D globe: one translucent 10 km rectangle per screening box, coloured by its score
// (the same colour scale as the pins), and an amber outline around the selected box.
//
// - All boxes are one GroundPrimitive, so they drape on World Terrain (or on the ellipsoid without a token).
// - Rescoring only changes per-box colours, never the geometry. Cesium 1.145 has no readyPromise, so
//   colour changes made before the primitive is ready wait in `pending` and are applied after a frame.
// - A click or tap on a box calls onPick(id); anything else (route lines, the globe) is ignored.
// - In close-up (state.view is not 'globe') the fills hide and only the outline stays, on the 3D terrain.
// - The data credits are shown while the layer is shown.
//
// globe.show() destroys the viewer, so call attach(globe.viewer) again after every globe.show('earth').
//
//   const layer = new BoxLayer({ onPick: (id) => ... });
//   layer.attach(viewer); layer.setData(screening); layer.setScores(scoreBoxes()); layer.setShown(true);
//   layer.setSelected(id | null); layer.detach();

import { state, on } from '../state.js';
import { esc } from '../util.js';
import { boxFill } from '../screening.js';

const SHRINK = 0.02;          // each rectangle is 2 % smaller than its box, so the cells read as a grid
const OUTLINE_CSS = '#fff2ce';
const OUTLINE_WIDTH = 4;      // pixels

// Used only when the data file carries no credits (the file's sources[].credit come first).
const FALLBACK_CREDITS = [
  { url: 'https://power.larc.nasa.gov/docs/referencing/', credit: "The data was obtained from National Aeronautics and Space Administration (NASA) Langley Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA Earth Science Division." },
  { url: 'https://doi.org/10.5270/ESA-c5d3d65', credit: 'Produced using Copernicus WorldDEM-90 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved.' },
  { url: 'https://doi.org/10.25928/igme-5000', credit: 'IGME5000, © BGR, Hannover, 2005, https://doi.org/10.25928/igme-5000, modified: reclassified to Analog Atlas rock ids' },
  { url: 'https://www.naturalearthdata.com/', credit: 'Made with Natural Earth' },
];

// The data sources credited on the globe (design 4.2): POWER, Copernicus (Art. 6(b) notice), IGME5000, Natural Earth.
// Other entries of sources[] (the cited Open-Meteo pixel rule gives no data) stay on the box page and in Method & data.
const GLOBE_CREDIT_IDS = ['nasa-power-climatology-regional', 'copernicus-dem-glo90', 'igme5000', 'naturalearth-admin0-10m'];

// One credit per distinct sources[].credit text of those sources in the data file.
function creditList(sources) {
  const byText = new Map();
  for (const s of sources || []) {
    if (s && s.credit && GLOBE_CREDIT_IDS.includes(s.id) && !byText.has(s.credit)) byText.set(s.credit, s);
  }
  return byText.size ? [...byText.values()] : FALLBACK_CREDITS;
}

// Credits go in Cesium's "Data attribution" list, like the other layers of the globe.
function makeCredit(source) {
  const text = `Jordan screening boxes: ${esc(source.credit)}`;
  return new Cesium.Credit(source.url ? `<a href="${esc(source.url)}" target="_blank" rel="noopener">${text}</a>` : text, false);
}

function shrunk(b) {
  const dLat = ((b.n - b.s) * SHRINK) / 2;
  const dLon = ((b.e - b.w) * SHRINK) / 2;
  return Cesium.Rectangle.fromDegrees(b.w + dLon, b.s + dLat, b.e - dLon, b.n - dLat);
}

const colorCache = new Map();
function toColor(fill) {
  const key = `${fill.css}|${fill.alpha}`;
  if (!colorCache.has(key)) colorCache.set(key, Cesium.Color.fromCssColorString(fill.css).withAlpha(fill.alpha));
  return { color: colorCache.get(key), show: fill.show !== false };
}

const NO_SCORE = boxFill(null, false);
const sameColor = (a, b) => a && b && a.show === b.show && Cesium.Color.equals(a.color, b.color);
const alive = (viewer) => !!viewer && !viewer.isDestroyed();

export class BoxLayer {
  constructor({ onPick } = {}) {
    this.onPick = onPick || (() => {});
    this.viewer = null;
    this.fill = null;         // GroundPrimitive with every box
    this.outline = null;      // GroundPolylinePrimitive around the selected box
    this.outlineId = null;
    this.handler = null;      // LEFT_CLICK picking
    this.removeRender = null;
    this.credits = [];
    this.creditsOn = false;
    this.screening = null;
    this.boxes = [];          // [{ id, bounds }]
    this.byId = new Map();
    this.result = null;       // the last scoreBoxes() result
    this.colors = new Map();  // id -> { color, show }: the latest colours
    this.pending = new Map(); // colours not yet written to the primitive
    this.selectedId = null;
    this.shown = false;
    this.warned = false;      // "cannot drape" is said once
    this.closeup = state.view !== 'globe';
    this.offChange = on('change', (patch) => {
      if ('view' in patch) this.setCloseup(state.view !== 'globe');
    });
  }

  // ---------- public ----------

  // Use this viewer. Safe to call after every globe.show(): the same viewer is a no-op, a destroyed one is
  // dropped first, and a Moon or Mars viewer only detaches (the boxes exist on Earth only).
  attach(viewer) {
    if (!alive(viewer) || viewer === this.viewer) return;
    this.detach();
    if (!Cesium.Ellipsoid.WGS84.equals(viewer.scene.globe.ellipsoid)) return;
    this.viewer = viewer;
    this.removeRender = viewer.scene.postRender.addEventListener(() => this.flush());
    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    this.handler.setInputAction((e) => this.pick(e.position), Cesium.ScreenSpaceEventType.LEFT_CLICK);
    this.credits = creditList(this.screening && this.screening.doc.sources).map(makeCredit);
    this.render();
  }

  // Remove everything from the viewer (if it still exists). Data, colours, selection and visibility are kept,
  // so the next attach() shows the same picture.
  detach() {
    const viewer = this.viewer;
    if (alive(viewer)) {
      if (this.removeRender) this.removeRender();
      this.removeCredits();
      this.removeFill();
      this.removeOutline();
    }
    if (this.handler && !this.handler.isDestroyed()) this.handler.destroy();
    this.viewer = null;
    this.handler = null;
    this.removeRender = null;
    this.fill = null;
    this.outline = null;
    this.outlineId = null;
    this.credits = [];
    this.creditsOn = false;
    this.pending.clear();
  }

  // The loaded screening data (from loadScreening). A new data set rebuilds the rectangles.
  setData(screening) {
    if (screening === this.screening) return;
    this.screening = screening || null;
    this.boxes = screening ? screening.boxes.map((b) => ({ id: b.id, bounds: b.bounds })) : [];
    this.byId = new Map(this.boxes.map((b) => [b.id, b]));
    this.colors = this.colorsFor(this.result);
    this.pending.clear();
    if (!this.byId.has(this.selectedId)) this.selectedId = null;
    if (!this.viewer) return;
    this.removeCredits();
    this.removeFill();
    this.removeOutline();
    this.credits = creditList(screening && screening.doc.sources).map(makeCredit);
    this.render();
  }

  // Colours from a scoreBoxes() result (row.fill = boxFill(...)). Only colours change, never the geometry.
  setScores(result) {
    this.result = result || null;
    const next = this.colorsFor(this.result);
    for (const [id, c] of next) if (!sameColor(this.colors.get(id), c)) this.pending.set(id, c);
    this.colors = next;
    this.flush();
  }

  setShown(shown) {
    this.shown = !!shown;
    this.render();
  }

  // Outline one box (any id that is not a box clears it).
  setSelected(id) {
    this.selectedId = this.byId.has(id) ? id : null;
    this.render();
  }

  setCloseup(closeup) {
    if (closeup === this.closeup) return;
    this.closeup = closeup;
    this.render();
  }

  isBox(id) {
    return typeof id === 'string' && this.byId.has(id);
  }

  destroy() {
    this.detach();
    if (this.offChange) this.offChange();
    this.offChange = null;
  }

  // ---------- inside ----------

  colorsFor(result) {
    const colors = new Map();
    for (const b of this.boxes) {
      const row = result && result.byId.get(b.id);
      colors.set(b.id, toColor(row ? row.fill : NO_SCORE));
    }
    return colors;
  }

  // Bring the viewer in line with the current data, visibility, close-up state and selection.
  render() {
    if (!alive(this.viewer)) return;
    if (this.shown && this.boxes.length && !this.fill) this.buildFill();
    if (this.fill) this.fill.show = this.shown && !this.closeup;
    this.syncOutline();
    this.syncCredits();
  }

  buildFill() {
    if (!Cesium.GroundPrimitive.isSupported(this.viewer.scene)) {
      if (!this.warned) console.warn('This browser cannot drape shapes on the globe; the Discover list still works.');
      this.warned = true;
      return;
    }
    const instances = this.boxes.map((b) => {
      const c = this.colors.get(b.id) || toColor(NO_SCORE);
      return new Cesium.GeometryInstance({
        id: b.id,
        geometry: new Cesium.RectangleGeometry({ rectangle: shrunk(b.bounds), ellipsoid: Cesium.Ellipsoid.WGS84 }),
        attributes: {
          color: Cesium.ColorGeometryInstanceAttribute.fromColor(c.color),
          show: new Cesium.ShowGeometryInstanceAttribute(c.show),
        },
      });
    });
    this.fill = this.viewer.scene.groundPrimitives.add(new Cesium.GroundPrimitive({
      geometryInstances: instances,
      appearance: new Cesium.PerInstanceColorAppearance({ flat: true, translucent: true }),
      classificationType: Cesium.ClassificationType.TERRAIN,
      asynchronous: true,
    }));
    this.pending.clear(); // the new primitive already has the latest colours
    if (this.outline) this.viewer.scene.groundPrimitives.raiseToTop(this.outline);
  }

  // Write waiting colour changes once the primitive is ready (runs after every frame).
  flush() {
    if (!this.pending.size || !this.fill || !this.fill.ready) return;
    try {
      for (const [id, c] of this.pending) {
        const a = this.fill.getGeometryInstanceAttributes(id);
        if (!a) continue;
        a.color = Cesium.ColorGeometryInstanceAttribute.toValue(c.color, a.color);
        a.show = Cesium.ShowGeometryInstanceAttribute.toValue(c.show, a.show);
      }
      this.pending.clear();
    } catch (err) {
      console.warn('box colours not applied yet', err);
    }
  }

  syncOutline() {
    const id = this.shown ? this.selectedId : null;
    if (id === this.outlineId && (this.outline || !id)) return;
    this.removeOutline();
    if (!id || !Cesium.GroundPolylinePrimitive.isSupported(this.viewer.scene)) return;
    const b = this.byId.get(id).bounds;
    this.outline = this.viewer.scene.groundPrimitives.add(new Cesium.GroundPolylinePrimitive({
      geometryInstances: new Cesium.GeometryInstance({
        geometry: new Cesium.GroundPolylineGeometry({
          positions: Cesium.Cartesian3.fromDegreesArray([b.w, b.s, b.e, b.s, b.e, b.n, b.w, b.n]),
          loop: true,
          width: OUTLINE_WIDTH,
          arcType: Cesium.ArcType.RHUMB, // follow the parallels, like the rectangle edges
        }),
      }),
      appearance: new Cesium.PolylineMaterialAppearance({ material: Cesium.Material.fromType('Color', { color: Cesium.Color.fromCssColorString(OUTLINE_CSS) }) }),
      classificationType: Cesium.ClassificationType.TERRAIN,
      allowPicking: false,
      asynchronous: true,
    }));
    this.outlineId = id;
  }

  syncCredits() {
    const want = this.shown && this.boxes.length > 0;
    if (want === this.creditsOn) return;
    const display = this.viewer.creditDisplay;
    for (const c of this.credits) {
      if (want) display.addStaticCredit(c);
      else display.removeStaticCredit(c);
    }
    this.creditsOn = want;
  }

  removeCredits() {
    if (this.creditsOn && alive(this.viewer)) for (const c of this.credits) this.viewer.creditDisplay.removeStaticCredit(c);
    this.creditsOn = false;
  }

  removeFill() {
    if (this.fill && alive(this.viewer)) this.viewer.scene.groundPrimitives.remove(this.fill);
    this.fill = null;
  }

  removeOutline() {
    if (this.outline && alive(this.viewer)) this.viewer.scene.groundPrimitives.remove(this.outline);
    this.outline = null;
    this.outlineId = null;
  }

  // Only a box id counts: the route lines are Entities (their id is an object) and the globe gives nothing.
  pick(position) {
    if (!this.shown || this.closeup || !this.fill || !alive(this.viewer)) return;
    let picked;
    try {
      picked = this.viewer.scene.pick(position);
    } catch (err) {
      console.warn('box pick failed', err);
      return;
    }
    const id = picked && picked.id;
    if (this.isBox(id)) this.onPick(id);
  }
}
