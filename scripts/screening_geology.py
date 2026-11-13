#!/usr/bin/env python3
"""Jordan screening layer, stage 4: the main rock of every 10 km box (geology).

Reads the IGME5000 geology map (BGR, 1:5 million, shapefile v01) and looks up the map
unit at 5 x 5 points in every box of data/raw/screening/stages/grid.json: at -4, -2,
0, +2 and +4 km north and east of the box centre, placed with
compute_terrain.destination(). The most frequent unit is the box's unit, and the
curated table data/screening_rockmap_igme5000.json turns it into Analog Atlas rock ids.

Writes (from the project folder):
  data/raw/screening/geology/samples_jordan.json  the 25 unit codes (and polygon record
                                                  numbers) of every box, and the unit table
  data/raw/screening/stages/geology.json          main rock of every box, the 5 site controls
  data/raw/screening/geology/macrostrat_crosscheck.json   only with --crosscheck

Python 3.12 standard library only. Run from any folder:

  python -I scripts/screening_geology.py                     # zip from the cache (downloads it if missing)
  python -I scripts/screening_geology.py --igme-zip PATH     # use a copy of IGME5000.zip you already have
  python -I scripts/screening_geology.py --offline           # never use the network
  python -I scripts/screening_geology.py --crosscheck        # also ask Macrostrat at 20 points (1 s apart)

IGME5000.zip (47.5 MB) is kept outside the project, in the cache folder
(%LOCALAPPDATA%\\analog-atlas\\screening-cache, elsewhere ~/.cache/analog-atlas/screening).
Its sha256 must match IGME_SHA256 below, or the script stops. The shapefile is read
straight out of the zip; nothing is unpacked to disk.

Every run checks the projection against the worked example of EPSG Guidance Note 7-2,
checks the .prj against EPSG:3034, and checks the map unit at the 5 Jordan sites.
"""

import argparse
import collections
import datetime
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compute_terrain  # noqa: E402  (read-only: destination() and the Earth radius)
import shp_lite  # noqa: E402

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(ROOT, "data", "raw", "screening")
GRID_IN = os.path.join(SCREEN_DIR, "stages", "grid.json")
STAGE_OUT = os.path.join(SCREEN_DIR, "stages", "geology.json")
SAMPLES_OUT = os.path.join(SCREEN_DIR, "geology", "samples_jordan.json")
CROSSCHECK_FILE = os.path.join(SCREEN_DIR, "geology", "macrostrat_crosscheck.json")
ROCKMAP = os.path.join(ROOT, "data", "screening_rockmap_igme5000.json")
SCORING_JS = os.path.join(ROOT, "js", "scoring.js")
SITES_META = os.path.join(ROOT, "data", "sites_meta.json")
TARGETS = os.path.join(ROOT, "data", "targets.json")
SCRIPT = "scripts/screening_geology.py"
GRID_ID = "jordan-10km-v1"

IGME_URL = "https://download.bgr.de/bgr/Geologie/IGME5000/shp/IGME5000.zip"
IGME_ZIP_NAME = "IGME5000.zip"
IGME_SHA256 = "33e6f843c0c46bd3909fb2c978569513d47e051152cbeb8ae73d12d89ad8a97e"
IGME_BYTES = 47487638
IGME_LAYER = "europe/data/IGME5000_europeEPSG3034shp_geology_poly_v01"
IGME_DOI = "https://doi.org/10.25928/igme-5000"
IGME_METADATA = "https://metadata.europe-geology.eu/record/full/9FD6624C-0AA7-46D4-9DA3-955E558CD5F1"
GEONUTZV_URL = "https://sg.geodatenzentrum.de/web_public/gdz/lizenz/geonutzv.pdf"
IGME_CREDIT = ("IGME5000, © BGR, Hannover, 2005, https://doi.org/10.25928/igme-5000, "
               "modified: reclassified to Analog Atlas rock ids")
IGME_CITATION = ("Asch, K. (2005): The 1:5 Million International Geological Map of Europe and "
                 "Adjacent Areas (IGME5000). Bundesanstalt für Geowissenschaften und Rohstoffe (BGR), "
                 "Hannover. https://doi.org/10.25928/igme-5000")
USER_AGENT = "analog-atlas-screening/1.0 (NASA Space Apps 2026 project; Python urllib)"

RADIUS_M = compute_terrain.RADIUS_M["earth"]
COORD_DECIMALS = compute_terrain.COORD_DECIMALS
OFFSETS_KM = (-4, -2, 0, 2, 4)          # design 2.1: 5 x 5 points, 2 km apart
N_SAMPLES = len(OFFSETS_KM) ** 2
CENTRE_SAMPLE = N_SAMPLES // 2          # row-major index of the (0, 0) point
MIN_SECONDARY = 5                       # other units with >= 5 of 25 points add their primary
EXTENT_MARGIN_M = 1000.0
CERTAINTY_RANK = {"high": 2, "medium": 1, "low": 0}
NULL_UNITS = ("8500007", "600017")      # water; undifferentiated Neogene (design 2.1)
WATER_UNIT = "8500007"
PER_POLYGON_FIELDS = ("area_id", "Shape_STAr", "Shape_STLe", "MARIN")

# The map unit at each Jordan site's own point (data/sites_meta.json), as found by the geology
# scout and confirmed by Macrostrat's lookup of the same map. A change means the reader broke.
EXPECTED_SITE_UNITS = {"wadi-rum": "600023", "harrat": "601014", "waqf-as-suwwan": "601002",
                       "lisan-dead-sea": "601062", "qa-al-jafr": "600021"}

