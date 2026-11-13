#!/usr/bin/env python3
"""Jordan screening layer, stage 1: the Jordan boundary and the 10 km grid.

Reads Jordan's polygon from Natural Earth 1:10m Admin 0 - Countries (v5.1.1,
public domain), lays one fixed grid of 10 km boxes over it and keeps every box
whose centre is inside the polygon. Every later stage (climate, terrain,
geology, build) reads the boxes from the file written here.

Writes (from the project folder):
  data/raw/screening/boundary/jordan_ne10m_v5.1.1.json  the polygon ring, DBF attributes,
                                                       zip sha256, bbox and area
  data/raw/screening/stages/grid.json                   grid constants and the boxes

Python 3.12 standard library only. Run from any folder:

  python -I scripts/screening_grid.py                       # zip from the cache (downloads it if missing)
  python -I scripts/screening_grid.py --ne-zip PATH         # use a zip you already have
  python -I scripts/screening_grid.py --offline             # never use the network

The zip (4.9 MB) is kept outside the project, in the cache folder
(%LOCALAPPDATA%\\analog-atlas\\screening-cache, elsewhere ~/.cache/analog-atlas/screening).
Its sha256 must match NE_SHA256 below, or the script stops.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
import struct
import sys
import time
import urllib.request
import zipfile

sys.dont_write_bytecode = True

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(ROOT, "data", "raw", "screening")
BOUNDARY_OUT = os.path.join(SCREEN_DIR, "boundary", "jordan_ne10m_v5.1.1.json")
GRID_OUT = os.path.join(SCREEN_DIR, "stages", "grid.json")
SITES_META = os.path.join(ROOT, "data", "sites_meta.json")
SCRIPT = "scripts/screening_grid.py"

GRID_ID = "jordan-10km-v1"
R_EARTH_M = 6371008.8            # mean radius, same as compute_terrain.RADIUS_M["earth"]
BOX_M = 10000.0                  # box side
SOUTH = 29.18                    # south-west corner of the grid (the task's bounding box)
WEST = 34.95
LON_STEP_LAT = 31.28             # the column step is 10 km at this latitude
NROWS = 47                       # row 0 = south
NCOLS = 42                       # col 0 = west
DLAT = math.degrees(BOX_M / R_EARTH_M)                    # 0.0899320363724538 deg
DLON = DLAT / math.cos(math.radians(LON_STEP_LAT))        # 0.1052279594642279 deg
COORD_DECIMALS = 6               # box centres, as in compute_terrain.py
KM_PER_DEG = math.radians(1.0) * R_EARTH_M / 1000.0
NEAR_BORDER_KM = 7.1             # about half a box diagonal (design section 0)
COVERAGE_STEP_DEG = 0.02         # lattice of the coverage check (design section 2.4)
COVERAGE_BORDER_KM = 14.2        # one box diagonal

NE_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
NE_TERMS_URL = "https://www.naturalearthdata.com/about/terms-of-use/"
NE_ZIP_NAME = "ne_10m_admin_0_countries.zip"
NE_BASE = "ne_10m_admin_0_countries"
NE_VERSION = "5.1.1"
NE_SHA256 = "ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6"
NE_BYTES = 4930492
NE_TERMS_QUOTE = ("All versions of Natural Earth raster + vector map data found on this website "
                  "are in the public domain.")
USER_AGENT = "analog-atlas-screening/1.0 (NASA Space Apps 2026 project; Python urllib)"


def log(msg):
    print(msg, flush=True)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def default_cache_dir():
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "analog-atlas", "screening-cache")
    return os.path.join(os.path.expanduser("~"), ".cache", "analog-atlas", "screening")


# --------------------------------------------------------------------------
# The Natural Earth zip: find it, check it, download it if needed
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
            with urllib.request.urlopen(req, timeout=180) as resp:
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
    if args.ne_zip:
        path, how = args.ne_zip, "--ne-zip"
    else:
        path, how = os.path.join(args.cache_dir, NE_ZIP_NAME), "cache"
        if not os.path.exists(path):
            if args.offline:
                raise SystemExit("%s is not in the cache and --offline is set" % NE_ZIP_NAME)
            network.append(NE_URL)
            download(NE_URL, path)
            how = "downloaded"
    if not os.path.exists(path):
        raise SystemExit("not found: " + path)
    digest = sha256_file(path)
    if digest != NE_SHA256:
        raise SystemExit("sha256 of %s is %s, expected %s (v%s). Natural Earth may have released "
                         "a new version; check it before changing NE_SHA256."
                         % (path, digest, NE_SHA256, NE_VERSION))
    return path, how


# --------------------------------------------------------------------------
# Shapefile and DBF (only what a single polygon record needs)
# --------------------------------------------------------------------------
def dbf_fields(raw):
    fields, off = [], 32
    while raw[off] != 0x0D:
        name = raw[off:off + 11].split(b"\x00")[0].decode("ascii")
        fields.append((name, chr(raw[off + 11]), raw[off + 16], raw[off + 17]))
        off += 32
    return fields


def dbf_value(text, ftype, decimals):
    if ftype in ("N", "F"):
        if text == "":
            return None
        try:
            return int(text) if decimals == 0 and "." not in text else float(text)
        except ValueError:
            return text
    return text


def read_dbf(raw):
    """All records as dicts. Field lengths are bytes, so slice before decoding (UTF-8, see .cpg);
    Natural Earth pads text with NUL bytes, which are dropped."""
    nrec = struct.unpack("<I", raw[4:8])[0]
    hlen, rlen = struct.unpack("<HH", raw[8:12])
    fields = dbf_fields(raw)
    recs = []
    for i in range(nrec):
        p = hlen + i * rlen + 1          # skip the deletion flag
        rec = {}
        for name, ftype, flen, dec in fields:
            text = raw[p:p + flen].rstrip(b"\x00 ").decode("utf-8", "replace").strip()
            rec[name] = dbf_value(text, ftype, dec)
            p += flen
        recs.append(rec)
    return recs


def read_shp_polygon(shp, shx, index):
    """(shape type, bbox [w, s, e, n], rings as lists of (lon, lat)) of one polygon record."""
    off = struct.unpack(">I", shx[100 + 8 * index:104 + 8 * index])[0] * 2
    clen = struct.unpack(">I", shx[104 + 8 * index:108 + 8 * index])[0] * 2
    c = shp[off + 8:off + 8 + clen]
    stype = struct.unpack("<i", c[0:4])[0]
    if stype not in (5, 15, 25):
        raise SystemExit("record %d is not a polygon (shape type %d)" % (index, stype))
    bbox = list(struct.unpack("<4d", c[4:36]))
    nparts, npts = struct.unpack("<ii", c[36:44])
    parts = list(struct.unpack("<%di" % nparts, c[44:44 + 4 * nparts])) + [npts]
    p0 = 44 + 4 * nparts
    xy = struct.unpack("<%dd" % (2 * npts), c[p0:p0 + 16 * npts])
    pts = [(xy[2 * k], xy[2 * k + 1]) for k in range(npts)]
    rings = [pts[parts[k]:parts[k + 1]] for k in range(nparts)]
    return stype, bbox, rings


# --------------------------------------------------------------------------
# Geometry (longitude/latitude; the ring is closed: first vertex == last)
# --------------------------------------------------------------------------
def ring_area_m2(ring):
    """Signed spherical area in m2 (Chamberlain & Duquette 2007); positive for a clockwise ring
    such as a shapefile outer ring."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        s += math.radians(x2 - x1) * (2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2)))
    return s * R_EARTH_M ** 2 / 2.0


