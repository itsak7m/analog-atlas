#!/usr/bin/env python3
"""Terrain-slope statistics for Analog Atlas (NASA Space Apps 2026, Amman).

For every point in data/terrain_points.json the script samples a 21 x 21 grid of
elevations (500 m spacing, a 10 km x 10 km box centred on the point) from a
public elevation service, computes the slope at each interior grid point by
central differences over a 1 km baseline, and writes summary statistics to
data/terrain.json.

Elevation sources (verified 2026-10-09):
  Earth  Open-Meteo Elevation API, Copernicus DEM GLO-90
  Moon   NASA Solar System Treks, LRO LOLA DEM Global 128 ppd v04 (ArcGIS ImageServer getSamples)
  Mars   NASA Solar System Treks, MGS MOLA Global DEM 128/64 ppd merge (ArcGIS ImageServer getSamples)

Raw API responses are cached in data/raw/terrain/<id>.json, so later runs work
offline. Python 3.12 standard library only. Run from any folder:

  python -I scripts/compute_terrain.py              # use the cache, download what is missing
  python -I scripts/compute_terrain.py --refresh    # download every point again
  python -I scripts/compute_terrain.py --only gale  # one point (merged into data/terrain.json)
  python -I scripts/compute_terrain.py --offline    # never use the network

Open-Meteo's free API allows 600 calls/min, 5,000/hour and 10,000/day per IP
address, and its source code counts every coordinate as one call. One Earth
point needs 441 coordinates, so all 19 Earth sites need 8,379 "calls". The
script therefore pauses between requests, stays under an hourly budget and, if
needed, waits for the next clock hour. Interrupted runs resume from the cache.
"""

import argparse
import collections
import datetime
import http.client
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# Paths and method constants
# --------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POINTS = os.path.join(ROOT, "data", "terrain_points.json")
DEFAULT_OUT = os.path.join(ROOT, "data", "terrain.json")
DEFAULT_CACHE = os.path.join(ROOT, "data", "raw", "terrain")

GRID_N = 21                     # samples per side
HALF = GRID_N // 2              # index of the centre row/column
SPACING_M = 500.0               # grid spacing
BASELINE_M = 2 * SPACING_M      # central-difference baseline (1 km)
SAFE_SLOPE_DEG = 10.0            # landing-zone slope limit (NASA Artemis III: under 10 deg over 100 m, NTRS 20250009323)
FLAT_FRACTION = 0.20            # share of identical elevations that flags a flat (water) surface
COORD_DECIMALS = 6              # 1e-6 deg is <= 0.11 m on Earth
RADIUS_M = {"earth": 6371008.8, "moon": 1737400.0, "mars": 3389500.0}   # mean radii
KINDS = ("site", "target", "candidate-target")
CACHE_FORMAT = 1
USER_AGENT = "analog-atlas-terrain/1.0 (NASA Space Apps 2026 project; Python urllib)"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
OPEN_METEO_MAX_COORDS = 100     # documented maximum per request
OPEN_METEO_PAUSE_S = 12.0       # <= 5 requests (500 coordinates) per minute; limit is 600
OPEN_METEO_HOURLY_BUDGET = 4800 # coordinates per clock hour; limit is 5,000

TREK_CHUNK = 147                # points per GET (POST is refused; URLs above ~8 kB get HTTP 414)
TREK_MAX_URL = 7500
TREK_PAUSE_S = 1.0
TREK_INTERPOLATION = "RSP_BilinearInterpolation"

TREK_MOON = "https://trek.nasa.gov/moon/trekarcgis/rest/services/LRO_LOLA_DEM_Global_128ppd_v04/ImageServer"
TREK_MARS = ("https://trek.nasa.gov/mars/trekarcgis/rest/services/"
             "mola128_mola64_merge_90Nto90S_SimpleC_clon0/ImageServer")