MACROSTRAT_URL = "https://macrostrat.org/api/v2/geologic_units/map?lat=%s&lng=%s"
MACROSTRAT_SOURCE_ID = 147              # Macrostrat's copy of IGME5000
MACROSTRAT_POINTS = 20
MACROSTRAT_SEED = 2026
MACROSTRAT_BBOX = (34.95, 29.18, 39.31, 33.38)   # the task's bounding box: w, s, e, n
MACROSTRAT_PAUSE_S = 1.0


def log(msg=""):
    print(msg, flush=True)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def default_cache_dir():
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "analog-atlas", "screening-cache")
    return os.path.join(os.path.expanduser("~"), ".cache", "analog-atlas", "screening")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# The IGME5000 zip: find it, check it, download it if needed
# --------------------------------------------------------------------------
def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, path):
    """Plain HTTPS GET into path (via a .part file), with a few slow retries."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = resp.read()
            with open(path + ".part", "wb") as f:
                f.write(body)
            os.replace(path + ".part", path)
            log("downloaded %s (%d bytes)" % (url, len(body)))
            return
        except Exception as err:  # network hiccups: wait and try again
            log("download attempt %d failed: %s" % (attempt + 1, err))
            time.sleep(5 * (attempt + 1))
    raise SystemExit("could not download " + url)


def locate_zip(args, network):
    """Return (path, how). Stops if the file is missing (offline) or its sha256 is wrong."""
    if args.igme_zip:
        path, how = args.igme_zip, "--igme-zip"
    else:
        path, how = os.path.join(args.cache_dir, IGME_ZIP_NAME), "cache"
        if not os.path.exists(path):
            if args.offline:
                raise SystemExit("%s is not in the cache and --offline is set" % IGME_ZIP_NAME)
            network.append(IGME_URL)
            download(IGME_URL, path)
            how = "downloaded"
    if not os.path.exists(path):
        raise SystemExit("not found: " + path)
    digest = sha256_file(path)
    if digest != IGME_SHA256:
        raise SystemExit("sha256 of %s is %s, expected %s. BGR may have released a new file; "
                         "check it (and the rock table) before changing IGME_SHA256."
                         % (path, digest, IGME_SHA256))
    return path, how


def read_layer(zpath):
    """The geology polygon layer straight out of the zip, with each member's size and sha256."""
    z = zipfile.ZipFile(zpath)
    layer, members = {}, {}
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        data = z.read(IGME_LAYER + ext)
        layer[ext] = data
        members[IGME_LAYER + ext] = {"bytes": len(data), "sha256": sha256_bytes(data)}
    encoding = layer[".cpg"].decode("ascii").strip()
    if encoding.upper() not in ("UTF-8", "UTF8"):
        raise SystemExit("unexpected DBF encoding in the .cpg: %r" % encoding)
    return layer, members


def check_prj(prj_text):
    """The .prj must describe EPSG:3034 (ETRS89 / LCC Europe) exactly."""
    got = shp_lite.parse_prj(prj_text)
    diffs = {k: got.get(k) for k, v in shp_lite.EPSG_3034.items() if got.get(k) != v}
    ok = got.get("projection") == "Lambert_Conformal_Conic" and got.get("unit") == "Meter" and not diffs
    return {"prj": prj_text.strip(), "parsed": got, "expected": "EPSG:3034 " + json.dumps(shp_lite.EPSG_3034),
            "differences": diffs, "ok": ok}


# --------------------------------------------------------------------------
# The rock table and the rock vocabulary
# --------------------------------------------------------------------------
def js_object(text, name):
    """{key: 'string value'} of `export const NAME = { ... };` in a JS file (keys may be quoted)."""
    m = re.search(r"export const %s = \{(.*?)\n\};" % re.escape(name), text, re.S)
    if not m:
        raise SystemExit("%s not found in %s" % (name, rel(SCORING_JS)))
    return dict(re.findall(r"^\s*'?([\w-]+)'?:\s*'([^']*)',?\s*$", m.group(1), re.M))


def load_vocabulary():
    with open(SCORING_JS, encoding="utf-8") as f:
        text = f.read()
    return js_object(text, "ROCK_LABEL"), js_object(text, "ROCK_FAMILY")


def check_rockmap(units, rock_label):
    """Problems in the curated table: unknown rock ids, bad certainty, missing reason, and the
    design rule that water and undifferentiated Neogene have no rock id."""
    problems = []
    for code, row in units.items():
        ids = ([row["primary"]] if row.get("primary") else []) + list(row.get("secondary", []))
        for rid in ids:
            if rid not in rock_label:
                problems.append("unit %s: rock id %r is not in ROCK_LABEL" % (code, rid))
        if row.get("primary") in row.get("secondary", []):
            problems.append("unit %s: primary repeated in secondary" % code)
        if len(set(row.get("secondary", []))) != len(row.get("secondary", [])):
            problems.append("unit %s: secondary has duplicates" % code)
        if row.get("certainty") not in CERTAINTY_RANK:
            problems.append("unit %s: certainty %r" % (code, row.get("certainty")))
        if not str(row.get("reason", "")).strip():
            problems.append("unit %s: no reason" % code)
        for key in ("petrography", "age", "region"):
            if key not in row:
                problems.append("unit %s: no %s" % (code, key))
    for code in NULL_UNITS:
        if code not in units or units[code]["primary"] is not None:
            problems.append("unit %s must be in the table with primary null" % code)
    return problems


# --------------------------------------------------------------------------
# Map units from the DBF
# --------------------------------------------------------------------------
def petrography(attrs):
    return [attrs[k] for k in ("Portr_Petr", "Portr_Pe_1", "Portr_Pe_2", "Portr_Pe_3") if attrs.get(k)]


