// Analog Atlas – local settings template.
// Copy this file to config.js and fill in your own values there.
//
// IMPORTANT: everything in config.js is visible to anyone who opens the app
// in a browser (that is how browser apps work). The Cesium ion token is made
// for this, but in your Cesium ion account set its Allowed URLs to
// http://localhost:8080 and http://127.0.0.1:8080 (the app opens on both).
// Never put secret keys (for example a Claude API key) in this file.
//
// Before you copy, zip or share the project folder, leave config.js out
// (or delete it). Share this template instead.
window.ANALOG_ATLAS_CONFIG = {
  // Free token from https://ion.cesium.com/tokens (scope: assets:read).
  // Needed for 3D terrain on Earth, the Moon and Mars. Without it the app
  // still runs with offline globe images.
  cesiumIonToken: "",
};
