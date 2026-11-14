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

export const BASE_INTERIORS = [
  { id: 'habitat', label: 'Habitat', description: 'Crew bunks, a shared work table and equipment lockers.' },
  { id: 'greenhouse', label: 'Greenhouse', description: 'Hydroponic growing racks with lights and a clear central aisle.' },
  { id: 'comm', label: 'Communications', description: 'A console for mission planning and messages to Earth.' },
];

// [east m, north m] positions on the platform (its centre is the centre of the base).
const PLATFORM_R = 44;
const HABITATS = [[-12, 15], [12, 15]];
const HAB_R = 8;
const GREENHOUSE = [0, -15];
const GH_R = 12.5;
const COMM = [27, -3];
const SOLAR = [[-35, 7], [-31, -6], [-27, -19]];
const COMM_ANGLE = 20 * Math.PI / 180;
const commPoint = (x, y, z) => [COMM[0] + x * Math.cos(COMM_ANGLE) - y * Math.sin(COMM_ANGLE), COMM[1] + x * Math.sin(COMM_ANGLE) + y * Math.cos(COMM_ANGLE), z];
const ROOM_VIEWS = {
  habitat: { approach: [-12, 2.5, 3.1], inside: [-12, 9.4, 3.2], focus: [-11.6, 16, 3.1] },
  greenhouse: { approach: [0, -35, 3.5], inside: [2.9, -23.3, 3.7], focus: [2.8, -13.5, 3.3] },
  comm: { approach: commPoint(0, -9, 3.2), inside: commPoint(0, -3.6, 3.3), focus: commPoint(0, 2.5, 3.2) },
};

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
  const doors = new Map();
  const labelEntities = [];
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
    const entity = viewer.entities.add(spec);
    added.push(entity);
    if (spec.label) labelEntities.push(entity);
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
  const WALL = '#dce2e8';
  const LIGHT = '#a8f0df';
  const gate = (id, draw) => {
    const start = added.length;
    draw();
    doors.set(id, added.slice(start));
  };

  // ---------- habitat: the platform, two domed modules and the tunnel between them ----------
  part = 'habitat';
  // Round grey platform, 1.2 m above the ground, on a deep footing so it never floats on rough ground.
  cyl(0, 0, -2.4, 7.2, PLATFORM_R, '#8d939d', { outline: '#5d6370' });
  cyl(0, 0, 1.25, 0.1, PLATFORM_R - 3, '#a2a8b1');
  HABITATS.forEach(([e, n], i) => {
    cyl(e, n, 1.2 + 0.4, 0.8, HAB_R + 0.6, '#5d6370'); // dark footing ring
    if (i) cyl(e, n, 4.8, 6.4, HAB_R, WALL, { outline: '#9aa3b2' });
    else {
      // A hollow ring with a south opening, so the camera can enter the furnished west habitat.
      for (let panel = 0; panel < 24; panel += 1) {
        const a = panel * Math.PI / 12;
        const doorway = panel === 18;
        box(e + 7.91 * Math.cos(a), n + 7.91 * Math.sin(a), doorway ? 6.5 : 4.8,
          [2.13, 0.38, doorway ? 3 : 6.4], WALL, { heading: -Cesium.Math.toDegrees(a) - 90, outline: false });
      }
      cyl(e, n, 2.04, 0.12, 7.7, '#8996a2');
      box(e, n + 0.2, 2.14, [3.2, 8.7, 0.08], '#475969', { outline: false });
      for (const de of [-4.8, 4.8]) {
        box(e + de, n + 1.4, 2.55, [2.15, 4.7, 0.85], '#354555');
        box(e + de, n + 1.4, 3.02, [2.0, 4.5, 0.23], '#c9d8e2', { outline: false });
        box(e + de, n + 2.95, 3.18, [1.6, 0.8, 0.18], '#eef3ed', { outline: false });
        box(e + de * 0.86, n + 4.95, 3.35, [1.9, 1.3, 2.55], '#5b7988');
        box(e + de * 0.82, n + 4.26, 3.55, [1.2, 0.08, 0.07], LIGHT, { outline: false });
      }
      box(e, n + 3.2, 3.05, [3.5, 1.55, 0.16], '#d9ab77');
      for (const de of [-1.35, 1.35]) box(e + de, n + 3.2, 2.57, [0.23, 1.05, 0.94], DARK);
      box(e, n + 5.85, 4.35, [3.9, 0.21, 1.7], '#243741');
      box(e, n + 5.72, 4.38, [3.35, 0.06, 1.23], '#648fa2', { outline: false });
      for (const de of [-2.2, 2.2]) box(e + de, n, 6.05, [0.20, 8.2, 0.10], LIGHT, { outline: false });
    }
    const dome = at(e, n, 7.9);
    add({ position: dome, orientation: upright(dome), ellipsoid: { radii: new Cesium.Cartesian3(HAB_R, HAB_R, 6.2), maximumCone: Math.PI / 2, material: colour('#f3f5f8'), outline: true, outlineColor: colour('#b8c0cc'), slicePartitions: 16, stackPartitions: 6 } });
    cyl(e, n, 14.2, 0.6, 2.2, DARK); // skylight
    // Door with its frame on the south side, and two windows.
    const door = () => {
      box(e, n - HAB_R + 0.2, 3.45, [2.6, 0.65, 3.9], '#d3d8e0', { outline: DOOR });
      box(e, n - HAB_R - 0.14, 3.5, [1.2, 0.05, 1.1], '#c9a86a', { outline: DOOR });
    };
    if (i) door(); else gate('habitat', door);
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
      box(e + de, n, 3.31, [3.0, 14, 0.28], '#486b51', { outline: false });
      for (const dn of [-5.5, -3.3, -1.1, 1.1, 3.3, 5.5]) {
        box(e + de, n + dn, 3.63, [2.7, 1.5, 0.48], '#71bc69', { outline: false }); // one tray of greens
      }
    }
    // Entrance vestibule on the south side.
    for (const side of [-1, 1]) box(e + side * 1.98, n - GH_R - 1.45, 3.45, [0.3, 4.2, 4.4], WALL);
    box(e, n - GH_R - 1.45, 5.55, [4.2, 4.2, 0.3], WALL);
    box(e, n - GH_R - 1.45, 1.38, [4.2, 4.2, 0.22], '#778e86');
    gate('greenhouse', () => box(e, n - GH_R - 3.57, 3.45, [3.65, 0.3, 4.0], '#d3d8e0', { outline: DOOR }));
    for (const de of [-6, 0, 6]) {
      for (const dn of [-5.5, 0, 5.5]) box(e + de, n + dn, 4.65, [3.55, 0.13, 0.10], LIGHT, { outline: false });
    }
    add({ position: at(e, n, 13), label: label('Hydroponic greenhouse', '#9be3a5') });
  }

  // ---------- communication room: a box with a lattice mast and an orange dish ----------
  part = 'comm';
  {
    const [e, n] = COMM;
    const interiorBox = (x, y, z, dims, material, outline = '#5d6370') => box(...commPoint(x, y, z), dims, material, { heading: -20, outline });
    interiorBox(0, 0, 1.38, [12, 10, 0.36], '#81909d');
    interiorBox(0, 0, 8.2, [12, 10, 0.4], WALL);
    interiorBox(0, 4.84, 4.8, [12, 0.32, 6.8], WALL);
    for (const x of [-5.84, 5.84]) interiorBox(x, 0, 4.8, [0.32, 10, 6.8], WALL);
    for (const x of [-3.65, 3.65]) interiorBox(x, -4.84, 4.8, [4.7, 0.32, 6.8], WALL);
    interiorBox(0, -4.84, 6.85, [2.6, 0.32, 2.7], WALL);
    gate('comm', () => interiorBox(0, -4.95, 3.4, [2.59, 0.38, 4.05], '#d3d8e0', DOOR));
    interiorBox(0, 0, 1.57, [2.7, 7.4, 0.08], '#536576', false);
    for (const x of [-3.1, 0, 3.1]) {
      interiorBox(x, 2.56, 2.36, [2.85, 1.6, 1.55], '#354555');
      interiorBox(x, 2.30, 3.08, [2.82, 1.65, 0.12], '#b2bfc9');
      interiorBox(x, 3.08, 3.95, [2.66, 0.22, 1.40], '#1d3442');
      interiorBox(x, 2.94, 3.99, [2.39, 0.06, 1.12], '#6a9fae', false);
      interiorBox(x, 2.89, 4.19, [1.65, 0.04, 0.04], LIGHT, false);
      interiorBox(x, 0.50, 2.20, [0.9, 1.0, 0.22], '#344452');
      interiorBox(x, 0.92, 2.59, [0.88, 0.15, 0.75], '#526d80');
    }
    for (const x of [-3, 3]) interiorBox(x, 0.4, 6.55, [0.25, 6.65, 0.12], LIGHT, false);
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

  const remove = () => { if (!viewer.isDestroyed()) for (const entity of added) viewer.entities.remove(entity); };
  remove.reveal = (id) => { if (shownAt[id] == null) shownAt[id] = performance.now(); };
  remove.openRoom = (id) => {
    for (const [room, panels] of doors) for (const panel of panels) panel.show = room !== id;
    for (const entity of labelEntities) entity.show = !id;
  };
  remove.roomView = (id) => {
    const room = ROOM_VIEWS[id];
    if (!room) return null;
    const focus = at(...room.focus);
    const view = (coords) => {
      const destination = at(...coords);
      const direction = Cesium.Cartesian3.normalize(Cesium.Cartesian3.subtract(focus, destination, new Cesium.Cartesian3()), new Cesium.Cartesian3());
      return { destination, orientation: { direction, up } };
    };
    const [e, n] = room.approach;
    return { above: view([e, n, 45]), approach: view(room.approach), inside: view(room.inside) };
  };
  return remove;
}