def unit_tables(attrs):
    """(units, polygons, problems). units: {code: the unit's DBF fields, which must be the same
    in all its polygons}; polygons: {record: {GEO, MARIN, area_id}}."""
    units, polygons, problems = {}, {}, []
    for rec, a in sorted(attrs.items()):
        if a is None:
            problems.append("record %d is deleted in the DBF" % rec)
            continue
        code = str(a["GEO"])
        polygons[rec] = {"GEO": code, "MARIN": a.get("MARIN"), "area_id": a.get("area_id")}
        fields = {k: v for k, v in a.items() if k not in PER_POLYGON_FIELDS}
        if code not in units:
            units[code] = dict(fields, nPolygons=0)
        elif any(units[code][k] != v for k, v in fields.items()):
            problems.append("unit %s: polygons disagree on its attributes (record %d)" % (code, rec))
        units[code]["nPolygons"] += 1
    return units, polygons, problems


def rockmap_vs_map(rockmap, units, used):
    """Every unit the samples hit must be in the rock table, with the map's own words."""
    problems = []
    for code in sorted(used, key=int):
        row, a = rockmap.get(code), units[code]
        if row is None:
            problems.append("unit %s (%s; %s; %s) is not in %s: add a row"
                            % (code, ", ".join(petrography(a)), a["AgeName"], a["regName"], rel(ROCKMAP)))
            continue
        for key, value in (("petrography", petrography(a)), ("age", a["AgeName"]), ("region", a["regName"])):
            if row[key] != value:
                problems.append("unit %s: %s is %r in the rock table but %r in the map"
                                % (code, key, row[key], value))
    return problems


# --------------------------------------------------------------------------
# Sampling and lookup
# --------------------------------------------------------------------------
def sample_points(lat, lon):
    """The 5 x 5 points around a centre, row-major: row 0 is the southern row (-4 km), column 0
    the western column; placed like compute_terrain.build_grid() and rounded to 6 decimals."""
    pts = []
    for dn in OFFSETS_KM:
        for de in OFFSETS_KM:
            north, east = dn * 1000.0, de * 1000.0
            la, lo = compute_terrain.destination(lat, lon, math.atan2(east, north),
                                                 math.hypot(east, north), RADIUS_M)
            pts.append((round(la, COORD_DECIMALS), round(lo, COORD_DECIMALS)))
    return pts


def projected_extent(points, project):
    xs, ys = zip(*(project(lon, lat) for lat, lon in points))
    m = EXTENT_MARGIN_M
    return [min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m]


class Lookup:
    """Map unit at a point; counts points that fall in no polygon or in more than one."""

    def __init__(self, index, project, attrs):
        self.index, self.project, self.attrs = index, project, attrs
        self.n = self.missed = self.multi = 0

    def at(self, lat, lon):
        """(unit code, polygon record) or (None, None). Overlaps take the lowest record."""
        hits = self.index.find(*self.project(lon, lat))
        self.n += 1
        if not hits:
            self.missed += 1
            return None, None
        if len(hits) > 1:
            self.multi += 1
        return str(self.attrs[hits[0]]["GEO"]), hits[0]

    def sample(self, points):
        """([unit codes], [polygon records]) of a list of (lat, lon) points."""
        found = [self.at(lat, lon) for lat, lon in points]
        return [c for c, _ in found], [r for _, r in found]


# --------------------------------------------------------------------------
# One box: dominant unit -> rock ids
# --------------------------------------------------------------------------
def histogram(codes):
    """{code: count}, most frequent first, then by code."""
    cnt = collections.Counter(c for c in codes if c is not None)
    return {c: cnt[c] for c in sorted(cnt, key=lambda c: (-cnt[c], int(c)))}


def dominant(hist, rockmap):
    """Most frequent unit; ties go to the higher certainty, then to the lower unit code."""
    return min(hist, key=lambda c: (-hist[c], -CERTAINTY_RANK[rockmap[c]["certainty"]], int(c)))


def secondary_ids(unit, primary, hist, rockmap):
    """Rock table secondaries of the unit, plus the primary of every other unit with
    >= MIN_SECONDARY points whose certainty is not low; minus the primary."""
    if primary is None:
        return []
    ids = list(rockmap[unit]["secondary"])
    for code, n in hist.items():
        row = rockmap[code]
        if code != unit and n >= MIN_SECONDARY and row["certainty"] != "low" and row["primary"]:
            ids.append(row["primary"])
    out = []
    for rid in ids:
        if rid != primary and rid not in out:
            out.append(rid)
    return out


def why_no_rock(unit, row, inferred):
    """Short reason when a box has no primary rock (None when it has one)."""
    if unit is None:
        return "No IGME5000 polygon at these points"
    if unit == WATER_UNIT:
        return "Water on the map (Dead Sea or Gulf of Aqaba)"
    if row["certainty"] == "low" and inferred:
        return "Low-certainty map unit: %s is a guess, shown but not scored" % inferred
    if row["certainty"] == "low":
        return "The map gives only an age here, so no rock type"
    return "This map unit has no rock id: " + row["reason"]


