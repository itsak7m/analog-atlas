// Analog Atlas – Cesium ion token for the public GitHub Pages copy (https://itsak7m.github.io/analog-atlas/).
//
// This token is public on purpose: browser apps always show their keys. It is safe because, in the
// Cesium ion account, it is limited to:
//   - Allowed URLs: https://itsak7m.github.io only (it does not work on any other site),
//   - scope assets:read only, and only the 5 assets the app uses (1, 2, 2684829, 3644333, 2683531).
// It is used only on itsak7m.github.io. On your own computer the app keeps using config.js (not in git).
(function () {
  if (location.hostname !== 'itsak7m.github.io') return;
  const cfg = (window.ANALOG_ATLAS_CONFIG = window.ANALOG_ATLAS_CONFIG || {});
  if (!cfg.cesiumIonToken) cfg.cesiumIonToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImJmeGQ1Nzl1TkJDUmFnN2EiLCJqdGkiOiI5ZmY3NTdhNi01YmI4LTQwYzYtYTI4NS0zMjMzODNmZGFhNTAiLCJpZCI6NTE4ODIzLCJzdWIiOiJfYWs3bSIsImlzcyI6Imh0dHBzOi8vYXBpLmNlc2l1bS5jb20iLCJhdWQiOiJhbmFsb2ctYXRsYXMtcGFnZXMiLCJpYXQiOjE3OTQ1NjczMTF9.KXpXkpC7DTCLQTxONiXC_hKnhnws3pXBa4XpnajoSLM';
})();
