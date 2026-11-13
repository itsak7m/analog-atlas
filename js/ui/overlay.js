// Accessible full-screen overlay (dialog) used by the 360° viewer, Method & data and Tune factors.

import { esc } from '../util.js';

let current = null;

export function openOverlay({ title, badge = '', body, wide = true, onClose }) {
  closeOverlay();
  const root = document.getElementById('overlay-root');
  const lastFocus = document.activeElement;
  const id = `ov-${Date.now()}`;
  root.innerHTML = `<div class="overlay" role="dialog" aria-modal="true" aria-labelledby="${id}">
    <div class="sheet bracket" style="${wide ? '' : 'width:min(760px,100%)'}">
      <div class="sheet-head"><h2 id="${id}">${esc(title)}</h2>${badge}<div class="spacer"></div>
        <button type="button" class="btn small" data-close>✕ Close</button></div>
      ${body}
    </div></div>`;
  const el = root.firstElementChild;
  const close = () => closeOverlay();
  el.querySelector('[data-close]').addEventListener('click', close);
  el.addEventListener('click', (e) => { if (e.target === el) close(); });
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); }
    if (e.key === 'Tab') {
      // Keep keyboard focus inside the dialog.
      const items = [...el.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.disabled && x.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  document.addEventListener('keydown', onKey, true);
  current = { el, onKey, onClose, lastFocus };
  el.querySelector('[data-close]').focus();
  return el;
}

export function closeOverlay() {
  if (!current) return;
  const { el, onKey, onClose, lastFocus } = current;
  current = null;
  document.removeEventListener('keydown', onKey, true);
  if (onClose) onClose();
  el.remove();
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

export const overlayOpen = () => !!current;