def box_geology(codes, polys, rockmap):
    """The geology record of one box (design 2.1 and 2.3) from its 25 unit codes."""
    hist = histogram(codes)
    if not hist:
        return {"primary": None, "secondary": [], "unit": None, "share": 0, "certainty": None,
                "inferred": None, "units": {}, "centrePolygon": polys[CENTRE_SAMPLE],
                "why": why_no_rock(None, None, None), "flags": ["noGeology"]}
    unit = dominant(hist, rockmap)
    row = rockmap[unit]
    low = row["certainty"] == "low"
    primary = None if low else row["primary"]
    inferred = row["primary"] if low else None
    rec = {"primary": primary,
           "secondary": secondary_ids(unit, primary, hist, rockmap),
           "unit": unit,
           "share": round(hist[unit] / N_SAMPLES, 2),
           "certainty": row["certainty"],
           "inferred": inferred,
           "units": hist,
           "centrePolygon": polys[CENTRE_SAMPLE],
           "why": None if primary else why_no_rock(unit, row, inferred)}
    rec["flags"] = ["lowCertaintyGeology"] if low else (["noGeology"] if primary is None else [])
    return rec


# --------------------------------------------------------------------------
# Controls: the 5 Jordan sites
# --------------------------------------------------------------------------
def geology_match(site, target, family):
    """Score of js/scoring.js geologyMatch(), ported read-only for the validation printout."""
    if not site or not target or not site.get("primary") or not target.get("primary"):
        return None
    s_sec, t_sec = site.get("secondary") or [], target.get("secondary") or []
    if site["primary"] == target["primary"]:
        return 1.0
    if target["primary"] in s_sec or site["primary"] in t_sec:
        return 0.5
    fam = family.get(site["primary"])
    return 0.5 if fam and fam == family.get(target["primary"]) else 0.0


def point_record(code, rec, rockmap):
    if code is None:
        return {"unit": None, "polygon": None, "primary": None, "secondary": [], "certainty": None, "inferred": None}
    row = rockmap[code]
    low = row["certainty"] == "low"
    return {"unit": code, "polygon": rec, "primary": None if low else row["primary"],
            "secondary": [] if low or not row["primary"] else list(row["secondary"]),
            "certainty": row["certainty"], "inferred": row["primary"] if low else None}


def site_controls(grid, lookup, rockmap, targets, family):
    """Map unit at each Jordan site's point and in a 5 x 5 box centred on it, against the
    project's hand-assigned geology (data/sites_meta.json)."""
    meta = {s["id"]: s for s in load_json(SITES_META)["sites"]}
    out, samples = {}, {}
    for sid, c in grid["controls"].items():
        project_geo = {k: meta[sid]["geology"].get(k) for k in ("primary", "secondary")}
        code, rec = lookup.at(c["lat"], c["lon"])
        point = point_record(code, rec, rockmap)
        codes, polys = lookup.sample(sample_points(c["lat"], c["lon"]))
        mapped = point if point["primary"] else None
        changes = {}
        for t in targets:
            a = geology_match(project_geo, t.get("geology"), family)
            b = geology_match(mapped, t.get("geology"), family)
            if a != b:
                changes[t["id"]] = {"project": a, "map": b}
        out[sid] = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "source": c["source"], "box": c["box"],
                    "project": project_geo, "point": point, "sampled": box_geology(codes, polys, rockmap),
                    "expectedUnit": EXPECTED_SITE_UNITS.get(sid),
                    "unitOk": code == EXPECTED_SITE_UNITS.get(sid),
                    "samePrimary": point["primary"] == project_geo["primary"],
                    "geologyMatch": geology_match(mapped, project_geo, family),
                    "targetScoresThatChange": changes}
        samples[sid] = {"lat": c["lat"], "lon": c["lon"], "point": [code, rec], "units": codes, "polygons": polys}
    return out, samples


def same_unit_as(unit, controls):
    return [sid for sid, c in controls.items() if unit is not None and c["point"]["unit"] == unit]


# --------------------------------------------------------------------------
# Optional cross-check with Macrostrat (its source 147 is the same IGME5000 map)
# --------------------------------------------------------------------------
def crosscheck_points(ring):
    """20 seeded random points inside Jordan (seed 2026, the task's bounding box, 4 decimals)."""
    rnd = random.Random(MACROSTRAT_SEED)
    w, s, e, n = MACROSTRAT_BBOX
    pts = []
    while len(pts) < MACROSTRAT_POINTS:
        lon, lat = rnd.uniform(w, e), rnd.uniform(s, n)
        if shp_lite.point_in_rings(lon, lat, [ring]):
            pts.append((round(lat, 4), round(lon, 4)))
    return pts


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def macrostrat_words(lith):
    """Rock words of a Macrostrat 'lith' string such as 'Major:{marl}, Minor{sand,silt}'."""
    parts = re.findall(r"\{([^}]*)\}", lith or "") or [lith or ""]
    return [w.strip().lower() for p in parts for w in p.split(",") if w.strip()]


def age_words(text):
    text = (text or "").lower().replace("palaeo", "paleo")
    return set(w for w in re.findall(r"[a-z]+|[ivx]+", text) if w != "undifferentiated")


def compare_macrostrat(unit, m):
    """Same first rock word (or both without one) and the same age words."""
    ours = [p.lower() for p in petrography(unit) if p != "undifferentiated"]
    theirs = macrostrat_words(m.get("lith"))
    lith_ok = (ours[:1] == theirs[:1]) or (not ours and not theirs)
    their_age = age_words("%s %s" % (m.get("b_int_name") or "", m.get("t_int_name") or ""))
    age_ok = age_words(unit["AgeName"]) == their_age
    return lith_ok and age_ok, lith_ok, age_ok


CROSSCHECK_ABOUT = ("Cross-check of our IGME5000 point lookup against Macrostrat's lookup of the same map "
                    "(Macrostrat source_id 147 = IGME5000) at 20 seeded random points inside Jordan. "
                    "Agreement = same first rock word (or neither has one) and the same age words.")


