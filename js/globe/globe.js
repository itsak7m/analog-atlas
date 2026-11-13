/* global Cesium */
// The 3D globe: one CesiumJS viewer at a time for Earth, the Moon or Mars.
// Cesium keeps the body's shape in a global setting (Ellipsoid.default), so
// switching bodies means destroying the viewer and building a new one.

import { HAS_ION, ION, GIBS, TREK, TEXTURES, REDUCED_MOTION } from '../config.js';
import { clamp } from '../util.js';

const rad = Cesium.Math.toRadians;
const deg = Cesium.Math.toDegrees;

export const BODIES = {
  earth: { name: 'Earth', home: { lon: 36, lat: 22, height: 2.0e7 }, approach: 260000, range: 9000, eye: 30 },
  moon: { name: 'Moon', home: { lon: 55, lat: -38, height: 6.6e6 }, approach: 140000, range: 6500, eye: 2 },
  mars: { name: 'Mars', home: { lon: 107, lat: 7, height: 1.25e7 }, approach: 180000, range: 7500, eye: 2 },
};

// The far view of the lunar south pole (the Moon base and ice targets), tilted and seen from the Mons Mouton
// side. The Cesium Moon 3D tiles show the area within a few degrees of the pole as a darker square with less
// detail and some hard edges: that is their own polar imagery (taken in low sunlight), not something drawn by
// the app, and it gets sharper close up. A straight-down or north-side view puts that square, and the 0°/180°
// seam of the global mosaic, in the middle of the screen; from here both lie near the horizon, and the four
// south-pole pins stay far enough apart for their labels.
export const SOUTH_POLE_VIEW = { lat: -84.5, lon: 12, height: 6e5, pitch: -28, heading: 168 };

const SPIN_RATE = rad(1.6);      // radians per second while idle
const ORBIT_RATE = rad(2.4);     // radians per second around a site
const IDLE_RESUME_MS = 120000;   // start spinning again after 2 minutes without input (globe view only)

export const ellipsoidFor = (body) => (body === 'moon' ? Cesium.Ellipsoid.MOON : body === 'mars' ? Cesium.Ellipsoid.MARS : Cesium.Ellipsoid.WGS84);

function flyPromise(camera, options) {
  return new Promise((resolve) => {
    camera.flyTo({ ...options, complete: () => resolve(true), cancel: () => resolve(false) });
  });
}

function flySpherePromise(camera, sphere, options) {
  return new Promise((resolve) => {
    camera.flyToBoundingSphere(sphere, { ...options, complete: () => resolve(true), cancel: () => resolve(false) });
  });
}

export class Globe {
  constructor({ container, creditContainer, onFrame, onInput, onStatus, knownHeight }) {
    this.container = container;
    this.creditContainer = creditContainer;
    this.onFrame = onFrame || (() => {});
    this.onInput = onInput || (() => {});
    this.onStatus = onStatus || (() => {});
    this.viewer = null;
    this.body = null;
    this.spinning = !REDUCED_MOTION;
    this.lastInput = performance.now();
    this.lastTick = performance.now();
    this.orbit = null;
    this.look = null;
    this.mode = 'globe';
    this.tileset = null;
    this.tilesetVisible = false;
    this.detailLayer = null;
    this.terrainReady = Promise.resolve(false); // Earth: resolves true when World Terrain is ready
    this.tilesReady = Promise.resolve(false);   // Moon/Mars: resolves true when the 3D tiles are showing
    this.has3D = false;
    this.heightCache = new Map();
    // Measured ground height at a place (LOLA, MOLA or Copernicus DEM from data/terrain.json), or null.
    // Used only while the 3D terrain is still too slow to answer, so the camera never ends up underground.
    this.knownHeight = knownHeight || (() => null);
    // Every camera move gets a new number, so a slow move can tell that a newer one took over.
    this.flightId = 0;
    // Clicks and keys anywhere (panels, tour, corridor) count as activity, so the idle spin waits.
    const active = () => { this.lastInput = performance.now(); };
    for (const type of ['pointerdown', 'keydown', 'wheel', 'touchstart']) document.addEventListener(type, active, { passive: true, capture: true });
  }

  get ellipsoid() { return ellipsoidFor(this.body); }
  get scene() { return this.viewer.scene; }
  get camera() { return this.viewer.camera; }

