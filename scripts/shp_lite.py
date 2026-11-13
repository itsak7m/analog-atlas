#!/usr/bin/env python3
"""Small readers for an ESRI shapefile, its dBase table and its map projection.

Used by scripts/screening_geology.py to read the IGME5000 geology map (BGR).
Python 3.12 standard library only. Everything works on bytes already in memory
(for example read straight out of a zip), so nothing is unpacked to disk.

  read_shp_header(shp)              file length, shape type and bounding box
  iter_polygons(shp, bbox)          polygon records (index, bbox, rings), optionally only
                                    those whose bounding box meets `bbox`
  dbf_fields(dbf), dbf_count(dbf)   the field list and the number of rows
  read_dbf_rows(dbf, rows)          chosen rows only, read by offset (fast on a big table)
  parse_prj(text)                   the parameters of a Lambert Conformal Conic .prj (ESRI WKT)
  make_lcc_2sp(...)                 the ellipsoidal Lambert Conic Conformal (2SP) forward
                                    projection, EPSG method 9802 (EPSG Guidance Note 7-2)
  lcc_selftest()                    the worked example of EPSG Guidance Note 7-2
  point_in_rings(x, y, rings)       even-odd test over all rings of a record (holes work)
  PolygonIndex                      a bucket index: which polygons hold a point
"""

import math
import re
import struct

POLYGON_TYPES = (5, 15, 25)     # Polygon, PolygonZ, PolygonM


# --------------------------------------------------------------------------
# Shapefile (.shp)
# --------------------------------------------------------------------------
def read_shp_header(shp):
    """{fileLength, shapeType, bbox [xmin, ymin, xmax, ymax]} from the 100-byte header."""
    if struct.unpack(">i", shp[0:4])[0] != 9994:
        raise ValueError("not a shapefile (file code is not 9994)")
    return {"fileLength": struct.unpack(">i", shp[24:28])[0] * 2,
            "shapeType": struct.unpack("<i", shp[32:36])[0],
            "bbox": list(struct.unpack("<4d", shp[36:68]))}


def bbox_meets(a, b):
    """Do two boxes [xmin, ymin, xmax, ymax] touch or overlap?"""
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def decode_rings(rec):
    """Rings of one polygon record body (after the 8-byte record header)."""
    nparts, npts = struct.unpack("<2i", rec[36:44])
    parts = list(struct.unpack("<%di" % nparts, rec[44:44 + 4 * nparts])) + [npts]
    p0 = 44 + 4 * nparts
    xy = struct.unpack("<%dd" % (2 * npts), rec[p0:p0 + 16 * npts])
    pts = list(zip(xy[0::2], xy[1::2]))
    return [pts[parts[k]:parts[k + 1]] for k in range(nparts)]


def iter_polygons(shp, bbox=None):
    """Yield (index, bbox, rings) for each polygon record; index is 0-based and equals the
    dBase row. With bbox = [xmin, ymin, xmax, ymax], records whose own bounding box does not
    meet it are skipped before their points are decoded. Null shapes are skipped."""
    pos, index, end = 100, 0, len(shp)
    while pos + 8 <= end:
        clen = struct.unpack(">i", shp[pos + 4:pos + 8])[0] * 2
        rec = shp[pos + 8:pos + 8 + clen]
        pos += 8 + clen
        i, index = index, index + 1
        stype = struct.unpack("<i", rec[0:4])[0] if len(rec) >= 4 else 0
        if stype == 0:
            continue
        if stype not in POLYGON_TYPES:
            raise ValueError("record %d has shape type %d, not a polygon" % (i, stype))
        rbox = list(struct.unpack("<4d", rec[4:36]))
        if bbox is not None and not bbox_meets(rbox, bbox):
            continue
        yield i, rbox, decode_rings(rec)


# --------------------------------------------------------------------------
# dBase table (.dbf)
# --------------------------------------------------------------------------
def dbf_fields(dbf):
    """[(name, type, length, decimals)] from the header."""
    fields, off = [], 32
    while dbf[off] != 0x0D:
        name = dbf[off:off + 11].split(b"\x00")[0].decode("ascii")
        fields.append((name, chr(dbf[off + 11]), dbf[off + 16], dbf[off + 17]))
        off += 32
    return fields


