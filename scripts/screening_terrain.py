#!/usr/bin/env python3
"""Jordan screening layer, stage 3: terrain from the Copernicus DEM GLO-90 tiles.

For every 10 km box of data/raw/screening/stages/grid.json the script takes the same 21 x 21
samples, 500 m apart, as the hand-picked sites (compute_terrain.build_grid). It reads each
sample straight from the Copernicus DEM GLO-90 tiles on AWS with Open-Meteo's own pixel rule,
rounds it to whole metres, and computes the statistics with compute_terrain.compute_point(),
unchanged. A box is therefore measured exactly like a site in data/terrain.json, and the
Open-Meteo API is never called.

Pixel rule (Open-Meteo, Sources/App/Dem/DownloadDem.swift, Dem90.read; only the index arithmetic
is re-implemented, no code is copied), in 32-bit float arithmetic:
  lati = floor(lat), latrow = trunc(lat * 1200 + 108000) mod 1200, lonrow = trunc((lon + 180) * 1200)
On the AWS tiles that is the pixel whose centre is at lat (lati * 1200 + latrow + 1) / 1200 and
lon (lonrow - 216000) / 1200, which is 0 to 1 pixel north and west of the point.

Water rule: when compute_point flags a flat surface (flat_water_suspect) and the most common
elevation is at most -390 m (the Dead Sea and its evaporation ponds) or exactly 0 m (the Gulf of
Aqaba), water_pct is the share of samples at that elevation. 50 % or more: the box gets
terrainExclude ("Mostly water ...") and the flag 'water'; 20 to 50 %: the flag 'partWater'.
Playas such as Qa' al-Jafr and Azraq keep their terrain.

Hard check: the 5 Jordan sites must come out exactly as in data/terrain.json (all 441 samples
equal the cached Open-Meteo answers and every statistic is equal), or the script stops.

Writes (from the project folder):
  data/raw/screening/dem/tiles.json              the tiles: name, URL, bytes, sha256, MD5/ETag, Last-Modified
  data/raw/screening/dem/samples_jordan.json.gz  441 whole-metre samples per box, Copernicus notices first
  data/raw/screening/stages/terrain.json         statistics of every box, water rule, checks

Python 3.12 standard library only. Run from any folder:

  python -I scripts/screening_terrain.py                 # tiles from the cache (downloads what is missing)
  python -I scripts/screening_terrain.py --dem-dir DIR   # use tiles you already have
  python -I scripts/screening_terrain.py --offline       # never use the network

The tiles (about 88 MB) are kept outside the project, in the cache folder
(%LOCALAPPDATA%\\analog-atlas\\screening-cache\\copernicus-dem-glo90). A tile that tiles.json
already lists must match its sha256. A tile it does not list yet is compared with the AWS object
first (HEAD request: Content-Length and the ETag, which is the file's MD5) instead of downloading
it again.
"""

import argparse
import collections
import datetime
import gzip
import hashlib
import json
import math
import os
import statistics
import struct
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compute_terrain as ct  # noqa: E402  (read-only: grid, baselines and statistics of data/terrain.json)
import screening_grid as sg  # noqa: E402  (grid helpers, read-only use)
from geotiff_lite import GeoTiff  # noqa: E402

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------
ROOT = sg.ROOT
DEM_DIR = os.path.join(sg.SCREEN_DIR, "dem")
TILES_OUT = os.path.join(DEM_DIR, "tiles.json")
SAMPLES_OUT = os.path.join(DEM_DIR, "samples_jordan.json.gz")
STAGE_OUT = os.path.join(sg.SCREEN_DIR, "stages", "terrain.json")
TERRAIN_JSON = os.path.join(ROOT, "data", "terrain.json")
TERRAIN_POINTS = os.path.join(ROOT, "data", "terrain_points.json")
RAW_TERRAIN = os.path.join(ROOT, "data", "raw", "terrain")
SCRIPT = "scripts/screening_terrain.py"

DATASET = "copernicus-dem-glo90@aws-cog+open-meteo-pixel-rule"
R_EARTH = ct.RADIUS_M["earth"]
PX = 1200                         # pixels per degree below 50 deg latitude
BUCKET = "https://copernicus-dem-90m.s3.amazonaws.com"
TILE_LIST_URL = BUCKET + "/tileList.txt"
LICENCE_URL = ("https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/"
               "copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf")
