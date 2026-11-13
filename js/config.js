// Settings and fixed service addresses.
// The Cesium ion token comes from config.js (window.ANALOG_ATLAS_CONFIG), or, if that is empty,
// from the "Turn on 3D" box in the app, which keeps it in this browser only (localStorage).

const user = window.ANALOG_ATLAS_CONFIG || {};
export const TOKEN_STORE_KEY = 'analog-atlas-ion-token';

function storedToken() {
  try { return (localStorage.getItem(TOKEN_STORE_KEY) || '').trim(); } catch { return ''; }
}

const fileToken = typeof user.cesiumIonToken === 'string' ? user.cesiumIonToken.trim() : '';
export const ION_TOKEN = fileToken || storedToken();
export const TOKEN_SOURCE = fileToken ? 'config.js' : ION_TOKEN ? 'browser' : 'none';
// ?no3d in the address turns 3D off for this visit, even with a token (fallback when the venue has no internet).
export const NO_3D = /[?&]no3d\b/.test(location.search);
export const HAS_ION = !NO_3D && ION_TOKEN.length > 20;

// Cesium ion assets (see Method & data for credits).
export const ION = {
  worldTerrain: 1,      // Cesium World Terrain
  bing: 2,              // Bing Maps Aerial imagery
  moon: 2684829,        // "Cesium Moon": LOLA + Kaguya elevation, LROC imagery (NASA, USGS)
  mars: 3644333,        // "Cesium Mars": MOLA + HRSC elevation, Viking/CTX/HiRISE imagery (NASA, USGS)
  artemis3: 2683531,    // Artemis III candidate landing regions (GeoJSON)
};

// NASA GIBS (no key needed): Blue Marble by day, Black Marble city lights at night.
export const GIBS = {
  blueMarble: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
  blackMarble: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png',
};

// NASA Solar System Treks (no key needed): global image mosaics.
export const TREK = {
  moon: { url: 'https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg', maximumLevel: 8, credit: 'NASA/GSFC/Arizona State University (LRO WAC) via NASA Solar System Treks' },
  mars: { url: 'https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg', maximumLevel: 7, credit: 'NASA/JPL/USGS (Viking MDIM 2.1) via NASA Solar System Treks' },
};

// Offline fallback pictures (equirectangular, −180° at the left edge).
export const TEXTURES = {
  earth: 'textures/earth.jpg',
  moon: 'textures/moon.jpg',
  mars: 'textures/mars.jpg',
};

export const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
