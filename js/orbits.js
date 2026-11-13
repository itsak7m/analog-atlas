// Where Earth and Mars are, from JPL's "Approximate Positions of the Planets" (E. M. Standish, Table 1:
// Keplerian elements and their rates, mean ecliptic and equinox of J2000, valid 1800-2050).
// https://ssd.jpl.nasa.gov/planets/approx_pos.html  · Used for the signal delay and the solar conjunction
// in Base plan. Accuracy: a fraction of a degree in position, so distances to well under 1 %.

const AU_KM = 149597870.7; // IAU 2012, exact
export const LIGHT_KM_S = 299792.458; // exact (SI definition)

// a (au), e, I (deg), L (deg), long. of perihelion (deg), long. of ascending node (deg); then the rates per century.
const ELEMENTS = {
  earth: [[1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0],
    [0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0]], // Earth-Moon barycentre
  mars: [[1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891],
    [0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343]],
};

const RAD = Math.PI / 180;
const julianDay = (date) => date.getTime() / 86400000 + 2440587.5;

// Heliocentric ecliptic position (km) of 'earth' or 'mars' at a Date.
export function position(planet, date) {
  const T = (julianDay(date) - 2451545.0) / 36525;
  const [el, rate] = ELEMENTS[planet];
  const [a, e, I, L, peri, node] = el.map((v, i) => v + rate[i] * T);
  const w = peri - node;
  let M = (L - peri) % 360;
  if (M > 180) M -= 360;
  if (M < -180) M += 360;
  const eStar = e / RAD;
  let E = M + eStar * Math.sin(M * RAD);
  for (let i = 0; i < 20; i++) {
    const dM = M - (E - eStar * Math.sin(E * RAD));
    const dE = dM / (1 - e * Math.cos(E * RAD));
    E += dE;
    if (Math.abs(dE) < 1e-8) break;
  }
  const xp = a * (Math.cos(E * RAD) - e);
  const yp = a * Math.sqrt(1 - e * e) * Math.sin(E * RAD);
  const [cw, sw, cO, sO, cI, sI] = [Math.cos(w * RAD), Math.sin(w * RAD), Math.cos(node * RAD), Math.sin(node * RAD), Math.cos(I * RAD), Math.sin(I * RAD)];
  const x = (cw * cO - sw * sO * cI) * xp + (-sw * cO - cw * sO * cI) * yp;
  const y = (cw * sO + sw * cO * cI) * xp + (-sw * sO + cw * cO * cI) * yp;
  const z = (sw * sI) * xp + (cw * sI) * yp;
  return [x * AU_KM, y * AU_KM, z * AU_KM];
}

const sub = (p, q) => p.map((v, i) => v - q[i]);
const len = (p) => Math.hypot(...p);

// Earth-Mars distance (km) at a Date.
export function marsDistanceKm(date) {
  return len(sub(position('mars', date), position('earth', date)));
}

// One-way light time (seconds) from Earth to Mars at a Date.
export const marsDelaySeconds = (date) => marsDistanceKm(date) / LIGHT_KM_S;

// Angle Sun-Earth-Mars (degrees). Near 0 with Mars far away = solar conjunction (Mars behind the Sun).
export function marsElongationDeg(date) {
  const earth = position('earth', date);
  const toSun = earth.map((v) => -v);
  const toMars = sub(position('mars', date), earth);
  const cos = toSun.reduce((s, v, i) => s + v * toMars[i], 0) / (len(toSun) * len(toMars));
  return Math.acos(Math.max(-1, Math.min(1, cos))) / RAD;
}

// The next solar conjunction after a Date: the day with the smallest Sun-Earth-Mars angle while Mars is
// on the far side of the Sun. Searches day by day over one synodic period (about 780 days), then by hour.
export function nextConjunction(from) {
  const day = 86400000;
  let best = null;
  for (let i = 0; i <= 800; i++) {
    const d = new Date(from.getTime() + i * day);
    const el = marsElongationDeg(d);
    if (marsDistanceKm(d) > AU_KM * 1.5 && (!best || el < best.el)) best = { d, el };
    if (best && el > best.el + 5) break; // past the minimum
  }
  if (!best) return null;
  let fine = best;
  for (let h = -36; h <= 36; h++) {
    const d = new Date(best.d.getTime() + h * 3600000);
    const el = marsElongationDeg(d);
    if (el < fine.el) fine = { d, el };
  }
  return { date: fine.d, elongationDeg: fine.el };
}

// "3 min 2 s", "1.28 s", "22 min".
export function formatDelay(seconds) {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return s ? `${m} min ${s} s` : `${m} min`;
}
