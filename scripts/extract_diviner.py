#!/usr/bin/env python3
"""Extract real LRO Diviner south-polar temperatures at the Malapert Massif
Artemis notional landing site (Kring et al. 2025) and validate the projection.
The same is done for two more south-pole base sites (Mons Mouton, centre from
the USGS Gazetteer; Shackleton connecting ridge, point from NASA NTRS
20240009936) and for the Shackleton crater floor (a validation point).

Data: LRO Diviner Level-4 polar temperature maps, 240 m/pixel, south polar
stereographic (sphere R = 1737.4 km, true scale at the pole), produced by
J.-P. Williams (UCLA) from all Diviner nadir RDR data:

  * Williams et al. (2019), "Seasonal polar temperatures on the Moon",
    JGR Planets 124, 2505-2521, doi:10.1029/2019JE006028 -- seasonal
    (summer / winter) min, avg and max bolometric temperature maps
    ("additional_maps", float32 GeoTIFF; data 2009-07-05 .. 2019-02-17).
  * Schorghofer & Williams (2020), PSJ 1, 54, doi:10.3847/PSJ/abb6ff --
    annual (all-season) mean and Fourier-smoothed max temperature maps from
    24 subsolar-longitude x 6 Ls bins ("24x6_240m/additional_maps",
    GMT/netCDF-3 .grd; data 2009-07-05 .. 2020-03-15).
  The underlying binned tables are archived in PDS (Diviner RDR dataset
  LRO-L-DLRE-4-RDR-V1.0, doi:10.17189/1520651; PDS4 bundle
  urn:nasa:pds:lro_diviner_derived1, collection data_derived_pcp).

Python 3.12 stdlib only.  Usage:
    python -I scripts/extract_diviner.py [--dl DIR] [--no-ascii-check]

The big rasters (~25 MB each) are downloaded into --dl (NOT the repo).
Only 5x5 pixel windows + metadata are written into data/raw/diviner/ and the
summary into data/diviner_malapert.json ("values" = Malapert; "base_points" =
every base site). If the UCLA server cannot be reached, the ASCII cross-check
of a pixel reuses the earlier result in that file when the pixel value is the same.
"""
import argparse
import datetime as _dt
import json
import math
import os
import ssl
import struct
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import tempfile
DEFAULT_DL = os.path.join(tempfile.gettempdir(), "analog-atlas-diviner-dl")  # big rasters stay outside the project
UCLA = "https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_polar"

R_MOON = 1737400.0          # m, sphere used by the products (labels: 1737.4 km)
HALF = 2                    # 5x5 window

LAYERS = [
    # key, url, kind, description
    ("summer_avg", f"{UCLA}/additional_maps/polar_south_80_summer_avg-float.tif", "tif",
     "Williams+2019: south-polar SUMMER (subsolar lat < 0) diurnal-average bolometric T"),
    ("summer_min", f"{UCLA}/additional_maps/polar_south_80_summer_min-float.tif", "tif",
     "Williams+2019: south-polar SUMMER minimum bolometric T"),
    ("summer_max", f"{UCLA}/additional_maps/polar_south_80_summer_max-float.tif", "tif",
     "Williams+2019: south-polar SUMMER maximum bolometric T"),
    ("winter_avg", f"{UCLA}/additional_maps/polar_south_80_winter_avg-float.tif", "tif",
     "Williams+2019: south-polar WINTER (subsolar lat > 0) diurnal-average bolometric T"),
    ("winter_min", f"{UCLA}/additional_maps/polar_south_80_winter_min-float.tif", "tif",
     "Williams+2019: south-polar WINTER minimum bolometric T"),
    ("winter_max", f"{UCLA}/additional_maps/polar_south_80_winter_max-float.tif", "tif",
     "Williams+2019: south-polar WINTER maximum bolometric T"),
    ("annual_mean", f"{UCLA}/24x6_240m/additional_maps/polar_south_80_Tmean.grd", "grd",
     "Schorghofer & Williams 2020: mean T averaged over ecliptic (Ls) and subsolar longitudes"),
    ("annual_max_smoothed", f"{UCLA}/24x6_240m/additional_maps/polar_south_80_Tmax.grd", "grd",
     "Schorghofer & Williams 2020: maximum T after Fourier smoothing (all seasons)"),
]
# Same seasonal maps as sparse ASCII tables (x, y normalised by R, clon, clat, tbol):
# used to cross-check the GeoTIFF georeferencing against the authors' own lat/lon.
ASCII = {k: f"{UCLA}/additional_maps/polar_south_80_{k}.txt"
         for k in ("summer_avg", "summer_min", "summer_max", "winter_avg", "winter_min", "winter_max")}