def run_crosscheck(points, lookup, units, fetch, offline, network):
    """Compare our unit with Macrostrat's at each point. Stored answers are reused; new ones are
    fetched only when fetch is True (1 s apart). Returns the file content or None."""
    stored = load_json(CROSSCHECK_FILE) if os.path.exists(CROSSCHECK_FILE) else None
    answers = {a["url"]: a for a in (stored or {}).get("answers", [])}
    urls = [MACROSTRAT_URL % (lat, lon) for lat, lon in points]
    missing = [u for u in urls if u not in answers]
    if missing and not (fetch and not offline):
        if stored is None:
            return None
        log("crosscheck: %d of %d stored answers missing; run with --crosscheck to fetch them"
            % (len(missing), len(urls)))
        return {"about": CROSSCHECK_ABOUT, "agree": None, "n": len(urls), "missing": len(missing),
                "ok": False, "current": False}
    for k, url in enumerate(missing):
        if k:
            time.sleep(MACROSTRAT_PAUSE_S)
        network.append(url)
        answers[url] = {"url": url, "fetched": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "response": fetch_json(url)}
    rows, agree = [], 0
    for (lat, lon), url in zip(points, urls):
        code, rec = lookup.at(lat, lon)
        data = answers[url]["response"].get("success", {}).get("data", [])
        m = next((d for d in data if d.get("source_id") == MACROSTRAT_SOURCE_ID), None)
        ok = lith_ok = age_ok = False
        if code is not None and m is not None:
            ok, lith_ok, age_ok = compare_macrostrat(units[code], m)
        agree += ok
        rows.append({"lat": lat, "lon": lon, "unit": code, "polygon": rec,
                     "ours": code and {"petrography": petrography(units[code]), "age": units[code]["AgeName"],
                                       "region": units[code]["regName"]},
                     "macrostrat": m and {k: m.get(k) for k in ("map_id", "name", "lith", "b_int_name", "t_int_name")},
                     "lithOk": lith_ok, "ageOk": age_ok, "agree": ok})
    fetched = sorted(a["fetched"] for a in answers.values() if a["url"] in urls)
    return {"about": CROSSCHECK_ABOUT,
            "url": "https://macrostrat.org/api/v2/geologic_units/map",
            "licence": "CC-BY 4.0", "licenceUrl": "https://creativecommons.org/licenses/by/4.0/",
            "credit": "Macrostrat (https://macrostrat.org), data CC-BY 4.0",
            "points": {"n": MACROSTRAT_POINTS, "seed": MACROSTRAT_SEED, "bbox": list(MACROSTRAT_BBOX),
                       "rule": "random.Random(2026): lon, lat uniform in the bbox, kept when inside the "
                               "Natural Earth Jordan ring, rounded to 4 decimals"},
            "fetched": [fetched[0], fetched[-1]] if fetched else [],
            "agree": agree, "n": len(rows), "ok": agree == len(rows), "current": True,
            "results": rows,
            "answers": [answers[u] for u in urls]}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "), allow_nan=False)


def dumps_rows(obj, row_keys):
    """Pretty JSON (indent 1) where the entries of the listed top-level keys sit one per line."""
    lines = ["{"]
    items = list(obj.items())
    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if key in row_keys and isinstance(value, dict) and value:
            rows = ["  %s: %s" % (json.dumps(k, ensure_ascii=False), compact(v)) for k, v in value.items()]
            lines.append(" %s: {\n%s\n }%s" % (json.dumps(key), ",\n".join(rows), comma))
        elif key in row_keys and isinstance(value, list) and value:
            rows = ["  " + compact(v) for v in value]
            lines.append(" %s: [\n%s\n ]%s" % (json.dumps(key), ",\n".join(rows), comma))
        else:
            text = json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False).replace("\n", "\n ")
            lines.append(" %s: %s%s" % (json.dumps(key), text, comma))
    lines.append("}")
    text = "\n".join(lines) + "\n"
    if json.loads(text) != obj:
        raise SystemExit("internal error: JSON writer changed the data")
    return text


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".tmp", path)
    log("wrote %s (%d bytes)" % (rel(path), os.path.getsize(path)))
    return sha256_bytes(text.encode("utf-8"))


def igme_source(accessed):
    return {"id": "igme5000",
            "label": "IGME5000: The 1:5 Million International Geological Map of Europe and Adjacent Areas "
                     "(BGR), geology polygons",
            "url": IGME_URL,
            "licence": "GeoNutzV (German federal licence for geodata): any use, with source notes and a "
                       "note of modification",
            "licenceUrl": GEONUTZV_URL,
            "credit": IGME_CREDIT,
            "notice": IGME_CREDIT,
            "version": "1st edition 2005; shapefile release v01 (layer %s)" % IGME_LAYER.rsplit("/", 1)[1],
            "accessed": accessed,
            "sha256": IGME_SHA256,
            "doi": IGME_DOI,
            "metadataUrl": IGME_METADATA}


def macrostrat_source(cc):
    return {"id": "macrostrat-crosscheck",
            "label": "Macrostrat API v2, geologic_units/map (source 147 = IGME5000); used only to "
                     "cross-check the point lookup",
            "url": cc["url"], "licence": cc["licence"], "licenceUrl": cc["licenceUrl"],
            "credit": cc["credit"], "notice": cc["credit"], "version": "API v2",
            "accessed": cc["fetched"][-1][:10] if cc["fetched"] else None,
            "sha256": None, "file": rel(CROSSCHECK_FILE)}


