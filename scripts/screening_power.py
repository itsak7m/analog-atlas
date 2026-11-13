#!/usr/bin/env python3
"""Jordan screening layer, stage 2: climate from NASA POWER (regional climatology).

Every 10 km box of data/raw/screening/stages/grid.json gets the POWER cells that hold its
centre, with the rule NASA's point API itself uses, so a box is scored exactly like a
hand-picked site:
  MERRA-2 (11 weather parameters, 0.5 x 0.625 deg)  lat_c = round(lat / 0.5) * 0.5
                                                    lon_c = -180 + round((lon + 180) / 0.625) * 0.625
  CERES SYN1deg (3 solar parameters, 1 x 1 deg)     lat_c = floor(lat) + 0.5, lon_c = floor(lon) + 0.5

Downloads (17 requests, one parameter each, one at a time with 3 s pauses), saved unchanged:
  data/raw/screening/power/merra/<P>.json    14 parameters, box 28.9-33.6 N, 34.9-39.4 E
  data/raw/screening/power/syn1deg/<P>.json  3 solar parameters, box 28.9-33.6 N, 34.4-39.6 E
  data/raw/screening/power/manifest.json     URL, bytes, sha256, UTC time, API version, period label
Writes data/raw/screening/stages/power.json (cells, the cells of every box, checks).

Hard check: the cells of the 5 Jordan sites and Amman must equal the project's own point files
data/raw/power/<id>.json (1,092 of 1,092 values and 6 of 6 grid elevations), or the script stops.

Python 3.12 standard library only. Run from any folder:

  python -I scripts/screening_power.py                    # use the project copies, download what is missing
  python -I scripts/screening_power.py --power-dir DIR    # reuse earlier answers kept with a manifest.json
  python -I scripts/screening_power.py --refresh          # download all 17 answers again
  python -I scripts/screening_power.py --offline          # never use the network
"""

import argparse
import datetime
import json
import math
import os
import statistics
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screening_grid as sg  # noqa: E402  (grid helpers, read-only use)

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------
ROOT = sg.ROOT
POWER_DIR = os.path.join(sg.SCREEN_DIR, "power")
MANIFEST = os.path.join(POWER_DIR, "manifest.json")
STAGE_OUT = os.path.join(sg.SCREEN_DIR, "stages", "power.json")
POINT_DIR = os.path.join(ROOT, "data", "raw", "power")
SITES_JSON = os.path.join(ROOT, "data", "sites.json")
SCRIPT = "scripts/screening_power.py"

ENDPOINT = "https://power.larc.nasa.gov/api/temporal/climatology/regional"
REFERENCING_URL = "https://power.larc.nasa.gov/docs/referencing/"
POLICY_URL = "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-information-policy"
CITATION = ("The data was obtained from National Aeronautics and Space Administration (NASA) Langley "
            "Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded through "
            "the NASA Earth Science Division.")
NOTIFY = "larc-power-project@mail.nasa.gov"
COMMUNITY = "RE"
FILL_VALUE = -999.0

# The 14 parameters of scripts/fetch_power.py, in the same order.
PARAMETERS = [
    "T2M", "T2M_MAX", "T2M_MIN", "T2M_RANGE", "RH2M", "PRECTOTCORR",
    "ALLSKY_SFC_UV_INDEX", "ALLSKY_SFC_SW_DWN", "WS2M", "PS",
    "TS", "TS_MAX", "TS_MIN", "ALLSKY_SRF_ALB",
]
SOLAR = ["ALLSKY_SRF_ALB", "ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_UV_INDEX"]      # CERES SYN1deg, 1 x 1 deg
WEATHER = [p for p in PARAMETERS if p not in SOLAR]                          # MERRA-2, 0.5 x 0.625 deg
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ANN"]

# Request boxes. POWER returns the cells whose CENTRE is inside the box, so both boxes reach past
# Jordan to include edge cells that overlap it; the solar box is wider for the 34-35 E and 39-40 E columns.
GROUPS = {
    "merra": {"box": (28.9, 33.6, 34.9, 39.4), "params": PARAMETERS},
    "syn1deg": {"box": (28.9, 33.6, 34.4, 39.6), "params": SOLAR},
}
REQUEST_PAUSE_S = 3.0