  // Build the viewer for one body. Resolves when the far view is ready.
  async show(body) {
    this.flightId += 1;
    this.exitLook();
    this.orbit = null;
    if (this.viewer) {
      this.viewer.destroy();
      this.viewer = null;
    }
    this.body = body;
    this.tileset = null;
    this.tilesetVisible = false;
    this.tilesReady = Promise.resolve(false);
    this.detailLayer = null;
    this.has3D = false;
    const ellipsoid = ellipsoidFor(body);
    Cesium.Ellipsoid.default = ellipsoid; // must be set before the viewer is created
    if (body === 'earth') Cesium.Camera.DEFAULT_VIEW_RECTANGLE = Cesium.Rectangle.fromDegrees(-95, -20, -70, 90);

    const viewer = new Cesium.Viewer(this.container, {
      baseLayer: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      scene3DOnly: true,
      creditContainer: this.creditContainer,
      msaaSamples: 4,
      useBrowserRecommendedResolution: false,
      globe: new Cesium.Globe(ellipsoid),
      skyBox: body === 'earth' ? undefined : Cesium.SkyBox.createEarthSkyBox(),
      skyAtmosphere: body === 'earth' ? undefined : body === 'mars' ? new Cesium.SkyAtmosphere(ellipsoid) : false,
      shadows: body === 'moon',
      contextOptions: { webgl: { powerPreference: 'high-performance' } },
    });
    this.viewer = viewer;
    // Render at the screen's real resolution (sharp), but cap very dense phone screens at 2x for speed.
    const dpr = window.devicePixelRatio || 1;
    if (dpr > 2) viewer.resolutionScale = 2 / dpr;
    viewer.scene.postProcessStages.fxaa.enabled = true;
    viewer.clock.shouldAnimate = false;
    viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    const globe = viewer.scene.globe;
    globe.baseColor = Cesium.Color.fromCssColorString(body === 'mars' ? '#3a2219' : body === 'moon' ? '#2a2c31' : '#0b1626');
    globe.maximumScreenSpaceError = 1.5;
    const ssc = viewer.scene.screenSpaceCameraController;
    const R = ellipsoid.maximumRadius;
    ssc.minimumZoomDistance = 25;
    ssc.maximumZoomDistance = R * 6;

    if (body === 'earth') this.buildEarth(viewer);
    else this.buildMoonMars(viewer, body);

    this.goHome(0);
    this.attachInput(viewer);
    viewer.scene.preUpdate.addEventListener(() => this.tick());
    viewer.scene.postRender.addEventListener(() => this.afterRender());
    return viewer;
  }