DATASETS = {
    "earth": {
        "key": "copernicus-dem-glo90@open-meteo",
        "body": "earth",
        "name": "Copernicus DEM GLO-90 (2021 release) via the Open-Meteo Elevation API",
        "resolution": ("3 arc-seconds (~90 m; longitude spacing widens above 50 deg latitude). "
                       "The API returns the value of the DEM pixel that contains each coordinate "
                       "(no interpolation)."),
        "elev_datum": "m above the EGM2008 geoid (Copernicus DEM; horizontal datum WGS84-G1150)",
        "coordinates": "WGS84 latitude, longitude east-positive -180..180",
        "licence": ("Copernicus DEM GLO-90 is free to use under the Copernicus DEM licence (ESA). "
                    "Open-Meteo API data: CC BY 4.0; the free API is for non-commercial use "
                    "(600 calls/min, 5,000/h, 10,000/day; each coordinate counts as one call)."),
        "credit": ("Produced using Copernicus WorldDEM-90 (c) DLR e.V. 2010-2014 and (c) Airbus "
                   "Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European "
                   "Union and ESA; all rights reserved. Elevation API by Open-Meteo.com."),
        "url": OPEN_METEO_URL,
        "docs": [
            "https://open-meteo.com/en/docs/elevation-api",
            "https://open-meteo.com/en/terms",
            "https://doi.org/10.5270/ESA-c5d3d65",
            "https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Dem/DownloadDem.swift",
        ],
        "caveats": ("Copernicus DEM flattens lakes and seas to a single height, which is what the "
                    "flat_water_suspect flag detects. Values come back in whole metres."),
    },
    "moon": {
        "key": "lro-lola-dem-global-128ppd-v04@trek",
        "body": "moon",
        "name": "LRO LOLA DEM Global 128 ppd v04 (NASA Solar System Treks, Moon Trek)",
        "resolution": ("128 pixels per degree (~237 m at the equator), float32. Sampled with "
                       "ArcGIS getSamples, bilinear interpolation."),
        "elev_datum": "m relative to the 1,737,400 m reference sphere (Moon 2000; radius = value + 1,737,400 m)",
        "coordinates": ("GCS_Moon_2000 (wkid 104903): latitude, longitude east-positive -180..180; "
                        "service extent -180..180 / -90..90"),
        "wkid": 104903,
        "licence": "NASA data; Trek metadata: 'Access constraints: None; Use constraints: None'.",
        "credit": ("LOLA Instrument Team, NASA Goddard Space Flight Center (Lunar Reconnaissance "
                   "Orbiter); served by NASA Solar System Treks (trek.nasa.gov)."),
        "url": TREK_MOON,
        "docs": [
            "https://trek.nasa.gov/moon/TrekWS/rest/cat/metadata/fgdc/html?label=LRO_LOLA_DEM_Global_128ppd_v04",
            TREK_MOON + "?f=json",
            "https://developers.arcgis.com/rest/services-reference/enterprise/get-samples/",
        ],
        "caveats": ("Pixels without LOLA shots are filled by interpolation; LOLA cross-track spacing "
                    "is ~1.2 km at the equator and ~25 m above 85 deg, so near-equator slopes at a "
                    "1 km baseline are smoothed. Trek also serves higher-resolution LOLA DEMs that "
                    "are NOT used here, to keep all Moon points consistent: "
                    "LRO_LOLA_DEM_Global_256ppd_v06 (~118 m), LRO_LOLA_DEM_SPole75_30mp_v04 "
                    "(30 m, polar stereographic, 75 S to the pole), LRO_LOLA_DEM_SPole875_5mp_v04 "
                    "(5 m, 87.5 S to the pole)."),
        "expected_resolution": 0.0078125,
    },
    "mars": {
        "key": "mgs-mola-dem-128-64ppd-merge@trek",
        "body": "mars",
        "name": "MGS MOLA Global DEM, 128/64 ppd merge (NASA Solar System Treks, Mars Trek)",
        "resolution": ("Blend of the 128 and 64 pixels-per-degree MOLA grids; most of the surface is "
                       "at 128 ppd (~463 m at the equator), whose data are sparse above 87 N/S. "
                       "16-bit integer metres. Sampled with ArcGIS getSamples, bilinear interpolation."),
        "elev_datum": "m above the MOLA areoid (Mars geoid from gravity model GMM-2B, degree and order 50)",
        "coordinates": ("GCS_Mars_2000 (wkid 104905): planetocentric latitude, longitude east-positive "
                        "-180..180 (0..360 longitudes are not accepted by the service)"),
        "wkid": 104905,
        "licence": "NASA data, public domain (USGS Astrogeology lists the MOLA 463 m DEM as CC0).",
        "credit": ("MOLA Science Team, NASA Goddard Space Flight Center (Mars Global Surveyor); "
                   "served by NASA Solar System Treks (trek.nasa.gov)."),
        "url": TREK_MARS,
        "docs": [
            ("https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems?"
             "proj=urn:ogc:def:crs:EPSG::104905&start=0&rows=10&key=MOLA"),
            TREK_MARS + "?f=json",
            "https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m",
            "https://developers.arcgis.com/rest/services-reference/enterprise/get-samples/",
        ],
        "caveats": ("Gaps of 1-2 km between MOLA tracks are common (up to 12 km near the equator) "
                    "and are interpolated, so slopes at a 1 km baseline are smoothed."),
        "expected_resolution": 0.00781224569558698,
    },
}