LICENCE_NAME = "Licence for COP-DEM-GLO-90-F Global 90m Full, Free & Open (pages 19-21 of the PDF)"
DOI = "https://doi.org/10.5270/ESA-c5d3d65"
PIXEL_RULE_URL = "https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Dem/DownloadDem.swift"
ART6C = ("The organisations in charge of the Copernicus programme by law or by delegation do not incur "
         "any liability for any use of the Copernicus WorldDEM™-90")
NO_ENDORSEMENT = "No official endorsement is implied."
TILE_PAUSE_S = 0.5                # between requests to AWS

MAX_BASELINE_ERROR_M = 1.0        # the same limit as compute_terrain.get_cache
WATER_MODE_MAX_M = -390.0         # Dead Sea surface and evaporation ponds
SEA_LEVEL_M = 0.0                 # Gulf of Aqaba
WATER_EXCLUDE_PCT = 50.0
PART_WATER_PCT = 20.0
CONTROL_SKIP = ("dataset", "fetched")   # provenance fields of data/terrain.json, not statistics

# Box terrain record: the fields of the app file first (design 2.3), then the other statistics.
TERRAIN_KEYS = ["median_slope_deg", "max_flat_square_km", "pct_lt_10", "relief_m", "centre_elev_m"]
EXTRA_KEYS = ["mean_slope_deg", "p90_slope_deg", "pct_lt_8", "pct_lt_15", "n_slope_cells", "max_identical_pct"]

PIXEL_RULE = ("Open-Meteo's own pixel rule (Dem90.read in Sources/App/Dem/DownloadDem.swift), re-implemented "
              "in 32-bit float arithmetic: lati = floor(lat), latrow = trunc(lat * 1200 + 108000) mod 1200, "
              "lonrow = trunc((lon + 180) * 1200). On the AWS tiles that is the pixel whose centre is at lat "
              "(lati * 1200 + latrow + 1) / 1200, lon (lonrow - 216000) / 1200: 0 to 1 pixel north and west "
              "of the point, with no interpolation. Values are rounded to whole metres (Python round, ties to "
              "even), as the API returns whole metres; this reproduces every cached Open-Meteo sample of the 5 "
              "Jordan sites (checks.controls). Only the index arithmetic is re-implemented; no code is copied.")
WATER_RULE = ("If flat_water_suspect (at least 20 % of the 441 samples share one elevation) and that elevation "
              "is at most -390 m (the Dead Sea and its evaporation ponds) or exactly 0 m (the Gulf of Aqaba), "
              "water_pct = the share of samples at it, else 0. water_pct >= 50: terrainExclude ('Mostly "
              "water ...') and flag 'water', so terrain and landing are not scored; 20 to 50: flag "
              "'partWater'. Playas (Qa' al-Jafr, Azraq) keep their terrain.")


def log(msg):
    print(msg, flush=True)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def art6b_notice():
    """The Art. 6(b) notice: compute_terrain's Copernicus credit without its Open-Meteo sentence."""
    credit = ct.DATASETS["earth"]["credit"]
    end = credit.index("all rights reserved.") + len("all rights reserved.")
    return credit[:end]


def notices():
    return {"copernicusArt6b": art6b_notice(), "copernicusArt6c": ART6C, "endorsement": NO_ENDORSEMENT}


# --------------------------------------------------------------------------
# The Open-Meteo pixel rule on the AWS tiles
# --------------------------------------------------------------------------
def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def openmeteo_index(lat, lon):
    """Global pixel-centre index (R, C) that Open-Meteo picks: centre lat = R / 1200, lon = C / 1200.

    Open-Meteo builds its files with gdal_translate -of NetCDF from these AWS tiles; GDAL writes
    NetCDF bottom-up, so its latrow 0 is the southern row (centre lati + 1/1200)."""
    la, lo = f32(lat), f32(lon)
    lati = math.floor(la)
    latrow = int(f32(f32(la * 1200.0) + 108000.0)) % PX
    lonrow = int(f32(f32(lo + 180.0) * 1200.0))
    return lati * PX + latrow + 1, lonrow - 180 * PX


