#!/usr/bin/env python3
"""Extract real LOLA illumination values at the three south-pole base sites
(Malapert, Mons Mouton, Shackleton connecting ridge), with the Shackleton crater
floor as a validation point.

Data: NASA PDS Geosciences Node, LRO LOLA archive, EXTRAS/ILLUMINATION
(Mazarico et al. 2011, Icarus 211, 1066-1081, doi:10.1016/j.icarus.2010.10.030),
release 201608, south pole, polar stereographic (sphere R = 1737.4 km):

  * AVGVISIB_*S_*_201608        average illumination by the solar disc
                                (share of time steps in sunlight, 0..1)
  * AVGVISIB_*S_*_201608_EARTH  the same for the Earth disc (Earth in view)
  * LPSR_*S_*_201608            permanently shadowed regions (1 = PSR)

Both the 60 m maps (85S, used for the values) and the 120 m maps (75S, a
cross-check) are read. Each label states the scaling used here:
  AVERAGE_VISIBILITY = DN * 0.00004        PERMANENT_SHADOW = DN * 0.000025 + 0.5

Projection check: the PSR map must be 1 at the centres of known shadowed craters
(Shackleton, Haworth, Faustini, Shoemaker, Cabeus); the script stops if it is not.

Python 3.12 stdlib only. Usage:
    python -I scripts/extract_illumination.py [--dl DIR]

The rasters (51-116 MB each) are downloaded into --dl (NOT the repo). Only 5x5
windows + label facts go to data/raw/illumination/, and the summary to
data/illumination.json.
"""
import argparse
import datetime as _dt
import json
import math
import os
import struct
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DL = os.path.join(os.environ.get("TEMP", "."), "lola-illumination-dl")
PDS = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/extras/illumination/img"
R_MOON = 1737400.0
HALF = 2            # 5x5 window
PSR_SEARCH_KM = 30  # nearest-PSR search radius

GRIDS = {  # name: (lines = samples, projection offset in pixels, metres per pixel)
    "85s_060m": (5058, 2528.5, 60.0),
    "75s_120m": (7624, 3811.5, 120.0),
}
LAYERS = {  # key: (file stem, scale, offset)
    "sun": ("avgvisib_{g}_201608", 0.00004, 0.0),
    "earth": ("avgvisib_{g}_201608_earth", 0.00004, 0.0),
    "psr": ("lpsr_{g}_201608", 0.000025, 0.5),
}

POINTS = {  # same pins as data/targets.json and scripts/extract_diviner.py
    "malapert": (-85.964, -2.319),
    "mons-mouton": (-84.60, 31.00),
    "shackleton-ridge": (-89.46752, -138.012788),
    "southpole": (-89.67, 129.78),  # Shackleton crater floor (validation: must be PSR)
}
BASE = ("malapert", "mons-mouton", "shackleton-ridge")
# Projection check only (crater centres, USGS Gazetteer, rounded): each must fall in a PSR.
CHECK_PSR = {"Shackleton": (-89.67, 129.78), "Haworth": (-87.45, -5.07), "Faustini": (-87.3, 77.0),
             "Shoemaker": (-88.1, 44.9), "Cabeus": (-85.33, -42.13)}


def ll_to_ps(lat, lon):
    """South polar stereographic, +y toward lon 0, +x toward lon 90E (as the Diviner script)."""
    rho = 2.0 * R_MOON * math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)
    return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))


def ps_to_ll(x, y):
    rho = math.hypot(x, y)
    lat = -90.0 + 2.0 * math.degrees(math.atan(rho / (2.0 * R_MOON)))
    return lat, math.degrees(math.atan2(x, y))


