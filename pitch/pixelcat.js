// Cosmic Cats mascot: our own pixel-art cat in a space helmet (sprite 38 x 24 pixels, faces right).
// Shared by promo.html and deck/backgrounds.html. makePixelCat(g, W) draws into the 2D context g (canvas width W).
export function makePixelCat(g, W) {
  const C = { amber: '#ffb547', mars: '#ff6a3d', cyan: '#5ce1e6' };
  const CAT_HEAD = ['.KK.......KK.', '.KgK.....KgK.', '.KggKKKKKggK.', 'KgggggggggggK', 'KggWKgggWKggK', 'KggKKgggKKggK', 'KppgggKgggppK', 'KgggKgKgKgggK', '.KgggggggggK.', '..KKKKKKKKK..'];
  const PIX = { K: '#1b1b22', g: '#a3a9b4', G: '#5d6370', w: '#f2f3f6', s: '#c3c8d0', a: '#ffb547', p: '#f4a3b5', W: '#ffffff', c: '#e6f4ff' };
  const catCv = document.createElement('canvas'); catCv.width = 38; catCv.height = 24;
  function catSprite(t, walk, light) {
    const q = catCv.getContext('2d'), px = (x, y, c) => { q.fillStyle = PIX[c] || c; q.fillRect(x, y, 1, 1); };
    q.clearRect(0, 0, 38, 24);
    const step = Math.floor(t * 8) % 2;
    for (let i = 0; i < 5; i++) { const x = 5 - i, y = 12 - Math.floor(i * 0.6) + Math.round(Math.sin(t * 9 - i * 0.9)); px(x, y, 'K'); px(x, y + 1, 'g'); px(x, y + 2, 'g'); px(x, y + 3, 'K'); } // tail
    [8, 11, 17, 20].forEach((x, k) => { const l = walk && k % 2 === step ? 1 : 0; for (const r of [20, 21]) { px(x, r - l, 's'); px(x + 1, r - l, 'w'); } px(x, 22 - l, 'G'); px(x + 1, 22 - l, 'G'); }); // legs + boots
    for (let x = 6; x <= 23; x++) for (let y = 10; y <= 19; y++) { // suit
      const ex = x === 6 || x === 23, ey = y === 10 || y === 19; if (ex && ey) continue;
      px(x, y, ex || ey ? 'K' : y === 18 ? 's' : 'w'); }
    for (const [x, y] of [[12, 14], [13, 14], [12, 15], [13, 15], [11, 13], [14, 13]]) px(x, y, 'a'); // paw badge
    const hx = 27, hy = 8.5, R = 8.6; // helmet glass
    for (let x = 17; x < 38; x++) for (let y = 0; y < 19; y++) { const d = Math.hypot(x + 0.5 - hx, y + 0.5 - hy); if (d < R - 0.5) px(x, y, 'rgba(170,215,255,0.22)'); }
    CAT_HEAD.forEach((row, r) => [...row].forEach((c, i) => { if (c !== '.') px(21 + i, 4 + r, c); }));
    for (let x = 17; x < 38; x++) for (let y = 0; y < 19; y++) { const d = Math.hypot(x + 0.5 - hx, y + 0.5 - hy), a = Math.atan2(y + 0.5 - hy, x + 0.5 - hx);
      if (d >= R - 0.5 && d < R + 0.5) px(x, y, 'c'); else if (d >= R - 2.2 && d < R - 1.2 && a > -2.6 && a < -1.9) px(x, y, 'rgba(255,255,255,0.8)'); }
    px(33, 1, 's'); px(34, 1, 's'); if (light > 0) px(34, 1, '#fff8d0'); // headlamp
  }
  function pixelCat(x, y, P, t, { walk = true, light = 0, flag = 0 } = {}) { // (x, y) = feet, P = screen pixels per sprite pixel
    const X = (c) => x + (c - 18) * P, Y = (r) => y + (r - 23) * P;
    if (light > 0) { const lb = g.createLinearGradient(X(35), Y(1), 1100, Y(1)); lb.addColorStop(0, `rgba(255,250,220,${0.55 * light})`); lb.addColorStop(1, 'rgba(255,250,220,0)'); g.fillStyle = lb; g.beginPath(); g.moveTo(X(35), Y(1)); g.lineTo(x + 900, y - 520); g.lineTo(x + 900, y + 60); g.closePath(); g.fill(); }
    catSprite(t, walk, light);
    g.save(); g.imageSmoothingEnabled = false; g.shadowColor = 'rgba(0,0,0,0.4)'; g.shadowBlur = 14; g.drawImage(catCv, X(0), Y(0), 38 * P, 24 * P); g.restore();
    if (flag > 0) { // pixel flag with a paw print
      const fx = X(37), top = y - Math.round(26 * flag) * P;
      g.fillStyle = '#ddd'; g.fillRect(fx, top, P, y - top);
      const fw = Math.round(10 * flag), fh = Math.round(7 * flag); g.fillStyle = C.amber; g.fillRect(fx + P, top, fw * P, fh * P);
      if (flag > 0.95) { g.fillStyle = '#1b1b22'; for (const [a, b] of [[3, 1], [5, 1], [2, 2], [6, 2], [3, 3], [4, 3], [5, 3], [3, 4], [4, 4], [5, 4]]) g.fillRect(fx + (a + 1) * P, top + b * P, P, P); }
    }
  }
  function flyCat(x, y, P, t) { // Nyan-style fly-by with a trail in the team colours; (x, y) = centre of the sprite
    const y0 = y - 12 * P, tail = x - 16 * P, seg = 8 * P;
    g.save();
    for (let j = 0, sx = tail; sx > -seg; j++, sx -= seg) { const off = ((j + Math.floor(t * 8)) % 2) * P;
      [C.mars, C.amber, C.cyan].forEach((col, k) => { g.fillStyle = col; g.fillRect(sx - seg, y0 + (11 + 2 * k) * P + off, seg + 1, 2 * P); }); }
    for (let k = 0; k < 9; k++) { const sx = W - ((k * 263 + t * 500) % (W + 100)), sy = y0 - 120 + (k * 137) % (24 * P + 240), s = Math.max(2, P * 0.8); // sparkles
      g.globalAlpha = 0.5 + 0.5 * Math.sin(t * 12 + k); g.fillStyle = '#fff'; g.fillRect(sx - s, sy, 3 * s, s); g.fillRect(sx, sy - s, s, 3 * s); }
    g.restore();
    pixelCat(x, y0 + 23 * P, P, t, { walk: true });
  }
  return { pixelCat, flyCat };
}