POINTS = {
    "malapert": dict(lat=-85.964, lon=357.681,
                     source="Kring et al. 2025, JGR Planets, doi:10.1029/2024JE008905 "
                            "(NASA notional Artemis landing site, Malapert Massif summit)"),
    "shackleton_floor": dict(lat=-89.67, lon=129.78,
                             source="Shackleton crater floor (validation; permanently shadowed)"),
    "mons_mouton": dict(lat=-84.60, lon=31.00,
                        source="USGS Gazetteer of Planetary Nomenclature, Mons Mouton (Feature 16070): "
                               "center latitude -84.60, center longitude 31.00 (planetographic, +East)"),
    "shackleton_ridge": dict(lat=-89.46752, lon=360.0 - 138.012788,
                             source="NASA NTRS 20240009936 (Grier et al. 2024, NASA Langley, Tall Lunar Tower "
                                    "thermal analysis): 'Shackleton Connecting Ridge (-89.46752, -138.012788 with "
                                    "elevation of 1937.83 meters)'"),
}
# Base sites: the derived annual values are written for each of these (Malapert first, as before).
BASE_POINTS = ("malapert", "mons_mouton", "shackleton_ridge")
ASCII_KEYS = ("summer_avg", "summer_min", "summer_max", "winter_avg", "winter_min", "winter_max")


# ----------------------------------------------------------------- projection
def ll_to_ps(lat, lon):
    """South polar stereographic, sphere R, scale 1 at the pole, central meridian 0.
    +y points to lon 0, +x to lon 90E (Snyder 1987 eq. 21-5/21-6, south aspect)."""
    phi, lam = math.radians(lat), math.radians(lon)
    rho = 2.0 * R_MOON * math.tan(math.pi / 4.0 + phi / 2.0)
    return rho * math.sin(lam), rho * math.cos(lam)


def ps_to_ll(x, y):
    rho = math.hypot(x, y)
    lat = -90.0 + 2.0 * math.degrees(math.atan(rho / (2.0 * R_MOON)))
    lon = math.degrees(math.atan2(x, y)) % 360.0
    return lat, lon


