/* global Cesium */
// A 3D concept of a base, drawn with Cesium shapes (no model files) at a place on the ground: a round platform,
// two habitat domes joined by a tunnel, a hydroponic greenhouse dome with growing racks, a communication room with
// a lattice mast and a dish, and tilted solar arrays. The look follows a concept picture we made with an SI image
// model (Higgsfield, GPT Image 2.6); the shapes are drawn by code (SI-assisted, see README section 10). It is a
// concept, not a design or a measurement. Sizes are rough, in metres, so the base reads at a glance from about 250 m.

export const BASE_PARTS = [
  { id: 'habitat', label: 'Habitat', colour: '#d9dee8' },
  { id: 'greenhouse', label: 'Hydroponic greenhouse', colour: '#7fd18b' },
  { id: 'comm', label: 'Communication room', colour: '#ffb547' },
  { id: 'solar', label: 'Solar power', colour: '#4f7bd9' },
];

// [east m, north m] positions on the platform (its centre is the centre of the base).
const PLATFORM_R = 44;
const HABITATS = [[-12, 15], [12, 15]];
const HAB_R = 8;
const GREENHOUSE = [0, -15];
const GH_R = 12.5;
const COMM = [27, -3];
const SOLAR = [[-35, 7], [-31, -6], [-27, -19]];