METHOD_TEXT = (
    "Each point is the centre of a 21 x 21 grid of elevation samples spaced 500 m apart "
    "(a 10 km x 10 km box). At the centre, rows run north and columns run east. Every sample "
    "is placed with the spherical destination-point formula (distance sqrt(dx^2 + dy^2), "
    "bearing atan2(dx, dy) from the centre) on a sphere with the body's mean radius "
    "(Earth 6,371,008.8 m; Moon 1,737,400 m; Mars 3,389,500 m), so the grid stays valid near "
    "the poles. At each of the 19 x 19 = 361 interior samples, dz/dx and dz/dy are central "
    "differences over the 1 km (2 x 500 m) baseline, and slope = atan(sqrt((dz/dx)^2 + "
    "(dz/dy)^2)) in degrees. Statistics: median, mean and 90th percentile of the 361 slopes "
    "(percentile by linear interpolation, Python statistics.quantiles 'inclusive'); percent of "
    "slope cells below 8, below 10 and below 15 degrees (pct_lt_8, pct_lt_10, pct_lt_15); "
    "max_flat_square_km = side of the largest square of interior samples in which every slope "
    "is below 10 degrees (NASA's Artemis III landing slope limit), in 500 m steps from 0.5 to "
    "9.5 km (0 if no sample qualifies), which the landing-zone pillar uses; relief = highest "
    "minus lowest of the 441 elevations; elevation of the centre sample; flat_water_suspect = "
    "true when at least 20% "
    "of the samples share one identical elevation (lakes or sea surfaces, which the Copernicus "
    "DEM flattens; also salt flats). Slopes at a 1 km baseline describe kilometre-scale terrain, "
    "not boulders or metre-scale roughness, and depend on each DEM's resolution (about 90 m "
    "Earth, 237 m Moon, 463 m Mars), so comparisons across bodies are approximate."
)


class FetchError(Exception):
    """A download failed for good."""


class QuotaError(FetchError):
    """Open-Meteo's daily limit is used up; later Earth downloads cannot work today."""


def log(msg=""):
    print(msg, flush=True)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
def normalize_lon(lon):
    """Wrap a longitude into [-180, 180)."""
    lon = math.fmod(lon + 180.0, 360.0)
    if lon < 0:
        lon += 360.0
    return lon - 180.0


def destination(lat, lon, bearing_rad, dist_m, radius_m):
    """Spherical destination point from (lat, lon) along an initial bearing."""
    if dist_m == 0:
        return lat, normalize_lon(lon)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    delta = dist_m / radius_m
    sin_phi2 = (math.sin(phi1) * math.cos(delta)
                + math.cos(phi1) * math.sin(delta) * math.cos(bearing_rad))
    sin_phi2 = max(-1.0, min(1.0, sin_phi2))
    phi2 = math.asin(sin_phi2)
    y = math.sin(bearing_rad) * math.sin(delta) * math.cos(phi1)
    x = math.cos(delta) - math.sin(phi1) * sin_phi2
    lam2 = lam1 + math.atan2(y, x)
    return math.degrees(phi2), normalize_lon(math.degrees(lam2))


def great_circle_m(lat1, lon1, lat2, lon2, radius_m):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def build_grid(lat, lon, radius_m):
    """21 x 21 sample grid, row-major: row 0 is the southern edge, column 0 the western edge."""
    if abs(lat) > 89.99:
        raise ValueError("centre is at a pole, where north/east are undefined")
    lats, lons = [], []
    for r in range(GRID_N):
        north = (r - HALF) * SPACING_M
        for c in range(GRID_N):
            east = (c - HALF) * SPACING_M
            la, lo = destination(lat, lon, math.atan2(east, north), math.hypot(east, north), radius_m)
            lats.append(round(la, COORD_DECIMALS))
            lons.append(round(lo, COORD_DECIMALS))
    return lats, lons


def check_baselines(lats, lons, radius_m):
    """Largest deviation (m) of any central-difference pair from the nominal 1 km baseline."""
    worst = 0.0
    for r in range(1, GRID_N - 1):
        for c in range(1, GRID_N - 1):
            pairs = (((r, c - 1), (r, c + 1)), ((r - 1, c), (r + 1, c)))
            for (r1, c1), (r2, c2) in pairs:
                i, j = r1 * GRID_N + c1, r2 * GRID_N + c2
                d = great_circle_m(lats[i], lons[i], lats[j], lons[j], radius_m)
                worst = max(worst, abs(d - BASELINE_M))
    return worst


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def parse_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Open-Meteo prints a missing value as a bare 'nan', which is not valid JSON.
        return json.loads(re.sub(r"(?<![A-Za-z\"])nan(?![A-Za-z\"])", "NaN", text))