def method_text():
    return {
        "citation": IGME_CITATION,
        "doi": IGME_DOI,
        "credit": IGME_CREDIT,
        "scale": "1:5,000,000 (features smaller than a few km are not shown)",
        "sampling": ("5 x 5 points per box at -4, -2, 0, +2 and +4 km north and east of the box centre, placed "
                     "with compute_terrain.destination() on a sphere of R = 6,371,008.8 m and rounded to 6 "
                     "decimals; each point takes the unit of the IGME5000 polygon that holds it"),
        "projection": ("longitude/latitude -> EPSG:3034 (ETRS89 / LCC Europe, Lambert Conic Conformal 2SP, "
                       "GRS80) with the formulas of EPSG Guidance Note 7-2, checked on its worked example; "
                       "WGS84 and ETRS89 are treated as the same (they differ by about 1 m)"),
        "dominant": "the most frequent unit of the 25 points; ties go to the higher certainty, then the lower unit code",
        "primaryRule": ("primary = the rock table's primary for the box's unit when its certainty is high or "
                        "medium; for a low-certainty unit primary is null and the guess is kept as 'inferred' "
                        "(display only)"),
        "secondaryRule": ("secondary = the rock table's secondaries of the box's unit, plus the primary of every "
                          "other unit with at least 5 of the 25 points and certainty not low, minus the primary; "
                          "empty when there is no primary"),
        "nullRule": "water (8500007) and undifferentiated Neogene (600017) have no rock id",
        "share": "points in the box's unit / 25",
        "centrePolygon": "0-based record number (shapefile and DBF) of the polygon at the box centre",
        "flags": "lowCertaintyGeology: the box's unit has low certainty; noGeology: no primary for another reason (water)",
        "sameUnitAs": "Jordan sites whose own point (data/sites_meta.json) lies in the box's unit",
        "rockTable": rel(ROCKMAP),
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def describe(code, units):
    if code is None:
        return "no polygon"
    u = units[code]
    words = ", ".join(petrography(u)) or u.get("genElement") or "no rock named"
    return "%s (%s; %s)" % (code, words, u["AgeName"])


def print_controls(controls, units):
    log("5-site validation (map unit at each site's point, against data/sites_meta.json):")
    for sid, c in controls.items():
        p, s = c["point"], c["sampled"]
        rock = p["primary"] or ("(%s, low certainty)" % p["inferred"] if p["inferred"] else "none")
        sec = ("+" + "+".join(p["secondary"])) if p["secondary"] else ""
        proj = c["project"]["primary"] + (("+" + "+".join(c["project"]["secondary"])) if c["project"]["secondary"] else "")
        log("  %-15s %s %s -> %s%s [%s] | project %s | %s, geologyMatch %s | 5x5 here: %s %d/25 -> %s | box %s"
            % (sid, "OK  " if c["unitOk"] else "FAIL", describe(p["unit"], units), rock, sec, p["certainty"],
               proj, "same main rock" if c["samePrimary"] else "different main rock", c["geologyMatch"],
               s["unit"], round(s["share"] * N_SAMPLES), s["primary"] or s["inferred"] or "none", c["box"]))
    for sid, c in controls.items():
        for tid, v in c["targetScoresThatChange"].items():
            log("  geology score %-15s vs %-13s project rock %s -> map rock %s" % (sid, tid, v["project"], v["map"]))


def count_by(values):
    cnt = collections.Counter("null" if v is None else v for v in values)
    return dict(cnt.most_common())


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--igme-zip", help="path of %s (checked against its sha256)" % IGME_ZIP_NAME)
    parser.add_argument("--cache-dir", default=default_cache_dir(), help="folder for big downloads")
    parser.add_argument("--offline", action="store_true", help="never use the network")
    parser.add_argument("--crosscheck", action="store_true",
                        help="fetch Macrostrat answers that are not stored yet (20 points, 1 s apart)")
    return parser.parse_args(argv)


def run_selftest():
    st = shp_lite.lcc_selftest()
    log("projection self-test (EPSG GN 7-2, LCC 2SP): E %.4f N %.4f ftUS, expected %.2f %.2f "
        "(diff %+.4f %+.4f ft); n %.8f, F %.8f, rF %.4f -> %s"
        % (st["got"]["E"], st["got"]["N"], st["expected"]["E"], st["expected"]["N"], st["diff"]["E"],
           st["diff"]["N"], st["got"]["n"], st["got"]["F"], st["got"]["rF"], "OK" if st["ok"] else "FAILED"))
    if not st["ok"]:
        raise SystemExit("projection self-test failed: %s" % st)
    return st


def load_inputs():
    """The grid stage, the rock vocabulary, the checked rock table and the targets."""
    grid = load_json(GRID_IN)
    if grid.get("stage") != "grid" or grid.get("grid") != GRID_ID:
        raise SystemExit("%s is not the %s grid stage" % (rel(GRID_IN), GRID_ID))
    rock_label, family = load_vocabulary()
    rockmap = load_json(ROCKMAP)["units"]
    problems = check_rockmap(rockmap, rock_label)
    if problems:
        raise SystemExit("rock table problems:\n  " + "\n  ".join(problems))
    return grid, rockmap, family, load_json(TARGETS)["targets"]


def open_map(args, network):
    """The checked zip, its geology layer, and the projection named by the .prj."""
    zpath, how = locate_zip(args, network)
    layer, members = read_layer(zpath)
    prj = check_prj(layer[".prj"].decode("ascii"))
    if not prj["ok"]:
        raise SystemExit("the .prj is not EPSG:3034: %s" % prj["differences"])
    header = shp_lite.read_shp_header(layer[".shp"])
    log("IGME5000 (%s, sha256 %s...): %d records, shape type %d, .prj = EPSG:3034 OK"
        % (how, IGME_SHA256[:12], shp_lite.dbf_count(layer[".dbf"]), header["shapeType"]))
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(zpath), datetime.timezone.utc)
    return {"path": zpath, "bytes": os.path.getsize(zpath), "accessed": mtime.strftime("%Y-%m-%d"),
            "layer": layer, "members": members, "prj": prj,
            "project": shp_lite.lcc_from_params(shp_lite.EPSG_3034)}