// Draws the base around (lon, lat) at ground height h on the globe's ellipsoid. Returns a function that removes it.
// With { build: true } (Story mode) every part starts hidden; remove.reveal(partId) makes that part rise out of
// the ground in about a second (at once with reduced motion).
export function drawBase(viewer, ellipsoid, { lon, lat }, h, { build = false, reducedMotion = false } = {}) {
  const centre = Cesium.Cartesian3.fromDegrees(lon, lat, h, ellipsoid);
  const enu = Cesium.Transforms.eastNorthUpToFixedFrame(centre, ellipsoid);
  const at = (e, n, up = 0) => Cesium.Matrix4.multiplyByPoint(enu, new Cesium.Cartesian3(e, n, up), new Cesium.Cartesian3());
  const turned = (pos, heading = 0, pitch = 0, roll = 0) => Cesium.Transforms.headingPitchRollQuaternion(
    pos, new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(heading), Cesium.Math.toRadians(pitch), Cesium.Math.toRadians(roll)), ellipsoid);
  const upright = (pos) => turned(pos);
  const colour = (css, a = 1) => Cesium.Color.fromCssColorString(css).withAlpha(a);
  const added = [];
  // Build animation: when each part was revealed (performance.now()), and the local "up" direction.
  const shownAt = {};
  const up = Cesium.Cartesian3.normalize(Cesium.Cartesian3.subtract(at(0, 0, 1), centre, new Cesium.Cartesian3()), new Cesium.Cartesian3());
  const RISE_MS = 1100;
  const DROP_M = 16;
  let part = null; // the part the next add() calls belong to
  const add = (spec) => {
    if (build && part) {
      const id = part;
      spec.show = new Cesium.CallbackProperty(() => shownAt[id] != null, false);
      if (spec.position && !reducedMotion) {
        const final = spec.position;
        spec.position = new Cesium.CallbackProperty((time, result) => {
          const t = shownAt[id] == null ? 0 : Math.min(1, (performance.now() - shownAt[id]) / RISE_MS);
          const drop = DROP_M * (1 - t) ** 3;
          return Cesium.Cartesian3.add(final, Cesium.Cartesian3.multiplyByScalar(up, -drop, new Cesium.Cartesian3()), result || new Cesium.Cartesian3());
        }, false);
      }
    }
    added.push(viewer.entities.add(spec));
  };
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
  // Small helpers: an upright box or cylinder centred at (e, n, z).
  const box = (e, n, z, [dx, dy, dz], css, { heading = 0, outline = '#5d6370', a = 1 } = {}) => {
    const pos = at(e, n, z);
    add({ position: pos, orientation: turned(pos, heading), box: { dimensions: new Cesium.Cartesian3(dx, dy, dz), material: colour(css, a), outline: !!outline, outlineColor: colour(outline || '#000') } });
  };
  const cyl = (e, n, z, length, r, css, { outline = null, top = r } = {}) => {
    const pos = at(e, n, z);
    add({ position: pos, orientation: upright(pos), cylinder: { length, topRadius: top, bottomRadius: r, material: colour(css), outline: !!outline, outlineColor: colour(outline || '#000'), slices: 36 } });
  };
  const DOOR = '#4a515f';
  const DARK = '#2b313c';

  // ---------- habitat: the platform, two domed modules and the tunnel between them ----------
  part = 'habitat';
  // Round grey platform, 1.2 m above the ground, on a deep footing so it never floats on rough ground.
  cyl(0, 0, -2.4, 7.2, PLATFORM_R, '#8d939d', { outline: '#5d6370' });
  cyl(0, 0, 1.25, 0.1, PLATFORM_R - 3, '#a2a8b1');
  HABITATS.forEach(([e, n], i) => {
    cyl(e, n, 1.2 + 0.4, 0.8, HAB_R + 0.6, '#5d6370'); // dark footing ring
    cyl(e, n, 1.2 + 3.6, 6.4, HAB_R, '#e9ecf1', { outline: '#9aa3b2' }); // wall
    const dome = at(e, n, 7.9);
    add({ position: dome, orientation: upright(dome), ellipsoid: { radii: new Cesium.Cartesian3(HAB_R, HAB_R, 6.2), maximumCone: Math.PI / 2, material: colour('#f3f5f8'), outline: true, outlineColor: colour('#b8c0cc'), slicePartitions: 16, stackPartitions: 6 } });
    cyl(e, n, 14.2, 0.6, 2.2, DARK); // skylight
    // Door with its frame on the south side, and two windows.
    box(e, n - HAB_R + 0.2, 1.2 + 1.9, [2.6, 0.8, 3.8], '#d3d8e0', { outline: DOOR });
    box(e, n - HAB_R - 0.1, 1.2 + 2.1, [1.2, 0.4, 1.1], '#c9a86a', { outline: DOOR });
    box(e + (i ? 5.4 : -5.4), n - 5.6, 5.2, [1.8, 0.5, 1.4], '#c9a86a', { heading: i ? -45 : 45, outline: DOOR });
    // Steps in front of the door.
    box(e, n - HAB_R - 1.4, 1.2 + 0.35, [2.6, 2.2, 0.7], '#6f7682', { outline: DOOR });
  });
  // Pressurised tunnel between the two modules (a cylinder lying east-west).
  {
    const pos = at(0, HABITATS[0][1], 4.6);
    add({ position: pos, orientation: turned(pos, 0, 0, 90), cylinder: { length: 2 * (HABITATS[1][0] - HAB_R) + 2, topRadius: 2.2, bottomRadius: 2.2, material: colour('#a9afb9'), outline: true, outlineColor: colour('#6f7682'), slices: 24 } });
  }
  add({ position: at(0, 15, 17), label: label('Habitat', '#eef2f8') });

  // ---------- hydroponic greenhouse: a ribbed glass dome with growing racks inside ----------
  part = 'greenhouse';
  {
    const [e, n] = GREENHOUSE;
    cyl(e, n, 1.2 + 0.5, 1.0, GH_R + 0.5, '#5d6370');
    const pos = at(e, n, 2.2);
    add({ position: pos, orientation: upright(pos), ellipsoid: { radii: new Cesium.Cartesian3(GH_R, GH_R, 9.5), maximumCone: Math.PI / 2, material: colour('#7fd18b', 0.42), outline: true, outlineColor: colour('#e3f7e6', 0.95), slicePartitions: 18, stackPartitions: 7 } });
    for (const de of [-6, 0, 6]) {
      box(e + de, n, 1.2 + 1.0, [3.4, 15, 2.0], '#2f8a3e', { outline: '#1d5a28' }); // rack
      box(e + de, n, 1.2 + 2.3, [3.0, 14, 0.8], '#66d16f', { outline: false }); // lettuce row
    }
    // Entrance vestibule on the south side.
    box(e, n - GH_R - 1.6, 1.2 + 2.2, [4.2, 4.0, 4.4], '#e9ecf1', { outline: '#9aa3b2' });
    box(e, n - GH_R - 3.7, 1.2 + 2.0, [2.0, 0.3, 3.2], '#d3d8e0', { outline: DOOR });
    add({ position: at(e, n, 13), label: label('Hydroponic greenhouse', '#9be3a5') });
  }

  // ---------- communication room: a box with a lattice mast and an orange dish ----------
  part = 'comm';
  {
    const [e, n] = COMM;
    box(e, n, 1.2 + 3.6, [12, 10, 7.2], '#e4e7ec', { heading: -20, outline: '#9aa3b2' });
    box(e - 1.8, n - 5.2, 1.2 + 2.0, [2.0, 0.4, 3.4], '#d3d8e0', { heading: -20, outline: DOOR });
    box(e + 3, n - 5.0, 1.2 + 5.2, [1.6, 0.6, 1.2], '#7a828f', { heading: -20, outline: DARK }); // vent
    box(e - 3, n + 1, 1.2 + 7.9, [2.6, 2.0, 1.4], '#c9ced8', { heading: -20, outline: DOOR }); // AC unit on the roof
    // Lattice mast: four thin legs and cross bars, 26 m tall.
    const mx = e + 3.5;
    const my = n + 3.5;
    const MAST = 26;
    for (const [dx, dy] of [[-0.8, -0.8], [0.8, -0.8], [-0.8, 0.8], [0.8, 0.8]]) cyl(mx + dx, my + dy, 8.4 + MAST / 2, MAST, 0.14, '#9aa3b2');
    for (let z = 10; z < 8.4 + MAST; z += 3) box(mx, my, z, [1.8, 1.8, 0.15], '#9aa3b2', { outline: '#6f7682', a: 0.0 });
    cyl(mx, my, 8.4 + MAST + 3, 6, 0.08, '#c9ced8'); // antenna tip
    box(mx + 0.9, my, 8.4 + MAST - 4, [0.6, 0.6, 2.4], '#eef2f8', { outline: '#9aa3b2' }); // radio units
    // Dish on its mount, facing up towards the sky.
    cyl(e - 2, n + 2.5, 8.4 + 1.2, 2.4, 0.9, '#7a828f');
    const dish = at(e - 2, n + 2.5, 8.4 + 4.2);
    add({ position: dish, orientation: turned(dish, -40, 0, 38), ellipsoid: { radii: new Cesium.Cartesian3(4.4, 4.4, 1.3), minimumCone: Math.PI / 2, material: colour('#ff8a3d'), outline: true, outlineColor: colour('#ffd2a8'), slicePartitions: 20, stackPartitions: 5 } });
    add({ position: at(e, n, 37), label: label('Communication room', '#ffcf7a') });
  }

  // ---------- solar power: three tilted arrays on posts ----------
  part = 'solar';
  SOLAR.forEach(([e, n], i) => {
    cyl(e, n, 1.2 + 2.2, 4.4, 0.35, '#6f7682');
    const pos = at(e, n, 1.2 + 5.0);
    add({ position: pos, orientation: turned(pos, 30, -35, 0), box: { dimensions: new Cesium.Cartesian3(10, 7, 0.3), material: colour('#2f5fd0'), outline: true, outlineColor: colour('#cfdcff') } });
    if (i === 1) add({ position: at(e - 6, n, 13), label: label('Solar power', '#a8c0ff') });
  });

  const remove = () => { for (const ent of added) { try { viewer.entities.remove(ent); } catch { /* viewer rebuilt */ } } };
  remove.reveal = (id) => { if (shownAt[id] == null) shownAt[id] = performance.now(); };
  return remove;
}