def planar_area(poly):
    """Shoelace area in square degrees (absolute)."""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def crossings(ring, lat):
    """Longitudes where the ring crosses the parallel `lat` (half-open rule of ray casting)."""
    xs = []
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat):
            xs.append((x2 - x1) * (lat - y1) / (y2 - y1) + x1)
    return xs


def inside(ring, lon, lat):
    """Even-odd ray casting: is (lon, lat) inside the ring?"""
    return sum(1 for x in crossings(ring, lat) if lon < x) % 2 == 1


def segment_hits_rect(x1, y1, x2, y2, w, s, e, n):
    """Liang-Barsky: does the segment touch the closed rectangle [w, e] x [s, n]?"""
    t0, t1 = 0.0, 1.0
    dx, dy = x2 - x1, y2 - y1
    for p, q in ((-dx, x1 - w), (dx, e - x1), (-dy, y1 - s), (dy, n - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
        if t0 > t1:
            return False
    return True


def ring_crosses_rect(ring, w, s, e, n):
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if max(x1, x2) < w or min(x1, x2) > e or max(y1, y2) < s or min(y1, y2) > n:
            continue
        if segment_hits_rect(x1, y1, x2, y2, w, s, e, n):
            return True
    return False


def clip_to_rect(poly, w, s, e, n):
    """Sutherland-Hodgman clip of any polygon by a rectangle. The result may contain zero-width
    pieces along the rectangle's edges, but its shoelace area is exact."""
    def clip(points, keep, cut):
        out = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            if keep(cur):
                if not keep(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif keep(prev):
                out.append(cut(prev, cur))
        return out

    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    pts = list(poly[:-1]) if poly[0] == poly[-1] else list(poly)
    for keep, cut in ((lambda p: p[0] >= w, at_x(w)), (lambda p: p[0] <= e, at_x(e)),
                      (lambda p: p[1] >= s, at_y(s)), (lambda p: p[1] <= n, at_y(n))):
        pts = clip(pts, keep, cut)
        if not pts:
            return []
    return pts


def dist_to_ring_km(ring, lon, lat):
    """Shortest distance from (lon, lat) to the ring's edges, km (local equirectangular
    projection centred on the point; good to well under 1 % at these distances)."""
    kx = math.cos(math.radians(lat)) * KM_PER_DEG
    ky = KM_PER_DEG
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
        dx, dy = (x2 - x1) * kx, (y2 - y1) * ky
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
        px, py = ax + t * dx, ay + t * dy
        best = min(best, px * px + py * py)
    return math.sqrt(best)


# --------------------------------------------------------------------------
# The grid
# --------------------------------------------------------------------------
def box_id(row, col):
    return "jo-r%02dc%02d" % (row, col)


def box_bounds(row, col):
    """(s, n, w, e) in degrees, not rounded."""
    return (SOUTH + row * DLAT, SOUTH + (row + 1) * DLAT, WEST + col * DLON, WEST + (col + 1) * DLON)


def box_centre(row, col):
    """(lat, lon) rounded to COORD_DECIMALS; the inclusion test uses these rounded values."""
    return (round(SOUTH + (row + 0.5) * DLAT, COORD_DECIMALS),
            round(WEST + (col + 0.5) * DLON, COORD_DECIMALS))


def box_of_point(lat, lon):
    """(row, col) of the box holding a point (a point on an edge goes to the box north/east of it),
    or None outside the grid."""
    row = math.floor((lat - SOUTH) / DLAT)
    col = math.floor((lon - WEST) / DLON)
    if 0 <= row < NROWS and 0 <= col < NCOLS:
        return row, col
    return None


def box_area_km2(s, n, w, e):
    return (R_EARTH_M / 1000.0) ** 2 * math.radians(e - w) * (math.sin(math.radians(n))
                                                             - math.sin(math.radians(s)))


def share_inside(ring, s, n, w, e):
    clipped = clip_to_rect(ring, w, s, e, n)
    return planar_area(clipped) / ((e - w) * (n - s)) if len(clipped) >= 3 else 0.0


def build_boxes(ring):
    """Every grid cell with its share inside Jordan; returns (kept boxes, all cell shares)."""
    boxes, cells = {}, []
    for row in range(NROWS):
        for col in range(NCOLS):
            s, n, w, e = box_bounds(row, col)
            lat, lon = box_centre(row, col)
            centre_in = inside(ring, lon, lat)
            crosses = ring_crosses_rect(ring, w, s, e, n)
            share = share_inside(ring, s, n, w, e) if crosses else (1.0 if centre_in else 0.0)
            if crosses and centre_in and round(share, 4) >= 1.0:
                share = 0.9999   # a box that touches the boundary never reads as wholly inside
            cells.append({"row": row, "col": col, "share": share, "area_km2": box_area_km2(s, n, w, e),
                          "crosses": crosses, "centreIn": centre_in,
                          "exactCentreIn": inside(ring, WEST + (col + 0.5) * DLON,
                                                  SOUTH + (row + 0.5) * DLAT)})
            if not centre_in:
                continue
            bid = box_id(row, col)
            boxes[bid] = {"id": bid, "row": row, "col": col, "lat": lat, "lon": lon,
                          "s": s, "n": n, "w": w, "e": e,
                          "inJordan": round(share, 4),
                          "borderKm": round(dist_to_ring_km(ring, lon, lat), 2)}
    return boxes, cells


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def coverage_check(ring, bbox, boxes):
    """Design 2.4: on a 0.02 deg lattice, every point inside the polygon is in a kept box or
    within 14.2 km of the border."""
    step = COVERAGE_STEP_DEG
    k_lat0, k_lat1 = math.ceil(bbox[1] / step), math.floor(bbox[3] / step)
    k_lon0, k_lon1 = math.ceil(bbox[0] / step), math.floor(bbox[2] / step)
    n_in = n_kept = n_near = 0
    far_max = 0.0
    failures = []
    for i in range(k_lat0, k_lat1 + 1):
        lat = round(i * step, 10)
        xs = crossings(ring, lat)
        for j in range(k_lon0, k_lon1 + 1):
            lon = round(j * step, 10)
            if sum(1 for x in xs if lon < x) % 2 == 0:
                continue
            n_in += 1
            rc = box_of_point(lat, lon)
            if rc and box_id(*rc) in boxes:
                n_kept += 1
                continue
            d = dist_to_ring_km(ring, lon, lat)
            far_max = max(far_max, d)
            if d <= COVERAGE_BORDER_KM:
                n_near += 1
            else:
                failures.append([lat, lon, round(d, 2)])
    return {"rule": ("every point of a %.2f deg lattice (multiples of %.2f deg) inside the polygon "
                     "is in a kept box or within %.1f km of the border" % (step, step, COVERAGE_BORDER_KM)),
            "pointsInside": n_in, "inKeptBox": n_kept, "notInKeptBoxButNearBorder": n_near,
            "maxBorderKmOfThoseNotInKeptBox": round(far_max, 2),
            "failures": failures, "ok": not failures}


def area_check(ring_area_km2, cells):
    """The polygon area must equal the sum over all grid cells of share x cell area
    (this proves the clipping and that the grid covers the whole polygon)."""
    summed = sum(c["share"] * c["area_km2"] for c in cells)
    diff_pct = 100.0 * (summed - ring_area_km2) / ring_area_km2
    return {"rule": "sum over all grid cells of (share inside x cell area) equals the polygon area within 0.1 %",
            "polygonArea_km2": round(ring_area_km2, 1), "sumOfShares_km2": round(summed, 1),
            "diffPct": round(diff_pct, 4), "ok": abs(diff_pct) < 0.1}


def extent_check(ring, bbox):
    """How far the polygon reaches outside the grid, and the area it has there."""
    north, east = SOUTH + NROWS * DLAT, WEST + NCOLS * DLON
    lat_mid = (bbox[1] + bbox[3]) / 2
    kx = math.cos(math.radians(lat_mid)) * KM_PER_DEG
    beyond = {"w": max(0.0, WEST - bbox[0]) * kx, "e": max(0.0, bbox[2] - east) * kx,
              "s": max(0.0, SOUTH - bbox[1]) * KM_PER_DEG, "n": max(0.0, bbox[3] - north) * KM_PER_DEG}
    outside_deg2 = planar_area(ring[:-1]) - planar_area(clip_to_rect(ring, WEST, SOUTH, east, north))
    return {"rule": "the polygon's area outside the grid is under 1 km2",
            "polygonBeyondGridKm": {k: round(v, 3) for k, v in beyond.items()},
            "polygonAreaOutsideGrid_km2": round(outside_deg2 * kx * KM_PER_DEG, 4),
            "ok": outside_deg2 * kx * KM_PER_DEG < 1.0}


def controls_for_sites(ring, boxes):
    """The Jordan sites of data/sites_meta.json and the box that holds each one."""
    meta = json.load(open(SITES_META, encoding="utf-8"))
    out = {}
    for site in meta["sites"]:
        if not site.get("jordan"):
            continue
        rc = box_of_point(site["lat"], site["lon"])
        bid = box_id(*rc) if rc else None
        out[site["id"]] = {"name": site["name"], "lat": site["lat"], "lon": site["lon"],
                           "source": "data/sites_meta.json",
                           "inPolygon": inside(ring, site["lon"], site["lat"]),
                           "box": bid, "boxKept": bid in boxes,
                           "borderKm": round(dist_to_ring_km(ring, site["lon"], site["lat"]), 2)}
    return out


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
            rows = [" %s: %s" % (json.dumps(k, ensure_ascii=False), compact(v)) for k, v in value.items()]
            lines.append(" %s: {\n%s\n }%s" % (json.dumps(key), ",\n".join(" " + r for r in rows), comma))
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
    log("wrote %s (%d bytes)" % (os.path.relpath(path, ROOT), os.path.getsize(path)))


def ne_source(zip_sha, accessed):
    return {"id": "naturalearth-admin0-10m",
            "label": "Natural Earth 1:10m Cultural Vectors, Admin 0 - Countries",
            "url": NE_URL,
            "licence": "Public domain",
            "licenceUrl": NE_TERMS_URL,
            "credit": "Made with Natural Earth",
            "notice": "None required: the data are in the public domain and the credit is optional.",
            "version": NE_VERSION,
            "accessed": accessed,
            "sha256": zip_sha}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ne-zip", help="path of %s (checked against its sha256)" % NE_ZIP_NAME)
    parser.add_argument("--cache-dir", default=default_cache_dir(), help="folder for big downloads")
    parser.add_argument("--offline", action="store_true", help="never use the network")
    args = parser.parse_args(argv)

    network = []
    zpath, how = locate_zip(args, network)
    # date the zip was downloaded = its file time (kept when the cache copy is reused)
    accessed = datetime.datetime.fromtimestamp(os.path.getmtime(zpath), datetime.timezone.utc).strftime("%Y-%m-%d")
    z = zipfile.ZipFile(zpath)
    version = z.read(NE_BASE + ".VERSION.txt").decode("ascii").strip()
    if version != NE_VERSION:
        raise SystemExit("zip says version %s, expected %s" % (version, NE_VERSION))
    shp, shx, dbf = (z.read(NE_BASE + ext) for ext in (".shp", ".shx", ".dbf"))
    recs = read_dbf(dbf)
    idx = [i for i, r in enumerate(recs) if r.get("ADM0_A3") == "JOR"]
    if len(idx) != 1:
        raise SystemExit("expected one ADM0_A3 = JOR record, found %d" % len(idx))
    stype, bbox, rings = read_shp_polygon(shp, shx, idx[0])
    if len(rings) != 1:
        raise SystemExit("expected one ring for Jordan, found %d" % len(rings))
    ring = rings[0]
    if ring[0] != ring[-1]:
        raise SystemExit("the ring is not closed")
    area_km2 = abs(ring_area_m2(ring)) / 1e6
    log("Natural Earth %s (%s, sha256 %s...): %s, record %d, %d vertices, %.0f km2"
        % (version, how, NE_SHA256[:12], recs[idx[0]]["ADMIN"], idx[0], len(ring), area_km2))
    log("bbox lon %.4f..%.4f, lat %.4f..%.4f" % (bbox[0], bbox[2], bbox[1], bbox[3]))

    members = {}
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".VERSION.txt"):
        data = z.read(NE_BASE + ext)
        members[NE_BASE + ext] = {"bytes": len(data), "sha256": sha256_bytes(data)}
    boundary = {
        "about": ("Jordan's boundary as drawn by Natural Earth 1:10m Admin 0 - Countries: the de facto, "
                  "generalised boundary. The West Bank belongs to a separate Natural Earth feature "
                  "(Palestine, PSX) and is not included. Indicative only. Written by "
                  "scripts/screening_grid.py: the ring is copied unchanged from the shapefile; the "
                  "attributes are the record's DBF fields (padding removed, numbers as numbers)."),
        "source": "Natural Earth 1:10m Cultural Vectors, Admin 0 - Countries",
        "version": version,
        "url": NE_URL,
        "licence": "Public domain",
        "licenceUrl": NE_TERMS_URL,
        "licenceQuote": NE_TERMS_QUOTE,
        "accessed": accessed,
        "zip": {"name": NE_ZIP_NAME, "bytes": os.path.getsize(zpath), "sha256": NE_SHA256, "members": members},
        "crs": z.read(NE_BASE + ".prj").decode("ascii").strip(),
        "record": {"index": idx[0], "shapeType": stype, "match": "ADM0_A3 = JOR"},
        "bbox": {"w": bbox[0], "s": bbox[1], "e": bbox[2], "n": bbox[3]},
        "area_km2": round(area_km2, 1),
        "areaMethod": "spherical polygon area (Chamberlain & Duquette 2007), R = 6,371,008.8 m",
        "nVertices": len(ring),
        "ringNote": "[lon, lat] in degrees (WGS84), as stored in the shapefile; closed (first = last); clockwise",
        "attributes": recs[idx[0]],
        "ring": [[x, y] for x, y in ring],
    }
    boundary_text = dumps_rows(boundary, ("ring",))
    write_text(BOUNDARY_OUT, boundary_text)
    boundary_sha = sha256_bytes(boundary_text.encode("utf-8"))

    t0 = time.time()
    boxes, cells = build_boxes(ring)
    n_cross = sum(1 for b in boxes.values() if b["inJordan"] < 1)
    n_near = sum(1 for b in boxes.values() if b["borderKm"] < NEAR_BORDER_KM)
    n_rounding = sum(1 for c in cells if c["centreIn"] != c["exactCentreIn"])
    n_capped = sum(1 for c in cells if c["crosses"] and c["centreIn"] and c["share"] == 0.9999)
    log("grid %d rows x %d cols = %d boxes; kept (centre inside Jordan): %d; %.1f s"
        % (NROWS, NCOLS, NROWS * NCOLS, len(boxes), time.time() - t0))
    log("kept boxes that cross the boundary: %d; centre within %.1f km of it: %d"
        % (n_cross, NEAR_BORDER_KM, n_near))
    if n_rounding:
        log("note: %d centres change side when rounded to %d decimals" % (n_rounding, COORD_DECIMALS))

    coverage = coverage_check(ring, bbox, boxes)
    area = area_check(area_km2, cells)
    extent = extent_check(ring, bbox)
    log("polygon beyond the grid edges (km): %s; area outside the grid %.4f km2"
        % (extent["polygonBeyondGridKm"], extent["polygonAreaOutsideGrid_km2"]))
    log("coverage: %d lattice points inside, %d in kept boxes, %d near the border, %d failures"
        % (coverage["pointsInside"], coverage["inKeptBox"], coverage["notInKeptBoxButNearBorder"],
           len(coverage["failures"])))
    log("area: polygon %.1f km2, sum of shares %.1f km2 (%+.4f %%)"
        % (area["polygonArea_km2"], area["sumOfShares_km2"], area["diffPct"]))
    controls = controls_for_sites(ring, boxes)
    for sid, c in controls.items():
        log("control %-15s box %s kept %s, %.1f km from the border" % (sid, c["box"], c["boxKept"], c["borderKm"]))

    grid = {
        "stage": "grid",
        "generated": utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": SCRIPT,
        "grid": GRID_ID,
        "sources": [ne_source(NE_SHA256, accessed)],
        "network": network,
        "constants": {
            "id": GRID_ID,
            "south": SOUTH, "west": WEST,
            "dlat": DLAT, "dlon": DLON,
            "nrows": NROWS, "ncols": NCOLS,
            "north": SOUTH + NROWS * DLAT, "east": WEST + NCOLS * DLON,
            "radius_m": R_EARTH_M, "box_m": BOX_M, "lonStepLat": LON_STEP_LAT,
            "dlatFormula": "degrees(10000 / 6371008.8): 10 km of latitude",
            "dlonFormula": "dlat / cos(radians(31.28)): 10 km of longitude at 31.28 N",
            "rowZero": "south", "colZero": "west",
            "idPattern": "jo-rRRcCC (RR = row, CC = col, two digits each)",
            "bounds": ("s = south + row * dlat, n = south + (row + 1) * dlat, "
                       "w = west + col * dlon, e = west + (col + 1) * dlon (degrees, not rounded)"),
            "centre": "lat = south + (row + 0.5) * dlat, lon = west + (col + 0.5) * dlon, rounded to 6 decimals",
            "inclusion": ("a box is kept when its centre (6 decimals) is inside the Natural Earth 10m v5.1.1 "
                          "Jordan polygon (even-odd ray casting in longitude/latitude)"),
            "inJordan": ("share of the box inside the polygon, 0 to 1, 4 decimals: exact clipping of the "
                         "polygon by the box in longitude/latitude; 1 only when the boundary does not "
                         "touch the box (a touching box shows at most 0.9999)"),
            "borderKm": ("distance from the box centre to the nearest point of the polygon boundary, km, "
                         "2 decimals (local equirectangular projection, R = 6,371,008.8 m)"),
            "pointToBox": "row = floor((lat - south) / dlat), col = floor((lon - west) / dlon)",
        },
        "boundary": {"file": "data/raw/screening/boundary/jordan_ne10m_v5.1.1.json", "sha256": boundary_sha,
                     "nVertices": len(ring), "area_km2": round(area_km2, 1), "bbox": boundary["bbox"]},
        "counts": {"gridBoxes": NROWS * NCOLS, "kept": len(boxes), "crossBoundary": n_cross,
                   "centreWithin7_1km": n_near, "centreSideChangedByRounding": n_rounding,
                   "shareCappedAt0_9999": n_capped},
        "checks": {"coverage": coverage, "area": area, "extent": extent},
        "boxes": boxes,
        "controls": controls,
    }
    write_text(GRID_OUT, dumps_rows(grid, ("boxes", "controls")))

    if not (coverage["ok"] and area["ok"] and extent["ok"]):
        log("CHECK FAILED")
        return 1
    log("checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