def make_lookup(igme, points):
    """Polygons whose bounding box meets the points' extent, their units, and a Lookup."""
    extent = projected_extent(points, igme["project"])
    polygons = list(shp_lite.iter_polygons(igme["layer"][".shp"], extent))
    attrs = shp_lite.read_dbf_rows(igme["layer"][".dbf"], [i for i, _, _ in polygons])
    units, poly_table, problems = unit_tables(attrs)
    if problems:
        raise SystemExit("map problems:\n  " + "\n  ".join(problems))
    return Lookup(shp_lite.PolygonIndex(polygons), igme["project"], attrs), units, poly_table, len(polygons)


def box_counts(boxes, samples, rockmap, n_points, n_polygons):
    recs = list(boxes.values())
    codes = [c for cs, _ in samples.values() for c in cs]
    return {"boxes": len(recs), "points": n_points,
            "primary": count_by(r["primary"] for r in recs),
            "certainty": count_by(r["certainty"] for r in recs),
            "inferred": count_by(r["inferred"] for r in recs if r["certainty"] == "low"),
            "flags": count_by(f for r in recs for f in r["flags"]),
            "unitOfBox": count_by(r["unit"] for r in recs),
            "pointsPerUnit": count_by(codes),
            "wholeBoxOneUnit": sum(1 for r in recs if r["share"] == 1),
            "tieBroken": sum(1 for r in recs if list(r["units"].values()).count(r["units"].get(r["unit"])) > 1),
            "secondaryAddedByPointRule": sum(1 for r in recs if r["primary"]
                                             and set(r["secondary"]) - set(rockmap[r["unit"]]["secondary"])),
            "sameUnitAsSite": count_by(s for r in recs for s in r["sameUnitAs"]),
            "polygonsInExtent": n_polygons,
            "polygonsHit": len({p for _, ps in samples.values() for p in ps}),
            "unitsHit": len(set(codes))}


def stage_checks(selftest, prj, lookup, rockmap, used, controls, grid, boxes, cc):
    checks = {
        "projection": selftest,
        "prj": {k: prj[k] for k in ("expected", "differences", "ok")},
        "everyPointInOnePolygon": {"rule": "every looked-up point lies in exactly one IGME5000 polygon",
                                   "points": lookup.n, "outside": lookup.missed, "inMoreThanOne": lookup.multi,
                                   "ok": lookup.missed == 0 and lookup.multi == 0},
        "rockTable": {"rule": "every rock id is in ROCK_LABEL (js/scoring.js); every unit hit is in the table with "
                              "the map's own petrography, age and region; 8500007 and 600017 have no rock id",
                      "unitsInTable": len(rockmap), "unitsHit": len(used),
                      "unusedRows": sorted(set(rockmap) - used, key=int), "ok": True},
        "sites": {"rule": "the map unit at each Jordan site's point is the one the scout and Macrostrat found",
                  "expected": EXPECTED_SITE_UNITS,
                  "found": {sid: c["point"]["unit"] for sid, c in controls.items()},
                  "samePrimary": "%d of %d" % (sum(1 for c in controls.values() if c["samePrimary"]), len(controls)),
                  "ok": all(c["unitOk"] for c in controls.values())},
        "boxCount": {"rule": "one record per grid box", "grid": len(grid["boxes"]), "geology": len(boxes),
                     "ok": sorted(grid["boxes"]) == sorted(boxes)},
    }
    if cc:
        checks["macrostrat"] = {"rule": cc["about"], "agree": cc["agree"], "n": cc["n"],
                                "current": cc["current"], "ok": cc["ok"] or not cc["current"]}
    return checks


def samples_document(igme, units_raw, counts, used, poly_table, samples, control_samples):
    """The raw samples file. It holds no run time, so the same inputs always give the same bytes
    (and the same sha256 in the stage and the app file)."""
    referenced = {p for _, ps in samples.values() for p in ps}
    referenced |= {p for s in control_samples.values() for p in s["polygons"] + [s["point"][1]]}
    return {
        "about": ("The IGME5000 unit code (GEO) and polygon record number (0-based, the same in the .shp and "
                  "the .dbf) at each of the 25 points of every box, row-major: row 0 = the southern row "
                  "(-4 km), column 0 = the western column (-4 km). 'units' holds each unit's own fields "
                  "from the DBF. Written by %s." % SCRIPT),
        "script": SCRIPT, "grid": GRID_ID,
        "source": {"zip": {"name": IGME_ZIP_NAME, "url": IGME_URL, "bytes": igme["bytes"],
                           "sha256": IGME_SHA256, "members": igme["members"]},
                   "layer": IGME_LAYER, "crs": igme["prj"]["prj"], "credit": IGME_CREDIT, "doi": IGME_DOI},
        "sampling": {"offsetsKm": list(OFFSETS_KM), "order": "row-major, row 0 south, column 0 west",
                     "centreIndex": CENTRE_SAMPLE, "method": method_text()["sampling"]},
        "units": {c: dict(units_raw[c], nPoints=counts["pointsPerUnit"].get(c, 0)) for c in sorted(used, key=int)},
        "polygons": {str(k): poly_table[k] for k in sorted(p for p in referenced if p is not None)},
        "boxes": {bid: {"units": codes, "polygons": polys} for bid, (codes, polys) in samples.items()},
        "controls": control_samples,
    }