  buildEarth(viewer) {
    const scene = viewer.scene;
    const layers = viewer.imageryLayers;
    const globe = scene.globe;
    globe.enableLighting = true;
    globe.dynamicAtmosphereLighting = true;
    globe.dynamicAtmosphereLightingFromSun = true;
    globe.showGroundAtmosphere = true;
    if (scene.moon) scene.moon.show = false;

    // Day-side pictures stay faintly visible at night ("moonlit"), so the globe's outline never disappears.
    const NIGHT_TINT = 0.16;
    // 1. Offline base picture: our NASA Blue Marble file if present, else Natural Earth II shipped with CesiumJS.
    const base = Cesium.ImageryLayer.fromProviderAsync(
      Cesium.SingleTileImageryProvider.fromUrl(TEXTURES.earth, { credit: 'Blue Marble: NASA Earth Observatory' })
        .catch(() => Cesium.TileMapServiceImageryProvider.fromUrl(Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII'))),
    );
    layers.add(base);
    // 2. NASA Blue Marble, tiled (online, no key).
    const blue = layers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: GIBS.blueMarble,
      maximumLevel: 8,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      credit: new Cesium.Credit('Blue Marble Next Generation: NASA Earth Observatory, via NASA GIBS'),
    }));
    for (const layer of [base, blue]) { layer.nightAlpha = NIGHT_TINT; }
    // 3. Sharp aerial imagery for close-ups (needs the Cesium ion token). Fades in near the ground.
    if (HAS_ION) {
      this.detailLayer = Cesium.ImageryLayer.fromProviderAsync(Cesium.IonImageryProvider.fromAssetId(ION.bing));
      this.detailLayer.alpha = 0;
      this.detailLayer.nightAlpha = NIGHT_TINT;
      this.detailLayer.errorEvent.addEventListener((err) => this.onStatus({ body: 'earth', ion: false, error: String(err) }));
      layers.add(this.detailLayer);
    }
    // 4. NASA Black Marble city lights, only on the night side.
    const night = layers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: GIBS.blackMarble,
      maximumLevel: 8,
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
      credit: new Cesium.Credit('Black Marble (VIIRS 2016): NASA Earth Observatory, via NASA GIBS'),
    }));
    this.nightLayer = night;
    night.dayAlpha = 0.0;
    night.nightAlpha = 1.0;
    night.brightness = 2.2;
    night.gamma = 0.8;

    // 5. Real 3D terrain (needs the Cesium ion token).
    this.terrainReady = HAS_ION ? this.loadEarthTerrain(viewer) : Promise.resolve(false);
  }

  // Cesium World Terrain. The smooth globe with its pictures stays on screen while the terrain loads,
  // and for good when it fails (no internet, slow Wi-Fi, or a token that Cesium ion does not accept).
  // (scene.setTerrain() would remove the globe until Cesium ion answers.) No vertex normals: with them
  // Cesium ignores the day/night setting of the layers, and the city lights cover the day side too.
  loadEarthTerrain(viewer) {
    return Cesium.CesiumTerrainProvider.fromIonAssetId(ION.worldTerrain, { requestWaterMask: true })
      .then((terrain) => {
        if (this.viewer !== viewer) return false; // the user switched body meanwhile
        viewer.scene.terrainProvider = terrain;
        this.has3D = true;
        this.onStatus({ body: 'earth', terrain: true });
        return true;
      })
      .catch((err) => {
        console.warn('World Terrain failed', err);
        if (this.viewer === viewer) this.onStatus({ body: 'earth', ion: false, error: String(err) });
        return false;
      });
  }

  buildMoonMars(viewer, body) {
    const scene = viewer.scene;
    const ellipsoid = ellipsoidFor(body);
    const layers = viewer.imageryLayers;
    const tiling = new Cesium.GeographicTilingScheme({ ellipsoid });
    scene.globe.enableLighting = false;
    scene.globe.showGroundAtmosphere = false; // Earth's blue ground haze must not tint the Moon or Mars

    // 1. Offline picture (if downloaded).
    layers.add(Cesium.ImageryLayer.fromProviderAsync(
      Cesium.SingleTileImageryProvider.fromUrl(TEXTURES[body], {
        ellipsoid,
        credit: body === 'moon' ? 'Moon map: NASA' : 'Mars map: Viking MDIM 2.1, NASA/JPL/USGS',
      }),
    ));
    // 2. NASA Solar System Treks global mosaic (online, no key).
    layers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: TREK[body].url,
      maximumLevel: TREK[body].maximumLevel,
      tilingScheme: tiling,
      ellipsoid,
      credit: new Cesium.Credit(TREK[body].credit),
    }));

    if (body === 'mars') {
      // Mars sky settings from CesiumJS's official Mars example.
      const sky = scene.skyAtmosphere;
      sky.atmosphereMieCoefficient = new Cesium.Cartesian3(9.0e-5, 2.0e-5, 1.0e-5);
      sky.atmosphereRayleighCoefficient = new Cesium.Cartesian3(9.0e-6, 2.0e-6, 1.0e-6);
      sky.atmosphereRayleighScaleHeight = 9000;
      sky.atmosphereMieScaleHeight = 2700.0;
      sky.saturationShift = -0.1;
      sky.perFragmentAtmosphere = true;
    }

    // Artemis III candidate landing regions near the lunar south pole (NASA data, served by Cesium ion).
    if (body === 'moon' && HAS_ION) {
      Cesium.IonResource.fromAssetId(ION.artemis3)
        .then((resource) => Cesium.GeoJsonDataSource.load(resource, {
          clampToGround: true,
          fill: Cesium.Color.fromCssColorString('#ffb547').withAlpha(0.3),
          stroke: Cesium.Color.fromCssColorString('#ffb547'),
          strokeWidth: 2,
        }))
        .then((source) => {
          if (this.viewer !== viewer) return;
          source.name = 'Artemis III candidate regions';
          viewer.dataSources.add(source);
          this.onStatus({ body, artemis: true });
        })
        .catch((err) => {
          console.warn('Artemis III regions unavailable', err);
          if (this.viewer === viewer) this.onStatus({ body, artemis: false, error: String(err), status: err?.statusCode });
        });
    }

    // 3. Real 3D terrain as 3D Tiles (needs the Cesium ion token).
    if (HAS_ION) {
      this.tilesReady = new Promise((resolve) => {
        Cesium.Cesium3DTileset.fromIonAssetId(body === 'moon' ? ION.moon : ION.mars, { enableCollision: true })
          .then((tileset) => {
            if (this.viewer !== viewer) { resolve(false); return; } // the user switched body meanwhile
            this.tileset = tileset;
            scene.primitives.add(tileset);
            tileset.initialTilesLoaded.addEventListener(() => {
              if (this.viewer !== viewer) { resolve(false); return; }
              scene.globe.show = false; // the tiles replace the flat globe
              this.tilesetVisible = true;
              this.has3D = true;
              if (body === 'mars') {
                // Brighter, richer colours for the Mars tiles (settings from CesiumJS's official Mars example).
                const bloom = scene.postProcessStages.bloom;
                bloom.enabled = true;
                bloom.uniforms.brightness = -0.5;
                bloom.uniforms.stepSize = 1.0;
                bloom.uniforms.sigma = 3.0;
                bloom.uniforms.delta = 1.5;
                scene.highDynamicRange = true;
                scene.postProcessStages.exposure = 1.5;
              }
              resolve(true);
              this.onStatus({ body, tiles: true });
            });
          })
          .catch((err) => {
            console.warn('3D tiles unavailable', err);
            resolve(false);
            this.onStatus({ body, tiles: false, error: String(err) });
          });
      });
    }
  }

  // ---------- input, spin and per-frame work ----------
  attachInput(viewer) {
    const stop = () => {
      this.lastInput = performance.now();
      if (this.spinning) this.spinning = false;
      if (this.orbit && !this.orbit.paused) this.orbit.paused = true;
      this.onInput();
    };
    const canvas = viewer.canvas;
    canvas.setAttribute('tabindex', '0');
    canvas.setAttribute('aria-label', `3D globe of ${BODIES[this.body].name}. Drag to rotate, scroll or pinch to zoom.`);
    for (const type of ['pointerdown', 'wheel', 'touchstart']) canvas.addEventListener(type, stop, { passive: true });
    canvas.addEventListener('keydown', (e) => this.onKey(e));
  }

  // Arrow keys rotate the globe, +/- zoom (keyboard access).
  onKey(e) {
    if (this.look) return;
    const cam = this.camera;
    const h = this.ellipsoid.cartesianToCartographic(cam.positionWC).height;
    const step = rad(4);
    let used = true;
    switch (e.key) {
      case 'ArrowLeft': cam.rotate(Cesium.Cartesian3.UNIT_Z, step); break;
      case 'ArrowRight': cam.rotate(Cesium.Cartesian3.UNIT_Z, -step); break;
      case 'ArrowUp': cam.rotateUp(step); break;
      case 'ArrowDown': cam.rotateDown(step); break;
      case '+': case '=': cam.zoomIn(h * 0.25); break;
      case '-': case '_': cam.zoomOut(h * 0.33); break;
      default: used = false;
    }
    if (used) {
      e.preventDefault();
      this.spinning = false;
      this.lastInput = performance.now();
    }
  }

  tick() {
    const now = performance.now();
    const dt = Math.min(0.1, (now - this.lastTick) / 1000);
    this.lastTick = now;
    if (!this.viewer) return;
    if (this.mode === 'globe' && !this.spinning && !REDUCED_MOTION && now - this.lastInput > IDLE_RESUME_MS) this.spinning = true;
    if (this.mode === 'globe' && this.spinning) this.camera.rotate(Cesium.Cartesian3.UNIT_Z, -SPIN_RATE * dt);
    if (this.orbit && !this.orbit.paused && !REDUCED_MOTION) {
      this.orbit.heading += ORBIT_RATE * dt;
      this.camera.lookAt(this.orbit.center, new Cesium.HeadingPitchRange(this.orbit.heading, this.orbit.pitch, this.orbit.range));
    }
  }

  afterRender() {
    if (!this.viewer) return;
    if (this.detailLayer) {
      const h = this.ellipsoid.cartesianToCartographic(this.camera.positionWC).height;
      this.detailLayer.alpha = clamp((2.6e6 - h) / 1.6e6, 0, 1);
    }
    this.onFrame(this);
  }

  // Camera read-out for the HUD.
  cameraInfo() {
    const c = this.ellipsoid.cartesianToCartographic(this.camera.positionWC);
    if (!c) return null;
    return {
      height: c.height,
      lat: deg(c.latitude),
      lon: deg(c.longitude),
      heading: (deg(this.camera.heading) + 360) % 360,
      pitch: deg(this.camera.pitch),
    };
  }

  // True when a place is on the near side of the globe and inside the window.
  onScreen(lon, lat) {
    if (!this.viewer) return false;
    const p = Cesium.Cartesian3.fromDegrees(lon, lat, 0, this.ellipsoid);
    if (!new Cesium.EllipsoidalOccluder(this.ellipsoid, this.camera.positionWC).isPointVisible(p)) return false;
    const toWindow = Cesium.SceneTransforms.worldToWindowCoordinates || Cesium.SceneTransforms.wgs84ToWindowCoordinates;
    const w = toWindow(this.scene, p);
    const c = this.viewer.canvas;
    return !!w && w.x >= 0 && w.y >= 0 && w.x <= c.clientWidth && w.y <= c.clientHeight;
  }

  // Resolves when the pictures (or the 3D tiles) of the current view have loaded, or after ms at most.
  // Used for slide pictures, so a half-loaded view is never captured.
  settled(ms = 20000) {
    const viewer = this.viewer;
    const end = performance.now() + ms;
    let calm = 0;
    return new Promise((resolve) => {
      const check = () => {
        if (this.viewer !== viewer || !viewer) { resolve(false); return; }
        const loaded = this.tilesetVisible && this.tileset ? this.tileset.tilesLoaded : viewer.scene.globe.tilesLoaded;
        calm = loaded ? calm + 1 : 0;
        if (calm >= 5) resolve(true);
        else if (performance.now() > end) resolve(false);
        else setTimeout(check, 200);
      };
      check();
    });
  }

  // ---------- camera moves ----------
  goHome(duration = 2.5) {
    const { lon, lat, height } = BODIES[this.body].home;
    this.flightId += 1;
    this.exitLook();
    this.orbit = null;
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    this.setRealSun();
    const destination = Cesium.Cartesian3.fromDegrees(lon, lat, height, this.ellipsoid);
    this.mode = 'globe';
    if (!duration || REDUCED_MOTION) {
      this.camera.setView({ destination });
      return Promise.resolve(true);
    }
    return flyPromise(this.camera, { destination, duration, easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT });
  }

  // Point the camera at a place from some height, without landing: straight down, or with pitch (degrees,
  // e.g. -35) tilted from the equator side towards the pole. The tilted view is for the lunar south pole,
  // where a straight-down view shows the stretched polar seams of the map pictures.
  // The idle spin waits 2 minutes from here, so the place stays on screen.
  async lookAtPlace(place, { duration = 2, height, pitch, heading } = {}) {
    this.flightId += 1;
    this.exitLook();
    this.orbit = null;
    this.spinning = false;
    this.lastInput = performance.now();
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    this.setRealSun();
    if (!height) height = Math.min(BODIES[this.body].home.height * 0.55, this.ellipsoid.maximumRadius * 2.2);
    this.mode = 'globe';
    const ease = Cesium.EasingFunction.QUADRATIC_IN_OUT;
    if (pitch != null) {
      const center = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, 0, this.ellipsoid);
      const offset = new Cesium.HeadingPitchRange(heading != null ? rad(heading) : place.lat < 0 ? Math.PI : 0, rad(pitch), height);
      return flySpherePromise(this.camera, new Cesium.BoundingSphere(center, 10), { offset, duration: REDUCED_MOTION ? 0 : duration, easingFunction: ease });
    }
    const destination = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, height, this.ellipsoid);
    if (REDUCED_MOTION) { this.camera.setView({ destination }); return true; }
    return flyPromise(this.camera, { destination, duration, easingFunction: ease });
  }

  // Height for SOUTH_POLE_VIEW. Cesium's field of view spans the longer side of the window, so on a tall phone
  // screen the four pins would sit twice as close together: the camera then comes closer by the same factor.
  southPoleHeight() {
    const c = this.viewer?.canvas;
    const aspect = c ? c.clientWidth / Math.max(1, c.clientHeight) : 1;
    return SOUTH_POLE_VIEW.height * Math.min(1, aspect * 1.1);
  }

  // Ground height under a place: { h, sampled }. Waits a few seconds at most and remembers real answers,
  // so a second visit is instant. While the 3D terrain is still loading it uses the measured height from
  // data/terrain.json (or 0, the bare globe) and does not remember that; sampled is then false, and
  // refineHeight() moves the camera once the 3D terrain answers. Without this the camera could end up
  // inside a mountain (Malapert's summit is about 5 km above the Moon's reference sphere).
  async groundHeight(lon, lat) {
    const key = `${this.body}:${lon.toFixed(4)}:${lat.toFixed(4)}`;
    if (this.heightCache.has(key)) return { h: this.heightCache.get(key), sampled: true };
    const h = await Promise.race([this.sampleHeight(lon, lat), new Promise((resolve) => setTimeout(() => resolve(null), 8000))]);
    if (Number.isFinite(h)) {
      this.heightCache.set(key, h);
      return { h, sampled: true };
    }
    const known = this.knownHeight(this.body, lon, lat);
    return { h: Number.isFinite(known) ? known : 0, sampled: false };
  }

  // After a move that had to guess the ground height: wait for the 3D terrain (no time limit) and,
  // if the same move still owns the camera, call apply(height) with the real height.
  refineHeight(lon, lat, stillCurrent, apply) {
    this.sampleHeight(lon, lat).then((h) => {
      if (!Number.isFinite(h) || !stillCurrent()) return;
      this.heightCache.set(`${this.body}:${lon.toFixed(4)}:${lat.toFixed(4)}`, h);
      apply(h);
    });
  }

  // Height of the 3D terrain at a place, or null when there is no 3D terrain (yet) or sampling failed.
  // On the Moon and Mars it first waits for the 3D tiles to show (groundHeight limits the wait).
  async sampleHeight(lon, lat) {
    const viewer = this.viewer;
    const carto = Cesium.Cartographic.fromDegrees(lon, lat);
    try {
      if (this.body === 'earth') {
        if (!(await this.terrainReady)) return null;
        const [p] = await Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [carto]);
        return p && Number.isFinite(p.height) ? p.height : null;
      }
      if (!(await this.tilesReady) || this.viewer !== viewer || !viewer.scene.sampleHeightSupported) return null;
      const [p] = await viewer.scene.sampleHeightMostDetailed([carto]);
      return p && Number.isFinite(p.height) ? p.height : null;
    } catch (err) {
      console.warn('height sampling failed', err);
      return null;
    }
  }

  // Fly from space down to the place, tilt towards the horizon, then slowly orbit it.
  // Resolves false when the flight was interrupted or a newer camera move (or another world) took over.
  // Base plan: come closer to the place of the current close-up (the slow orbit goes on), so a base about
  // 80 m wide fills the view. Returns the ground height of the orbit centre, or null if there is no close-up.
  async closeOrbit(range, pitchDeg) {
    const o = this.orbit;
    if (!o || this.mode !== 'closeup') return null;
    o.paused = true;
    const pitch = rad(pitchDeg);
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    const ok = await flySpherePromise(this.camera, new Cesium.BoundingSphere(o.center, 10), {
      offset: new Cesium.HeadingPitchRange(o.heading, pitch, range),
      duration: REDUCED_MOTION ? 0 : 2.4,
      easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
    });
    if (!ok || this.orbit !== o) return null;
    Object.assign(o, { pitch, range, paused: false });
    this.camera.lookAt(o.center, new Cesium.HeadingPitchRange(o.heading, pitch, range));
    return this.ellipsoid.cartesianToCartographic(o.center).height;
  }

  // World swap of the Base plan: put the camera straight into the slow orbit around a place, with no flight,
  // at the same heading, pitch and range as before, so the base stays in the same spot on the screen.
  // Returns the ground height of the orbit centre, or null when a newer camera move took over.
  async jumpOrbit(place, { heading, pitch, range }) {
    const viewer = this.viewer;
    const ellipsoid = this.ellipsoid;
    this.flightId += 1;
    const token = this.flightId;
    const current = () => this.viewer === viewer && this.flightId === token;
    this.exitLook();
    this.orbit = null;
    this.spinning = false;
    this.lastInput = performance.now();
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    this.setSunForPlace(place);
    // Look at the place first (at its measured height, if known), so its terrain starts loading at once.
    const guess = this.knownHeight(this.body, place.lon, place.lat);
    const look = (h) => {
      const center = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, h, ellipsoid);
      this.camera.lookAt(center, new Cesium.HeadingPitchRange(heading, pitch, range));
      return center;
    };
    look(Number.isFinite(guess) ? guess : 0);
    this.mode = 'flying';
    const { h } = await this.groundHeight(place.lon, place.lat);
    if (!current()) return null;
    const center = look(h);
    this.orbit = { center, heading, pitch, range, paused: true }; // resumeOrbit() once the new world is shown
    this.mode = 'closeup';
    return h;
  }

  // Resolves when the ground on screen has finished loading (a few calm frames in a row), or after ms.
  waitForTiles(ms = 8000) {
    const viewer = this.viewer;
    const t0 = performance.now();
    let calm = 0;
    return new Promise((resolve) => {
      const step = () => {
        if (this.viewer !== viewer) { resolve(false); return; }
        const ts = this.tileset;
        const loaded = viewer.scene.globe.tilesLoaded && (!ts || !ts.show || ts.tilesLoaded);
        calm = loaded ? calm + 1 : 0;
        if (calm >= 4) { resolve(true); return; }
        if (performance.now() - t0 > ms) { resolve(false); return; }
        requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  // A picture of the 3D view as it is now (data: URL), taken right after a frame is drawn; null if not possible.
  snapshot() {
    const scene = this.viewer?.scene;
    if (!scene) return Promise.resolve(null);
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => { if (done) return; done = true; remove(); resolve(v); };
      const remove = scene.postRender.addEventListener(() => {
        try { finish(scene.canvas.toDataURL('image/jpeg', 0.9)); } catch { finish(null); }
      });
      scene.requestRender();
      setTimeout(() => finish(null), 1000);
    });
  }

  async flyToPlace(place) {
    const body = BODIES[this.body];
    const ellipsoid = this.ellipsoid;
    const viewer = this.viewer;
    this.flightId += 1;
    const token = this.flightId;
    const current = () => this.viewer === viewer && this.flightId === token;
    this.exitLook();
    this.orbit = null;
    this.spinning = false;
    this.lastInput = performance.now();
    this.mode = 'flying';
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    this.setSunForPlace(place);
    const fast = REDUCED_MOTION;
    const above = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, body.approach, ellipsoid);
    const ok = await flyPromise(this.camera, {
      destination: above,
      orientation: { heading: 0, pitch: rad(-90), roll: 0 },
      duration: fast ? 0 : 3.4,
      easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
    });
    if (!ok) { if (current()) this.mode = 'globe'; return false; }
    const { h, sampled } = await this.groundHeight(place.lon, place.lat);
    if (!current()) return false; // the newer move owns the camera and the mode
    const center = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, h, ellipsoid);
    const heading = rad(25);
    const pitch = rad(-15);
    const range = body.range;
    const ok2 = await flySpherePromise(this.camera, new Cesium.BoundingSphere(center, 10), {
      offset: new Cesium.HeadingPitchRange(heading, pitch, range),
      duration: fast ? 0 : 4.6,
      easingFunction: Cesium.EasingFunction.QUADRATIC_IN_OUT,
    });
    if (!ok2) { if (current()) this.mode = 'globe'; return false; }
    if (!current()) return false;
    this.orbit = { center, heading, pitch, range, paused: false };
    this.camera.lookAt(center, new Cesium.HeadingPitchRange(heading, pitch, range));
    this.mode = 'closeup';
    if (!sampled) {
      this.refineHeight(place.lon, place.lat, () => current() && this.mode === 'closeup' && this.orbit, (real) => {
        this.orbit.center = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, real, this.ellipsoid);
        this.camera.lookAt(this.orbit.center, new Cesium.HeadingPitchRange(this.orbit.heading, this.orbit.pitch, this.orbit.range));
      });
    }
    return true;
  }

  resumeOrbit() {
    if (this.orbit) this.orbit.paused = false;
  }

  // Eye-level view on the 3D terrain (used when no real photo exists). Drag to look around.
  // Resolves false when a newer camera move (or another world) took over.
  async standHere(place) {
    const body = BODIES[this.body];
    const viewer = this.viewer;
    this.flightId += 1;
    const token = this.flightId;
    const current = () => this.viewer === viewer && this.flightId === token;
    // Pressed again while already standing: drop the old look-around state (its heading and pitch),
    // so the first arrow key or drag starts from the new view.
    this.exitLook();
    this.orbit = null;
    this.spinning = false;
    this.lastInput = performance.now();
    this.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);
    this.setSunForPlace(place);
    const { h, sampled } = await this.groundHeight(place.lon, place.lat);
    if (!current()) return false;
    const destination = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, h + body.eye, this.ellipsoid);
    const ok = await flyPromise(this.camera, {
      destination,
      orientation: { heading: rad(20), pitch: rad(-4), roll: 0 },
      duration: REDUCED_MOTION ? 0 : 3,
    });
    if (!ok || !current()) return false;
    this.enterLook();
    this.mode = 'ground';
    if (!sampled) {
      this.refineHeight(place.lon, place.lat, () => current() && this.mode === 'ground', (real) => {
        const cam = this.camera;
        cam.setView({
          destination: Cesium.Cartesian3.fromDegrees(place.lon, place.lat, real + body.eye, this.ellipsoid),
          orientation: { heading: cam.heading, pitch: cam.pitch, roll: 0 },
        });
      });
    }
    return { eyeHeight: body.eye, groundHeight: h };
  }

  enterLook() {
    if (this.look) return;
    const ssc = this.scene.screenSpaceCameraController;
    const saved = { rotate: ssc.enableRotate, translate: ssc.enableTranslate, zoom: ssc.enableZoom, tilt: ssc.enableTilt, look: ssc.enableLook };
    ssc.enableRotate = ssc.enableTranslate = ssc.enableZoom = ssc.enableTilt = ssc.enableLook = false;
    const cam = this.camera;
    let heading = cam.heading;
    let pitch = cam.pitch;
    let drag = null;
    const apply = () => cam.setView({ orientation: { heading, pitch, roll: 0 } });
    const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.canvas);
    handler.setInputAction((e) => { drag = Cesium.Cartesian2.clone(e.position); }, Cesium.ScreenSpaceEventType.LEFT_DOWN);
    handler.setInputAction(() => { drag = null; }, Cesium.ScreenSpaceEventType.LEFT_UP);
    handler.setInputAction((m) => {
      if (!drag) return;
      const k = cam.frustum.fov / this.viewer.canvas.clientHeight;
      heading -= (m.endPosition.x - m.startPosition.x) * k;
      pitch = clamp(pitch + (m.endPosition.y - m.startPosition.y) * k, rad(-80), rad(60));
      apply();
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction((delta) => {
      const fov = clamp(cam.frustum.fov - delta * 0.0008, rad(25), rad(100));
      cam.frustum.fov = fov;
    }, Cesium.ScreenSpaceEventType.WHEEL);
    const keys = (e) => {
      const step = rad(5);
      if (e.key === 'ArrowLeft') heading -= step;
      else if (e.key === 'ArrowRight') heading += step;
      else if (e.key === 'ArrowUp') pitch = clamp(pitch + step, rad(-80), rad(60));
      else if (e.key === 'ArrowDown') pitch = clamp(pitch - step, rad(-80), rad(60));
      else return;
      e.preventDefault();
      apply();
    };
    this.viewer.canvas.addEventListener('keydown', keys);
    this.look = { handler, saved, keys, fov: cam.frustum.fov };
    cam.frustum.fov = rad(75);
  }

  exitLook() {
    if (!this.look || !this.viewer) { this.look = null; return; }
    const ssc = this.scene.screenSpaceCameraController;
    const s = this.look.saved;
    ssc.enableRotate = s.rotate; ssc.enableTranslate = s.translate; ssc.enableZoom = s.zoom; ssc.enableTilt = s.tilt; ssc.enableLook = s.look;
    this.look.handler.destroy();
    this.viewer.canvas.removeEventListener('keydown', this.look.keys);
    this.camera.frustum.fov = this.look.fov;
    this.look = null;
  }

  // ---------- lighting ----------
  // Far view: the Sun is placed at 13:00 local solar time over the home longitude (Jordan on Earth),
  // so the area we talk about is lit and the night side with city lights is still visible.
  // Close-ups: 10:00 local solar time at the site. Both are display choices, not the current time.
  setRealSun() {
    if (!this.viewer) return;
    this.setClockForLocalTime(BODIES[this.body].home.lon, 13);
    this.scene.light = new Cesium.SunLight();
    this.setDayNight(true);
  }

  // Day/night shading only in the far view. Close to the ground the satellite photos already carry
  // their own daylight and shadows, and the night layer would wrongly show on slopes facing away.
  setDayNight(on) {
    if (this.body !== 'earth' || !this.viewer) return;
    const globe = this.scene.globe;
    globe.enableLighting = on;
    globe.dynamicAtmosphereLighting = on;
    if (this.nightLayer) this.nightLayer.show = on;
  }

  setClockForLocalTime(lon, localHour) {
    const now = new Date();
    const midnight = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
    const utcHours = localHour - lon / 15;
    this.viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(midnight + utcHours * 3600e3));
  }

  setSunForPlace(place) {
    if (!this.viewer) return;
    if (this.body === 'earth') {
      this.setClockForLocalTime(place.lon, 10);
      this.scene.light = new Cesium.SunLight();
      this.setDayNight(false);
      return;
    }
    // Moon and Mars: a fixed light 30° above the eastern horizon of the site (a display choice, shown in the HUD).
    const center = Cesium.Cartesian3.fromDegrees(place.lon, place.lat, 0, this.ellipsoid);
    const enu = Cesium.Transforms.eastNorthUpToFixedFrame(center, this.ellipsoid);
    const el = rad(30);
    const az = rad(110);
    const toSunLocal = new Cesium.Cartesian3(Math.cos(el) * Math.sin(az), Math.cos(el) * Math.cos(az), Math.sin(el));
    const toSun = Cesium.Matrix4.multiplyByPointAsVector(enu, toSunLocal, new Cesium.Cartesian3());
    Cesium.Cartesian3.normalize(toSun, toSun);
    this.scene.light = new Cesium.DirectionalLight({ direction: Cesium.Cartesian3.negate(toSun, new Cesium.Cartesian3()), intensity: 2.2 });
  }
}