def http_get_text(url, what, on_429=None, attempts=6, timeout=90):
    """GET with retries and exponential backoff. Raises FetchError with a clear message."""
    delay = 2.0
    last = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code == 429 and on_429 is not None:
                on_429(body)          # waits as the API asks, or raises QuotaError
                continue
            if e.code in (408, 429, 500, 502, 503, 504):
                last = "HTTP %d: %s" % (e.code, body[:200].strip())
            else:
                raise FetchError("%s: HTTP %d %s: %s" % (what, e.code, e.reason, body[:300].strip()))
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            last = "%s: %s" % (type(e).__name__, e)
        if attempt < attempts:
            log("    retry %d/%d in %.0f s (%s: %s)" % (attempt, attempts - 1, delay, what, last))
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
    raise FetchError("%s: giving up after %d attempts (%s)" % (what, attempts, last))


def http_get_json(url, what, on_429=None, attempts=3):
    """http_get_text plus JSON parsing; a malformed (e.g. cut-off) body is fetched again."""
    for attempt in range(1, attempts + 1):
        text = http_get_text(url, what, on_429=on_429)
        try:
            return parse_json(text), text
        except ValueError:
            if attempt == attempts:
                raise FetchError("%s: response is not valid JSON: %s" % (what, text[:200]))
            log("    %s: response is not valid JSON, fetching again" % what)
            time.sleep(5 * attempt)


