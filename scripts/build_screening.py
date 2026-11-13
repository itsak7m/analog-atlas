#!/usr/bin/env python3
"""Jordan screening layer, last stage: build the app file data/screening_jordan.json.

Reads the four stage files and joins them into one record per 10 km box:
  data/raw/screening/stages/grid.json      the boxes and the grid      (scripts/screening_grid.py)
  data/raw/screening/stages/power.json     climate cells               (scripts/screening_power.py)
  data/raw/screening/stages/terrain.json   terrain statistics          (scripts/screening_terrain.py)
  data/raw/screening/stages/geology.json   main rock                   (scripts/screening_geology.py)

It does not trust the stage files. Before it writes anything it checks them against the raw
files they came from and against the project's own data (design section 2.4):
  - every grid box has exactly one record from each stage, and no stage check failed
  - the box grid, ids, centres and bounds follow the grid constants; the boxes cover Jordan
  - every climate number equals the NASA POWER answers in data/raw/screening/power/, and the
    cells of the 5 Jordan sites and Amman equal the project's point files data/raw/power/*.json
  - every terrain statistic is computed again from dem/samples_jordan.json.gz with
    compute_terrain.compute_point(); the 5 Jordan sites equal data/terrain.json exactly
  - the main rock of every box is worked out again from geology/samples_jordan.json and the
    rock table; every rock id exists in js/scoring.js
  - every sha256 recorded by a stage matches its file; DEM tile sha256 values match the manifest
  - no stage fetched anything from Open-Meteo
  - no NaN, no missing value where one is needed, known flags only, water and terrainExclude agree
  - the file is under 1 MB (target: under 600 KB)
If any check fails, nothing is written and the script exits with code 1.

Python 3.12 standard library only, no network. Run from any folder:

  python -I scripts/build_screening.py
  python -I scripts/build_screening.py --dem-dir DIR   # also re-hash the DEM tiles kept in DIR
  python -I scripts/build_screening.py --igme-zip PATH --ne-zip PATH   # also re-hash these zips

The big downloads live outside the project (see data/raw/screening/README.txt). When they are
found (--dem-dir, --igme-zip, --ne-zip or the cache folder), their sha256 is checked too;
when they are not, the build checks the sha256 values the stages recorded for them.
"""

import argparse
import collections
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:             # python -I does not add the script's folder
    sys.path.insert(0, HERE)

import compute_terrain as ct          # noqa: E402  read-only: build_grid, compute_point, DATASETS
import screening_grid as sg           # noqa: E402  grid constants and polygon helpers

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------
ROOT = os.path.dirname(HERE)
SCREEN = os.path.join(ROOT, "data", "raw", "screening")
STAGE_FILES = {name: os.path.join(SCREEN, "stages", name + ".json")
               for name in ("grid", "power", "terrain", "geology")}
STAGE_SCRIPTS = {name: "scripts/screening_%s.py" % name for name in STAGE_FILES}
BOUNDARY_FILE = os.path.join(SCREEN, "boundary", "jordan_ne10m_v5.1.1.json")
POWER_DIR = os.path.join(SCREEN, "power")
MANIFEST_FILE = os.path.join(POWER_DIR, "manifest.json")
TILES_FILE = os.path.join(SCREEN, "dem", "tiles.json")
DEM_SAMPLES = os.path.join(SCREEN, "dem", "samples_jordan.json.gz")
GEO_SAMPLES = os.path.join(SCREEN, "geology", "samples_jordan.json")
ROCK_TABLE = os.path.join(ROOT, "data", "screening_rockmap_igme5000.json")
SITES_JSON = os.path.join(ROOT, "data", "sites.json")
TERRAIN_JSON = os.path.join(ROOT, "data", "terrain.json")
TERRAIN_POINTS = os.path.join(ROOT, "data", "terrain_points.json")
RAW_POWER = os.path.join(ROOT, "data", "raw", "power")
RAW_TERRAIN = os.path.join(ROOT, "data", "raw", "terrain")
UTIL_JS = os.path.join(ROOT, "js", "util.js")
SCORING_JS = os.path.join(ROOT, "js", "scoring.js")
SCREENING_JS = os.path.join(ROOT, "js", "screening.js")
OUT_FILE = os.path.join(ROOT, "data", "screening_jordan.json")
SCRIPT = "scripts/build_screening.py"

FORMAT = 1
LABEL = "Screening candidate — found by data, not field-checked"
SIZE_TARGET = 600 * 1000          # bytes (design 2.3: target under 600 KB)
SIZE_LIMIT = 1000 * 1000          # bytes (the build fails above 1 MB)
R_EARTH_M = ct.RADIUS_M["earth"]
R_EARTH_KM = R_EARTH_M / 1000.0   # util.distanceKm uses 6371.0088 km
JORDAN_SITES = ("wadi-rum", "harrat", "waqf-as-suwwan", "lisan-dead-sea", "qa-al-jafr")
CLIMATE_POINTS = JORDAN_SITES + ("amman",)

MERRA_PARAMS = ("T2M", "T2M_MAX", "T2M_MIN", "T2M_RANGE", "RH2M", "PRECTOTCORR", "WS2M", "PS",
                "TS", "TS_MAX", "TS_MIN")
SYN_PARAMS = ("ALLSKY_SRF_ALB", "ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_UV_INDEX")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ANN")
MERRA_DLAT, MERRA_DLON, SYN_STEP = 0.5, 0.625, 1.0
FILL_VALUE = -999.0

TERRAIN_FIELDS = ("median_slope_deg", "max_flat_square_km", "pct_lt_10", "relief_m", "centre_elev_m",
                  "mean_elev_m", "flat_water_suspect", "water_pct", "n_samples", "notes")
GEOLOGY_FIELDS = ("primary", "secondary", "unit", "share", "certainty", "inferred", "units",
                  "centrePolygon", "why")
UNIT_FIELDS = ("petrography", "age", "region", "primary", "secondary", "certainty", "reason")
SOURCE_FIELDS = ("id", "label", "url", "licence", "licenceUrl", "credit", "notice", "version",
                 "accessed", "sha256")
NO_FILE_SOURCES = ("open-meteo-pixel-rule",)   # a cited rule, not a file: its sha256 and credit are null
# The sources whose credit the globe shows while Discover is on (design 4.2); no other source has a credit.
CREDITED_SOURCES = ("nasa-power-climatology-regional", "copernicus-dem-glo90", "igme5000", "naturalearth-admin0-10m")

FLAGS = ("border", "cellGap", "climateCellMostlyOutside", "straddlesCellEdge", "partWater", "water",
         "lowCertaintyGeology", "noGeology")
STAGE_FLAGS = {"power": {"climateCellMostlyOutside", "straddlesCellEdge"},
               "terrain": {"partWater", "water"},
               "geology": {"lowCertaintyGeology", "noGeology"}}

# Terrain water rule (design 2.1), written again here so the check is independent of the stage script.
WATER_MODE_MAX_M = -390.0         # the Dead Sea and its evaporation ponds
SEA_LEVEL_M = 0.0                 # the Gulf of Aqaba
WATER_PCT = 50.0
PART_WATER_PCT = 20.0

# Copernicus licence notices (design section 8; the same text as data/raw/screening/README.txt).
ART6C = ("The organisations in charge of the Copernicus programme by law or by delegation do not incur "
         "any liability for any use of the Copernicus WorldDEM™-90")
ENDORSEMENT = "No official endorsement is implied."
IGME_CREDIT = ("IGME5000, © BGR, Hannover, 2005, https://doi.org/10.25928/igme-5000, "
               "modified: reclassified to Analog Atlas rock ids")
POWER_CITATION = ("The data was obtained from National Aeronautics and Space Administration (NASA) Langley "
                  "Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded "
                  "through the NASA Earth Science Division.")
IGME_SHA256 = "33e6f843c0c46bd3909fb2c978569513d47e051152cbeb8ae73d12d89ad8a97e"
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

ABOUT = (
    "Discover Jordan: Jordan covered with 10 km boxes, each measured like a hand-picked site. "
    "Climate: the NASA POWER cells that hold the box centre (the rule of the POWER point API used for "
    "the sites). Terrain: 441 Copernicus DEM samples per box, with the same statistics as "
    "data/terrain.json. Geology: the main rock from the IGME5000 map (1:5 million) at 25 points per box. "
    "The app scores every box against each Moon and Mars target with the same formula as the sites; "
    "boxes have no resources data, so that pillar is left out, and a box % can only be compared with a "
    "site % that also leaves resources out. Every box is a screening candidate: found by data, not "
    "field-checked, and not checked for access, protection or safety. Built by "
    "scripts/build_screening.py from data/raw/screening/stages/; the raw files are in "
    "data/raw/screening/ (see README.txt there).")