MERRA_DLAT, MERRA_DLON = 0.5, 0.625
SYN_STEP = 1.0
SHARE_STEP_DEG = 0.01           # sampling step of a cell's share inside Jordan
MOSTLY_OUTSIDE = 0.5            # a cell with less than half of its area in Jordan
CLIMATE_SOURCE_ID = "nasa-power-climatology-regional"


def log(msg):
    print(msg, flush=True)


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def iso_utc(text):
    """'2026-10-10T10:32:52+00:00' or '...Z' -> '2026-10-10T10:32:52Z'."""
    t = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Downloads and reuse
# --------------------------------------------------------------------------
def request_url(group, param):
    s, n, w, e = GROUPS[group]["box"]
    return ("%s?latitude-min=%s&latitude-max=%s&longitude-min=%s&longitude-max=%s"
            "&parameters=%s&community=%s&format=JSON" % (ENDPOINT, s, n, w, e, param, COMMUNITY))


def raw_path(group, param):
    return os.path.join(POWER_DIR, group, param + ".json")


def reuse_index(folder):
    """URL -> (file, earlier manifest record) for every manifest.json under `folder`.
    Reads both this script's manifest and the scouts' (one manifest per folder of <PARAM>.json)."""
    index = {}
    if not folder:
        return index
    for here, _dirs, files in os.walk(folder):
        if "manifest.json" not in files:
            continue
        try:
            records = load_json(os.path.join(here, "manifest.json")).get("requests", [])
        except (OSError, ValueError, AttributeError):
            continue
        for r in records:
            if isinstance(r, dict) and r.get("url") and r.get("sha256"):
                name = r.get("file") or r.get("parameter", "") + ".json"
                index[r["url"]] = (os.path.join(here, name), r)
    return index


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": sg.USER_AGENT, "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.status, resp.read()
        except Exception as err:  # network hiccups: wait and try again
            log("  attempt %d failed: %s" % (attempt + 1, err))
            time.sleep(5 * (attempt + 1))
    raise SystemExit("could not download " + url)


def check_answer(body, param):
    """The answer must be a POWER FeatureCollection for `param`; returns the parsed JSON."""
    data = json.loads(body)
    if not isinstance(data, dict) or not data.get("features"):
        raise SystemExit("POWER answer for %s has no features: %r" % (param, body[:300]))
    if param not in data["features"][0]["properties"]["parameter"]:
        raise SystemExit("POWER answer does not hold %s" % param)
    return data


def manifest_record(group, param, url, status, fetched, body):
    data = check_answer(body, param)
    header = data.get("header", {})
    return {
        "group": group, "parameter": param, "file": "%s/%s.json" % (group, param), "url": url,
        "httpStatus": status, "fetched": fetched, "bytes": len(body), "sha256": sg.sha256_bytes(body),
        "features": len(data["features"]),
        "apiVersion": header.get("api", {}).get("version"),
        "headerSources": header.get("sources"),
        "headerStart": header.get("start"), "headerEnd": header.get("end"),
        "rangeLabel": " ".join(data.get("messages") or []),
    }


def write_bytes(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "wb") as f:
        f.write(body)
    os.replace(path + ".tmp", path)


