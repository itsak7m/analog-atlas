// Tiny canvas line chart for live sensor values (no external library).

// minSpan: the smallest y-range drawn (display only), so tiny noise does not look like big jumps.
// note: a word drawn at the bottom left, e.g. "Simulated", so a simulated chart never reads as a measurement.
export function drawChart(canvas, points, { color = '#5ce1e6', unit = '', digits = 1, label = '', minSpan = 0, note = '' } = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  g.font = '500 11px "IBM Plex Sans Condensed", sans-serif';
  g.fillStyle = '#8f9cb3';
  g.fillText(label.toUpperCase(), 0, 10);
  if (note) {
    g.fillStyle = '#ffb547';
    g.fillText(note.toUpperCase(), 0, h - 1);
  }
  const vals = points.filter((p) => Number.isFinite(p.v));
  if (vals.length < 2) {
    g.fillStyle = '#8090a8'; // same as --dim in css/app.css (AA contrast)
    g.fillText(vals.length ? `${vals[0].v.toFixed(digits)} ${unit}` : 'no data', 0, h / 2 + 8);
    return;
  }
  let lo = Math.min(...vals.map((p) => p.v));
  let hi = Math.max(...vals.map((p) => p.v));
  if (hi - lo < (minSpan || 1e-6)) {
    const mid = (hi + lo) / 2;
    const span = minSpan || 2; // no minimum given: a flat line gets a range of 2
    lo = mid - span / 2; hi = mid + span / 2;
  }
  const t0 = vals[0].t;
  const t1 = vals[vals.length - 1].t || t0 + 1;
  const top = 16;
  const bottom = h - 12;
  const x = (t) => ((t - t0) / Math.max(1, t1 - t0)) * (w - 2) + 1;
  const y = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
  g.strokeStyle = '#1a2640';
  g.lineWidth = 1;
  g.beginPath(); g.moveTo(0, bottom + 0.5); g.lineTo(w, bottom + 0.5); g.stroke();
  g.strokeStyle = color;
  g.lineWidth = 1.6;
  g.beginPath();
  vals.forEach((p, i) => (i ? g.lineTo(x(p.t), y(p.v)) : g.moveTo(x(p.t), y(p.v))));
  g.stroke();
  const last = vals[vals.length - 1];
  g.fillStyle = color;
  g.beginPath(); g.arc(x(last.t), y(last.v), 2.5, 0, Math.PI * 2); g.fill();
  g.font = '500 11px "IBM Plex Mono", monospace';
  g.textAlign = 'right';
  g.fillText(`${last.v.toFixed(digits)} ${unit}`.trim(), w, 10);
  g.fillStyle = '#8090a8'; // same as --dim in css/app.css (AA contrast)
  g.font = '11px "IBM Plex Mono", monospace';
  g.fillText(`${lo.toFixed(digits)}–${hi.toFixed(digits)}`, w, h - 1);
  g.textAlign = 'left';
}