def gc_dist(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return R_MOON * math.acos(max(-1.0, min(1.0, c)))


# ----------------------------------------------------------------- readers
class GeoTiff:
    """Minimal reader for uncompressed, single-band float32 strip GeoTIFFs."""
    TS = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
    TF = {1: "B", 3: "H", 4: "I", 5: "I", 11: "f", 12: "d", 16: "Q"}

    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(8)
        self.bo = "<" if hdr[:2] == b"II" else ">"
        assert struct.unpack(self.bo + "H", hdr[2:4])[0] == 42, "BigTIFF not supported"
        off = struct.unpack(self.bo + "I", hdr[4:8])[0]
        self.f.seek(off)
        n = struct.unpack(self.bo + "H", self.f.read(2))[0]
        ents = self.f.read(12 * n)
        self.tags = {}
        for i in range(n):
            tag, typ, cnt = struct.unpack(self.bo + "HHI", ents[12 * i:12 * i + 8])
            raw = ents[12 * i + 8:12 * i + 12]
            size = self.TS[typ] * cnt
            if size > 4:
                self.f.seek(struct.unpack(self.bo + "I", raw)[0])
                raw = self.f.read(size)
            if typ == 2:
                val = raw[:cnt].rstrip(b"\0").decode("latin-1")
            else:
                k = cnt * (2 if typ == 5 else 1)
                val = struct.unpack(self.bo + self.TF[typ] * k, raw[:size])
            self.tags[tag] = val
        t = self.tags
        self.nx, self.ny = t[256][0], t[257][0]
        assert t[258][0] == 32 and t[339][0] == 3, "expect float32"
        assert t[259][0] == 1, "only uncompressed TIFF supported"
        assert t.get(277, (1,))[0] == 1
        self.rps = t.get(278, (self.ny,))[0]
        self.offsets, self.counts = t[273], t[279]
        sx, sy, _ = t[33550]
        i0, j0, _, X0, Y0, _ = t[33922]
        self.dx, self.dy = sx, sy
        # GTRasterTypeGeoKey: 1 = PixelIsArea (tiepoint at pixel corner)
        gk = self.geokeys()
        self.raster_type = gk.get(1025, 1)
        corner_shift = 0.0 if self.raster_type == 1 else 0.5
        self.xmin = X0 - (i0 + corner_shift) * sx      # left edge of column 0
        self.ymax = Y0 + (j0 + corner_shift) * sy      # top edge of row 0
        self.nodata = t.get(42113)

    def geokeys(self):
        k = self.tags.get(34735)
        dbl = self.tags.get(34736, ())
        asc = self.tags.get(34737, "")
        out = {}
        if not k:
            return out
        for i in range(k[3]):
            kid, loc, cnt, val = k[4 + 4 * i:8 + 4 * i]
            if loc == 0:
                out[kid] = val
            elif loc == 34736:
                out[kid] = dbl[val] if cnt == 1 else dbl[val:val + cnt]
            elif loc == 34737:
                out[kid] = asc[val:val + cnt]
        return out

    def georef(self):
        gk = self.geokeys()
        names = {1024: "GTModelType", 1025: "GTRasterType", 2057: "SemiMajorAxis_m",
                 2058: "SemiMinorAxis_m", 3075: "ProjCoordTrans(15=PolarStereographic)",
                 3081: "ProjNatOriginLat", 3082: "FalseEasting", 3083: "FalseNorthing",
                 3092: "ScaleAtNatOrigin", 3095: "StraightVertPoleLong"}
        return {
            "format": "GeoTIFF float32, uncompressed",
            "size": [self.nx, self.ny],
            "pixel_size_m": [self.dx, self.dy],
            "upper_left_corner_m": [self.xmin, self.ymax],
            "nodata": self.nodata,
            "geokeys": {names.get(k, str(k)): v for k, v in gk.items() if k in names},
        }

    def rowcol(self, x, y):
        return math.floor((self.ymax - y) / self.dy), math.floor((x - self.xmin) / self.dx)

    def center(self, r, c):
        return self.xmin + (c + 0.5) * self.dx, self.ymax - (r + 0.5) * self.dy

    def read(self, r, c):
        strip, within = divmod(r, self.rps)
        self.f.seek(self.offsets[strip] + (within * self.nx + c) * 4)
        v = struct.unpack(self.bo + "f", self.f.read(4))[0]
        return None if (math.isnan(v) or v <= 0) else v


class GmtGrd:
    """Minimal reader for GMT netCDF-3 classic grids (x, y, z) as written by
    grdwrite2.m; x/y arrays are pixel centres normalised by R (node_offset=1)."""
    SZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
    FM = {1: "b", 3: "h", 4: "i", 5: "f", 6: "d"}

    def __init__(self, path):
        self.f = open(path, "rb")
        d = self.f.read(200000)
        assert d[:3] == b"CDF", "not netCDF classic"
        ver = d[3]
        p = 8

        def u32():
            nonlocal p
            v = struct.unpack(">I", d[p:p + 4])[0]
            p += 4
            return v

        def name():
            nonlocal p
            n = u32()
            s = d[p:p + n].decode()
            p += (n + 3) // 4 * 4
            return s

        def atts():
            nonlocal p
            u32()
            n = u32()
            out = {}
            for _ in range(n):
                nm = name()
                t = u32()
                k = u32()
                raw = d[p:p + k * self.SZ[t]]
                p += (k * self.SZ[t] + 3) // 4 * 4
                out[nm] = raw.decode(errors="replace") if t == 2 else struct.unpack(">" + self.FM[t] * k, raw)
            return out

        u32()                                   # NC_DIMENSION tag
        ndims = u32()
        dims = []
        for _ in range(ndims):
            dn = name()
            dims.append((dn, u32()))
        self.gatts = atts()
        u32()
        nv = u32()
        self.vars = {}
        for _ in range(nv):
            nm = name()
            ids = [u32() for _ in range(u32())]
            a = atts()
            t = u32()
            u32()
            beg = u32() if ver == 1 else struct.unpack(">Q", d[p:p + 8])[0]
            if ver != 1:
                p += 8
            self.vars[nm] = dict(dims=[dims[i] for i in ids], atts=a, type=t, begin=beg)
        self.xs = self._vec("x")
        self.ys = self._vec("y")
        z = self.vars["z"]
        assert [dn for dn, _ in z["dims"]] == ["y", "x"] and z["type"] == 5
        self.nx, self.ny = len(self.xs), len(self.ys)
        self.dxn = (self.xs[-1] - self.xs[0]) / (self.nx - 1)
        self.dyn = (self.ys[-1] - self.ys[0]) / (self.ny - 1)

    def _vec(self, nm):
        v = self.vars[nm]
        n = v["dims"][0][1]
        self.f.seek(v["begin"])
        return struct.unpack(">%d%s" % (n, self.FM[v["type"]]), self.f.read(n * self.SZ[v["type"]]))

    def georef(self):
        return {
            "format": "GMT netCDF-3 classic grid (x, y pixel centres normalised by R=1737.4 km)",
            "size": [self.nx, self.ny],
            "pixel_size_m": [self.dxn * R_MOON, abs(self.dyn) * R_MOON],
            "x_range_norm": [self.xs[0], self.xs[-1]],
            "y_range_norm": [self.ys[0], self.ys[-1]],
            "row0_is": "south (y increasing)" if self.dyn > 0 else "north (y decreasing)",
            "global_attributes": self.gatts,
            "z_attributes": self.vars["z"]["atts"],
        }

    def rowcol(self, x, y):
        # rows indexed so that row 0 is the TOP (north, +y) like the GeoTIFF,
        # mapped internally to the file's storage order.
        xn, yn = x / R_MOON, y / R_MOON
        c = round((xn - self.xs[0]) / self.dxn)
        k = round((yn - self.ys[0]) / self.dyn)        # storage row
        return (self.ny - 1 - k) if self.dyn > 0 else k, c

    def _krow(self, r):
        return (self.ny - 1 - r) if self.dyn > 0 else r

    def center(self, r, c):
        return self.xs[c] * R_MOON, self.ys[self._krow(r)] * R_MOON

    def read(self, r, c):
        k = self._krow(r)
        self.f.seek(self.vars["z"]["begin"] + (k * self.nx + c) * 4)
        v = struct.unpack(">f", self.f.read(4))[0]
        return None if (math.isnan(v) or v <= 0) else v


# ----------------------------------------------------------------- helpers
def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
        return
    print("downloading", url)
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=600, context=SSL_CTX) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, path)