def gc_dist(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(math.radians(lon2 - lon1))
    return R_MOON * math.acos(max(-1.0, min(1.0, c)))


class Img:
    """PDS3 IMG, LSB int16, no header (the labels are detached)."""

    def __init__(self, path, n, off, scale_m, a, b):
        self.f = open(path, "rb")
        self.n, self.off, self.m, self.a, self.b = n, off, scale_m, a, b
        assert os.path.getsize(path) == n * n * 2, f"unexpected size: {path}"

    def rowcol(self, x, y):
        # 0-based pixel centres; the pole is at (off, off). Line grows toward -y.
        return round(self.off - y / self.m), round(self.off + x / self.m)

    def center(self, r, c):
        return (c - self.off) * self.m, (self.off - r) * self.m

    def row(self, r, c0, c1):
        self.f.seek((r * self.n + c0) * 2)
        k = c1 - c0
        return [v * self.a + self.b for v in struct.unpack(f"<{k}h", self.f.read(2 * k))]

    def read(self, r, c):
        return self.row(r, c, c + 1)[0]


def download(url, path):
    if os.path.exists(path):
        return
    print("downloading", url)
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=600) as r, open(tmp, "wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, path)


def label_facts(path):
    keys = ("PRODUCT_ID", "START_TIME", "STOP_TIME", "PRODUCT_CREATION_TIME", "MAP_SCALE",
            "SCALING_FACTOR", "OFFSET", "LINE_PROJECTION_OFFSET", "LINES")
    out = {}
    with open(path, encoding="latin-1") as f:
        text = f.read()
    for line in text.splitlines():
        k = line.split("=")[0].strip()
        if k in keys and k not in out:
            out[k] = line.split("=", 1)[1].strip().strip('"')
    d0 = text.find("DESCRIPTION")
    out["DESCRIPTION"] = " ".join(text[d0:text.find('"', text.find('"', d0) + 1)].split('"', 1)[1].split())
    return out


def psr_pixels(img, x, y, km):
    """All PSR pixels within km of (x, y), nearest first, as (map distance m, row, col)."""
    r0, c0 = img.rowcol(x, y)
    h = int(km * 1000 / img.m)
    found = []
    for r in range(max(0, r0 - h), min(img.n, r0 + h + 1)):
        vals = img.row(r, max(0, c0 - h), min(img.n, c0 + h + 1))
        for i, v in enumerate(vals):
            if v >= 0.5:
                c = max(0, c0 - h) + i
                px, py = img.center(r, c)
                found.append((math.hypot(px - x, py - y), r, c))
    return sorted(found)


def psr_hit(img, x, y, r, c, area=None):
    lat0, lon0 = ps_to_ll(x, y)
    plat, plon = ps_to_ll(*img.center(r, c))
    out = {"distance_m": round(gc_dist(lat0, lon0, plat, plon), 1), "pixel": [r, c],
           "pixel_center_latlon": [round(plat, 5), round(plon, 4)]}
    if area is not None:
        out["patch_km2"] = area
    return out


def nearest_psr(img, x, y, km, min_km2=0.0):
    """The nearest PSR pixel within km whose connected patch is at least min_km2 (0 = any pixel)."""
    done = set()
    for _, r, c in psr_pixels(img, x, y, km):
        if (r, c) in done:
            continue
        area, _, members = psr_patch(img, r, c)
        done |= members
        if area >= min_km2:
            return psr_hit(img, x, y, r, c, area)
    return None


def psr_patch(img, r, c, cap=200000):
    """Size (km2) of the connected PSR patch (8-neighbour) that holds pixel (r, c), capped flag, members."""
    seen = {(r, c)}
    todo = [(r, c)]
    while todo and len(seen) < cap:
        rr, cc = todo.pop()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                q = (rr + dr, cc + dc)
                if q in seen or not (0 <= q[0] < img.n and 0 <= q[1] < img.n):
                    continue
                if img.read(*q) >= 0.5:
                    seen.add(q)
                    todo.append(q)
    return round(len(seen) * (img.m / 1000) ** 2, 3), len(seen) >= cap, seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dl", default=DEFAULT_DL, help="directory for the big rasters")
    args = ap.parse_args()
    os.makedirs(args.dl, exist_ok=True)
    imgs, labels = {}, {}
    for g, (n, off, m) in GRIDS.items():
        for key, (stem, a, b) in LAYERS.items():
            name = stem.format(g=g)
            for ext in ("lbl", "img"):
                download(f"{PDS}/{name}.{ext}", os.path.join(args.dl, f"{name}.{ext}"))
            labels[name] = label_facts(os.path.join(args.dl, f"{name}.lbl"))
            assert float(labels[name]["SCALING_FACTOR"]) == a and float(labels[name]["OFFSET"]) == b
            assert int(labels[name]["LINES"]) == n and float(labels[name]["LINE_PROJECTION_OFFSET"].split()[0]) == off
            imgs[(g, key)] = Img(os.path.join(args.dl, f"{name}.img"), n, off, m, a, b)

    # Projection check against known permanently shadowed crater floors.
    check = {}
    for g in GRIDS:
        check[g] = {k: imgs[(g, "psr")].read(*imgs[(g, "psr")].rowcol(*ll_to_ps(*v))) >= 0.5 for k, v in CHECK_PSR.items()}
        if not all(check[g].values()):
            sys.exit(f"projection check failed on {g}: {check[g]}")

    out_raw = os.path.join(ROOT, "data", "raw", "illumination")
    os.makedirs(out_raw, exist_ok=True)
    points = {}
    for pid, (lat, lon) in POINTS.items():
        x, y = ll_to_ps(lat, lon)
        rec = {"point": {"lat": lat, "lon": lon, "x_m": round(x, 2), "y_m": round(y, 2)}, "grids": {}}
        for g in GRIDS:
            gi = {}
            for key in LAYERS:
                img = imgs[(g, key)]
                r, c = img.rowcol(x, y)
                plat, plon = ps_to_ll(*img.center(r, c))
                win = [[round(v, 4) for v in img.row(rr, c - HALF, c + HALF + 1)] for rr in range(r - HALF, r + HALF + 1)]
                flat = [v for row in win for v in row]
                gi[key] = {"row": r, "col": c, "pixel_center_latlon": [round(plat, 5), round(plon, 4)],
                           "point_to_pixel_center_m": round(gc_dist(lat, lon, plat, plon), 1),
                           "center": round(img.read(r, c), 4), "window_5x5": win,
                           "window_min": min(flat), "window_max": max(flat)}
            gi["nearest_psr"] = nearest_psr(imgs[(g, "psr")], x, y, PSR_SEARCH_KM)
            gi["nearest_psr_1km2"] = nearest_psr(imgs[(g, "psr")], x, y, PSR_SEARCH_KM, 1.0)
            rec["grids"][g] = gi
        points[pid] = rec
        with open(os.path.join(out_raw, f"{pid}_5x5_windows.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
            f.write("\n")
        print(pid, {g: (rec["grids"][g]["sun"]["center"], rec["grids"][g]["earth"]["center"],
                        rec["grids"][g]["psr"]["center"], (rec["grids"][g]["nearest_psr"] or {}).get("distance_m"))
                    for g in GRIDS})

    if points["southpole"]["grids"]["85s_060m"]["psr"]["center"] < 0.5:
        sys.exit("validation failed: the Shackleton floor pin is not in a PSR")
    meta = {"source": "NASA PDS Geosciences Node, LRO LOLA EXTRAS/ILLUMINATION release 201608 (Mazarico et al. 2011)",
            "base_url": PDS, "fetched": _dt.date.today().isoformat(), "labels": labels,
            "projection_check_psr": check, "psr_search_km": PSR_SEARCH_KM}
    with open(os.path.join(out_raw, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
        f.write("\n")

    g = "85s_060m"
    summary = {
        "about": "LOLA average illumination at the base-site pins (60 m pixel that holds the pin; 5x5 window range; "
                 "the 120 m map as a cross-check). sun = share of time steps when any part of the Sun is above the "
                 "local horizon; earth = the same for the Earth; nearest PSR = distance to the nearest permanently "
                 "shadowed 60 m pixel (any size, and in a shadowed patch of at least 1 km2). Made by scripts/extract_illumination.py.",
        "source": {"label": "Mazarico et al. 2011, Icarus 211: Illumination conditions of the lunar polar regions using LOLA topography",
                   "url": "https://doi.org/10.1016/j.icarus.2010.10.030", "data": PDS,
                   "quote": labels["avgvisib_85s_060m_201608"]["DESCRIPTION"]},
        "fetched": meta["fetched"],
        "points": {pid: {
            "sun": points[pid]["grids"][g]["sun"]["center"],
            "sun_window": [points[pid]["grids"][g]["sun"]["window_min"], points[pid]["grids"][g]["sun"]["window_max"]],
            "sun_120m": points[pid]["grids"]["75s_120m"]["sun"]["center"],
            "earth": points[pid]["grids"][g]["earth"]["center"],
            "earth_window": [points[pid]["grids"][g]["earth"]["window_min"], points[pid]["grids"][g]["earth"]["window_max"]],
            "psr_at_pin": points[pid]["grids"][g]["psr"]["center"] >= 0.5,
            "nearest_psr_m": (points[pid]["grids"][g]["nearest_psr"] or {}).get("distance_m"),
            "nearest_psr_patch_km2": (points[pid]["grids"][g]["nearest_psr"] or {}).get("patch_km2"),
            "nearest_psr_1km2_m": (points[pid]["grids"][g]["nearest_psr_1km2"] or {}).get("distance_m"),
            "nearest_psr_1km2_patch_km2": (points[pid]["grids"][g]["nearest_psr_1km2"] or {}).get("patch_km2"),
            "point_to_pixel_center_m": points[pid]["grids"][g]["sun"]["point_to_pixel_center_m"],
        } for pid in POINTS},
    }
    with open(os.path.join(ROOT, "data", "illumination.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(summary["points"], indent=1))


if __name__ == "__main__":
    main()