def acquire(group, param, args, previous, reuse, network, pacer):
    """Return (manifest record, how). Order: the project copy (sha256 = its manifest), an earlier
    answer under --power-dir (sha256 = its manifest, same URL), else a new download."""
    url = request_url(group, param)
    path = raw_path(group, param)
    if not args.refresh:
        prev = previous.get(url)
        if prev and os.path.exists(path) and sg.sha256_file(path) == prev["sha256"]:
            return prev, "project copy"
        if url in reuse:
            src, rec = reuse[url]
            if os.path.exists(src) and sg.sha256_file(src) == rec["sha256"]:
                with open(src, "rb") as f:
                    body = f.read()
                write_bytes(path, body)
                fetched = iso_utc(rec.get("fetched") or rec.get("fetched_utc"))
                status = rec.get("httpStatus", rec.get("http_status"))
                return manifest_record(group, param, url, status, fetched, body), "reused (sha256 matches)"
    if args.offline:
        raise SystemExit("%s/%s.json is missing or changed and --offline is set" % (group, param))
    pacer()
    network.append(url)
    status, body = http_get(url)
    record = manifest_record(group, param, url, status, sg.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"), body)
    write_bytes(path, body)
    return record, "downloaded"


def make_pacer():
    """Sequential requests with a pause between them (none before the first)."""
    last = [None]

    def pace():
        if last[0] is not None:
            time.sleep(max(0.0, last[0] + REQUEST_PAUSE_S - time.time()))
        last[0] = time.time()
    return pace


def acquire_all(args):
    previous = {}
    if os.path.exists(MANIFEST):
        previous = {r["url"]: r for r in load_json(MANIFEST).get("requests", [])}
    reuse = reuse_index(args.power_dir)
    network, records, pacer = [], [], make_pacer()
    for group, g in GROUPS.items():
        for param in g["params"]:
            rec, how = acquire(group, param, args, previous, reuse, network, pacer)
            log("%-8s %-20s %s (%d bytes, %d cells, fetched %s)"
                % (group, param, how, rec["bytes"], rec["features"], rec["fetched"]))
            records.append(rec)
    return records, network


def write_manifest(records):
    manifest = {
        "about": ("NASA POWER regional climatology answers for the Jordan screening layer, saved unchanged. "
                  "One request per parameter (the API allows one), sent one at a time. Written by "
                  "scripts/screening_power.py; 'fetched' is the UTC time of the download."),
        "endpoint": ENDPOINT,
        "community": COMMUNITY,
        "groups": {
            name: {"folder": name, "box": dict(zip(("latitude-min", "latitude-max", "longitude-min",
                                                     "longitude-max"), g["box"])),
                   "parameters": g["params"]}
            for name, g in GROUPS.items()},
        "requests": records,
    }
    sg.write_text(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return sg.sha256_file(MANIFEST)


# --------------------------------------------------------------------------
# Cells
# --------------------------------------------------------------------------
def merra_centre(lat, lon):
    return (round(lat / MERRA_DLAT) * MERRA_DLAT, -180 + round((lon + 180) / MERRA_DLON) * MERRA_DLON)


def syn_centre(lat, lon):
    return (math.floor(lat) + 0.5, math.floor(lon) + 0.5)


def cell_key(grid, lat, lon):
    return "%s%r_%r" % ("m" if grid == "merra" else "s", float(lat), float(lon))


def cell_bounds(grid, lat, lon):
    """(s, n, w, e) of a cell from its centre."""
    hy, hx = (MERRA_DLAT / 2, MERRA_DLON / 2) if grid == "merra" else (SYN_STEP / 2, SYN_STEP / 2)
    return lat - hy, lat + hy, lon - hx, lon + hx


def on_edge(lat, lon):
    """Grids for which the point lies exactly on a cell edge (the rule would then be a tie)."""
    out = []
    if (lat / MERRA_DLAT) % 1 == 0.5 or ((lon + 180) / MERRA_DLON) % 1 == 0.5:
        out.append("merra")
    if lat % 1 == 0 or lon % 1 == 0:
        out.append("syn")
    return out


def crosses_edge(lo, hi, origin, step):
    """Is there a cell edge (origin + k * step) strictly between lo and hi?"""
    k = math.floor((lo - origin) / step) + 1
    return origin + k * step < hi


def straddles(box):
    out = []
    if (crosses_edge(box["s"], box["n"], MERRA_DLAT / 2, MERRA_DLAT)
            or crosses_edge(box["w"], box["e"], -180 + MERRA_DLON / 2, MERRA_DLON)):
        out.append("merra")
    if crosses_edge(box["s"], box["n"], 0.0, SYN_STEP) or crosses_edge(box["w"], box["e"], 0.0, SYN_STEP):
        out.append("syn")
    return out


def cell_share(ring, s, n, w, e):
    """Share of a cell inside Jordan: the cell is cut into about 0.01 x 0.01 deg parts and the centre
    of each part is tested against the polygon (even-odd ray casting)."""
    n_lat = max(1, round((n - s) / SHARE_STEP_DEG))
    n_lon = max(1, round((e - w) / SHARE_STEP_DEG))
    hit = 0
    for i in range(n_lat):
        xs = sg.crossings(ring, s + (i + 0.5) * (n - s) / n_lat)
        for j in range(n_lon):
            lon = w + (j + 0.5) * (e - w) / n_lon
            hit += sum(1 for x in xs if lon < x) % 2
    return round(hit / (n_lat * n_lon), 4)


def load_group(group):
    """{param: {(lat, lon): (elev, monthly dict)}} for one folder of answers."""
    out = {}
    for param in GROUPS[group]["params"]:
        data = load_json(raw_path(group, param))
        cells = {}
        for f in data["features"]:
            lon, lat, elev = f["geometry"]["coordinates"]
            cells[(lat, lon)] = (elev, f["properties"]["parameter"][param])
        out[param] = cells
    return out


def check_grid_positions(merra, syn):
    """Every answer cell must sit exactly on its grid (MERRA-2 centres k*0.5 / -180+k*0.625, SYN x.5),
    and the files of one grid must hold the same cells."""
    bad = []
    for (lat, lon) in merra["T2M"]:
        if merra_centre(lat, lon) != (lat, lon):
            bad.append(["merra", lat, lon])
    for (lat, lon) in syn["ALLSKY_SRF_ALB"]:
        if syn_centre(lat, lon) != (lat, lon):
            bad.append(["syn", lat, lon])
    uneven = [p for p in WEATHER if set(merra[p]) != set(merra["T2M"])]
    uneven += [p for p in SOLAR if set(syn[p]) != set(syn["ALLSKY_SRF_ALB"])]
    return {"rule": ("every cell centre lies exactly on the MERRA-2 or SYN1deg grid, and every file of a grid "
                     "holds the same cells"),
            "merraCells": len(merra["T2M"]), "synCells": len(syn["ALLSKY_SRF_ALB"]),
            "offGrid": bad, "filesWithOtherCells": uneven, "ok": not bad and not uneven}


def check_elevations(merra, syn):
    """MERRA-2 cell elevation must be the same in all 11 weather files; SYN1deg in all 3 solar files."""
    m_bad = [[lat, lon, p] for (lat, lon), (z, _) in merra["T2M"].items() for p in WEATHER
             if merra[p][(lat, lon)][0] != z]
    s_bad = [[lat, lon, p] for (lat, lon), (z, _) in syn["ALLSKY_SRF_ALB"].items() for p in SOLAR
             if syn[p][(lat, lon)][0] != z]
    nearest_equal = nearest_total = 0
    for (lat, lon), (z, _) in syn["ALLSKY_SRF_ALB"].items():
        mc = merra_centre(lat, lon)
        if mc in merra["T2M"]:
            nearest_total += 1
            nearest_equal += merra["T2M"][mc][0] == z
    return {"rule": "a cell's elevation is identical in every parameter file of its grid",
            "merraMismatches": m_bad, "synMismatches": s_bad,
            "synElevationEqualsNearestMerraCell": "%d/%d" % (nearest_equal, nearest_total),
            "ok": not m_bad and not s_bad}


def check_solar_overlap(merra_solar, syn):
    """The 3 solar parameters come twice (narrow and wide box); where they overlap they must be equal."""
    diff, n = [], 0
    for p in SOLAR:
        for key, value in merra_solar[p].items():
            n += 1
            if syn[p].get(key) != value:
                diff.append([p, key[0], key[1]])
    return {"rule": "merra/<solar>.json (narrow box) equals syn1deg/<solar>.json (wide box) cell by cell",
            "cellsCompared": n, "differences": diff, "ok": not diff and n > 0}


def build_cell(grid, lat, lon, elev, values, ring):
    s, n, w, e = cell_bounds(grid, lat, lon)
    return {"grid": "MERRA-2" if grid == "merra" else "CERES SYN1deg", "lat": lat, "lon": lon,
            "s": s, "n": n, "w": w, "e": e, "elev_m": elev,
            "inJordan": cell_share(ring, s, n, w, e),
            "annual": values}


# --------------------------------------------------------------------------
# Controls (the hard check)
# --------------------------------------------------------------------------
def control_points(grid):
    """The 5 Jordan sites of grid.json (coordinates from data/sites_meta.json) plus Amman."""
    points = {sid: {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "source": c["source"]}
              for sid, c in grid["controls"].items()}
    amman = load_json(os.path.join(POINT_DIR, "amman.json"))
    lon, lat = amman["geometry"]["coordinates"][:2]
    points["amman"] = {"name": "Amman", "lat": lat, "lon": lon,
                       "source": "data/raw/power/amman.json (the request point)"}
    return points


def check_control(pid, pt, merra, syn, sites):
    """Compare every value of the project's point file with the regional cell that holds the point."""
    raw = load_json(os.path.join(POINT_DIR, pid + ".json"))
    mc, sc = merra_centre(pt["lat"], pt["lon"]), syn_centre(pt["lat"], pt["lon"])
    p_lon, p_lat, p_elev = raw["geometry"]["coordinates"]
    compared, mismatches = 0, []
    for p in PARAMETERS:
        reg = (syn[p][sc] if p in SOLAR else merra[p][mc])[1]
        for k, v in raw["properties"]["parameter"][p].items():
            compared += 1
            if reg.get(k) != v:
                mismatches.append([p, k, v, reg.get(k)])
    cell_elev = merra["T2M"][mc][0]
    rec = {"name": pt["name"], "lat": pt["lat"], "lon": pt["lon"], "source": pt["source"],
           "pointFile": "data/raw/power/%s.json" % pid,
           "pointFileRequest": [p_lat, p_lon], "pointFileApiVersion": raw["header"]["api"]["version"],
           "pointFileRange": raw["header"].get("range"),
           "merra": cell_key("merra", *mc), "syn": cell_key("syn", *sc),
           "valuesEqual": "%d/%d" % (compared - len(mismatches), compared),
           "gridElevation_m": p_elev, "cellElev_m": cell_elev, "elevEqual": p_elev == cell_elev,
           "mismatches": mismatches[:20]}
    sites_ok = True
    if pid in sites:
        site = sites[pid]["power"]
        n = sum(1 for p in PARAMETERS
                if site["annual"][p] == (syn[p][sc] if p in SOLAR else merra[p][mc])[1]["ANN"])
        n += site["gridElevation_m"] == cell_elev
        rec["sitesJsonEqual"] = "%d/%d" % (n, len(PARAMETERS) + 1)
        sites_ok = n == len(PARAMETERS) + 1
    same_point = [p_lat, p_lon] == [pt["lat"], pt["lon"]]
    rec["ok"] = not mismatches and rec["elevEqual"] and same_point and sites_ok
    return rec, compared, len(mismatches)


def run_controls(grid, merra, syn):
    sites = {s["id"]: s for s in load_json(SITES_JSON)["sites"]}
    controls, n_values, n_bad = {}, 0, 0
    for pid, pt in control_points(grid).items():
        rec, compared, bad = check_control(pid, pt, merra, syn, sites)
        controls[pid] = rec
        n_values += compared
        n_bad += bad
        log("control %-15s MERRA-2 %-14s SYN1deg %-11s values %s, grid elevation %s = %s %s%s"
            % (pid, rec["merra"], rec["syn"], rec["valuesEqual"], rec["gridElevation_m"], rec["cellElev_m"],
               "ok" if rec["elevEqual"] else "DIFFERENT",
               (", sites.json %s" % rec["sitesJsonEqual"]) if "sitesJsonEqual" in rec else ""))
    n_elev = sum(1 for c in controls.values() if c["elevEqual"])
    check = {"rule": ("the regional cells of the 5 Jordan sites and Amman equal the project's point files "
                      "data/raw/power/<id>.json value for value (14 parameters x 12 months + annual) "
                      "and in grid elevation; the 5 sites also equal data/sites.json power.annual and "
                      "gridElevation_m"),
             "values": "%d/%d" % (n_values - n_bad, n_values),
             "gridElevations": "%d/%d" % (n_elev, len(controls)),
             "ok": all(c["ok"] for c in controls.values())}
    return controls, check, n_values - n_bad, n_values


# --------------------------------------------------------------------------
# Boxes
# --------------------------------------------------------------------------
def assign_boxes(grid, merra, syn, cells, ring):
    """Cells of every box; adds each cell used to `cells`."""
    boxes, ties = {}, []
    for bid, b in grid["boxes"].items():
        mc, sc = merra_centre(b["lat"], b["lon"]), syn_centre(b["lat"], b["lon"])
        if mc not in merra["T2M"] or sc not in syn["ALLSKY_SRF_ALB"]:
            raise SystemExit("%s: its cell %s / %s is not in the POWER answers" % (bid, mc, sc))
        mk, sk = cell_key("merra", *mc), cell_key("syn", *sc)
        add_cell(cells, "merra", mc, merra, ring)
        add_cell(cells, "syn", sc, syn, ring)
        tie = on_edge(b["lat"], b["lon"])
        if tie:
            ties.append([bid] + tie)
        outside = [g for g, k in (("merra", mk), ("syn", sk)) if cells[k]["inJordan"] < MOSTLY_OUTSIDE]
        crossing = straddles(b)
        flags = ["straddlesCellEdge"] if crossing else []
        if "merra" in outside:
            flags.append("climateCellMostlyOutside")
        boxes[bid] = {"climate": {"merra": mk, "syn": sk, "straddles": crossing},
                      "cellsMostlyOutside": outside, "flags": flags}
    return boxes, ties


def add_cell(cells, grid, centre, data, ring):
    key = cell_key(grid, *centre)
    if key in cells:
        return
    params = WEATHER if grid == "merra" else SOLAR
    elev = data[params[0]][centre][0]
    annual = {p: data[p][centre][1]["ANN"] for p in params}
    cells[key] = build_cell(grid, centre[0], centre[1], elev, annual, ring)


def fill_check(cells):
    bad = [[k, p] for k, c in cells.items() for p, v in c["annual"].items() if v is None or v == FILL_VALUE]
    return {"rule": "no annual value of a used cell is the fill value -999 or missing", "bad": bad, "ok": not bad}


def counts_for(boxes, cells):
    per_cell = {}
    for b in boxes.values():
        per_cell[b["climate"]["merra"]] = per_cell.get(b["climate"]["merra"], 0) + 1
    n = sorted(per_cell.values())
    return {"boxes": len(boxes),
            "merraCellsUsed": sum(1 for k in cells if k.startswith("m")),
            "synCellsUsed": sum(1 for k in cells if k.startswith("s")),
            "boxesPerMerraCell": {"min": n[0], "median": statistics.median(n), "max": n[-1]},
            "straddleMerra": sum(1 for b in boxes.values() if "merra" in b["climate"]["straddles"]),
            "straddleSyn": sum(1 for b in boxes.values() if "syn" in b["climate"]["straddles"]),
            "merraCellMostlyOutside": sum(1 for b in boxes.values() if "merra" in b["cellsMostlyOutside"]),
            "synCellMostlyOutside": sum(1 for b in boxes.values() if "syn" in b["cellsMostlyOutside"]),
            "flagged": {f: sum(1 for b in boxes.values() if f in b["flags"])
                        for f in ("straddlesCellEdge", "climateCellMostlyOutside")}}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def power_source(records, manifest_sha):
    version = records[0]["apiVersion"]
    accessed = min(r["fetched"] for r in records)[:10]
    return {"id": CLIMATE_SOURCE_ID,
            "label": "NASA POWER Climatology API, regional (community RE): MERRA-2 and CERES SYN1deg cells",
            "url": ENDPOINT,
            "licence": "NASA open data (NASA Earth Science Data and Information Policy)",
            "licenceUrl": POLICY_URL,
            "credit": CITATION,
            "notice": ("POWER Climatology API %s, regional, accessed %s. NASA asks to be told about published "
                       "uses: %s. Citation rules: %s" % (version, accessed.replace("-", "/"), NOTIFY,
                                                         REFERENCING_URL)),
            "version": version,
            "accessed": accessed,
            "sha256": manifest_sha}


def climate_block(records, n_equal, n_values, today):
    versions = sorted({r["apiVersion"] for r in records})
    labels = sorted({r["rangeLabel"] for r in records})
    if len(versions) != 1 or len(labels) != 1:
        raise SystemExit("the 17 answers differ in API version or period label: %s %s" % (versions, labels))
    return {
        "api": ENDPOINT,
        "apiVersion": versions[0],
        "community": COMMUNITY,
        "periodLabel": labels[0],
        "headerPeriod": {"start": records[0]["headerStart"], "end": records[0]["headerEnd"]},
        "periodValidated": "values equal the project's 2001–2020 point files, %d/%d, %s" % (n_equal, n_values, today),
        "rule": ("Each box takes the POWER cells that hold its centre, which is the rule of the POWER point "
                 "API used for the hand-picked sites. MERRA-2 (T2M, T2M_MAX, T2M_MIN, T2M_RANGE, RH2M, "
                 "PRECTOTCORR, WS2M, PS, TS, TS_MAX, TS_MIN; 0.5 x 0.625 deg): lat_c = round(lat / 0.5) * 0.5, "
                 "lon_c = -180 + round((lon + 180) / 0.625) * 0.625. CERES SYN1deg (ALLSKY_SRF_ALB, "
                 "ALLSKY_SFC_SW_DWN, ALLSKY_SFC_UV_INDEX; 1 x 1 deg): lat_c = floor(lat) + 0.5, "
                 "lon_c = floor(lon) + 0.5. Nothing is averaged across cells. 'straddles' lists the grids "
                 "with a cell edge inside the box. A cell's elev_m is the elevation POWER reports with it; "
                 "for a SYN1deg cell that is the nearest MERRA-2 cell's elevation, not a 1 deg mean, so the "
                 "cell-gap check uses the MERRA-2 cell. inJordan = share of the cell inside the Natural "
                 "Earth polygon, from about 0.01 x 0.01 deg samples."),
        "rawFiles": ["data/raw/screening/power/manifest.json"] + ["data/raw/screening/power/" + r["file"]
                                                                  for r in records],
    }


FLAG_RULES = {
    "straddlesCellEdge": "a MERRA-2 or SYN1deg cell edge runs through the box ('straddles' is not empty)",
    "climateCellMostlyOutside": ("the box's MERRA-2 cell (4 of the 5 climate factors) has less than 50 % of its "
                                 "area in Jordan (inJordan < 0.5). 'cellsMostlyOutside' also lists the 1 deg "
                                 "SYN1deg albedo cell when it is under 50 %; that alone does not set the flag, "
                                 "because most 1 deg cells along the border are mostly outside Jordan"),
}


def load_ring(grid):
    """Jordan's ring from the boundary file named in grid.json (its sha256 must match)."""
    boundary = grid["boundary"]
    path = os.path.join(ROOT, boundary["file"])
    if sg.sha256_file(path) != boundary["sha256"]:
        raise SystemExit("%s does not match the sha256 in stages/grid.json; run screening_grid.py" % boundary["file"])
    return [tuple(p) for p in load_json(path)["ring"]]


def answer_checks(merra, syn):
    """Consistency of the 17 answers among themselves."""
    checks = {"gridPositions": check_grid_positions(merra, syn),
              "elevations": check_elevations(merra, syn),
              "solarOverlap": check_solar_overlap({p: merra[p] for p in SOLAR}, syn)}
    log("checks: cells on grid %s; elevations consistent %s (SYN1deg z = nearest MERRA-2 cell %s); "
        "solar overlap %d cells, %d differences"
        % (checks["gridPositions"]["ok"], checks["elevations"]["ok"],
           checks["elevations"]["synElevationEqualsNearestMerraCell"],
           checks["solarOverlap"]["cellsCompared"], len(checks["solarOverlap"]["differences"])))
    return checks


def cells_and_boxes(grid, controls, merra, syn, ring, checks):
    """Every used cell (control cells first, so every key resolves) and the cells of every box."""
    cells = {}
    for c in controls.values():
        add_cell(cells, "merra", merra_centre(c["lat"], c["lon"]), merra, ring)
        add_cell(cells, "syn", syn_centre(c["lat"], c["lon"]), syn, ring)
    boxes, ties = assign_boxes(grid, merra, syn, cells, ring)
    cells = dict(sorted(cells.items()))
    checks["fillValues"] = fill_check(cells)
    checks["edgeTies"] = {"rule": "no box centre lies exactly on a cell edge (where the rule would be a tie)",
                          "boxes": ties, "ok": not ties}
    checks["allBoxes"] = {"rule": "every box of stages/grid.json has one record", "grid": len(grid["boxes"]),
                          "here": len(boxes), "ok": len(boxes) == len(grid["boxes"])}
    return cells, boxes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--power-dir", help="folder with earlier POWER answers and their manifest.json "
                                            "(searched recursively; reused only when URL and sha256 match)")
    parser.add_argument("--refresh", action="store_true", help="download all 17 answers again")
    parser.add_argument("--offline", action="store_true", help="never use the network")
    args = parser.parse_args(argv)
    if args.refresh and args.offline:
        parser.error("--refresh and --offline cannot be combined")

    grid = load_json(sg.GRID_OUT)
    if grid.get("grid") != sg.GRID_ID:
        raise SystemExit("stages/grid.json is not grid %s" % sg.GRID_ID)
    ring = load_ring(grid)
    records, network = acquire_all(args)
    manifest_sha = write_manifest(records)

    merra, syn = load_group("merra"), load_group("syn1deg")
    checks = answer_checks(merra, syn)
    controls, control_check, n_equal, n_values = run_controls(grid, merra, syn)
    checks["controls"] = control_check
    log("climate controls: %s values and %s grid elevations equal the project's point files"
        % (control_check["values"], control_check["gridElevations"]))
    if not control_check["ok"]:
        log("HARD CHECK FAILED: the regional answers no longer equal the project's 2001-2020 point files. "
            "NASA may have regenerated the product. Fallback (not automatic): point requests with "
            "&start=2001&end=2020 at each cell centre.")
        return 1

    cells, boxes = cells_and_boxes(grid, controls, merra, syn, ring, checks)
    counts = counts_for(boxes, cells)
    log("boxes %d: %d MERRA-2 cells (boxes per cell %s), %d SYN1deg cells; straddle MERRA-2 %d, SYN1deg %d; "
        "cell mostly outside Jordan: MERRA-2 %d, SYN1deg %d; edge ties %d"
        % (counts["boxes"], counts["merraCellsUsed"], counts["boxesPerMerraCell"], counts["synCellsUsed"],
           counts["straddleMerra"], counts["straddleSyn"], counts["merraCellMostlyOutside"],
           counts["synCellMostlyOutside"], len(checks["edgeTies"]["boxes"])))

    today = sg.utc_now().strftime("%Y-%m-%d")
    stage = {
        "stage": "power",
        "generated": sg.utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": SCRIPT,
        "grid": sg.GRID_ID,
        "sources": [power_source(records, manifest_sha)],
        "network": network,
        "climate": climate_block(records, n_equal, n_values, today),
        "manifest": {"file": rel(MANIFEST), "sha256": manifest_sha},
        "flagRules": FLAG_RULES,
        "counts": counts,
        "checks": checks,
        "cells": cells,
        "boxes": boxes,
        "controls": controls,
    }
    sg.write_text(STAGE_OUT, sg.dumps_rows(stage, ("cells", "boxes", "controls")))
    failed = [name for name, c in checks.items() if not c["ok"]]
    if failed:
        log("CHECK FAILED: " + ", ".join(failed))
        return 1
    log("checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