def stage_document(generated, igme, network, cc, files, counts, checks, rockmap, used, boxes, controls):
    return {
        "stage": "geology", "generated": generated, "script": SCRIPT, "grid": GRID_ID,
        "sources": [igme_source(igme["accessed"])] + ([macrostrat_source(cc)] if cc and cc["current"] else []),
        "network": network,
        "method": method_text(),
        "files": files,
        "counts": counts,
        "checks": checks,
        "units": {c: {k: rockmap[c][k] for k in ("petrography", "age", "region", "primary", "secondary",
                                                 "certainty", "reason")} for c in sorted(used, key=int)},
        "boxes": boxes,
        "controls": controls,
    }


def print_summary(counts, controls, units_raw, cc):
    log("main rock of the boxes: %s" % counts["primary"])
    log("certainty of the box's unit: %s" % counts["certainty"])
    log("flags: %s; whole box in one unit: %d; ties broken: %d; secondary added by the 5-of-25 rule: %d"
        % (counts["flags"], counts["wholeBoxOneUnit"], counts["tieBroken"], counts["secondaryAddedByPointRule"]))
    log("low-certainty boxes (primary null, guess kept as 'inferred'): %s" % counts["inferred"])
    log("boxes in the same unit as a site's point: %s" % counts["sameUnitAsSite"])
    print_controls(controls, units_raw)
    if cc and cc["current"]:
        log("Macrostrat cross-check: %d of %d points agree" % (cc["agree"], cc["n"]))
    elif cc:
        log("Macrostrat cross-check: not run (%d of %d stored answers missing)" % (cc["missing"], cc["n"]))


def main(argv=None):
    args = parse_args(argv)
    t0 = time.time()
    network = []
    selftest = run_selftest()
    grid, rockmap, family, targets = load_inputs()
    igme = open_map(args, network)

    # every point to look up: 25 per box, the 5 sites (point and 25), the cross-check points
    box_points = {bid: sample_points(b["lat"], b["lon"]) for bid, b in grid["boxes"].items()}
    use_cc = args.crosscheck or os.path.exists(CROSSCHECK_FILE)
    ring = load_json(os.path.join(ROOT, grid["boundary"]["file"]))["ring"]
    cc_points = crosscheck_points(ring) if use_cc else []
    site_points = [p for c in grid["controls"].values()
                   for p in [(c["lat"], c["lon"])] + sample_points(c["lat"], c["lon"])]
    all_points = [p for pts in box_points.values() for p in pts] + site_points + cc_points
    lookup, units_raw, poly_table, n_polygons = make_lookup(igme, all_points)
    log("%d polygons (%d units) meet the extent of the points; %.1f s"
        % (n_polygons, len(units_raw), time.time() - t0))

    samples = {bid: lookup.sample(pts) for bid, pts in box_points.items()}
    n_points = lookup.n
    controls, control_samples = site_controls(grid, lookup, rockmap, targets, family)
    used = {c for codes, _ in samples.values() for c in codes if c is not None}
    used |= {c for s in control_samples.values() for c in s["units"] + [s["point"][0]] if c is not None}
    problems = rockmap_vs_map(rockmap, units_raw, used)
    if problems:
        raise SystemExit("rock table does not cover the map:\n  " + "\n  ".join(problems))
    boxes = {}
    for bid, (codes, polys) in samples.items():
        rec = box_geology(codes, polys, rockmap)
        rec["sameUnitAs"] = same_unit_as(rec["unit"], controls)
        boxes[bid] = dict({"id": bid}, **rec)
    log("sampled %d boxes x %d points = %d points; outside every polygon: %d; in more than one: %d; %.1f s"
        % (len(boxes), N_SAMPLES, n_points, lookup.missed, lookup.multi, time.time() - t0))
    cc = run_crosscheck(cc_points, lookup, units_raw, args.crosscheck, args.offline, network) if cc_points else None

    counts = box_counts(boxes, samples, rockmap, n_points, n_polygons)
    checks = stage_checks(selftest, igme["prj"], lookup, rockmap, used, controls, grid, boxes, cc)
    if cc and cc["current"] and args.crosscheck:
        write_text(CROSSCHECK_FILE, dumps_rows(cc, ("results", "answers")))
    generated = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    samples_sha = write_text(SAMPLES_OUT, dumps_rows(
        samples_document(igme, units_raw, counts, used, poly_table, samples, control_samples),
        ("units", "polygons", "boxes", "controls")))
    with open(ROCKMAP, "rb") as f:
        rockmap_sha = sha256_bytes(f.read())
    files = {"rockTable": {"file": rel(ROCKMAP), "sha256": rockmap_sha},
             "samples": {"file": rel(SAMPLES_OUT), "sha256": samples_sha},
             "crosscheck": {"file": rel(CROSSCHECK_FILE)} if cc and cc["current"] else None,
             "gridStage": {"file": rel(GRID_IN), "generated": grid["generated"]}}
    write_text(STAGE_OUT, dumps_rows(
        stage_document(generated, igme, network, cc, files, counts, checks, rockmap, used, boxes, controls),
        ("units", "boxes", "controls")))

    print_summary(counts, controls, units_raw, cc)
    log("network: %s; %.1f s" % (network or "none", time.time() - t0))
    failed = [k for k, v in checks.items() if not v["ok"]]
    if failed:
        log("CHECK FAILED: " + ", ".join(failed))
        return 1
    log("checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