FLAG_RULES = {
    "border": ("the box crosses the Natural Earth boundary: part of it is outside Jordan "
               "(inJordan below 1). The boundary is indicative."),
    "cellGap": ("the NASA POWER MERRA-2 cell is more than 400 m higher or lower than the ground at the "
                "box centre (|cellGap_m| > 400, the same rule as cellGap() in js/util.js)."),
    "climateCellMostlyOutside": ("less than half of the box's MERRA-2 cell lies in Jordan, so its "
                                 "climate mixes in neighbouring land or sea."),
    "straddlesCellEdge": ("a MERRA-2 or 1 deg SYN1deg cell edge runs through the box; the box takes "
                          "the cell that holds its centre."),
    "partWater": "20 to 50 % of the box is one flat water surface in the elevation data.",
    "water": ("50 % or more of the box is one flat water surface (the Dead Sea, its evaporation ponds "
              "or the Gulf of Aqaba); terrain is not scored (terrainExclude)."),
    "lowCertaintyGeology": ("the box's map unit has low certainty, so its rock is shown as 'inferred' "
                            "and not scored."),
    "noGeology": "the map has no rock type for the box's unit (water).",
}


def log(msg=""):
    print(msg, flush=True)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def default_cache_dir():
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "analog-atlas", "screening-cache")
    return os.path.join(os.path.expanduser("~"), ".cache", "analog-atlas", "screening")


# --------------------------------------------------------------------------
# Reading files (a duplicate key or a NaN in any input stops the build)
# --------------------------------------------------------------------------
def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key %r" % key)
        out[key] = value
    return out


def _no_nan(name):
    raise ValueError("%s is not allowed in the data" % name)


def parse_json(text, path):
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_nan)
    except ValueError as err:
        raise SystemExit("%s: %s" % (rel(path), err))


def read_bytes(path, hint=""):
    if not os.path.exists(path):
        raise SystemExit("missing %s%s" % (rel(path), hint))
    with open(path, "rb") as f:
        return f.read()


def load_json(path, hint=""):
    return parse_json(read_bytes(path, hint).decode("utf-8"), path)


