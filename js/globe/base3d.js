/* global Cesium */
// A simple 3D concept of a base, drawn with Cesium shapes (no model files) at a place on the ground:
// habitat modules, a hydroponic greenhouse dome, a communication room with its antenna, and solar arrays.
// It is a concept drawing made by code (SI-assisted, see README section 10), not a design or a measurement.
// Sizes are rough, in metres, so the base reads at a glance from about 250 m away.

// [east m, north m] offsets from the centre of the base.
const LAYOUT = {
  habitat: [[0, 0], [14, 0]],
  greenhouse: [-30, 6],
  comm: [30, 22],
  solar: [[-8, -32], [8, -32], [24, -32]],
  paths: [[[0, 0], [-30, 6]], [[14, 0], [30, 22]], [[0, 0], [14, 0]], [[7, 0], [8, -28]]],
};

export const BASE_PARTS = [
  { id: 'habitat', label: 'Habitat', colour: '#d9dee8' },
  { id: 'greenhouse', label: 'Hydroponic greenhouse', colour: '#7fd18b' },
  { id: 'comm', label: 'Communication room', colour: '#ffb547' },
  { id: 'solar', label: 'Solar power', colour: '#4f7bd9' },
];

// Draws the base around (lon, lat) at ground height h on the globe's ellipsoid. Returns a function that removes it.
export function drawBase(viewer, ellipsoid, { lon, lat }, h) {
  const centre = Cesium.Cartesian3.fromDegrees(lon, lat, h, ellipsoid);
  const enu = Cesium.Transforms.eastNorthUpToFixedFrame(centre, ellipsoid);
  const at = (e, n, up = 0) => Cesium.Matrix4.multiplyByPoint(enu, new Cesium.Cartesian3(e, n, up), new Cesium.Cartesian3());
  const upright = (pos) => Cesium.Transforms.headingPitchRollQuaternion(pos, new Cesium.HeadingPitchRoll(0, 0, 0), ellipsoid);
  const colour = (css, a = 1) => Cesium.Color.fromCssColorString(css).withAlpha(a);
  const added = [];
  const add = (spec) => added.push(viewer.entities.add(spec));
  const label = (text, css) => ({
    text,
    font: '600 15px "IBM Plex Sans", sans-serif',
    fillColor: colour(css),
    outlineColor: Cesium.Color.BLACK,
    outlineWidth: 3,
    style: Cesium.LabelStyle.FILL_AND_OUTLINE,
    verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
    pixelOffset: new Cesium.Cartesian2(0, -6),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
    showBackground: true,
    backgroundColor: colour('#05080f', 0.7),
  });

  // Habitat: two upright modules (radius 5 m, 7 m tall) on a 4 m deep footing, so they never float on rough ground.
  LAYOUT.habitat.forEach(([e, n], i) => {
    const pos = at(e, n, 1.5);
    add({ position: pos, orientation: upright(pos), cylinder: { length: 11, topRadius: 5, bottomRadius: 5, material: colour('#d9dee8'), outline: true, outlineColor: colour('#7a859c') } });
    const top = at(e, n, 7);
    add({ position: top, orientation: upright(top), ellipsoid: { radii: new Cesium.Cartesian3(5, 5, 2.4), maximumCone: Math.PI / 2, material: colour('#eef2f8') } });
    if (i === 0) add({ position: at(e + 7, n, 13), label: label('Habitat', '#eef2f8') });
  });
  // Greenhouse: a glass dome, radius 13 m.
  {
    const [e, n] = LAYOUT.greenhouse;
    const pos = at(e, n, -1);
    add({ position: pos, orientation: upright(pos), ellipsoid: { radii: new Cesium.Cartesian3(13, 13, 8), maximumCone: Math.PI / 2, material: colour('#7fd18b', 0.55), outline: true, outlineColor: colour('#bff0c6', 0.9), slicePartitions: 18, stackPartitions: 8 } });
    // growing racks inside
    for (const dn of [-6, 0, 6]) {
      const r = at(e, n + dn, 1.2);
      add({ position: r, orientation: upright(r), box: { dimensions: new Cesium.Cartesian3(16, 1.6, 2.4), material: colour('#2f8a3e') } });
    }
    add({ position: at(e, n, 9), label: label('Hydroponic greenhouse', '#9be3a5') });
  }
  // Communication room: a box with an 18 m mast and a dish.
  {
    const [e, n] = LAYOUT.comm;
    const room = at(e, n, 1.5);
    add({ position: room, orientation: upright(room), box: { dimensions: new Cesium.Cartesian3(9, 7, 7), material: colour('#c9ced8'), outline: true, outlineColor: colour('#7a859c') } });
    const mast = at(e + 2, n + 1, 9);
    add({ position: mast, orientation: upright(mast), cylinder: { length: 18, topRadius: 0.35, bottomRadius: 0.5, material: colour('#eef2f8') } });
    const dishPos = at(e + 2, n + 1, 18);
    const tilt = Cesium.Transforms.headingPitchRollQuaternion(dishPos, new Cesium.HeadingPitchRoll(0, 0, Cesium.Math.toRadians(40)), ellipsoid);
    add({ position: dishPos, orientation: tilt, ellipsoid: { radii: new Cesium.Cartesian3(3.6, 3.6, 1.0), minimumCone: Math.PI / 2, material: colour('#ffb547'), outline: true, outlineColor: colour('#ffd28a') } });
    add({ position: at(e, n, 21), label: label('Communication room', '#ffcf7a') });
  }
  // Solar arrays on posts.
  LAYOUT.solar.forEach(([e, n], i) => {
    const pos = at(e, n, 2.2);
    const tilt = Cesium.Transforms.headingPitchRollQuaternion(pos, new Cesium.HeadingPitchRoll(0, Cesium.Math.toRadians(-25), 0), ellipsoid);
    add({ position: pos, orientation: tilt, box: { dimensions: new Cesium.Cartesian3(13, 6, 0.3), material: colour('#4f7bd9'), outline: true, outlineColor: colour('#a8c0ff') } });
    const post = at(e, n, -1);
    add({ position: post, orientation: upright(post), cylinder: { length: 6, topRadius: 0.3, bottomRadius: 0.3, material: colour('#7a859c') } });
    if (i === 1) add({ position: at(e, n, 7), label: label('Solar power', '#a8c0ff') });
  });
  // Pressurised tunnels between the modules (drawn on the ground).
  for (const [[e1, n1], [e2, n2]] of LAYOUT.paths) {
    add({ polyline: { positions: [at(e1, n1, 0.6), at(e2, n2, 0.6)], width: 6, material: colour('#9aa6bd', 0.9) } });
  }
  return () => { for (const ent of added) { try { viewer.entities.remove(ent); } catch { /* viewer rebuilt */ } } };
}