def dbf_count(dbf):
    return struct.unpack("<I", dbf[4:8])[0]


def dbf_value(text, ftype, decimals):
    """Numbers as int or float (None when blank); text unchanged."""
    if ftype not in ("N", "F"):
        return text
    if text == "":
        return None
    try:
        return int(text) if decimals == 0 and "." not in text else float(text)
    except ValueError:
        return text


def read_dbf_rows(dbf, rows, encoding="utf-8"):
    """{row: {field: value}} for the given 0-based rows. Field lengths are bytes, so each field
    is sliced before it is decoded; NUL and space padding is dropped. Deleted rows are None."""
    nrec = dbf_count(dbf)
    hlen, rlen = struct.unpack("<HH", dbf[8:12])
    fields = dbf_fields(dbf)
    out = {}
    for r in sorted(set(rows)):
        if not 0 <= r < nrec:
            raise ValueError("row %d is outside the table (%d rows)" % (r, nrec))
        p = hlen + r * rlen
        if dbf[p:p + 1] == b"*":
            out[r] = None
            continue
        p += 1
        rec = {}
        for name, ftype, flen, dec in fields:
            text = dbf[p:p + flen].replace(b"\x00", b"").decode(encoding, "replace").strip()
            rec[name] = dbf_value(text, ftype, dec)
            p += flen
        out[r] = rec
    return out


# --------------------------------------------------------------------------
# Projection: Lambert Conic Conformal (2SP), EPSG method 9802
# --------------------------------------------------------------------------
def parse_prj(text):
    """Projection name, spheroid and parameters of an ESRI-WKT .prj, e.g.
    {"projection": "Lambert_Conformal_Conic", "a": 6378137.0, "invf": 298.257222101,
     "False_Easting": 4000000.0, ...}."""
    out = {}
    m = re.search(r'PROJECTION\["([^"]+)"\]', text)
    out["projection"] = m.group(1) if m else None
    m = re.search(r'SPHEROID\["[^"]*",\s*([-0-9.eE+]+),\s*([-0-9.eE+]+)\]', text)
    if m:
        out["a"], out["invf"] = float(m.group(1)), float(m.group(2))
    for name, value in re.findall(r'PARAMETER\["([^"]+)",\s*([-0-9.eE+]+)\]', text):
        out[name] = float(value)
    m = re.search(r'UNIT\["([^"]+)",\s*([-0-9.eE+]+)\]\]\s*$', text.strip())
    out["unit"] = m.group(1) if m else None
    return out


def make_lcc_2sp(a, invf, lat1, lat2, lat0, lon0, fe, fn):
    """Forward projection (lon, lat in degrees) -> (easting, northing), in the unit of a, fe
    and fn. Formulas of EPSG Guidance Note 7-2, section 'Lambert Conic Conformal (2SP)'.
    The returned function also carries n, F and rF for the self-test."""
    f = 1.0 / invf
    e2 = 2 * f - f * f
    e = math.sqrt(e2)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e2 * math.sin(phi) ** 2)

    def t(phi):
        s = math.sin(phi)
        return math.tan(math.pi / 4 - phi / 2) / ((1 - e * s) / (1 + e * s)) ** (e / 2)

    p1, p2, pf = math.radians(lat1), math.radians(lat2), math.radians(lat0)
    m1, m2 = m(p1), m(p2)
    t1, t2, tf = t(p1), t(p2), t(pf)
    n = (math.log(m1) - math.log(m2)) / (math.log(t1) - math.log(t2))
    big_f = m1 / (n * t1 ** n)
    r_f = a * big_f * tf ** n

    def forward(lon, lat):
        r = a * big_f * t(math.radians(lat)) ** n
        theta = n * math.radians(lon - lon0)
        return fe + r * math.sin(theta), fn + r_f - r * math.cos(theta)

    forward.n, forward.F, forward.rF = n, big_f, r_f
    return forward


# EPSG:3034, ETRS89 / LCC Europe: the CRS of the IGME5000 shapefiles (checked against the .prj)
EPSG_3034 = {"a": 6378137.0, "invf": 298.257222101, "Standard_Parallel_1": 35.0,
             "Standard_Parallel_2": 65.0, "Latitude_Of_Origin": 52.0, "Central_Meridian": 10.0,
             "False_Easting": 4000000.0, "False_Northing": 2800000.0}