def _ssl_ctx():
    # luna1.diviner.ucla.edu (old Apache) offers a 1024-bit DH key that OpenSSL 3
    # rejects at the default security level; relax it for these public downloads.
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    return ctx


SSL_CTX = _ssl_ctx()


def http_range(url, a, b):
    req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b}"})
    with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
        total = None
        cr = r.headers.get("Content-Range")
        if cr and "/" in cr:
            total = int(cr.split("/")[1])
        return r.read(), total


def ascii_lookup(url, tif, r, c):
    """Binary-search the authors' sparse ASCII table (sorted by y desc, x asc,
    fixed-width lines) for pixel (r, c) of the GeoTIFF grid; return its row."""
    head, total = http_range(url, 0, 400)
    first_nl = head.index(b"\n")
    second_nl = head.index(b"\n", first_nl + 1)
    hdr_len = first_nl + 1
    L = second_nl - first_nl
    n = (total - hdr_len) // L
    dn = tif.dx / R_MOON

    def key_at(i):
        raw, _ = http_range(url, hdr_len + i * L, hdr_len + (i + 1) * L - 1)
        parts = [float(s) for s in raw.decode().strip().split(",")]
        x, y = parts[0], parts[1]
        rr = math.floor((tif.ymax / R_MOON - y) / dn)
        cc = math.floor((x - tif.xmin / R_MOON) / dn)
        return (rr, cc), parts

    lo, hi = 0, n - 1
    target = (r, c)
    while lo < hi:
        mid = (lo + hi) // 2
        k, _ = key_at(mid)
        if k < target:
            lo = mid + 1
        else:
            hi = mid
    k, parts = key_at(lo)
    if k != target:
        return {"found": False, "nearest_key": list(k)}
    return {"found": True, "x_norm": parts[0], "y_norm": parts[1], "clon": parts[2],
            "clat": parts[3], "tbol_K": parts[4], "line_index": lo, "line_bytes": L}


