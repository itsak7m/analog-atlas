// "Turn on 3D": paste a free Cesium ion token without editing files.
// The token is kept only in this browser (localStorage). config.js, if filled in, wins.

import { HAS_ION, NO_3D, TOKEN_SOURCE, TOKEN_STORE_KEY } from '../config.js';
import { esc, toast } from '../util.js';
import { openOverlay } from './overlay.js';

const looksLikeToken = (t) => /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(t) && t.length > 100;

// The same address with or without ?no3d (the switch that turns 3D off for one visit).
export function addressWith3D(on) {
  const p = new URLSearchParams(location.search);
  if (on) p.delete('no3d'); else p.set('no3d', '');
  const q = p.toString().replace(/=(?=&|$)/g, '');
  return `${location.pathname}${q ? `?${q}` : ''}`;
}

// The last 3D problem reported by the globe (main.js), shown in the dialog. Empty when 3D works.
let problem = '';
export function setIonProblem(text) { problem = text || ''; }

export function openTokenSetup() {
  const off = `<a href="${esc(addressWith3D(false))}">${esc(location.host)}/?no3d</a>`;
  const status = NO_3D
    ? `<p class="caveat">3D is off for this visit: the address has <b>?no3d</b>. The globe shows the NASA pictures without 3D terrain and does not use Cesium ion, so it also works without internet. <a href="${esc(addressWith3D(true))}">Turn 3D back on</a>.</p>`
    : HAS_ION
      ? `${problem
        ? `<p class="caveat">A token is set (in <b>${TOKEN_SOURCE === 'config.js' ? 'config.js' : 'this browser'}</b>), but 3D did not load: ${esc(problem)}</p>`
        : `<p class="caveat" style="border-left-color:var(--green);color:#c9f2cf">3D is on. The token comes from <b>${TOKEN_SOURCE === 'config.js' ? 'config.js' : 'this browser'}</b>.</p>`}
        <p class="src">No internet at the venue? Open ${off} to turn 3D off for one visit. The globe then shows the NASA pictures without 3D terrain and does not wait for Cesium ion. The token stays saved.</p>`
      : '<p class="caveat">3D terrain is off. The app works, but close-ups are flat.</p>';
  const el = openOverlay({
    title: 'Turn on 3D terrain',
    wide: false,
    body: `<div class="sheet-body">
      ${status}
      <ol class="setup-steps">
        <li>Open <a href="https://ion.cesium.com/signup" target="_blank" rel="noopener">ion.cesium.com/signup</a> and create a free account (Community plan).</li>
        <li>In <b>Asset Depot</b>, find <b>Cesium Moon</b> and press <b>Add to my assets</b>. Do the same for <b>Cesium Mars</b>.</li>
        <li>In <b>Access Tokens</b>, press <b>Create token</b>: name <code>analog-atlas-local</code>, keep only <b>assets:read</b>, and under <b>Allowed URLs</b> add <code>http://localhost:8080</code> and <code>http://127.0.0.1:8080</code> (the same app can open at either address). Press <b>Create</b>, then <b>Copy</b>.</li>
        <li>Paste the token here and press <b>Save</b>. The page reloads with 3D.</li>
      </ol>
      <form id="token-form" class="token-form">
        <label for="token-input">Cesium ion token</label>
        <input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="Paste the token here (it starts with eyJ…)" ${TOKEN_SOURCE === 'config.js' ? 'disabled' : ''}>
        <div class="actions" style="margin-top:8px">
          <button type="submit" class="btn primary" ${TOKEN_SOURCE === 'config.js' ? 'disabled' : ''}>Save</button>
          ${TOKEN_SOURCE === 'browser' ? '<button type="button" class="btn primary" id="token-file">Save it for all browsers (config.js)</button><button type="button" class="btn" id="token-remove">Remove saved token</button>' : ''}
        </div>
      </form>
      <p class="src">${TOKEN_SOURCE === 'config.js'
    ? 'The token is saved in the file config.js in the project folder. Before you copy, zip or share the folder, leave config.js out (config.example.js is the empty template).'
    : 'The token is saved only in this browser on this computer.'} Do not share it in chats or emails. Cesium tokens are always visible to people who use the app, so keep the "Allowed URLs" limit. When you publish the app one day, make a new token for the new address.</p>
    </div>`,
  });
  el.querySelector('#token-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const value = el.querySelector('#token-input').value.trim();
    if (!looksLikeToken(value)) {
      toast('That does not look like a Cesium token. Copy it again from Access Tokens (it starts with eyJ).', 6000);
      return;
    }
    try {
      localStorage.setItem(TOKEN_STORE_KEY, value);
    } catch {
      toast('This browser blocked saving. Put the token in config.js instead (see README).', 6000);
      return;
    }
    location.reload();
  });
  el.querySelector('#token-file')?.addEventListener('click', async () => {
    let token = '';
    try { token = localStorage.getItem(TOKEN_STORE_KEY) || ''; } catch { /* ignore */ }
    try {
      const res = await fetch('/api/save-token', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
      if (!res.ok) throw new Error(`server answered ${res.status}`);
      toast('Saved in config.js: 3D now works in every browser on this computer. Leave config.js out when you share the project folder.', 7000);
    } catch (err) {
      toast(`Could not save config.js (${err.message}). Start the app with start.bat and try again.`, 7000);
    }
  });
  el.querySelector('#token-remove')?.addEventListener('click', () => {
    try { localStorage.removeItem(TOKEN_STORE_KEY); } catch { /* ignore */ }
    location.reload();
  });
}