def tile_of(R, C):
    """(T, L) of the tile that holds pixel centre (R, C): tile N{T}_E{L} has centre rows T + 1/1200 .. T + 1."""
    return -((-R) // PX) - 1, C // PX


def tile_name(T, L):
    return "Copernicus_DSM_COG_30_%s%02d_00_%s%03d_00_DEM" % ("N" if T >= 0 else "S", abs(T),
                                                              "E" if L >= 0 else "W", abs(L))


def tile_url(name):
    return "%s/%s/%s.tif" % (BUCKET, name, name)


class Mosaic:
    """The AWS GLO-90 tiles as one global grid of pixel centres (|lat| < 50 deg).

    Tile N{T}_E{L} (1200 x 1200 float32, PixelIsPoint) has the centre of pixel (0, 0) exactly at
    (T + 1, L); the AWS copies drop the shared south row and east column."""

    def __init__(self, paths):
        self.paths = paths          # (T, L) -> local file
        self.tiles = {}

    def _tile(self, key):
        if key not in self.tiles:
            self.tiles[key] = self._open(key)
        return self.tiles[key]

    def _open(self, key):
        path = self.paths.get(key)
        if path is None:
            return None
        t = GeoTiff(path)
        name = tile_name(*key)
        if (t.width, t.height) != (PX, PX) or t.typecode != "f" or not t.pixel_is_point:
            raise SystemExit("%s: unexpected layout %r" % (name, t.info()))
        clat, clon = t.pixel_center(0, 0)
        if abs(clat - (key[0] + 1)) > 1e-9 or abs(clon - key[1]) > 1e-9:
            raise SystemExit("%s: unexpected georeferencing %r" % (name, t.gt))
        return t

    def release(self, key):
        self.tiles.pop(key, None)

    def value(self, R, C):
        T, L = tile_of(R, C)
        t = self._tile((T, L))
        return None if t is None else t.pixel((T + 1) * PX - R, C - L * PX)


# --------------------------------------------------------------------------
# Tiles: find, check, download
# --------------------------------------------------------------------------
def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_tile(name, args):
    for folder in (args.dem_dir, args.tile_cache):
        if folder and os.path.exists(os.path.join(folder, name + ".tif")):
            return os.path.join(folder, name + ".tif")
    return None


def http(url, method):
    """(status, headers, body) of a plain anonymous request, with a few slow retries."""
    req = urllib.request.Request(url, method=method, headers={"User-Agent": sg.USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.status, dict(resp.headers.items()), resp.read()
        except Exception as err:  # network hiccups: wait and try again
            log("  %s %s attempt %d failed: %s" % (method, url, attempt + 1, err))
            time.sleep(5 * (attempt + 1))
    raise SystemExit("could not reach " + url)


def make_pacer():
    last = [None]

    def pace():
        if last[0] is not None:
            time.sleep(max(0.0, last[0] + TILE_PAUSE_S - time.time()))
        last[0] = time.time()
    return pace


def compare_with_aws(name, headers, size, md5):
    """Stop unless the AWS object has this size and (single-part ETag) this MD5."""
    etag = headers.get("ETag", "").strip('"')
    if int(headers.get("Content-Length", -1)) != size:
        raise SystemExit("%s: AWS says %s bytes, the file has %d" % (name, headers.get("Content-Length"), size))
    if "-" not in etag and etag != md5:
        raise SystemExit("%s: AWS ETag %s is not the file's MD5 %s" % (name, etag, md5))
    return etag


def tile_entry(name, path, md5, etag, last_modified, fetched, checked):
    return {"name": name, "url": tile_url(name), "bytes": os.path.getsize(path), "sha256": sg.sha256_file(path),
            "md5": md5, "etag": etag, "lastModified": last_modified, "fetched": fetched, "checked": checked}


def verify_tile(name, path, network, pace):
    """A tile on disk that tiles.json does not list yet: compare it with AWS without downloading it."""
    pace()
    network.append(tile_url(name))
    status, headers, _ = http(tile_url(name), "HEAD")
    md5 = md5_file(path)
    etag = compare_with_aws(name, headers, os.path.getsize(path), md5)
    now = sg.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = "HEAD %s (HTTP %d): Content-Length and ETag (MD5) equal the file" % (now, status)
    # fetched = when the file was downloaded (its file time), kept when an earlier copy is reused
    return tile_entry(name, path, md5, etag, headers.get("Last-Modified"), iso(os.path.getmtime(path)), checked)


def download_tile(name, args, prev, network, pace):
    pace()
    network.append(tile_url(name))
    status, headers, body = http(tile_url(name), "GET")
    md5 = hashlib.md5(body).hexdigest()
    etag = compare_with_aws(name, headers, len(body), md5)
    if prev and sg.sha256_bytes(body) != prev["sha256"]:
        raise SystemExit("%s: the AWS tile changed since tiles.json was written" % name)
    path = os.path.join(args.tile_cache, name + ".tif")
    os.makedirs(args.tile_cache, exist_ok=True)
    with open(path + ".part", "wb") as f:
        f.write(body)
    os.replace(path + ".part", path)
    now = sg.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = "GET %s (HTTP %d): ETag (MD5) equals the downloaded bytes" % (now, status)
    return path, tile_entry(name, path, md5, etag, headers.get("Last-Modified"), now, checked)


def acquire_tiles(keys, args, network):
    """{(T, L): path} and the tiles.json entries for every tile the samples need."""
    previous = {}
    if os.path.exists(TILES_OUT):
        previous = {t["name"]: t for t in load_json(TILES_OUT).get("tiles", [])}
    paths, entries, pace = {}, [], make_pacer()
    for key in sorted(keys):
        name = tile_name(*key)
        path, prev = find_tile(name, args), previous.get(name)
        if path and prev:
            if sg.sha256_file(path) != prev["sha256"]:
                raise SystemExit("%s: sha256 differs from tiles.json; delete the file to download it again" % path)
            entry, how = prev, "sha256 equals tiles.json"
        elif path:
            if args.offline:
                raise SystemExit("%s is not in tiles.json yet; run once without --offline so it can be "
                                 "compared with AWS" % name)
            entry, how = verify_tile(name, path, network, pace), "reused (size and MD5 equal the AWS object)"
        else:
            if args.offline:
                raise SystemExit("%s.tif is not in --dem-dir or the cache and --offline is set" % name)
            path, entry = download_tile(name, args, prev, network, pace)
            how = "downloaded"
        log("tile %s: %s (%d bytes, Last-Modified %s)" % (name, how, entry["bytes"], entry["lastModified"]))
        paths[key] = path
        entries.append(entry)
    return paths, entries


def write_tiles(entries):
    doc = {
        "about": ("The Copernicus DEM GLO-90 tiles read by scripts/screening_terrain.py. The tiles themselves are "
                  "kept outside the project (the screening cache folder); every run checks them against the "
                  "sha256 below. 'fetched' is when the file was downloaded; 'checked' is how its content was "
                  "compared with the AWS object."),
        "dataset": ("Copernicus DEM GLO-90 (COP-DEM_GLO-90-DGED, 2021 release): 1 x 1 deg Cloud Optimized "
                    "GeoTIFFs on AWS Open Data, s3://copernicus-dem-90m (float32, 3 arc-seconds, metres above "
                    "the EGM2008 geoid)"),
        "urlPattern": BUCKET + "/<NAME>/<NAME>.tif",
        "tileList": TILE_LIST_URL,
        "licence": LICENCE_NAME,
        "licenceUrl": LICENCE_URL,
        "doi": DOI,
        "notices": notices(),
        "tiles": entries,
    }
    sg.write_text(TILES_OUT, sg.dumps_rows(doc, ("tiles",)))
    return sg.sha256_file(TILES_OUT)


# --------------------------------------------------------------------------
# Sampling and statistics
# --------------------------------------------------------------------------
def fake_cache(lats, lons, z):
    """The shape compute_terrain.compute_point() reads (one Open-Meteo-like answer)."""
    return {"body": "earth", "grid": {"lat": lats, "lon": lons},
            "requests": [{"n_points": len(z), "response": {"elevation": z}}]}


def sample(mosaic, index):
    """Whole-metre elevations (float, None where there is no data; Python round, ties to even) and
    the positions and raw values of exact .5 samples, where the tie rule matters."""
    z, halves = [], []
    for k, (R, C) in enumerate(index):
        v = mosaic.value(R, C)
        if v is None:
            z.append(None)
            continue
        if v % 1 == 0.5:
            halves.append((k, v))
        z.append(float(round(v)))
    return z, halves


def tie_sensitivity(job, halves):
    """Statistics that would change if exact .5 samples were rounded away from zero instead."""
    z = list(job["z"])
    for k, v in halves:
        z[k] = math.copysign(math.floor(abs(v) + 0.5), v)
    alt = ct.compute_point(job["point"], fake_cache(job["lats"], job["lons"], z))
    keys = TERRAIN_KEYS + EXTRA_KEYS + ["flat_water_suspect"]
    return {k: [job["result"][k], alt[k]] for k in keys if alt[k] != job["result"][k]}


def water(t):
    """water_pct and (terrainExclude or None, flags) by the water rule."""
    mode = t["mode_elev_m"]
    if not t["flat_water_suspect"] or not (mode <= WATER_MODE_MAX_M or mode == SEA_LEVEL_M):
        return 0.0, None, []
    pct = t["max_identical_pct"]
    if pct >= WATER_EXCLUDE_PCT:
        what = "the Gulf of Aqaba" if mode == SEA_LEVEL_M else "the Dead Sea or its evaporation ponds"
        text = ("Mostly water: %.0f%% of the 10 km box is one flat surface at %.0f m in the elevation data (%s), "
                "so the slope would describe water, not ground." % (pct, mode, what))
        return pct, text, ["water"]
    if pct >= PART_WATER_PCT:
        return pct, None, ["partWater"]
    return pct, None, []


def terrain_record(r, z):
    """compute_point's result with the dataset overridden, plus mean and mode elevation and water_pct."""
    valid = [v for v in z if v is not None]
    mode_value = collections.Counter(valid).most_common(1)[0][0]   # same tie rule as compute_point
    t = {k: r[k] for k in TERRAIN_KEYS}
    t["mean_elev_m"] = round(statistics.fmean(valid), 1)
    t["flat_water_suspect"] = r["flat_water_suspect"]
    t["water_pct"] = 0.0
    t["n_samples"] = r["n_samples"]
    t["notes"] = r["notes"]
    t.update({k: r[k] for k in EXTRA_KEYS})
    t["mode_elev_m"] = mode_value
    t["dataset"] = DATASET
    pct, exclude, flags = water(t)
    t["water_pct"] = pct
    return t, exclude, flags


def plan(jobs):
    """Pixel indices of every job and the last job that needs each tile (tiles are freed after it)."""
    worst, last_use = 0.0, {}
    for i, job in enumerate(jobs):
        lats, lons = ct.build_grid(job["lat"], job["lon"], R_EARTH)
        worst = max(worst, ct.check_baselines(lats, lons, R_EARTH))
        job["lats"], job["lons"] = lats, lons
        job["index"] = [openmeteo_index(a, b) for a, b in zip(lats, lons)]
        for key in {tile_of(R, C) for R, C in job["index"]}:
            last_use[key] = i
    return worst, last_use


def run_jobs(jobs, mosaic, last_use):
    """Sample and measure every job in order. Returns the tie record: the number of exact .5 samples,
    the boxes that hold them, and the statistics that a ties-away-from-zero rule would change."""
    ties = {"samples": 0, "jobs": [], "changes": {}}
    for i, job in enumerate(jobs):
        z, halves = sample(mosaic, job["index"])
        job["z"] = z
        job["result"] = ct.compute_point(job["point"], fake_cache(job["lats"], job["lons"], z))
        if halves:
            ties["samples"] += len(halves)
            ties["jobs"].append(job["id"])
            change = tie_sensitivity(job, halves)
            if change:
                ties["changes"][job["id"]] = change
        for key in [k for k, last in last_use.items() if last == i]:
            mosaic.release(key)
        if job["kind"] == "box" and (i + 1) % 200 == 0:
            log("  %d of %d done" % (i + 1, len(jobs)))
    return ties


# --------------------------------------------------------------------------
# Jobs: the 5 control sites, then every box
# --------------------------------------------------------------------------
def control_jobs(grid):
    points = {p["id"]: p for p in load_json(TERRAIN_POINTS)}
    jobs = []
    for pid in grid["controls"]:
        p = points[pid]
        jobs.append({"kind": "control", "id": pid, "lat": p["lat"], "lon": p["lon"], "point": p})
    return jobs


def box_jobs(grid):
    jobs = []
    for bid in sorted(grid["boxes"]):
        b = grid["boxes"][bid]
        point = {"id": bid, "body": "earth", "lat": b["lat"], "lon": b["lon"], "kind": "screening-box",
                 "name": "Box r%d c%d" % (b["row"], b["col"]),
                 "coordSource": "box centre, data/raw/screening/stages/grid.json (%s)" % sg.GRID_ID}
        jobs.append({"kind": "box", "id": bid, "lat": b["lat"], "lon": b["lon"], "point": point})
    return jobs


def check_control(job, ref):
    """The hard check of one site: samples equal the cached Open-Meteo answer, statistics equal terrain.json."""
    cache = load_json(os.path.join(RAW_TERRAIN, job["id"] + ".json"))
    same_grid = cache["grid"]["lat"] == job["lats"] and cache["grid"]["lon"] == job["lons"]
    om, _ = ct.elevations_from_cache(cache)
    n_equal = sum(1 for a, b in zip(job["z"], om) if a == b)
    r = job["result"]
    mism = {k: [r.get(k), v] for k, v in ref.items() if k not in CONTROL_SKIP and r.get(k) != v}
    return {"samplesEqual": "%d/%d" % (n_equal, len(om)), "statsEqual": not mism, "mismatches": mism,
            "ok": same_grid and n_equal == len(om) == len(job["z"]) and not mism}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def write_samples(jobs, tiles_sha):
    as_int = lambda z: [None if v is None else int(v) for v in z]  # noqa: E731
    doc = {
        "copernicusNotices": notices(),
        "about": ("Elevation samples of the Jordan screening boxes: 441 per box (21 x 21, 500 m apart), read from "
                  "the Copernicus DEM GLO-90 tiles with Open-Meteo's pixel rule and rounded to whole metres. "
                  "Derived from Copernicus DEM data; written by scripts/screening_terrain.py."),
        "licence": LICENCE_NAME,
        "licenceUrl": LICENCE_URL,
        "doi": DOI,
        "dataset": DATASET,
        "tiles": {"file": rel(TILES_OUT), "sha256": tiles_sha},
        "pixelRule": PIXEL_RULE,
        "units": "metres above the EGM2008 geoid, whole metres (null = no data)",
        "grid": {"n": ct.GRID_N, "spacing_m": ct.SPACING_M, "radius_m": R_EARTH,
                 "order": "row-major; row 0 = southern edge (-5000 m north), column 0 = western edge (-5000 m east)",
                 "positions": ("compute_terrain.build_grid(lat, lon, 6371008.8) around the box centre of "
                               "data/raw/screening/stages/grid.json (controls: data/terrain_points.json)")},
        "boxes": {j["id"]: as_int(j["z"]) for j in jobs if j["kind"] == "box"},
        "controls": {j["id"]: as_int(j["z"]) for j in jobs if j["kind"] == "control"},
    }
    text = sg.dumps_rows(doc, ("boxes", "controls"))
    body = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)   # same bytes on every run
    os.makedirs(DEM_DIR, exist_ok=True)
    with open(SAMPLES_OUT + ".tmp", "wb") as f:
        f.write(body)
    os.replace(SAMPLES_OUT + ".tmp", SAMPLES_OUT)
    log("wrote %s (%d bytes, %d uncompressed)" % (rel(SAMPLES_OUT), len(body), len(text.encode("utf-8"))))
    return sg.sha256_bytes(body)


def sources(entries, tiles_sha):
    accessed = min(e["fetched"] for e in entries)[:10]
    return [
        {"id": "copernicus-dem-glo90",
         "label": "Copernicus DEM GLO-90 (2021 release), AWS Open Data tiles",
         "url": TILE_LIST_URL,
         "licence": LICENCE_NAME,
         "licenceUrl": LICENCE_URL,
         "credit": art6b_notice(),
         "notice": "%s. %s Citation: %s" % (ART6C, NO_ENDORSEMENT, DOI),
         "version": "COP-DEM_GLO-90-DGED, 2021 release",
         "accessed": accessed,
         "sha256": tiles_sha},
        # A cited rule, not data: no credit, so the globe's data credits stay the four of design 4.2
        # (POWER, Copernicus, IGME5000, Natural Earth). The citation is in the notice.
        {"id": "open-meteo-pixel-rule",
         "label": "Open-Meteo DEM pixel rule (Dem90.read, index arithmetic only)",
         "url": PIXEL_RULE_URL,
         "licence": "Not applicable: no code is copied; only the index arithmetic is re-implemented",
         "licenceUrl": PIXEL_RULE_URL,
         "credit": None,
         "notice": ("Pixel rule of Open-Meteo (open-meteo.com), Sources/App/Dem/DownloadDem.swift. The source "
                    "file is cited; the Open-Meteo API is not called."),
         "version": "main branch, read 2026-10-10",
         "accessed": "2026-10-10",
         "sha256": None},
    ]


def counts_for(boxes, seconds):
    t = [b["terrain"] for b in boxes.values()]
    slopes = sorted(x["median_slope_deg"] for x in t)
    steep = max(boxes, key=lambda k: boxes[k]["terrain"]["median_slope_deg"])
    return {"boxes": len(boxes),
            "flatWaterSuspect": sum(1 for x in t if x["flat_water_suspect"]),
            "water": sum(1 for b in boxes.values() if "water" in b["flags"]),
            "partWater": sum(1 for b in boxes.values() if "partWater" in b["flags"]),
            "flatButNotWater": sum(1 for x in t if x["flat_water_suspect"] and x["water_pct"] == 0),
            "pctLt10Is100": sum(1 for x in t if x["pct_lt_10"] == 100.0),
            "maxFlat9_5km": sum(1 for x in t if x["max_flat_square_km"] == 9.5),
            "medianSlopeQuartiles": [round(q, 2) for q in statistics.quantiles(slopes, n=4)],
            "steepestBox": {"id": steep, "median_slope_deg": boxes[steep]["terrain"]["median_slope_deg"]},
            "seconds": round(seconds, 1)}


def control_records(jobs, grid):
    """The hard check of every control site; returns (controls, check)."""
    ref = load_json(TERRAIN_JSON)["points"]
    controls, n_equal = {}, 0
    for job in (j for j in jobs if j["kind"] == "control"):
        check = check_control(job, ref[job["id"]])
        t, _exclude, _flags = terrain_record(job["result"], job["z"])
        controls[job["id"]] = {"name": job["point"]["name"], "lat": job["lat"], "lon": job["lon"],
                               "source": "data/terrain_points.json", "box": grid["controls"][job["id"]]["box"],
                               **check, "terrain": t}
        n_equal += int(check["samplesEqual"].split("/")[0])
        log("control %-15s samples %s equal the Open-Meteo cache; statistics equal data/terrain.json: %s%s"
            % (job["id"], check["samplesEqual"], check["statsEqual"],
               "" if check["statsEqual"] else " " + json.dumps(check["mismatches"])))
    n_ok = sum(1 for c in controls.values() if c["ok"])
    n_all = len(controls) * ct.GRID_N ** 2
    log("terrain controls: %d/%d equal data/terrain.json (%d/%d samples, all statistics)"
        % (n_ok, len(controls), n_equal, n_all))
    check = {"rule": ("the 5 Jordan sites (data/terrain_points.json) give exactly data/terrain.json: all 441 "
                      "samples equal the cached Open-Meteo answers in data/raw/terrain/<id>.json and every "
                      "statistic is equal (dataset and fetched are provenance, not compared)"),
             "samples": "%d/%d" % (n_equal, n_all), "sites": "%d/%d" % (n_ok, len(controls)),
             "ok": n_ok == len(controls) > 0}
    return controls, check


def box_records(jobs):
    boxes = {}
    for job in (j for j in jobs if j["kind"] == "box"):
        t, exclude, flags = terrain_record(job["result"], job["z"])
        boxes[job["id"]] = {"terrain": t, **({"terrainExclude": exclude} if exclude else {}), "flags": flags}
    return boxes


def make_checks(control_check, worst, entries, boxes, ties, network, grid):
    missing = [k for k, b in boxes.items() if b["terrain"]["n_samples"] != ct.GRID_N ** 2]
    return {
        "controls": control_check,
        "baselines": {"rule": ("every 1 km central-difference baseline is within %.0f m of 1 km"
                               % MAX_BASELINE_ERROR_M),
                      "worst_m": round(worst, 4), "ok": worst <= MAX_BASELINE_ERROR_M},
        "tiles": {"rule": "every tile read matches its sha256 in dem/tiles.json (a mismatch stops the run)",
                  "tiles": len(entries), "ok": True},
        "samples": {"rule": "every box has all 441 samples", "boxesWithMissing": missing, "ok": not missing},
        "roundingTies": {
            "rule": ("information, not a pass/fail test: samples whose tile value is exactly x.5 m are rounded "
                     "with ties to even (Python round). The 5 controls hold no such sample, so they cannot show "
                     "Open-Meteo's own tie rule; 'changes' lists the statistics that rounding those samples away "
                     "from zero would change [ties to even, ties away]"),
            "exactHalfSamples": ties["samples"], "boxesWithThem": len(ties["jobs"]),
            "controlsWithThem": [j for j in ties["jobs"] if not j.startswith("jo-")],
            "changes": ties["changes"], "ok": True},
        "water": {"rule": "the flag 'water' is set exactly when terrainExclude is",
                  "ok": all(("water" in b["flags"]) == ("terrainExclude" in b) for b in boxes.values())},
        "noOpenMeteo": {"rule": "no request to Open-Meteo", "ok": not any("open-meteo" in u for u in network)},
        "allBoxes": {"rule": "every box of stages/grid.json has one record", "grid": len(grid["boxes"]),
                     "here": len(boxes), "ok": len(boxes) == len(grid["boxes"])},
    }


def terrain_block(entries, tiles_sha, samples_sha):
    """The 'terrain' block of the app file (design 2.3)."""
    return {"dataset": DATASET, "pixelRule": PIXEL_RULE, "method": "same as data/terrain.json",
            "methodDetail": ("statistics from scripts/compute_terrain.py compute_point(), unchanged (see "
                             "method.text in data/terrain.json); dataset set to %s; mean_elev_m, mode_elev_m "
                             "and water_pct added" % DATASET),
            "rawFile": rel(SAMPLES_OUT), "rawFileSha256": samples_sha,
            "tilesFile": rel(TILES_OUT), "tilesFileSha256": tiles_sha,
            "tiles": [{k: e[k] for k in ("name", "url", "bytes", "sha256", "lastModified")} for e in entries],
            "waterRule": WATER_RULE,
            "elevDatum": ct.DATASETS["earth"]["elev_datum"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem-dir", help="folder with Copernicus_DSM_COG_30_*_DEM.tif tiles you already have")
    parser.add_argument("--cache-dir", default=sg.default_cache_dir(), help="folder for big downloads")
    parser.add_argument("--offline", action="store_true", help="never use the network")
    args = parser.parse_args(argv)
    args.tile_cache = os.path.join(args.cache_dir, "copernicus-dem-glo90")
    t0 = time.time()

    grid = load_json(sg.GRID_OUT)
    if grid.get("grid") != sg.GRID_ID:
        raise SystemExit("stages/grid.json is not grid %s" % sg.GRID_ID)
    jobs = control_jobs(grid) + box_jobs(grid)
    worst, last_use = plan(jobs)
    log("%d controls + %d boxes, %d tiles needed; worst 1 km baseline error %.4f m"
        % (len(grid["controls"]), len(grid["boxes"]), len(last_use), worst))
    if worst > MAX_BASELINE_ERROR_M:
        raise SystemExit("grid check failed: a 1 km baseline is off by %.2f m" % worst)

    network = []
    paths, entries = acquire_tiles(set(last_use), args, network)
    tiles_sha = write_tiles(entries)
    ties = run_jobs(jobs, Mosaic(paths), last_use)

    controls, control_check = control_records(jobs, grid)
    if not control_check["ok"]:
        log("HARD CHECK FAILED: the tiles read with the pixel rule no longer give data/terrain.json")
        return 1
    boxes = box_records(jobs)
    samples_sha = write_samples(jobs, tiles_sha)
    checks = make_checks(control_check, worst, entries, boxes, ties, network, grid)
    counts = counts_for(boxes, time.time() - t0)
    log("boxes %d: flat surface %d (water %d, part water %d, playas and other flats kept %d); "
        "100%% under 10 deg %d; median slope quartiles %s; steepest %s"
        % (counts["boxes"], counts["flatWaterSuspect"], counts["water"], counts["partWater"],
           counts["flatButNotWater"], counts["pctLt10Is100"], counts["medianSlopeQuartiles"],
           counts["steepestBox"]))
    log("rounding ties: %d exact .5 samples in %d boxes (controls: %d); ties away from zero would change "
        "a statistic in %d boxes: %s" % (ties["samples"], len(ties["jobs"]), len(checks["roundingTies"]
                                         ["controlsWithThem"]), len(ties["changes"]), json.dumps(ties["changes"])))

    stage = {
        "stage": "terrain",
        "generated": sg.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": SCRIPT,
        "grid": sg.GRID_ID,
        "sources": sources(entries, tiles_sha),
        "network": network,
        "terrain": terrain_block(entries, tiles_sha, samples_sha),
        "counts": counts,
        "checks": checks,
        "boxes": boxes,
        "controls": controls,
    }
    sg.write_text(STAGE_OUT, sg.dumps_rows(stage, ("boxes", "controls")))
    failed = [name for name, c in checks.items() if not c["ok"]]
    if failed:
        log("CHECK FAILED: " + ", ".join(failed))
        return 1
    log("checks OK (%.0f s)" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