class OpenMeteoPacer:
    """Keeps Open-Meteo requests under the free-API limits (counted per coordinate)."""

    def __init__(self, pause_s, hourly_budget):
        self.pause_s = pause_s
        self.hourly_budget = hourly_budget
        self.last_call = 0.0
        self.hour = None
        self.used = 0
        self.blocked = None          # set to a message once the daily limit is hit

    def _roll_hour(self):
        hour = int(time.time() // 3600)
        if hour != self.hour:
            self.hour, self.used = hour, 0

    def wait_for_next_hour(self, reason):
        now = time.time()
        wait = 3600 - (now % 3600) + 90      # the server resets its hourly counters in minute 0
        resume = datetime.datetime.fromtimestamp(now + wait, datetime.timezone.utc)
        log("    %s - waiting %.0f min, until %s UTC" % (reason, wait / 60, resume.strftime("%H:%M")))
        time.sleep(wait)
        self._roll_hour()

    def before(self, n_coords):
        if self.blocked:
            raise QuotaError(self.blocked)
        self._roll_hour()
        if self.used + n_coords > self.hourly_budget:
            self.wait_for_next_hour("hourly budget of %d coordinates reached" % self.hourly_budget)
        wait = self.last_call + self.pause_s - time.time()
        if wait > 0:
            time.sleep(wait)

    def after(self, n_coords):
        self.last_call = time.time()
        self._roll_hour()
        self.used += n_coords

    def on_429(self, body):
        try:
            reason = str(json.loads(body).get("reason", ""))
        except (ValueError, AttributeError):
            reason = body[:200].strip()
        low = reason.lower()
        if "daily" in low:
            self.blocked = ("Open-Meteo daily limit reached (%s). Cached points are kept; run the "
                            "script again after 00:00 UTC to download the rest." % reason)
            raise QuotaError(self.blocked)
        if "hourly" in low:
            self.wait_for_next_hour("Open-Meteo: " + reason)
        elif "minutely" in low:
            log("    Open-Meteo: %s - waiting 65 s" % reason)
            time.sleep(65)
        else:
            log("    Open-Meteo HTTP 429 (%s) - waiting 30 s" % (reason or "no reason given"))
            time.sleep(30)
        self.last_call = time.time()


# --------------------------------------------------------------------------
# Downloads
# --------------------------------------------------------------------------
def fetch_open_meteo(point_id, lats, lons, pacer):
    requests_log = []
    n_chunks = (len(lats) + OPEN_METEO_MAX_COORDS - 1) // OPEN_METEO_MAX_COORDS
    for k, i in enumerate(range(0, len(lats), OPEN_METEO_MAX_COORDS), start=1):
        la = lats[i:i + OPEN_METEO_MAX_COORDS]
        lo = lons[i:i + OPEN_METEO_MAX_COORDS]
        query = urllib.parse.urlencode({
            "latitude": ",".join("%.6f" % v for v in la),
            "longitude": ",".join("%.6f" % v for v in lo),
        }, safe=",")
        url = OPEN_METEO_URL + "?" + query
        what = "%s Open-Meteo request %d/%d" % (point_id, k, n_chunks)
        pacer.before(len(la))
        try:
            data, text = http_get_json(url, what, on_429=pacer.on_429)
        finally:
            pacer.after(len(la))
        if not isinstance(data, dict) or data.get("error") or "elevation" not in data:
            raise FetchError("%s: unexpected response: %s" % (what, text[:300]))
        elev = data["elevation"]
        if len(elev) != len(la):
            raise FetchError("%s: asked for %d elevations, got %d" % (what, len(la), len(elev)))
        clean = [None if v is None or (isinstance(v, float) and math.isnan(v)) else v for v in elev]
        requests_log.append({"url": url, "n_points": len(la), "response": {"elevation": clean}})
        log("    %s ok" % what)
    return requests_log


_TREK_LAST_CALL = [0.0]


def trek_wait(pause_s):
    """Polite pause between Trek requests, also across points."""
    wait = _TREK_LAST_CALL[0] + pause_s - time.time()
    if wait > 0:
        time.sleep(wait)
    _TREK_LAST_CALL[0] = time.time()


def fetch_trek(point_id, ds, lats, lons, pause_s):
    requests_log = []
    n_chunks = (len(lats) + TREK_CHUNK - 1) // TREK_CHUNK
    for k, i in enumerate(range(0, len(lats), TREK_CHUNK), start=1):
        pts = [[lons[j], lats[j]] for j in range(i, min(len(lats), i + TREK_CHUNK))]
        geometry = json.dumps({"points": pts, "spatialReference": {"wkid": ds["wkid"]}},
                              separators=(",", ":"))
        url = ds["url"] + "/getSamples?" + urllib.parse.urlencode({
            "geometry": geometry,
            "geometryType": "esriGeometryMultipoint",
            "returnFirstValueOnly": "true",
            "interpolation": TREK_INTERPOLATION,
            "f": "json",
        })
        if len(url) > TREK_MAX_URL:
            raise FetchError("request URL too long (%d chars); lower TREK_CHUNK" % len(url))
        what = "%s Trek request %d/%d" % (point_id, k, n_chunks)
        data = None
        for attempt in range(1, 5):
            trek_wait(pause_s * attempt)
            data, _ = http_get_json(url, what)
            err = data.get("error") if isinstance(data, dict) else {"message": "not a JSON object"}
            if not err:
                break
            code = err.get("code") if isinstance(err, dict) else None
            if code in (500, 502, 503, 504) and attempt < 4:
                log("    %s: service error %s, retrying" % (what, json.dumps(err)[:200]))
                continue
            raise FetchError("%s: service error: %s" % (what, json.dumps(err)[:300]))
        if not isinstance(data.get("samples"), list):
            raise FetchError("%s: response has no 'samples' list" % what)
        requests_log.append({"url": url, "n_points": len(pts), "response": data})
        log("    %s ok" % what)
    return requests_log


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def request_params(body):
    if body == "earth":
        return {"service": "open-meteo elevation", "max_coords_per_request": OPEN_METEO_MAX_COORDS}
    return {"service": "arcgis getSamples", "interpolation": TREK_INTERPOLATION,
            "wkid": DATASETS[body]["wkid"], "chunk": TREK_CHUNK}


def write_json_atomic(path, obj, tmp_dir, compact=False):
    """Write JSON via a temporary file in tmp_dir, then rename (readers never see half a file)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(tmp_dir, ".tmp-%d-%s" % (os.getpid(), os.path.basename(path)))
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1, allow_nan=False)
        f.write("\n")
    os.replace(tmp, path)


def cache_is_valid(cache, point, lats, lons):
    ds = DATASETS[point["body"]]
    return (isinstance(cache, dict)
            and cache.get("format") == CACHE_FORMAT
            and cache.get("body") == point["body"]
            and cache.get("dataset") == ds["key"]
            and cache.get("service") == ds["url"]
            and cache.get("params") == request_params(point["body"])
            and cache.get("grid", {}).get("lat") == lats
            and cache.get("grid", {}).get("lon") == lons
            and isinstance(cache.get("requests"), list))


def get_cache(point, args, pacer):
    """Return the cached raw responses for a point, downloading them if needed."""
    pid, body = point["id"], point["body"]
    ds = DATASETS[body]
    lats, lons = build_grid(point["lat"], point["lon"], RADIUS_M[body])
    worst = check_baselines(lats, lons, RADIUS_M[body])
    if worst > 1.0:
        raise ValueError("grid check failed: a 1 km baseline is off by %.2f m" % worst)
    path = os.path.join(args.cache_dir, pid + ".json")

    if not args.refresh and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError) as e:
            cache = None
            log("    cache file unreadable (%s)" % e)
        if cache_is_valid(cache, point, lats, lons):
            return cache, "cache"
        log("    cache does not match the current point/grid/dataset")

    if args.offline:
        raise FetchError("no valid cache file %s and --offline was given" % path)

    if body == "earth":
        requests_log = fetch_open_meteo(pid, lats, lons, pacer)
    else:
        requests_log = fetch_trek(pid, ds, lats, lons, args.trek_pause)

    cache = {
        "format": CACHE_FORMAT,
        "id": pid,
        "body": body,
        "centre": {"lat": point["lat"], "lon": point["lon"]},
        "dataset": ds["key"],
        "service": ds["url"],
        "params": request_params(body),
        "fetched": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "grid": {
            "n": GRID_N, "spacing_m": SPACING_M, "radius_m": RADIUS_M[body],
            "order": "row-major; row 0 = southern edge (-5000 m north), column 0 = western edge (-5000 m east)",
            "lat": lats, "lon": lons,
        },
        "requests": requests_log,
    }
    write_json_atomic(path, cache, args.cache_dir, compact=True)
    return cache, "downloaded"


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def trek_value(raw):
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None                    # 'NoData' or similar
    if math.isnan(v) or abs(v) > 1e6:
        return None
    return v


def elevations_from_cache(cache):
    """Return (elevations, notes) in grid order; missing samples are None."""
    lats, lons = cache["grid"]["lat"], cache["grid"]["lon"]
    values, notes = [], []
    resolutions = set()
    offset = 0
    for req in cache["requests"]:
        n = req["n_points"]
        if cache["body"] == "earth":
            chunk = [None if v is None else float(v) for v in req["response"]["elevation"]]
        else:
            chunk = [None] * n
            for s in req["response"].get("samples", []):
                lid = s.get("locationId")
                if not isinstance(lid, int) or not 0 <= lid < n:
                    raise ValueError("sample with unexpected locationId %r" % lid)
                loc = s.get("location", {})
                if (abs(float(loc.get("x")) - lons[offset + lid]) > 1e-6
                        or abs(float(loc.get("y")) - lats[offset + lid]) > 1e-6):
                    raise ValueError("sample location does not match the requested point")
                chunk[lid] = trek_value(s.get("value"))
                if "resolution" in s:
                    resolutions.add(s["resolution"])
        if len(chunk) != n:
            raise ValueError("response length mismatch")
        values.extend(chunk)
        offset += n
    if len(values) != GRID_N * GRID_N:
        raise ValueError("expected %d samples, found %d" % (GRID_N * GRID_N, len(values)))
    expected = DATASETS[cache["body"]].get("expected_resolution")
    if expected is not None and resolutions and any(abs(r - expected) > 1e-9 for r in resolutions):
        notes.append("service reported pixel size(s) %s deg instead of %s"
                     % (", ".join("%.7g" % r for r in sorted(resolutions)), expected))
    return values, notes


def compute_point(point, cache):
    body = point["body"]
    ds = DATASETS[body]
    z, notes = elevations_from_cache(cache)
    valid = [v for v in z if v is not None]
    n_missing = len(z) - len(valid)
    if len(valid) < 2:
        raise ValueError("no usable elevations")

    slopes = []
    inner = GRID_N - 2
    flat_run = [[0] * inner for _ in range(inner)]  # side of the largest flat square ending here
    max_flat = 0
    for r in range(1, GRID_N - 1):
        for c in range(1, GRID_N - 1):
            zn, zs = z[(r + 1) * GRID_N + c], z[(r - 1) * GRID_N + c]
            ze, zw = z[r * GRID_N + c + 1], z[r * GRID_N + c - 1]
            if None in (zn, zs, ze, zw):
                continue
            dzdx = (ze - zw) / BASELINE_M
            dzdy = (zn - zs) / BASELINE_M
            slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
            slopes.append(slope)
            if slope < SAFE_SLOPE_DEG:
                i, j = r - 1, c - 1
                k = 1 if i == 0 or j == 0 else 1 + min(flat_run[i - 1][j], flat_run[i][j - 1], flat_run[i - 1][j - 1])
                flat_run[i][j] = k
                max_flat = max(max_flat, k)
    if len(slopes) < 2:
        raise ValueError("too few slope cells")

    centre = z[HALF * GRID_N + HALF]
    mode_value, mode_count = collections.Counter(valid).most_common(1)[0]
    identical_pct = 100.0 * mode_count / len(valid)
    flat = mode_count >= FLAT_FRACTION * len(valid)

    if n_missing:
        notes.append("%d of %d samples had no data and were skipped" % (n_missing, len(z)))
    if centre is None:
        notes.append("no elevation at the centre sample")
    if flat:
        if body == "earth":
            what = "sea surface" if mode_value == 0 else "flattened lake/sea surface or salt flat in the DEM"
            notes.append("%.0f%% of samples share the elevation %g m (%s)" % (identical_pct, mode_value, what))
        else:
            notes.append("%.0f%% of samples share the elevation %g m (constant DEM values; not water)"
                         % (identical_pct, mode_value))
    elif identical_pct >= 10:
        where = ", the lowest value in the box (like a lake surface)" if mode_value == min(valid) else ""
        notes.append("%.0f%% of samples share the elevation %g m%s; below the %d%% flag threshold"
                     % (identical_pct, mode_value, where, round(100 * FLAT_FRACTION)))
    if abs(point["lat"]) >= 80:
        dl = [normalize_lon(lo - point["lon"]) for lo in cache["grid"]["lon"]]
        notes.append("high-latitude box: sample longitudes span %.1f deg around the centre meridian"
                     % (max(dl) - min(dl)))

    return {
        "body": body,
        "lat": point["lat"],
        "lon": point["lon"],
        "median_slope_deg": round(statistics.median(slopes), 2),
        "mean_slope_deg": round(statistics.fmean(slopes), 2),
        "p90_slope_deg": round(statistics.quantiles(slopes, n=10, method="inclusive")[8], 2),
        "pct_lt_8": round(100.0 * sum(s < 8 for s in slopes) / len(slopes), 1),
        "pct_lt_10": round(100.0 * sum(s < 10 for s in slopes) / len(slopes), 1),
        "pct_lt_15": round(100.0 * sum(s < 15 for s in slopes) / len(slopes), 1),
        # Largest square in which every grid point is under 10 deg (side in km, 500 m steps).
        "max_flat_square_km": round(max_flat * SPACING_M / 1000.0, 1),
        "relief_m": round(max(valid) - min(valid), 1),
        "centre_elev_m": None if centre is None else round(centre, 1),
        "elev_datum": ds["elev_datum"],
        "n_samples": len(valid),
        "flat_water_suspect": flat,
        "dataset": ds["key"],
        "notes": "; ".join(notes),
        "name": point["name"],
        "kind": point["kind"],
        "coordSource": point["coordSource"],
        "n_slope_cells": len(slopes),
        "max_identical_pct": round(identical_pct, 1),
        "fetched": cache.get("fetched"),
    }


# --------------------------------------------------------------------------
# Input / output
# --------------------------------------------------------------------------
def load_points(path):
    with open(path, encoding="utf-8") as f:
        points = json.load(f)
    if not isinstance(points, list):
        raise SystemExit("%s must contain a JSON list" % path)
    seen = set()
    for p in points:
        for key in ("id", "body", "name", "lat", "lon", "kind", "coordSource"):
            if key not in p:
                raise SystemExit("point %r is missing '%s'" % (p.get("id"), key))
        if p["id"] in seen or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", p["id"]):
            raise SystemExit("bad or duplicate id %r" % p["id"])
        seen.add(p["id"])
        if p["body"] not in RADIUS_M:
            raise SystemExit("%s: unknown body %r" % (p["id"], p["body"]))
        if p["kind"] not in KINDS:
            raise SystemExit("%s: kind must be one of %s" % (p["id"], ", ".join(KINDS)))
        if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
            raise SystemExit("%s: latitude/longitude out of range" % p["id"])
    return points


def load_previous(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("points", {})
    except (OSError, ValueError, AttributeError):
        return {}


def print_table(points, out_points):
    log()
    log("%-20s %-5s %6s %6s %6s %6s %6s %8s %9s %5s" % (
        "id", "body", "median", "mean", "p90", "<8%", "<15%", "relief", "centre", "flat"))
    for p in points:
        r = out_points.get(p["id"])
        if not r:
            log("%-20s %-5s  (no result)" % (p["id"], p["body"]))
            continue
        centre = "-" if r["centre_elev_m"] is None else "%.0f" % r["centre_elev_m"]
        log("%-20s %-5s %6.2f %6.2f %6.2f %6.1f %6.1f %8.0f %9s %5s" % (
            p["id"], p["body"], r["median_slope_deg"], r["mean_slope_deg"], r["p90_slope_deg"],
            r["pct_lt_8"], r["pct_lt_15"], r["relief_m"], centre,
            "yes" if r["flat_water_suspect"] else "no"))


def print_rankings(points, out_points, top=5):
    earth = [(p["id"], out_points[p["id"]]) for p in points
             if p["body"] == "earth" and p["id"] in out_points]
    if not earth:
        return
    log()
    log("Earth sites closest in median slope (deg) to each target:")
    for p in points:
        if p["kind"] != "target" or p["id"] not in out_points:
            continue
        t = out_points[p["id"]]["median_slope_deg"]
        ranked = sorted(earth, key=lambda kv: abs(kv[1]["median_slope_deg"] - t))[:top]
        log("  %-10s %5.2f : %s" % (p["id"], t, ", ".join(
            "%s %.2f (d=%.2f)" % (pid, r["median_slope_deg"], abs(r["median_slope_deg"] - t))
            for pid, r in ranked)))


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Compute terrain-slope statistics for Analog Atlas.")
    ap.add_argument("--refresh", action="store_true", help="download again even if cached")
    ap.add_argument("--only", action="append", metavar="ID",
                    help="process only this point id (repeatable); other results are kept")
    ap.add_argument("--offline", action="store_true", help="use cached responses only")
    ap.add_argument("--points", default=DEFAULT_POINTS, help="input point list (JSON)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output file (JSON)")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE, help="raw response cache folder")
    ap.add_argument("--om-pause", type=float, default=OPEN_METEO_PAUSE_S,
                    help="seconds between Open-Meteo requests (default %(default)s)")
    ap.add_argument("--om-hourly-budget", type=int, default=OPEN_METEO_HOURLY_BUDGET,
                    help="Open-Meteo coordinates per clock hour (default %(default)s)")
    ap.add_argument("--trek-pause", type=float, default=TREK_PAUSE_S,
                    help="seconds between Trek requests (default %(default)s)")
    args = ap.parse_args(argv)
    if args.refresh and args.offline:
        ap.error("--refresh and --offline cannot be combined")
    return args


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    points = load_points(args.points)
    ids = {p["id"] for p in points}
    if args.only:
        unknown = sorted(set(args.only) - ids)
        if unknown:
            raise SystemExit("unknown id(s): %s" % ", ".join(unknown))
        selected = [p for p in points if p["id"] in set(args.only)]
    else:
        selected = list(points)
    # Moon and Mars first (fast); Earth last (rate-limited API).
    selected.sort(key=lambda p: p["body"] == "earth")
    os.makedirs(args.cache_dir, exist_ok=True)

    pacer = OpenMeteoPacer(args.om_pause, args.om_hourly_budget)
    results, failures = {}, {}
    for n, p in enumerate(selected, start=1):
        log("[%d/%d] %s (%s, %.4f, %.4f)" % (n, len(selected), p["id"], p["body"], p["lat"], p["lon"]))
        try:
            cache, source = get_cache(p, args, pacer)
            results[p["id"]] = compute_point(p, cache)
            r = results[p["id"]]
            log("    %s: median %.2f deg, relief %.0f m, %d samples%s" % (
                source, r["median_slope_deg"], r["relief_m"], r["n_samples"],
                ", FLAT" if r["flat_water_suspect"] else ""))
        except (FetchError, ValueError, KeyError, TypeError, AttributeError, OSError) as e:
            failures[p["id"]] = "%s: %s" % (type(e).__name__, e)
            log("    FAILED: %s" % failures[p["id"]])

    previous = load_previous(args.out)
    out_points, kept = {}, []
    for p in points:
        pid = p["id"]
        if pid in results:
            out_points[pid] = results[pid]
        elif (isinstance(previous.get(pid), dict) and previous[pid].get("lat") == p["lat"]
              and previous[pid].get("lon") == p["lon"] and previous[pid].get("body") == p["body"]):
            out_points[pid] = previous[pid]
            kept.append(pid)

    used_bodies = {out_points[pid]["body"] for pid in out_points}
    output = {
        "generated": utc_now().strftime("%Y-%m-%d"),
        "method": {
            "text": METHOD_TEXT,
            "grid": {"n": GRID_N, "spacing_m": SPACING_M, "box_m": (GRID_N - 1) * SPACING_M,
                     "baseline_m": BASELINE_M, "radius_m": RADIUS_M,
                     "flat_identical_fraction": FLAT_FRACTION},
            "script": "scripts/compute_terrain.py",
            "points_file": "data/terrain_points.json",
            "raw_cache": "data/raw/terrain/<id>.json",
            "datasets": [{k: v for k, v in DATASETS[b].items() if k not in ("expected_resolution",)}
                         for b in ("earth", "moon", "mars") if b in used_bodies],
        },
        "points": out_points,
    }
    write_json_atomic(args.out, output, args.cache_dir)

    print_table(points, out_points)
    print_rankings(points, out_points)
    log()
    log("Wrote %s (%d points)" % (args.out, len(out_points)))
    if kept:
        log("Kept earlier results for: %s" % ", ".join(kept))
    if failures:
        log("FAILED (%d): " % len(failures))
        for pid, msg in failures.items():
            log("  %s: %s" % (pid, msg))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