def load_json_gz(path, hint=""):
    return parse_json(gzip.decompress(read_bytes(path, hint)).decode("utf-8"), path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def js_constant(path, pattern):
    """A value written in a JS file (read-only), found with a regular expression; None if absent."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        m = re.search(pattern, f.read(), re.S)
    return m.group(1) if m else None


# --------------------------------------------------------------------------
# Check book-keeping
# --------------------------------------------------------------------------
class Checks:
    """Every check gets a name, a rule, a short result and ok. Lists of problems are cut to 10."""

    def __init__(self):
        self.items = collections.OrderedDict()

    def add(self, name, ok, rule, result, problems=(), quiet=False):
        problems = list(problems)
        entry = {"rule": rule, "result": result, "ok": bool(ok)}
        if problems:
            entry["problems"] = problems[:10]
            entry["nProblems"] = len(problems)
        self.items[name] = entry
        if not quiet:
            self.show(name)
        return bool(ok)

    def show(self, name):
        e = self.items[name]
        log("%s %-22s %s" % ("ok  " if e["ok"] else "FAIL", name, e["result"]))
        for p in e.get("problems", []):
            log("       %s" % (p,))

    def failed(self):
        return [k for k, v in self.items.items() if not v["ok"]]

    def summary(self):
        return {k: {"ok": v["ok"], "result": v["result"]} for k, v in self.items.items()}


# --------------------------------------------------------------------------
# 1. Stage files: frame, one record per box, their own checks, network
# --------------------------------------------------------------------------
def load_stages():
    stages = {}
    for name, path in STAGE_FILES.items():
        stages[name] = load_json(path, ": run python -I %s first" % STAGE_SCRIPTS[name])
    return stages


def check_frames(checks, stages):
    keys = ("stage", "generated", "script", "grid", "sources", "network", "boxes", "controls")
    bad = []
    for name, st in stages.items():
        missing = [k for k in keys if k not in st]
        if missing:
            bad.append("%s: missing %s" % (name, ", ".join(missing)))
            continue
        if st["stage"] != name or st["script"] != STAGE_SCRIPTS[name] or st["grid"] != sg.GRID_ID:
            bad.append("%s: stage %r, script %r, grid %r" % (name, st["stage"], st["script"], st["grid"]))
        if not isinstance(st["boxes"], dict) or not isinstance(st["network"], list):
            bad.append("%s: boxes must be an object and network a list" % name)
    return checks.add("stageFrames", not bad,
                      "every stage file has {stage, generated, script, grid:'%s', sources, network, boxes, "
                      "controls}" % sg.GRID_ID, "4 stage files" if not bad else "%d problems" % len(bad), bad)


def check_one_record_each(checks, stages, dem_samples, geo_samples):
    """Duplicate keys already stop the build when a file is read, so equal id sets mean exactly one each."""
    ids = set(stages["grid"]["boxes"])
    sets = {"power": set(stages["power"]["boxes"]), "terrain": set(stages["terrain"]["boxes"]),
            "geology": set(stages["geology"]["boxes"]), "dem samples": set(dem_samples["boxes"]),
            "geology samples": set(geo_samples["boxes"])}
    bad = ["%s: %d missing, %d extra" % (k, len(ids - v), len(v - ids)) for k, v in sets.items() if v != ids]
    return checks.add("oneRecordPerStage", not bad and len(ids) > 0,
                      "every grid box has exactly one record in each stage and sample file (duplicate keys "
                      "stop the build)", "%d boxes x %d files" % (len(ids), len(sets)), bad)


def find_oks(obj, path=""):
    """Every 'ok' value in a stage's checks, with its path."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "ok":
                out.append((path or "checks", v))
            else:
                out.extend(find_oks(v, "%s.%s" % (path, k) if path else k))
    return out


def check_stage_checks(checks, stages):
    found, bad = 0, []
    for name, st in stages.items():
        oks = find_oks(st.get("checks", {}))
        oks += [("controls.%s" % cid, c["ok"]) for cid, c in st["controls"].items()
                if isinstance(c, dict) and "ok" in c]
        found += len(oks)
        bad += ["%s: %s" % (name, p) for p, ok in oks if ok is not True]
    return checks.add("stageChecks", not bad and found > 0,
                      "every check recorded by a stage script (checks.*.ok, controls.*.ok) passed",
                      "%d recorded checks" % found, bad)


def check_stage_flags(checks, stages):
    bad = []
    for name, allowed in STAGE_FLAGS.items():
        for bid, rec in stages[name]["boxes"].items():
            extra = set(rec.get("flags", [])) - allowed
            if extra or len(set(rec.get("flags", []))) != len(rec.get("flags", [])):
                bad.append("%s %s: flags %s" % (name, bid, rec.get("flags")))
    return checks.add("stageFlags", not bad,
                      "each stage sets only its own flags (power: climate cell flags; terrain: water flags; "
                      "geology: rock flags), each at most once",
                      "%d stages" % len(STAGE_FLAGS), bad)


def check_network(checks, stages):
    urls = [u for st in stages.values() for u in st["network"]]
    bad = [u for u in urls if "open-meteo" in str(u).lower()]
    return checks.add("noOpenMeteo", not bad,
                      "no Open-Meteo URL in any stage's network list (the API is never called)",
                      "%d URLs fetched by the stages, 0 from Open-Meteo" % len(urls) if not bad
                      else "%d Open-Meteo URLs" % len(bad), bad), urls


# --------------------------------------------------------------------------
# 2. Files: every sha256 a stage recorded matches its file
# --------------------------------------------------------------------------
def check_project_files(checks, stages, manifest, dem_samples, geo_samples):
    bad, n = [], 0

    def same(label, got, want):
        nonlocal n
        n += 1
        if got != want:
            bad.append("%s: %s != %s" % (label, str(got)[:16], str(want)[:16]))

    grid, power, terrain, geology = (stages[k] for k in ("grid", "power", "terrain", "geology"))
    same("boundary file", sha256_file(BOUNDARY_FILE), grid["boundary"]["sha256"])
    same("Natural Earth zip in grid sources", grid["sources"][0]["sha256"], sg.NE_SHA256)
    man_sha = sha256_file(MANIFEST_FILE)
    same("power manifest", man_sha, power["manifest"]["sha256"])
    same("power source", power["sources"][0]["sha256"], man_sha)
    for req in manifest["requests"]:
        path = os.path.join(POWER_DIR, req["file"])
        same(req["file"], sha256_file(path), req["sha256"])
        same(req["file"] + " bytes", os.path.getsize(path), req["bytes"])
    listed = set(power["climate"]["rawFiles"])
    wanted = {rel(MANIFEST_FILE)} | {"data/raw/screening/power/" + r["file"] for r in manifest["requests"]}
    same("climate.rawFiles", sorted(listed), sorted(wanted))
    tiles_sha = sha256_file(TILES_FILE)
    t = terrain["terrain"]
    same("tiles.json (terrain stage)", tiles_sha, t["tilesFileSha256"])
    same("tiles.json (samples header)", tiles_sha, dem_samples["tiles"]["sha256"])
    cop = [s for s in terrain["sources"] if s["id"] == "copernicus-dem-glo90"]
    same("tiles.json (Copernicus source)", tiles_sha, cop[0]["sha256"] if cop else None)
    same("samples_jordan.json.gz", sha256_file(DEM_SAMPLES), t["rawFileSha256"])
    files = geology["files"]
    same("rock table", sha256_file(ROCK_TABLE), files["rockTable"]["sha256"])
    same("geology samples", sha256_file(GEO_SAMPLES), files["samples"]["sha256"])
    same("geology grid stage", files["gridStage"]["generated"], grid["generated"])
    same("IGME5000 zip (samples)", geo_samples["source"]["zip"]["sha256"], IGME_SHA256)
    same("IGME5000 zip (source)", geology["sources"][0]["sha256"], IGME_SHA256)
    return checks.add("fileSha256", not bad,
                      "every sha256 (and byte count) a stage recorded matches the file in the project",
                      "%d comparisons" % n, bad)


def check_tiles(checks, terrain, tiles, args):
    """Tile sha256 values match the manifest (dem/tiles.json); the tiles are re-hashed when found."""
    bad = []
    listed = {e["name"]: e for e in tiles["tiles"]}
    stage = {e["name"]: e for e in terrain["terrain"]["tiles"]}
    if set(listed) != set(stage) or len(listed) != len(tiles["tiles"]):
        bad.append("tile names differ between dem/tiles.json and the terrain stage")
    for name in sorted(set(listed) & set(stage)):
        a, b = listed[name], stage[name]
        for k in ("url", "bytes", "sha256", "lastModified"):
            if a.get(k) != b.get(k):
                bad.append("%s %s differs" % (name, k))
        if a["url"] != tiles["urlPattern"].replace("<NAME>", name):
            bad.append("%s url does not follow the pattern" % name)
    dirs = [d for d in (args.dem_dir, os.path.join(args.cache_dir, "copernicus-dem-glo90")) if d]
    hashed = 0
    for name, e in sorted(listed.items()):
        path = next((os.path.join(d, name + ".tif") for d in dirs
                     if os.path.exists(os.path.join(d, name + ".tif"))), None)
        if path is None:
            continue
        hashed += 1
        if os.path.getsize(path) != e["bytes"] or sha256_file(path) != e["sha256"]:
            bad.append("%s: file %s does not match its sha256" % (name, path))
    where = ("all %d tile files re-hashed" % hashed if hashed == len(listed)
             else "%d of %d tile files found and re-hashed; the others are checked by their recorded sha256"
             % (hashed, len(listed)))
    return checks.add("tileSha256", not bad and len(listed) > 0,
                      "the DEM tiles of the terrain stage are the tiles of dem/tiles.json (name, URL, bytes, "
                      "sha256, Last-Modified); tile files found locally match their sha256",
                      "%d tiles; %s" % (len(listed), where), bad)


def check_big_zips(checks, args):
    """The Natural Earth and IGME5000 zips, when a copy is at hand (they live outside the project)."""
    found, bad = [], []
    for label, opt, name, want in (("Natural Earth", args.ne_zip, sg.NE_ZIP_NAME, sg.NE_SHA256),
                                   ("IGME5000", args.igme_zip, "IGME5000.zip", IGME_SHA256)):
        path = opt or os.path.join(args.cache_dir, name)
        if not os.path.exists(path):
            if opt:
                bad.append("%s: %s not found" % (label, path))
            continue
        found.append(label)
        if sha256_file(path) != want:
            bad.append("%s: %s does not match sha256 %s" % (label, path, want[:12]))
    result = ("re-hashed: %s" % ", ".join(found)) if found else "no local copy; recorded sha256 values used"
    return checks.add("sourceZips", not bad, "a local copy of a source zip, when found, matches its sha256",
                      result, bad)


# --------------------------------------------------------------------------
# 3. Grid: constants, ids, centres, bounds, inclusion, coverage
# --------------------------------------------------------------------------
def check_grid(checks, grid, boundary):
    c = grid["constants"]
    bad = []
    want = {"id": sg.GRID_ID, "south": sg.SOUTH, "west": sg.WEST, "dlat": sg.DLAT, "dlon": sg.DLON,
            "nrows": sg.NROWS, "ncols": sg.NCOLS}
    bad += ["constant %s = %r, expected %r" % (k, c.get(k), v) for k, v in want.items() if c.get(k) != v]
    if abs(c["dlat"] - math.degrees(10000.0 / R_EARTH_M)) > 1e-15:
        bad.append("dlat is not degrees(10000 / R)")
    if abs(c["dlon"] - c["dlat"] / math.cos(math.radians(31.28))) > 1e-15:
        bad.append("dlon is not dlat / cos(31.28 deg)")
    ring = [tuple(p) for p in boundary["ring"]]
    for bid, b in grid["boxes"].items():
        row, col = b["row"], b["col"]
        bounds = (c["south"] + row * c["dlat"], c["south"] + (row + 1) * c["dlat"],
                  c["west"] + col * c["dlon"], c["west"] + (col + 1) * c["dlon"])
        if bid != b["id"] or bid != "jo-r%02dc%02d" % (row, col):
            bad.append("%s: id does not match row %d col %d" % (bid, row, col))
        if not (0 <= row < c["nrows"] and 0 <= col < c["ncols"]):
            bad.append("%s: outside the grid" % bid)
        if max(abs(x - y) for x, y in zip(bounds, (b["s"], b["n"], b["w"], b["e"]))) > 1e-9:
            bad.append("%s: bounds differ from the grid constants" % bid)
        if ((b["lat"], b["lon"]) != sg.box_centre(row, col)
                or abs(b["lat"] - (bounds[0] + bounds[1]) / 2) > 1e-6 or abs(b["lon"] - (bounds[2] + bounds[3]) / 2) > 1e-6):
            bad.append("%s: centre is not the middle of the box (6 decimals)" % bid)
    kept = {sg.box_id(r, k) for r in range(sg.NROWS) for k in range(sg.NCOLS)
            if sg.inside(ring, sg.box_centre(r, k)[1], sg.box_centre(r, k)[0])}
    if kept != set(grid["boxes"]):
        bad.append("inclusion rule: %d boxes have their centre inside Jordan, the grid stage keeps %d"
                   % (len(kept), len(grid["boxes"])))
    checks.add("gridBoxes", not bad,
               "ids, rows, columns, centres and bounds follow the grid constants (bounds to 1e-9); a box is "
               "kept exactly when its centre is inside the polygon",
               "%d of %d grid boxes kept" % (len(grid["boxes"]), c["nrows"] * c["ncols"]), bad)
    return ring


def check_border(checks, grid):
    """inJordan and borderKm must agree with the box size: a box that crosses the boundary has its
    centre within half a diagonal of it, and a centre very close to the boundary means a crossing."""
    bad = []
    for bid, b in grid["boxes"].items():
        if not 0 < b["inJordan"] <= 1 or b["borderKm"] < 0:
            bad.append("%s: inJordan %r borderKm %r out of range" % (bid, b["inJordan"], b["borderKm"]))
        if b["inJordan"] < 1 and b["borderKm"] > 7.2:
            bad.append("%s: crosses the boundary but its centre is %.2f km from it" % (bid, b["borderKm"]))
        if b["inJordan"] == 1 and b["borderKm"] < 4.8:
            bad.append("%s: centre %.2f km from the boundary but the box does not cross it" % (bid, b["borderKm"]))
    n = sum(1 for b in grid["boxes"].values() if b["inJordan"] < 1)
    return checks.add("borderShares", not bad,
                      "0 < inJordan <= 1; inJordan < 1 only when the centre is within 7.2 km of the "
                      "boundary (half a box diagonal is at most 7.15 km); a centre under 4.8 km from it "
                      "(half a box side is at least 4.88 km) gives inJordan < 1",
                      "%d boxes cross the boundary" % n, bad)


def check_boundary(checks, grid, boundary):
    bad = []
    ring = boundary["ring"]
    if ring[0] != ring[-1] or len(ring) != boundary["nVertices"] or len(ring) != grid["boundary"]["nVertices"]:
        bad.append("the ring is not closed or its vertex count differs")
    if boundary["zip"]["sha256"] != sg.NE_SHA256 or boundary["version"] != "5.1.1":
        bad.append("boundary file is not from Natural Earth 5.1.1 (sha256 %s)" % sg.NE_SHA256[:12])
    if boundary["bbox"] != grid["boundary"]["bbox"]:
        bad.append("bbox differs from the grid stage")
    return checks.add("boundary", not bad,
                      "the boundary ring is closed and is the Natural Earth 10m v5.1.1 Jordan polygon of the "
                      "grid stage", "%d vertices, %.1f km2" % (len(ring), boundary["area_km2"]), bad)


def check_coverage(checks, ring, boundary, box_ids):
    bb = boundary["bbox"]
    cov = sg.coverage_check(ring, [bb["w"], bb["s"], bb["e"], bb["n"]], set(box_ids))
    checks.add("coverage", cov["ok"], cov["rule"],
               "%d lattice points inside Jordan: %d in a box, %d within %.1f km of the border, %d failures"
               % (cov["pointsInside"], cov["inKeptBox"], cov["notInKeptBoxButNearBorder"],
                  sg.COVERAGE_BORDER_KM, len(cov["failures"])),
               ["%.2f N %.2f E, %.2f km from the border" % tuple(f) for f in cov["failures"]])
    return cov


# --------------------------------------------------------------------------
# 4. Climate: cells from the raw POWER answers, box cells by the point-API rule, controls
# --------------------------------------------------------------------------
def merra_centre(lat, lon):
    return round(lat / MERRA_DLAT) * MERRA_DLAT, -180 + round((lon + 180) / MERRA_DLON) * MERRA_DLON


def syn_centre(lat, lon):
    return math.floor(lat) + 0.5, math.floor(lon) + 0.5


def cell_key(prefix, lat, lon):
    return "%s%r_%r" % (prefix, float(lat), float(lon))


def crosses_edge(lo, hi, offset, step):
    """Is there a cell edge (offset + k * step) strictly between lo and hi?"""
    k = math.floor((lo - offset) / step) + 1
    return offset + k * step < hi


def box_straddles(b):
    out = []
    if (crosses_edge(b["s"], b["n"], MERRA_DLAT / 2, MERRA_DLAT)
            or crosses_edge(b["w"], b["e"], -180 + MERRA_DLON / 2, MERRA_DLON)):
        out.append("merra")
    if crosses_edge(b["s"], b["n"], 0.0, SYN_STEP) or crosses_edge(b["w"], b["e"], 0.0, SYN_STEP):
        out.append("syn")
    return out


def load_regional(checks, manifest, period_label):
    """{group: {param: {(lat, lon): (elev, values)}}} from the saved POWER answers."""
    out, bad = {"merra": {}, "syn1deg": {}}, []
    for req in manifest["requests"]:
        data = load_json(os.path.join(POWER_DIR, req["file"]))
        head = data.get("header", {})
        if head.get("api", {}).get("version") != req["apiVersion"] or data.get("messages", [None])[0] != period_label:
            bad.append("%s: API version or period label differs from the manifest" % req["file"])
        if head.get("fill_value") != FILL_VALUE:
            bad.append("%s: fill value %r" % (req["file"], head.get("fill_value")))
        cells = {}
        for f in data["features"]:
            lon, lat, elev = f["geometry"]["coordinates"]
            cells[(lat, lon)] = (elev, f["properties"]["parameter"][req["parameter"]])
        if len(cells) != req["features"]:
            bad.append("%s: %d cells, manifest says %d" % (req["file"], len(cells), req["features"]))
        out[req["group"]][req["parameter"]] = cells
    for group, params in (("merra", MERRA_PARAMS), ("syn1deg", SYN_PARAMS)):
        bad += ["%s/%s.json is missing" % (group, p) for p in params if p not in out[group]]
    checks.add("powerAnswers", not bad,
               "the 17 saved POWER answers have the manifest's API version, period label, fill value and "
               "cell count", "%d answers, API %s" % (len(manifest["requests"]), manifest["requests"][0]["apiVersion"]),
               bad)
    return out


def raw_cell(regional, grid_name, lat, lon):
    """(elev, {param: {JAN..ANN}}) of one cell straight from the raw answers, or None."""
    group, params = ("merra", MERRA_PARAMS) if grid_name == "MERRA-2" else ("syn1deg", SYN_PARAMS)
    if (lat, lon) not in regional[group][params[0]]:
        return None
    elevs = {regional[group][p][(lat, lon)][0] for p in params}
    if len(elevs) != 1:
        return None
    return elevs.pop(), {p: regional[group][p][(lat, lon)][1] for p in params}


def check_cells(checks, power, regional, ring):
    """Every cell of the stage equals the raw answers; its bounds and Jordan share are right."""
    bad, info = [], []
    for key, cell in power["cells"].items():
        merra = cell["grid"] == "MERRA-2"
        hy, hx = (MERRA_DLAT / 2, MERRA_DLON / 2) if merra else (SYN_STEP / 2, SYN_STEP / 2)
        lat, lon = cell["lat"], cell["lon"]
        if key != cell_key("m" if merra else "s", lat, lon) or cell["grid"] not in ("MERRA-2", "CERES SYN1deg"):
            bad.append("%s: key does not match its grid and centre" % key)
        if (cell["s"], cell["n"], cell["w"], cell["e"]) != (lat - hy, lat + hy, lon - hx, lon + hx):
            bad.append("%s: bounds" % key)
        raw = raw_cell(regional, cell["grid"], lat, lon)
        if raw is None:
            bad.append("%s: not in the raw answers (or elevations differ between files)" % key)
            continue
        elev, values = raw
        annual = {p: v["ANN"] for p, v in values.items()}
        if cell["elev_m"] != elev or cell["annual"] != annual:
            bad.append("%s: elevation or annual values differ from the raw answers" % key)
        if any(v == FILL_VALUE or not isinstance(v, (int, float)) for v in annual.values()):
            bad.append("%s: fill value or missing value" % key)
        exact = sg.share_inside(ring, cell["s"], cell["n"], cell["w"], cell["e"])
        if abs(exact - cell["inJordan"]) > 0.02:
            bad.append("%s: inJordan %.4f, exact clipping gives %.4f" % (key, cell["inJordan"], exact))
        elif (exact < 0.5) != (cell["inJordan"] < 0.5):
            info.append("%s: sampled %.4f and exact %.4f are on different sides of 0.5" % (key, cell["inJordan"], exact))
    checks.add("climateCells", not bad,
               "every cell's annual values and elevation equal the raw POWER answers; key and bounds follow "
               "its grid; its sampled Jordan share is within 0.02 of exact polygon clipping",
               "%d cells, 0 differences" % len(power["cells"]) if not bad else "%d problems" % len(bad),
               bad + info)


def check_box_climate(checks, power, grid):
    bad = []
    for bid, b in grid["boxes"].items():
        rec = power["boxes"][bid]["climate"]
        mk = cell_key("m", *merra_centre(b["lat"], b["lon"]))
        sk = cell_key("s", *syn_centre(b["lat"], b["lon"]))
        if rec["merra"] != mk or rec["syn"] != sk:
            bad.append("%s: cells %s %s, the point-API rule gives %s %s" % (bid, rec["merra"], rec["syn"], mk, sk))
        if rec["straddles"] != box_straddles(b):
            bad.append("%s: straddles %s, bounds give %s" % (bid, rec["straddles"], box_straddles(b)))
        if mk not in power["cells"] or sk not in power["cells"]:
            bad.append("%s: a cell is missing from the stage's cells" % bid)
            continue
        flags = set()
        if rec["straddles"]:
            flags.add("straddlesCellEdge")
        if power["cells"][mk]["inJordan"] < 0.5:
            flags.add("climateCellMostlyOutside")
        if flags != set(power["boxes"][bid]["flags"]):
            bad.append("%s: flags %s, rules give %s" % (bid, power["boxes"][bid]["flags"], sorted(flags)))
    return checks.add("boxClimate", not bad,
                      "every box takes the MERRA-2 cell round(lat/0.5)*0.5, -180+round((lon+180)/0.625)*0.625 "
                      "and the SYN1deg cell floor+0.5 of its centre; straddles and climate flags follow the "
                      "box bounds and the cell's Jordan share", "%d boxes" % len(grid["boxes"]), bad)


def check_climate_controls(checks, regional, sites_by_id, today):
    """Design 2.1 hard check: the regional cells equal the project's point files, value for value."""
    results, n_eq, n_all, e_eq, problems = {}, 0, 0, 0, []
    for pid in CLIMATE_POINTS:
        point = load_json(os.path.join(RAW_POWER, pid + ".json"))
        lon, lat, elev = point["geometry"]["coordinates"]
        mlat, mlon = merra_centre(lat, lon)
        slat, slon = syn_centre(lat, lon)
        m, s = raw_cell(regional, "MERRA-2", mlat, mlon), raw_cell(regional, "CERES SYN1deg", slat, slon)
        params = point["properties"]["parameter"]
        eq = total = 0
        for p in MERRA_PARAMS + SYN_PARAMS:
            cell = m if p in MERRA_PARAMS else s
            for month in MONTHS:
                total += 1
                if cell is not None and cell[1][p].get(month) == params[p][month]:
                    eq += 1
        elev_ok = m is not None and m[0] == elev
        res = {"pointFile": "data/raw/power/%s.json" % pid, "merra": cell_key("m", mlat, mlon),
               "syn": cell_key("s", slat, slon), "values": "%d/%d" % (eq, total), "gridElevation": elev_ok}
        if pid in sites_by_id:
            site = sites_by_id[pid]["power"]
            seq = sum(1 for p in MERRA_PARAMS + SYN_PARAMS
                      if (m if p in MERRA_PARAMS else s) is not None
                      and site["annual"].get(p) == (m if p in MERRA_PARAMS else s)[1][p]["ANN"])
            seq += int(m is not None and site["gridElevation_m"] == m[0])
            res["sitesJson"] = "%d/%d" % (seq, len(MERRA_PARAMS + SYN_PARAMS) + 1)
            if seq != len(MERRA_PARAMS + SYN_PARAMS) + 1:
                problems.append("%s: data/sites.json %s" % (pid, res["sitesJson"]))
        if eq != total or not elev_ok:
            problems.append("%s: %s values, grid elevation equal %s" % (pid, res["values"], elev_ok))
        results[pid] = res
        n_eq, n_all, e_eq = n_eq + eq, n_all + total, e_eq + int(elev_ok)
    ok = n_eq == n_all and e_eq == len(CLIMATE_POINTS) and not problems
    checks.add("climateControls", ok,
               "the cells of the 5 Jordan sites and Amman equal the point files data/raw/power/<id>.json "
               "(14 parameters x 12 months + annual) and their grid elevation; the 5 sites also equal "
               "data/sites.json (14 annual values + gridElevation_m)",
               "%d/%d values, %d/%d grid elevations" % (n_eq, n_all, e_eq, len(CLIMATE_POINTS)), problems)
    validated = "values equal the project's 2001–2020 point files, %d/%d, %s" % (n_eq, n_all, today)
    return results, validated


# --------------------------------------------------------------------------
# 5. Terrain: every statistic again from the samples, the water rule, the controls
# --------------------------------------------------------------------------
def fake_cache(lats, lons, z):
    """The shape compute_terrain.compute_point() reads (one Open-Meteo-like answer)."""
    return {"body": "earth", "grid": {"lat": lats, "lon": lons},
            "requests": [{"n_points": len(z), "response": {"elevation": z}}]}


def mode_of(values):
    """Most frequent value; ties go to the first one in grid order (as collections.Counter does)."""
    counts, first = {}, {}
    for i, v in enumerate(values):
        counts[v] = counts.get(v, 0) + 1
        first.setdefault(v, i)
    best = max(counts, key=lambda v: (counts[v], -first[v]))
    return best, counts[best]


def terrain_from_samples(point, z):
    """compute_point's statistics plus mean and mode elevation and the water rule, from 441 samples."""
    lats, lons = ct.build_grid(point["lat"], point["lon"], R_EARTH_M)
    r = ct.compute_point(point, fake_cache(lats, lons, [None if v is None else float(v) for v in z]))
    valid = [v for v in z if v is not None]
    mode, count = mode_of(valid)
    r["mean_elev_m"] = round(sum(valid) / len(valid), 1)
    r["mode_elev_m"] = float(mode)
    is_water = r["flat_water_suspect"] and (mode <= WATER_MODE_MAX_M or mode == SEA_LEVEL_M)
    r["water_pct"] = round(100.0 * count / len(valid), 1) if is_water else 0.0
    r["flag"] = ("water" if r["water_pct"] >= WATER_PCT else
                 "partWater" if r["water_pct"] >= PART_WATER_PCT else None)
    return r


def check_box_terrain(checks, terrain, grid, dem_samples):
    bad, n_stats = [], 0
    skip = ("dataset", "name", "kind", "coordSource", "body", "lat", "lon", "elev_datum", "fetched", "flag")
    for bid, b in grid["boxes"].items():
        z = dem_samples["boxes"][bid]
        if len(z) != ct.GRID_N ** 2 or any(v is None for v in z):
            bad.append("%s: %d samples, %d missing" % (bid, len(z), sum(v is None for v in z)))
            continue
        point = {"id": bid, "body": "earth", "lat": b["lat"], "lon": b["lon"], "kind": "screening-box",
                 "name": "Box r%d c%d" % (b["row"], b["col"]), "coordSource": "box centre"}
        mine = terrain_from_samples(point, z)
        rec = terrain["boxes"][bid]
        stage = rec["terrain"]
        diff = sorted(k for k in set(mine) | set(stage) if k not in skip and mine.get(k) != stage.get(k))
        n_stats += len([k for k in stage if k not in skip])
        if diff:
            bad.append("%s: %s differ from the samples" % (bid, ", ".join(diff)))
        flags = [mine["flag"]] if mine["flag"] else []
        if flags != rec["flags"] or ("terrainExclude" in rec) != (mine["flag"] == "water"):
            bad.append("%s: water flags %s / terrainExclude %s, the rule gives %s"
                       % (bid, rec["flags"], "terrainExclude" in rec, flags))
        if "terrainExclude" in rec and not str(rec["terrainExclude"]).startswith("Mostly water"):
            bad.append("%s: terrainExclude does not start with 'Mostly water'" % bid)
        if stage.get("dataset") != terrain["terrain"]["dataset"]:
            bad.append("%s: dataset %r" % (bid, stage.get("dataset")))
    return checks.add("boxTerrain", not bad,
                      "every box's terrain statistics, mean and mode elevation, water_pct, water flags and "
                      "terrainExclude come out again from its 441 samples (compute_terrain.compute_point, "
                      "unchanged; water rule of design 2.1)",
                      "%d boxes, %d values recomputed" % (len(grid["boxes"]), n_stats), bad)


def check_terrain_controls(checks, terrain, dem_samples):
    """Design 2.1 hard check: the 5 Jordan sites give exactly data/terrain.json."""
    points = {p["id"]: p for p in load_json(TERRAIN_POINTS)}
    ref = load_json(TERRAIN_JSON)["points"]
    out, bad, n_eq, n_all = {}, [], 0, 0
    for sid in JORDAN_SITES:
        p = points[sid]
        z = dem_samples["controls"][sid]
        cache = load_json(os.path.join(RAW_TERRAIN, sid + ".json"))
        om, _ = ct.elevations_from_cache(cache)
        lats, lons = ct.build_grid(p["lat"], p["lon"], R_EARTH_M)
        same_grid = cache["grid"]["lat"] == lats and cache["grid"]["lon"] == lons
        eq = sum(1 for a, b in zip(z, om) if a is not None and b is not None and float(a) == b)
        mine = terrain_from_samples(p, z)
        diff = sorted(k for k, v in ref[sid].items() if k not in ("dataset", "fetched") and mine.get(k) != v)
        stage = terrain["controls"][sid]["terrain"]
        diff_stage = sorted(k for k in stage if k != "dataset" and mine.get(k) != stage[k])
        if not same_grid or eq != len(om) or len(z) != len(om) or diff or diff_stage:
            bad.append("%s: samples %d/%d, grid same %s, differs from terrain.json: %s, from the stage: %s"
                       % (sid, eq, len(om), same_grid, diff, diff_stage))
        n_eq, n_all = n_eq + eq, n_all + len(om)
        out[sid] = {"samples": "%d/%d" % (eq, len(om)), "statsEqual": not diff, "terrain": mine}
    checks.add("terrainControls", not bad and n_eq == n_all,
               "the 5 Jordan sites: all 441 samples equal the cached Open-Meteo answers "
               "(data/raw/terrain/<id>.json) and every statistic equals data/terrain.json",
               "%d/%d samples, %d/%d sites" % (n_eq, n_all, len(JORDAN_SITES) - len(bad), len(JORDAN_SITES)), bad)
    return out


def check_notices(checks, tiles, dem_samples, terrain):
    """The Copernicus Art. 6(b) and 6(c) notices travel with the derived samples (design section 8)."""
    credit = ct.DATASETS["earth"]["credit"]
    art6b = credit[:credit.index("all rights reserved.") + len("all rights reserved.")]
    want = {"copernicusArt6b": art6b, "copernicusArt6c": ART6C, "endorsement": ENDORSEMENT}
    bad = []
    if dem_samples.get("copernicusNotices") != want or list(dem_samples)[0] != "copernicusNotices":
        bad.append("samples_jordan.json.gz: the notices are not the first key or differ")
    if tiles.get("notices") != want:
        bad.append("dem/tiles.json: notices differ")
    cop = next((s for s in terrain["sources"] if s["id"] == "copernicus-dem-glo90"), {})
    if cop.get("credit") != art6b or ART6C not in cop.get("notice", "") or ENDORSEMENT not in cop.get("notice", ""):
        bad.append("terrain stage: the Copernicus source does not carry the notices")
    checks.add("copernicusNotices", not bad,
               "Art. 6(b) notice (compute_terrain's credit up to 'all rights reserved.'), Art. 6(c) "
               "no-liability sentence and 'no endorsement' are in the samples file, tiles.json and sources",
               "3 notices in 3 places" if not bad else "%d problems" % len(bad), bad)
    return art6b


# --------------------------------------------------------------------------
# 6. Geology: the main rock again from the 25 unit codes and the rock table
# --------------------------------------------------------------------------
CERTAINTY_RANK = {"high": 2, "medium": 1, "low": 0}


def geology_from_codes(codes, polys, centre, table):
    """Design 2.1 geology rules, written again independently of the stage script."""
    hist = collections.Counter(codes)
    unit = min(hist, key=lambda u: (-hist[u], -CERTAINTY_RANK[table[u]["certainty"]], int(u)))
    row = table[unit]
    sure = row["certainty"] in ("high", "medium")
    primary = row["primary"] if sure else None
    secondary = set()
    if primary:
        secondary = set(row["secondary"])
        secondary |= {table[u]["primary"] for u, n in hist.items()
                      if u != unit and n >= 5 and table[u]["certainty"] != "low" and table[u]["primary"]}
        secondary.discard(primary)
    return {"primary": primary, "secondary": secondary, "unit": unit, "share": round(hist[unit] / len(codes), 2),
            "certainty": row["certainty"], "inferred": None if sure else row["primary"],
            "units": dict(hist), "centrePolygon": polys[centre]}


def rock_ids():
    """The rock ids of ROCK_LABEL in js/scoring.js (read-only)."""
    block = js_constant(SCORING_JS, r"export const ROCK_LABEL = \{(.*?)\};")
    if block is None:
        raise SystemExit("ROCK_LABEL not found in js/scoring.js")
    return set(re.findall(r"^\s*'?([a-z-]+)'?\s*:", block, re.M))


def check_units(checks, geology, table, rocks):
    bad = []
    for code, unit in geology["units"].items():
        row = table["units"].get(code)
        if row is None:
            bad.append("%s: not in the rock table" % code)
            continue
        if {k: row[k] for k in UNIT_FIELDS} != unit or set(unit) != set(UNIT_FIELDS):
            bad.append("%s: differs from the rock table" % code)
        used = [unit["primary"]] + list(unit["secondary"])
        bad += ["%s: rock id %r is not in ROCK_LABEL" % (code, r) for r in used if r is not None and r not in rocks]
        if unit["certainty"] not in CERTAINTY_RANK:
            bad.append("%s: certainty %r" % (code, unit["certainty"]))
    for code in ("8500007", "600017"):
        if code in geology["units"] and geology["units"][code]["primary"] is not None:
            bad.append("%s must have no rock id" % code)
    return checks.add("rockTable", not bad,
                      "every unit of the stage equals its row in data/screening_rockmap_igme5000.json; every "
                      "rock id is in ROCK_LABEL (js/scoring.js); water and undifferentiated Neogene have none",
                      "%d units" % len(geology["units"]), bad)


def site_units(geo_samples):
    """The map unit at each Jordan site's own point."""
    return {sid: c["point"][0] for sid, c in geo_samples["controls"].items()}


def check_box_geology(checks, geology, grid, geo_samples):
    table = geology["units"]
    centre = geo_samples["sampling"]["centreIndex"]
    at_site = site_units(geo_samples)
    bad = []
    for bid in grid["boxes"]:
        s = geo_samples["boxes"][bid]
        if len(s["units"]) != 25 or len(s["polygons"]) != 25:
            bad.append("%s: %d points" % (bid, len(s["units"])))
            continue
        missing = [u for u in set(s["units"]) if u not in table]
        if missing:
            bad.append("%s: units %s not in the unit table" % (bid, missing))
            continue
        mine = geology_from_codes(s["units"], s["polygons"], centre, table)
        rec = geology["boxes"][bid]
        for k, v in mine.items():
            got = set(rec[k]) if k == "secondary" else rec[k]
            if got != v:
                bad.append("%s: %s is %r, the samples give %r" % (bid, k, rec[k], v))
        if len(rec["secondary"]) != len(set(rec["secondary"])):
            bad.append("%s: repeated secondary rock" % bid)
        if (rec["why"] is None) != (rec["primary"] is not None):
            bad.append("%s: 'why' must be set exactly when there is no primary rock" % bid)
        flags = []
        if mine["certainty"] == "low":
            flags.append("lowCertaintyGeology")
        elif mine["primary"] is None:
            flags.append("noGeology")
        if flags != rec["flags"]:
            bad.append("%s: flags %s, rules give %s" % (bid, rec["flags"], flags))
        same = sorted(sid for sid, u in at_site.items() if u == mine["unit"])
        if sorted(rec["sameUnitAs"]) != same:
            bad.append("%s: sameUnitAs %s, the site points give %s" % (bid, rec["sameUnitAs"], same))
    return checks.add("boxGeology", not bad,
                      "every box's unit (most frequent of 25; ties: higher certainty, then lower code), share, "
                      "certainty, primary, secondary (table + other units with >= 5 of 25 points, not low), "
                      "inferred, histogram, centre polygon, flags and sameUnitAs come out again from "
                      "geology/samples_jordan.json and the rock table",
                      "%d boxes" % len(grid["boxes"]), bad)


# --------------------------------------------------------------------------
# 7. The app file
# --------------------------------------------------------------------------
def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def distance_km(lat1, lon1, lat2, lon2):
    """Haversine distance, the same formula and radius as distanceKm() in js/util.js."""
    r = math.pi / 180
    a = (math.sin((lat2 - lat1) * r / 2) ** 2
         + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2)
    return 2 * R_EARTH_KM * math.asin(math.sqrt(a))


def nearest_site(b, sites):
    """The nearest hand-picked site: id, distance (km, 1 decimal) and the box's direction from it."""
    best = min(sites, key=lambda s: (distance_km(s["lat"], s["lon"], b["lat"], b["lon"]), s["id"]))
    km = distance_km(best["lat"], best["lon"], b["lat"], b["lon"])
    d = COMPASS[int((bearing_deg(best["lat"], best["lon"], b["lat"], b["lon"]) + 22.5) // 45) % 8]
    return {"id": best["id"], "km": round(km, 1), "dir": d}


def sites_in_boxes(sites, box_ids):
    """{box id: site id} for every site whose own point lies in a kept box."""
    out = {}
    for s in sites:
        rc = sg.box_of_point(s["lat"], s["lon"])
        if rc and sg.box_id(*rc) in box_ids:
            if sg.box_id(*rc) in out:
                raise SystemExit("two sites in box %s" % sg.box_id(*rc))
            out[sg.box_id(*rc)] = s["id"]
    return out


def box_record(bid, stages, cell_limit, holds, sites):
    g = stages["grid"]["boxes"][bid]
    p = stages["power"]["boxes"][bid]
    t = stages["terrain"]["boxes"][bid]
    geo = stages["geology"]["boxes"][bid]
    merra = stages["power"]["cells"][p["climate"]["merra"]]
    gap = merra["elev_m"] - t["terrain"]["centre_elev_m"]
    flags = set(p["flags"]) | set(t["flags"]) | set(geo["flags"])
    if g["inJordan"] < 1:
        flags.add("border")
    if abs(gap) > cell_limit:
        flags.add("cellGap")
    rec = {"id": bid, "row": g["row"], "col": g["col"], "lat": g["lat"], "lon": g["lon"],
           "inJordan": g["inJordan"], "borderKm": g["borderKm"],
           "climate": {k: p["climate"][k] for k in ("merra", "syn", "straddles")},
           "terrain": {k: t["terrain"][k] for k in TERRAIN_FIELDS},
           "geology": {k: geo[k] for k in GEOLOGY_FIELDS}}
    if "terrainExclude" in t:
        rec["terrainExclude"] = t["terrainExclude"]
    rec["cellGap_m"] = round(gap, 2)
    rec["flags"] = [f for f in FLAGS if f in flags]
    unknown = flags - set(FLAGS)
    if unknown:
        raise SystemExit("%s: unknown flags %s" % (bid, sorted(unknown)))
    rec["containsSite"] = holds.get(bid)
    rec["nearestSite"] = nearest_site(g, sites)
    rec["sameUnitAs"] = list(geo["sameUnitAs"])
    return rec


def controls_block(stages, sites_by_id, climate_results, terrain_results, geo_samples):
    """The 5 Jordan site points run through the same pipeline as a box (the hard checks of 2.1)."""
    table = stages["geology"]["units"]
    gstage = stages["geology"]["controls"]
    out = {}
    for sid in JORDAN_SITES:
        site = sites_by_id[sid]
        c, t = climate_results[sid], terrain_results[sid]
        unit = geo_samples["controls"][sid]["point"][0]
        row = table.get(unit, {})
        sure = row.get("certainty") in ("high", "medium")
        out[sid] = {
            "name": site["name"], "lat": site["lat"], "lon": site["lon"],
            "source": "data/sites.json (terrain: data/terrain_points.json)",
            "box": stages["grid"]["controls"][sid]["box"],
            "climate": {"merra": c["merra"], "syn": c["syn"]},
            "terrain": {k: t["terrain"][k] for k in TERRAIN_FIELDS},
            "geology": {"unit": unit, "primary": row.get("primary") if sure else None,
                        "secondary": list(row.get("secondary", [])) if sure else [],
                        "certainty": row.get("certainty"), "inferred": None if sure else row.get("primary"),
                        "polygon": geo_samples["controls"][sid]["point"][1]},
            "siteGeology": site["geology"],
            "checks": {"climateValues": c["values"], "gridElevationEqual": c["gridElevation"],
                       "sitesJson": c.get("sitesJson"), "terrainSamples": t["samples"],
                       "terrainStatsEqual": t["statsEqual"], "geologyUnitExpected": gstage[sid]["unitOk"]},
        }
    return out


def sources_block(stages):
    order = ("power", "terrain", "geology", "grid")
    return [dict((k, s.get(k)) for k in SOURCE_FIELDS) | {k: v for k, v in s.items() if k not in SOURCE_FIELDS}
            for name in order for s in stages[name]["sources"]]


def check_sources(checks, sources, art6b):
    bad = []
    ids = [s["id"] for s in sources]
    if len(set(ids)) != len(ids):
        bad.append("repeated source id")
    for s in sources:
        for k in SOURCE_FIELDS:
            v = s.get(k)
            if v is None and not (k in ("sha256", "credit") and s["id"] in NO_FILE_SOURCES):
                bad.append("%s: %s is missing" % (s["id"], k))
        if not str(s.get("url", "")).startswith("https://") or not s.get("licence"):
            bad.append("%s: needs an https URL and a licence" % s["id"])
    credited = sorted(s["id"] for s in sources if s.get("credit"))
    if credited != sorted(CREDITED_SOURCES):
        bad.append("sources with a credit (shown on the globe): %s, expected %s" % (credited, sorted(CREDITED_SOURCES)))
    by_id = {s["id"]: s for s in sources}
    want = {"nasa-power-climatology-regional": POWER_CITATION, "copernicus-dem-glo90": art6b, "igme5000": IGME_CREDIT}
    bad += ["%s: credit is not the required text" % k for k, v in want.items() if by_id.get(k, {}).get("credit") != v]
    if "larc-power-project@mail.nasa.gov" not in by_id.get("nasa-power-climatology-regional", {}).get("notice", ""):
        bad.append("NASA POWER notice lacks the notification address")
    return checks.add("sources", not bad,
                      "every source has id, label, https URL, licence, licence URL, credit, notice, version, "
                      "access date and sha256 (sha256 and credit are null only for a cited rule with no file); "
                      "only NASA POWER, Copernicus, IGME5000 and Natural Earth carry a credit (the globe's data "
                      "credits, design 4.2); the NASA POWER citation, Copernicus Art. 6(b) notice and IGME5000 "
                      "credit are verbatim",
                      ", ".join(ids), bad)


def required_box_values(rec, cells, units):
    """Problems with one app box record: missing values, wrong types, unknown references."""
    bad = []
    num = (int, float)
    for k in ("row", "col", "lat", "lon", "inJordan", "borderKm", "cellGap_m"):
        if not isinstance(rec.get(k), num) or isinstance(rec.get(k), bool) or not math.isfinite(rec[k]):
            bad.append(k)
    c = rec["climate"]
    if c["merra"] not in cells or c["syn"] not in cells or not isinstance(c["straddles"], list):
        bad.append("climate")
    for k in TERRAIN_FIELDS:
        v = rec["terrain"].get(k)
        if v is None or (k == "notes" and not isinstance(v, str)) or (k == "flat_water_suspect" and not isinstance(v, bool)):
            bad.append("terrain." + k)
        elif k not in ("notes", "flat_water_suspect") and (not isinstance(v, num) or not math.isfinite(v)):
            bad.append("terrain." + k)
    g = rec["geology"]
    for k in ("unit", "share", "certainty", "units", "centrePolygon"):
        if g.get(k) is None:
            bad.append("geology." + k)
    if g.get("unit") not in units or any(u not in units for u in g.get("units", {})):
        bad.append("geology.unit not in units")
    if g["primary"] is None and not g.get("why"):
        bad.append("geology.why")
    if not isinstance(g["secondary"], list):
        bad.append("geology.secondary")
    n = rec["nearestSite"]
    if not n or n.get("id") is None or not isinstance(n.get("km"), num) or n.get("dir") not in COMPASS:
        bad.append("nearestSite")
    if not isinstance(rec["sameUnitAs"], list) or not isinstance(rec["flags"], list):
        bad.append("lists")
    if rec["containsSite"] is not None and not isinstance(rec["containsSite"], str):
        bad.append("containsSite")
    if "terrainExclude" in rec and not rec["terrainExclude"]:
        bad.append("terrainExclude")
    return bad


def check_doc(checks, doc, cell_limit):
    cells, units = doc["climate"]["cells"], doc["geology"]["units"]
    bad = []
    for rec in doc["boxes"]:
        miss = required_box_values(rec, cells, units)
        if miss:
            bad.append("%s: %s" % (rec["id"], ", ".join(miss)))
    for key, cell in cells.items():
        if any(cell.get(k) is None for k in ("grid", "lat", "lon", "s", "n", "w", "e", "elev_m", "inJordan", "annual")):
            bad.append("cell %s: missing value" % key)
    checks.add("requiredValues", not bad,
               "no None where a value is needed (box fields of design 2.3; primary may be null only with "
               "'why'; containsSite is a site id or null); every cell and unit a box names exists",
               "%d boxes, %d cells, %d units" % (len(doc["boxes"]), len(cells), len(units)), bad)

    bad = []
    for rec in doc["boxes"]:
        f = rec["flags"]
        if any(x not in FLAGS for x in f) or f != [x for x in FLAGS if x in f]:
            bad.append("%s: flags %s" % (rec["id"], f))
        if ("water" in f) != ("terrainExclude" in rec):
            bad.append("%s: water flag and terrainExclude disagree" % rec["id"])
        if ("cellGap" in f) != (abs(rec["cellGap_m"]) > cell_limit):
            bad.append("%s: cellGap flag and cellGap_m disagree" % rec["id"])
        if ("border" in f) != (rec["inJordan"] < 1):
            bad.append("%s: border flag and inJordan disagree" % rec["id"])
    checks.add("flags", not bad,
               "flags come from the known list, in its order; 'water' is set exactly when terrainExclude is; "
               "'cellGap' exactly when |cellGap_m| > %d m; 'border' exactly when inJordan < 1" % cell_limit,
               "%d boxes" % len(doc["boxes"]), bad)

    ids = [r["id"] for r in doc["boxes"]]
    bad = [] if ids == sorted(set(ids)) else ["box ids are not unique and sorted"]
    if doc["label"] != LABEL or "—" not in doc["label"]:
        bad.append("label differs from the exact string")
    js_label = js_constant(SCREENING_JS, r"export const SCREEN_LABEL = '([^']*)'")
    if js_label is not None and js_label != LABEL:
        bad.append("js/screening.js SCREEN_LABEL differs: %r" % js_label)
    checks.add("labelAndIds", not bad,
               "the label is exactly '%s' (and equals SCREEN_LABEL in js/screening.js when present); box ids "
               "are unique and sorted" % LABEL, "%d unique ids" % len(set(ids)), bad)


def pretty(value, path=()):
    """JSON text: the top level and its blocks one key per line, boxes/cells/units/tiles one per line."""
    def compact(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    if path == () or (len(path) == 1 and isinstance(value, dict) and path[0] not in ("controls",)):
        items = ["%s:%s" % (json.dumps(k, ensure_ascii=False), pretty(v, path + (k,))) for k, v in value.items()]
        pad = " " * len(path)
        return "{\n%s\n%s}" % (",\n".join(pad + " " + i for i in items), pad)
    rows = path in (("controls",), ("boxes",), ("sources",), ("climate", "cells"), ("climate", "validation"),
                    ("geology", "units"), ("terrain", "tiles"))
    if rows and isinstance(value, dict) and value:
        pad = " " * len(path)
        items = ["%s:%s" % (json.dumps(k, ensure_ascii=False), compact(v)) for k, v in value.items()]
        return "{\n%s\n%s}" % (",\n".join(pad + " " + i for i in items), pad)
    if rows and isinstance(value, list) and value:
        pad = " " * len(path)
        return "[\n%s\n%s]" % (",\n".join(pad + " " + compact(v) for v in value), pad)
    return compact(value)


def render(doc, checks):
    doc["checks"] = checks.summary()
    try:
        return pretty(doc) + "\n"
    except ValueError as err:          # NaN or Infinity somewhere
        checks.add("json", False, "the file is valid JSON with no NaN or Infinity", str(err))
        return ""


def check_text(checks, doc, text):
    """The text reads back to exactly the data, and it is small enough."""
    try:
        same = bool(text) and json.loads(text) == json.loads(json.dumps(doc, allow_nan=False))
        result = "valid JSON, reads back unchanged" if same else "the JSON writer changed the data"
    except ValueError as err:
        same, result = False, str(err)
    checks.add("json", same, "the file is valid JSON with no NaN or Infinity and reads back unchanged",
               result, quiet=True)
    size = len(text.encode("utf-8"))
    checks.add("size", 0 < size <= SIZE_LIMIT,
               "the file is at most %d bytes (design target: under %d)" % (SIZE_LIMIT, SIZE_TARGET),
               "%d bytes (%s the %d-byte target)" % (size, "under" if size < SIZE_TARGET else "over", SIZE_TARGET),
               quiet=True)


def counts_block(doc):
    boxes = doc["boxes"]
    flags = {f: sum(1 for b in boxes if f in b["flags"]) for f in FLAGS}
    rock = collections.Counter(b["geology"]["primary"] or "none" for b in boxes)
    return {"boxes": len(boxes), "flags": flags,
            "boxesWithoutFlags": sum(1 for b in boxes if not b["flags"]),
            "holdSite": sum(1 for b in boxes if b["containsSite"]),
            "primaryRock": dict(sorted(rock.items(), key=lambda kv: (-kv[1], kv[0]))),
            "merraCells": sum(1 for c in doc["climate"]["cells"].values() if c["grid"] == "MERRA-2"),
            "synCells": sum(1 for c in doc["climate"]["cells"].values() if c["grid"] != "MERRA-2"),
            "units": len(doc["geology"]["units"])}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dem-dir", help="folder with the Copernicus DEM tiles (re-hashed when found)")
    parser.add_argument("--igme-zip", help="IGME5000.zip (re-hashed when given)")
    parser.add_argument("--ne-zip", help="%s (re-hashed when given)" % sg.NE_ZIP_NAME)
    parser.add_argument("--cache-dir", default=default_cache_dir(), help="the screening cache folder")
    parser.add_argument("--out", default=OUT_FILE, help="where to write the app file (default %s)" % rel(OUT_FILE))
    return parser.parse_args(argv)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    try:
        return build(args)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as err:
        log("CHECK FAILED: an input file does not have the expected shape (%s: %s). Nothing was written."
            % (type(err).__name__, err))
        return 1


def build(args):
    t0 = time.time()
    now = utc_now()
    today = now.strftime("%Y-%m-%d")
    checks = Checks()

    stages = load_stages()
    grid, power, terrain, geology = (stages[k] for k in ("grid", "power", "terrain", "geology"))
    boundary = load_json(BOUNDARY_FILE)
    manifest = load_json(MANIFEST_FILE)
    tiles = load_json(TILES_FILE)
    dem_samples = load_json_gz(DEM_SAMPLES)
    geo_samples = load_json(GEO_SAMPLES)
    table = load_json(ROCK_TABLE)
    sites = load_json(SITES_JSON)["sites"]
    sites_by_id = {s["id"]: s for s in sites}
    cell_limit = js_constant(UTIL_JS, r"export const CELL_GAP_LIMIT_M = (\d+);")
    if cell_limit is None:
        raise SystemExit("CELL_GAP_LIMIT_M not found in js/util.js")
    cell_limit = int(cell_limit)

    log("Stage files")
    if not (check_frames(checks, stages) and check_one_record_each(checks, stages, dem_samples, geo_samples)):
        log("CHECK FAILED: %s. Re-run the stage scripts in order (see the docstring). Nothing was written."
            % ", ".join(checks.failed()))
        return 1
    check_stage_checks(checks, stages)
    _, network = check_network(checks, stages)
    check_project_files(checks, stages, manifest, dem_samples, geo_samples)
    check_tiles(checks, terrain, tiles, args)
    check_big_zips(checks, args)
    check_stage_flags(checks, stages)

    log("Grid")
    check_boundary(checks, grid, boundary)
    ring = check_grid(checks, grid, boundary)
    check_border(checks, grid)
    coverage = check_coverage(checks, ring, boundary, grid["boxes"])

    log("Climate")
    regional = load_regional(checks, manifest, power["climate"]["periodLabel"])
    check_cells(checks, power, regional, ring)
    check_box_climate(checks, power, grid)
    climate_results, validated = check_climate_controls(checks, regional, sites_by_id, today)

    log("Terrain")
    art6b = check_notices(checks, tiles, dem_samples, terrain)
    check_box_terrain(checks, terrain, grid, dem_samples)
    terrain_results = check_terrain_controls(checks, terrain, dem_samples)

    log("Geology")
    check_units(checks, geology, table, rock_ids())
    check_box_geology(checks, geology, grid, geo_samples)

    log("App file")
    ids = sorted(grid["boxes"])
    holds = sites_in_boxes(sites, set(ids))
    expected_holds = {c["box"]: sid for sid, c in grid["controls"].items() if c["boxKept"]}
    checks.add("siteBoxes", holds == expected_holds,
               "the boxes holding a hand-picked site (any of data/sites.json) are the grid stage's control boxes",
               ", ".join("%s %s" % (sid, bid) for bid, sid in sorted(holds.items(), key=lambda kv: kv[1])))
    boxes = [box_record(bid, stages, cell_limit, holds, sites) for bid in ids]
    used = sorted({b["climate"][k] for b in boxes for k in ("merra", "syn")}
                  | {climate_results[s][k] for s in JORDAN_SITES for k in ("merra", "syn")})
    missing_cells = [k for k in used if k not in power["cells"]]
    if missing_cells:
        raise SystemExit("cells missing from the power stage: %s" % missing_cells)

    doc = collections.OrderedDict()
    doc["format"] = FORMAT
    doc["generated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["label"] = LABEL
    doc["about"] = ABOUT
    doc["grid"] = dict(grid["constants"]) | {
        "stage": rel(STAGE_FILES["grid"]), "kept": len(ids), "gridBoxes": grid["counts"]["gridBoxes"],
        "coverage": "%d of %d lattice points inside Jordan are in a box; the other %d are within %.1f km "
                    "of the border (0.02 deg lattice)" % (coverage["inKeptBox"], coverage["pointsInside"],
                                                         coverage["notInKeptBoxButNearBorder"],
                                                         sg.COVERAGE_BORDER_KM)}
    doc["boundary"] = {
        "source": boundary["source"], "version": boundary["version"], "url": boundary["url"],
        "sha256": boundary["zip"]["sha256"], "licence": boundary["licence"], "licenceUrl": boundary["licenceUrl"],
        "accessed": boundary["accessed"],
        "note": ("Natural Earth's de facto, generalised boundary of Jordan. It is indicative only and does "
                 "not include the West Bank."),
        "file": rel(BOUNDARY_FILE), "fileSha256": grid["boundary"]["sha256"],
        "bbox": boundary["bbox"], "area_km2": boundary["area_km2"], "nVertices": boundary["nVertices"],
        "ring": boundary["ring"]}
    c = power["climate"]
    doc["climate"] = {
        "api": c["api"], "apiVersion": c["apiVersion"], "community": c["community"],
        "periodLabel": c["periodLabel"], "headerPeriod": c["headerPeriod"], "periodValidated": validated,
        "rule": c["rule"], "rawFiles": c["rawFiles"], "manifest": power["manifest"],
        "validation": {pid: climate_results[pid] for pid in CLIMATE_POINTS},
        "cells": {k: power["cells"][k] for k in used}}
    t = terrain["terrain"]
    doc["terrain"] = {k: t[k] for k in ("dataset", "pixelRule", "method", "methodDetail", "rawFile",
                                        "rawFileSha256", "tilesFile", "tilesFileSha256", "waterRule", "elevDatum")}
    doc["terrain"]["tiles"] = [{k: e[k] for k in ("name", "url", "bytes", "sha256", "lastModified")} for e in t["tiles"]]
    m = geology["method"]
    doc["geology"] = {k: m[k] for k in ("citation", "doi", "credit", "scale", "sampling", "projection",
                                        "dominant", "primaryRule", "secondaryRule", "nullRule", "share",
                                        "centrePolygon", "sameUnitAs")}
    doc["geology"] |= {"rockTable": rel(ROCK_TABLE), "rockTableSha256": geology["files"]["rockTable"]["sha256"],
                       "rockTableReview": table["review"]["status"], "rawFile": rel(GEO_SAMPLES),
                       "rawFileSha256": geology["files"]["samples"]["sha256"],
                       "units": dict(sorted(geology["units"].items()))}
    doc["flagRules"] = FLAG_RULES
    doc["controls"] = controls_block(stages, sites_by_id, climate_results, terrain_results, geo_samples)
    doc["sources"] = sources_block(stages)
    doc["stages"] = {k: {"file": rel(STAGE_FILES[k]), "generated": stages[k]["generated"],
                         "sha256": sha256_file(STAGE_FILES[k])} for k in STAGE_FILES}
    doc["network"] = network
    doc["boxes"] = boxes
    check_sources(checks, doc["sources"], art6b)
    check_doc(checks, doc, cell_limit)

    # The counts and the check summary go in the file too. The summary holds the size and JSON checks of
    # the final text, so render until the text no longer changes (the size only moves by a few digits).
    doc["counts"] = counts_block(doc)
    doc["checks"] = {}
    doc.move_to_end("boxes")
    text = render(doc, checks)
    for _ in range(5):
        check_text(checks, doc, text)
        new_text = render(doc, checks)
        if new_text == text:
            break
        text = new_text
    else:
        checks.add("size", False, "the rendered file must settle", "the text kept changing")
    checks.show("json")
    checks.show("size")

    failed = checks.failed()
    counts = doc["counts"]
    log("")
    log("boxes %d; flags %s" % (counts["boxes"], json.dumps(counts["flags"])))
    log("main rock %s; boxes holding a site %d" % (json.dumps(counts["primaryRock"]), counts["holdSite"]))
    log("%d checks, %d failed (%.1f s)" % (len(checks.items), len(failed), time.time() - t0))
    if failed:
        log("CHECK FAILED: %s. Nothing was written." % ", ".join(failed))
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(args.out + ".tmp", args.out)
    log("wrote %s (%d bytes, sha256 %s...)" % (os.path.relpath(args.out, ROOT).replace(os.sep, "/"),
                                                os.path.getsize(args.out), sha256_file(args.out)[:12]))
    log("checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