def lcc_from_params(p):
    return make_lcc_2sp(p["a"], p["invf"], p["Standard_Parallel_1"], p["Standard_Parallel_2"],
                        p["Latitude_Of_Origin"], p["Central_Meridian"],
                        p["False_Easting"], p["False_Northing"])


# EPSG Guidance Note 7-2 (Coordinate Conversions and Transformations including Formulas),
# worked example of the Lambert Conic Conformal (2SP): NAD27 / Texas South Central,
# Clarke 1866 ellipsoid, all lengths in US survey feet.
GN7_2 = {
    "about": ("EPSG Guidance Note 7-2, Lambert Conic Conformal (2SP) example: NAD27 / Texas South "
              "Central, Clarke 1866 (a = 6378206.400 m = 20925832.16 US survey ft, 1/f = 294.97870), "
              "lengths in US survey feet (1 ftUS = 1200/3937 m)"),
    "a": 6378206.400 * 3937 / 1200, "invf": 294.97870,
    "lat1": 28 + 23 / 60, "lat2": 30 + 17 / 60, "lat0": 27 + 50 / 60, "lon0": -99.0,
    "fe": 2000000.00, "fn": 0.00,
    "point": {"lat": 28.5, "lon": -96.0},
    "expected": {"E": 2963503.91, "N": 254759.80, "n": 0.48991263, "F": 2.31154807, "rF": 37807441.20},
    "tolerance": {"EN": 0.01, "n": 5e-9, "F": 5e-9, "rF": 0.01},
}


def lcc_selftest():
    """Run the GN 7-2 example; {expected, got, diff, ok}."""
    g = GN7_2
    fwd = make_lcc_2sp(g["a"], g["invf"], g["lat1"], g["lat2"], g["lat0"], g["lon0"], g["fe"], g["fn"])
    east, north = fwd(g["point"]["lon"], g["point"]["lat"])
    got = {"E": east, "N": north, "n": fwd.n, "F": fwd.F, "rF": fwd.rF}
    diff = {k: got[k] - v for k, v in g["expected"].items()}
    tol = g["tolerance"]
    ok = (abs(diff["E"]) <= tol["EN"] and abs(diff["N"]) <= tol["EN"] and abs(diff["n"]) <= tol["n"]
          and abs(diff["F"]) <= tol["F"] and abs(diff["rF"]) <= tol["rF"])
    return {"test": g["about"], "point": g["point"], "expected": g["expected"],
            "got": {k: round(v, 9 if k in ("n", "F") else 4) for k, v in got.items()},
            "diff": {k: float("%.3g" % v) for k, v in diff.items()},
            "tolerance": tol, "ok": ok}


# --------------------------------------------------------------------------
# Point in polygon
# --------------------------------------------------------------------------
def point_in_rings(x, y, rings):
    """Even-odd ray casting over all rings of one record, so holes are handled. Half-open in y,
    strict in x: a point on an edge shared by two polygons falls in exactly one of them."""
    inside = False
    for ring in rings:
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


class PolygonIndex:
    """Polygons put in square buckets by their bounding boxes; find(x, y) returns the indices of
    every polygon that holds the point, lowest index first."""

    def __init__(self, polygons, cell=20000.0):
        self.cell = cell
        self.polys = {i: (bb, rings) for i, bb, rings in polygons}
        self.buckets = {}
        for i, (bb, _) in self.polys.items():
            for key in self.keys(bb):
                self.buckets.setdefault(key, []).append(i)

    def keys(self, bb):
        c = self.cell
        for kx in range(math.floor(bb[0] / c), math.floor(bb[2] / c) + 1):
            for ky in range(math.floor(bb[1] / c), math.floor(bb[3] / c) + 1):
                yield kx, ky

    def find(self, x, y):
        hits = []
        for i in self.buckets.get((math.floor(x / self.cell), math.floor(y / self.cell)), ()):
            bb, rings = self.polys[i]
            if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and point_in_rings(x, y, rings):
                hits.append(i)
        return sorted(hits)