def stats(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return dict(n=0)
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    return dict(n=len(v), mean=round(m, 2), min=round(min(v), 2), max=round(max(v), 2), std=round(sd, 2))


def r2(v):
    return None if v is None else round(v, 2)


def k2c(v):
    return None if v is None else round(v - 273.15, 2)


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dl", default=DEFAULT_DL, help="directory for the big rasters")
    ap.add_argument("--no-ascii-check", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.dl, exist_ok=True)
    rawdir = os.path.join(ROOT, "data", "raw", "diviner")
    os.makedirs(rawdir, exist_ok=True)

    readers, files_meta = {}, {}
    for key, url, kind, desc in LAYERS:
        path = os.path.join(args.dl, url.rsplit("/", 1)[1])
        download(url, path)
        rd = GeoTiff(path) if kind == "tif" else GmtGrd(path)
        readers[key] = rd
        files_meta[key] = dict(url=url, description=desc, bytes=os.path.getsize(path),
                               georef=rd.georef())

    results = {}
    for pname, pt in POINTS.items():
        x, y = ll_to_ps(pt["lat"], pt["lon"])
        res = dict(lat=pt["lat"], lon_east=pt["lon"], x_m=round(x, 2), y_m=round(y, 2), layers={})
        for key, rd in readers.items():
            r, c = rd.rowcol(x, y)
            cx, cy = rd.center(r, c)
            clat, clon = ps_to_ll(cx, cy)
            win = [[rd.read(rr, cc) for cc in range(c - HALF, c + HALF + 1)]
                   for rr in range(r - HALF, r + HALF + 1)]
            flat = [v for row in win for v in row]
            res["layers"][key] = dict(
                row=r, col=c,
                pixel_center_latlon=[round(clat, 5), round(clon, 4)],
                point_to_pixel_center_m=round(gc_dist(pt["lat"], pt["lon"], clat, clon), 1),
                center_K=r2(rd.read(r, c)),
                window_5x5=dict(rows=[r - HALF, r + HALF], cols=[c - HALF, c + HALF],
                                values_K=[[r2(v) for v in row] for row in win],
                                stats_K=stats(flat)),
            )
        results[pname] = res

    # ---- independent cross-check against the authors' ASCII tables (own clon/clat)
    out_path = os.path.join(ROOT, "data", "diviner_malapert.json")
    try:
        with open(out_path, encoding="utf-8") as f:
            prev = json.load(f)
        prev_checks = prev["validation"]["ascii_table_crosscheck"]["checks"]
        prev_date = prev.get("fetched")
    except (OSError, ValueError, KeyError, TypeError):
        prev_checks, prev_date = {}, None
    ascii_checks = {}
    if not args.no_ascii_check:
        todo = [(p, k) for p in BASE_POINTS for k in ASCII_KEYS] + [("shackleton_floor", k) for k in ("summer_avg", "summer_max")]
        down = None                     # after one failed connection, do not wait for the server again
        for pname, key in todo:
            lay = results[pname]["layers"][key]
            try:
                if down:
                    raise down
                a = ascii_lookup(ASCII[key], readers[key], lay["row"], lay["col"])
            except Exception as e:      # network problems should not kill the run
                if isinstance(e, (OSError, TimeoutError)):
                    down = e
                a = {"found": False, "error": repr(e)}
                # Same raster pixel and value as an earlier run: keep that run's check, and say so.
                old = prev_checks.get(f"{pname}/{key}", {})
                if (old.get("found") and old.get("tif_center_K") == lay["center_K"]
                        and gc_dist(old["clat"], old["clon"], *lay["pixel_center_latlon"]) < 1.0):
                    a = dict(old, reused_from_run=old.get("reused_from_run") or prev_date,
                             reuse_reason="UCLA server not reachable in this run: " + a["error"])
            if a.get("found") and "reused_from_run" not in a:
                a["url"] = ASCII[key]
                a["tif_center_K"] = lay["center_K"]
                a["abs_diff_K"] = None if lay["center_K"] is None else round(abs(a["tbol_K"] - lay["center_K"]), 4)
                pt = POINTS[pname]
                a["authors_pixel_center_to_point_m"] = round(gc_dist(pt["lat"], pt["lon"], a["clat"], a["clon"]), 1)
                a["authors_vs_our_pixel_center_m"] = round(gc_dist(a["clat"], a["clon"], *lay["pixel_center_latlon"]), 2)
            ascii_checks[f"{pname}/{key}"] = a
            print("ascii check", pname, key, a)

    # ---- derived annual values at each base site (Malapert's are the top-level "values", as before)
    c = lambda d, k: d[k]["center_K"]

    def base_values(m):
        mins = [c(m, "summer_min"), c(m, "winter_min")]
        maxs = [c(m, "summer_max"), c(m, "winter_max")]
        return {
            "mean_K": c(m, "annual_mean"),
            "mean_C": k2c(c(m, "annual_mean")),
            "mean_source": "annual_mean layer (Schorghofer & Williams 2020 Tmean: average over 24 subsolar "
                           "longitudes x 6 Ls seasons, Diviner 2009-07-05..2020-03-15)",
            "mean_of_summer_and_winter_avg_K": r2((c(m, "summer_avg") + c(m, "winter_avg")) / 2),
            "min_K": r2(min(v for v in mins if v is not None)),
            "min_C": k2c(min(v for v in mins if v is not None)),
            "min_source": "min(summer_min, winter_min) of Williams et al. 2019 seasonal maps",
            "max_K": r2(max(v for v in maxs if v is not None)),
            "max_C": k2c(max(v for v in maxs if v is not None)),
            "max_source": "max(summer_max, winter_max) of Williams et al. 2019 seasonal maps",
            "max_fourier_smoothed_K": c(m, "annual_max_smoothed"),
            "summer_range_K": r2(c(m, "summer_max") - c(m, "summer_min")),
            "summer_range_source": "summer_max - summer_min of Williams et al. 2019 seasonal maps "
                                   "(the 'daily swing' value of the base-site targets)",
            "summer_avg_K": c(m, "summer_avg"), "summer_min_K": c(m, "summer_min"), "summer_max_K": c(m, "summer_max"),
            "winter_avg_K": c(m, "winter_avg"), "winter_min_K": c(m, "winter_min"), "winter_max_K": c(m, "winter_max"),
            "albedo": None,
            "albedo_note": "No albedo layer exists in the Diviner polar temperature product set "
                           "(Williams 2019 / Schorghofer & Williams 2020 / PDS PCP & PRP); not extracted.",
            "pixel": {"row": m["summer_avg"]["row"], "col": m["summer_avg"]["col"],
                      "grid": "2533 x 2533, row 0 = top (+y, toward lon 0), col 0 = left (-x, toward lon 270E)",
                      "pixel_center_latlon": m["summer_avg"]["pixel_center_latlon"],
                      "point_to_pixel_center_m": m["summer_avg"]["point_to_pixel_center_m"]},
            "window_5x5_stats_K": {k: v["window_5x5"]["stats_K"] for k, v in m.items()},
        }

    m = results["malapert"]["layers"]
    s = results["shackleton_floor"]["layers"]
    values = base_values(m)
    base_points = {}
    for pname in BASE_POINTS:
        pt = POINTS[pname]
        base_points[pname] = {
            "point": {"lat": pt["lat"], "lon": pt["lon"], "lon_signed": round((pt["lon"] + 180.0) % 360.0 - 180.0, 6),
                      "coordSource": pt["source"], "x_m": results[pname]["x_m"], "y_m": results[pname]["y_m"]},
            "values": base_values(results[pname]["layers"]),
        }

    # ---- validation
    shack_ok = all((s[k]["center_K"] is not None and s[k]["center_K"] < 110) for k in s)
    sa, wa = c(m, "summer_avg"), c(m, "winter_avg")
    pub_ok = abs(sa - 180) <= 15 and abs(wa - 130) <= 15
    same_pixel = len({(v["row"], v["col"]) for v in m.values()}) == 1
    same_pixel_base = {p: len({(v["row"], v["col"]) for v in results[p]["layers"].values()}) == 1 for p in BASE_POINTS}
    # A pixel that could not be looked up is listed in not_checked; it does not count as a pass.
    checked = [a for a in ascii_checks.values() if a.get("found")]
    not_checked = [k for k, a in ascii_checks.items() if not a.get("found")]
    ascii_ok = (all(a["abs_diff_K"] is not None and a["abs_diff_K"] < 0.01
                    and a["authors_vs_our_pixel_center_m"] < 1.0 for a in checked)
                if checked else None)
    # neighbourhood context for the published-value comparison
    def box_stats(key, half):
        rd = readers[key]
        r0, c0 = m[key]["row"], m[key]["col"]
        v = sorted(t for t in (rd.read(rr, cc) for rr in range(r0 - half, r0 + half + 1)
                               for cc in range(c0 - half, c0 + half + 1)) if t is not None)
        return dict(box_km=round((2 * half + 1) * 0.24, 2), n=len(v), min=r2(v[0]), p10=r2(v[len(v) // 10]),
                    median=r2(v[len(v) // 2]), p90=r2(v[9 * len(v) // 10]), max=r2(v[-1]))
    neighbourhood = {k: {f"{2 * h + 1}x{2 * h + 1}": box_stats(k, h) for h in (2, 5, 10, 20)}
                     for k in ("summer_avg", "winter_avg")}

    # orientation test: Shackleton floor vs the same point under mirrored/rotated
    # conventions (x->-x, y->-y, both).  Only the correct convention is cold.
    sm = readers["summer_max"]
    orient = {}
    for label, lon in (("correct", 129.78), ("mirror_x(lon->-lon)", 230.22),
                       ("mirror_y(lon->180-lon)", 50.22), ("rotate_180", 309.78)):
        xx, yy = ll_to_ps(-89.67, lon)
        rr, cc = sm.rowcol(xx, yy)
        win = [sm.read(a, b) for a in range(rr - 2, rr + 3) for b in range(cc - 2, cc + 3)]
        orient[label] = dict(summer_max_center_K=r2(sm.read(rr, cc)),
                             summer_max_5x5_max_K=r2(max(w for w in win if w is not None)))
    orient_ok = all(v["summer_max_5x5_max_K"] > 110 for k, v in orient.items() if k != "correct") \
        and orient["correct"]["summer_max_5x5_max_K"] < 110

    # zonal sanity: hemisphere season labels (summer must be warmer on average)
    zonal = {}
    for lat in (-82.0, -86.0, -88.0):
        acc = {"summer_avg": [], "winter_avg": []}
        for i in range(720):
            xx, yy = ll_to_ps(lat, i * 0.5)
            for k in acc:
                v = readers[k].read(*readers[k].rowcol(xx, yy))
                if v is not None:
                    acc[k].append(v)
        zonal[str(lat)] = {k: r2(sum(v) / len(v)) for k, v in acc.items()}
    zonal_ok = all(z["summer_avg"] > z["winter_avg"] for z in zonal.values())

    validation = {
        "orientation_test_shackleton": {"results": orient, "pass": orient_ok,
                                        "criterion": "only the documented convention puts a cold (<110 K max) "
                                                     "5x5 window on the Shackleton floor"},
        "zonal_season_label_check": {"zonal_mean_K": zonal, "pass": zonal_ok,
                                     "criterion": "south 'summer' (subsolar lat < 0) warmer than 'winter' zonally"},
        "shackleton_floor": {
            "point": [POINTS["shackleton_floor"]["lat"], POINTS["shackleton_floor"]["lon"]],
            "center_K": {k: v["center_K"] for k, v in s.items()},
            "window_5x5_stats_K": {k: v["window_5x5"]["stats_K"] for k, v in s.items()},
            "criterion": "all layers < 110 K (permanently shadowed crater floor)",
            "pass": shack_ok,
        },
        "malapert_vs_published": {
            "published": "~180 K summer, ~130 K winter (Wueller et al. 2025 citing Williams et al. 2019)",
            "summer_avg_K": sa, "winter_avg_K": wa,
            "summer_avg_window_mean_K": m["summer_avg"]["window_5x5"]["stats_K"].get("mean"),
            "winter_avg_window_mean_K": m["winter_avg"]["window_5x5"]["stats_K"].get("mean"),
            "criterion": "|summer_avg-180| <= 15 K and |winter_avg-130| <= 15 K",
            "pass": pub_ok,
            "neighbourhood_stats_K": neighbourhood,
            "interpretation": (
                "The centre-pixel summer average (~155 K) is ~25 K below the quoted ~180 K, while the winter "
                "average (~145 K) is ~15 K above ~130 K. This is NOT a georeferencing error: the authors' own "
                "ASCII tables give the identical temperatures for this pixel and place its centre (clat/clon) "
                "within 0.1 m of ours, the Shackleton floor is cold only under the documented orientation, and "
                "zonal means show the season labels are right. The summit sits on a ridge crest with very steep "
                "temperature gradients (5x5 window: summer avg 137-167 K, winter avg 90-171 K); the pole-facing "
                "flank 0.5-1 km away is ~165-177 K in summer and ~90 K in winter; over a ~10 km box the "
                "summer-avg 90th percentile is ~181 K and the winter-avg median ~129 K. The quoted 180/130 K are therefore most likely rounded massif-scale / "
                "sun-facing-slope values rather than the value of the single 240 m summit pixel. The full text of "
                "Wueller et al. 2025 (doi:10.1029/2025JE009127) could not be retrieved (HTTP 403) to confirm "
                "which statistic/area they quote."),
        },
        "tif_vs_grd_same_pixel": same_pixel,
        "tif_vs_grd_same_pixel_base_points": same_pixel_base,
        "ridge_point_on_pixel_centre": {
            "point_to_pixel_center_m": results["shackleton_ridge"]["layers"]["summer_avg"]["point_to_pixel_center_m"],
            "criterion": "NTRS 20240009936 says its ridge point was chosen to match LRO seasonal temperature data; "
                         "if our grid is right, the point falls on one of our pixel centres (< 1 m)",
            "pass": results["shackleton_ridge"]["layers"]["summer_avg"]["point_to_pixel_center_m"] < 1.0,
        },
        "ascii_table_crosscheck": {
            "description": "Same pixel looked up (HTTP range requests) in the authors' ASCII tables, which carry "
                           "their own pixel-centre clon/clat; tbol must equal the GeoTIFF value and the authors' "
                           "pixel centre must equal ours. 'pass' covers the pixels that were looked up; "
                           "'not_checked' lists those that could not be (server not reachable).",
            "pass": ascii_ok, "not_checked": not_checked, "checks": ascii_checks,
        },
        "projection_roundtrip_m": round(gc_dist(-85.964, 357.681,
                                                *ps_to_ll(*ll_to_ps(-85.964, 357.681))), 6),
    }

    out = {
        "source": {
            "dataset": "LRO Diviner Lunar Radiometer Level-4 polar temperature maps (UCLA Diviner team, J.-P. Williams)",
            "references": [
                "Williams, J.-P. et al. (2019) Seasonal polar temperatures on the Moon, JGR Planets 124, 2505-2521, doi:10.1029/2019JE006028",
                "Schorghofer, N. & Williams, J.-P. (2020) Mapping of ice storage processes on the Moon with time-dependent temperatures, PSJ 1, 54, doi:10.3847/PSJ/abb6ff",
            ],
            "doi": "10.17189/1520651",
            "doi_note": "PDS dataset DOI resolves to LRO-L-DLRE-4-RDR-V1.0 (Diviner RDR). The binned polar "
                        "cumulative tables behind these maps are in PDS4 bundle urn:nasa:pds:lro_diviner_derived1, "
                        "collection data_derived_pcp (https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_pcp/). "
                        "The gridded min/avg/max maps used here are the team's derived maps distributed by UCLA "
                        f"({UCLA}/), not separately PDS-archived.",
            "files": {k: {"url": v["url"], "description": v["description"], "bytes": v["bytes"]} for k, v in files_meta.items()},
            "ascii_crosscheck_files": ASCII,
            "product_version": "Williams+2019 maps: Diviner nadir RDR 2009-07-05..2019-02-17, GeoTIFF export 2023-02-07 "
                               "(grids created 2019-11-04); 24x6 Tmean/Tmax: RDR 2009-07-05..2020-03-15, grids 2021-11-13; "
                               "PDS PCP labels: PRODUCT_VERSION_ID 1, calibration software 4.0",
            "resolution": "240.036 m/pixel (polar stereographic, true scale at the pole), 2533x2533 grid, 80-90 S",
            "projection": "South polar stereographic on a sphere R=1737.4 km, latitude of origin -90, central meridian 0, "
                          "scale factor 1 at pole, false E/N 0; x = 2R tan(pi/4+lat/2) sin(lon), y = 2R tan(pi/4+lat/2) cos(lon); "
                          "GeoTIFF PixelIsArea, UL corner (-304005.54 m, +304005.54 m); planetocentric lat, east lon",
            "units": "Kelvin (float32), no scaling factor; nodata = NaN (GeoTIFF GDAL_NODATA 'nan', netCDF NaN)",
            "georef": {k: v["georef"] for k, v in files_meta.items()},
        },
        "point": {"lat": POINTS["malapert"]["lat"], "lon": POINTS["malapert"]["lon"], "lon_signed": -2.319,
                  "coordSource": POINTS["malapert"]["source"],
                  "x_m": results["malapert"]["x_m"], "y_m": results["malapert"]["y_m"]},
        "values": values,
        "base_points": base_points,
        "method": (
            "Lat/lon converted to south polar stereographic x,y with the products' own documented projection "
            "(sphere 1737.4 km, k0=1 at pole). GeoTIFF row = floor((ymax - y)/240.036), col = floor((x - xmin)/240.036); "
            "for the netCDF .grd maps the pixel is located by its own x/y centre arrays (y stored south-to-north, flipped). "
            "Centre pixel = pixel containing the point; a 5x5 window (1.2 x 1.2 km) is read around it. Values are "
            "bolometric brightness temperatures (Diviner channels 3-9), no scaling. Annual min/max combine the "
            "Williams+2019 summer and winter min/max maps; annual mean is the Schorghofer & Williams 2020 Tmean map. "
            "All values are point/pixel measurements on a 240 m grid; diurnal/seasonal averages, not a single epoch."
        ),
        "points_detail": results,
        "validation": validation,
        "fetched": _dt.date.today().isoformat(),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for pname, res in results.items():
        with open(os.path.join(rawdir, f"{pname}_5x5_windows.json"), "w", encoding="utf-8") as f:
            json.dump({"point": POINTS[pname], "x_m": res["x_m"], "y_m": res["y_m"],
                       "layers": res["layers"],
                       "files": {k: files_meta[k]["url"] for k in res["layers"]},
                       "note": "5x5 windows of the 240 m Diviner polar maps; row index increases southward "
                               "in map (top-down) order; values in K; null = no data"}, f, indent=1)
    with open(os.path.join(rawdir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in files_meta.items()}, f, indent=1)

    print(json.dumps({"values": {p: {k: v for k, v in b["values"].items() if not isinstance(v, dict)}
                                 for p, b in base_points.items()},
                      "validation": {k: (v.get("pass") if isinstance(v, dict) and "pass" in v else v)
                                     for k, v in validation.items()},
                      "ascii_not_checked": not_checked}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
