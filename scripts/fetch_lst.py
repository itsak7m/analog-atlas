#!/usr/bin/env python3
"""Land surface temperature (LST) from NASA MODIS MOD21A2 (Terra) and MYD21A2 (Aqua), Collection 6.1,
8-day, 1 km, composites starting 2003-01-01 ... 2020-12-31, for the 19 Earth sites and the 886
Jordan screening boxes.

Usage (from the project folder; Python 3.12 standard library only, no account, no key):
    python -I scripts/fetch_lst.py --sites       # 19 sites: one point-API request per composite
    python -I scripts/fetch_lst.py --boxes       # 886 boxes: COG range reads of 3 MODIS tiles (~3 GB)
    python -I scripts/fetch_lst.py --validate    # checks (a)-(d); prints them; writes manifest.json
    python -I scripts/fetch_lst.py --sites --boxes --validate --resume   # everything, reusing earlier downloads

Options:
    --resume          reuse what an earlier (interrupted) run already fetched; without it a step starts over
    --threads N       parallel point-API requests for --sites (default 16)
    --box-threads N   parallel COG workers for --boxes (default 6)
    --cache-dir DIR   per-composite cache of the box pixels (default: <system temp>/analog-atlas-lst-cache,
                      about 0.45 GB, outside the project; safe to delete after a complete run)
    --only ID,ID      --sites: fetch only these site ids (the other sites keep their saved series)

Writes:
    data/lst.json                    per-site LST statistics (the app file for the sites)
    data/screening_lst.json          per-box LST statistics (the app file for Discover Jordan)
    data/raw/lst/sites/<id>.jsonl.gz raw point-API answers per composite (compact JSON lines, gzip)
    data/raw/lst/manifest.json       STAC item ids per tile, counts, request totals, run times, checks
    data/raw/lst/README.txt          what this is and how to rerun it

Source: Microsoft Planetary Computer's copy of the NASA LP DAAC MOD21A2/MYD21A2 v061 files (COGs).
See scripts/lst_common.py for the endpoints and the QC rule.
"""

import argparse
import array
import datetime
import gzip
import hashlib
import json
import math
import os
import pathlib
import random
import shutil
import statistics as st
import sys
import tempfile
import threading
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lst_common as lc  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITES_JSON = ROOT / "data" / "sites.json"
GRID_JSON = ROOT / "data" / "screening_jordan.json"
OUT_SITES = ROOT / "data" / "lst.json"
OUT_BOXES = ROOT / "data" / "screening_lst.json"
RAW = ROOT / "data" / "raw" / "lst"
RAW_SITES = RAW / "sites"
MANIFEST = RAW / "manifest.json"
DEFAULT_CACHE = pathlib.Path(tempfile.gettempdir()) / "analog-atlas-lst-cache"

FIRST_YEAR, LAST_YEAR = 2003, 2020
ASSETS6 = ["LST_Day_1KM", "LST_Night_1KM", "QC_Day", "QC_Night", "View_Time_Day", "View_Time_Night"]
ASSETS4 = ASSETS6[:4]
BOX_TILES = [(20, 5), (21, 5), (21, 6)]
# MODIS land/water flag at 500 m (4 sub-pixels per 1 km pixel). Used: MOD09A1 v061 sur_refl_state_500m bits 3-5.
# Checks: the same product 10 years earlier, and MOD13A1 v061 VI_Quality bits 11-13, whose in-file 'Legend'
# ("[11-13] : Land/Water Flag", 000 shallow ocean ... 111 deep ocean) defines the codes; MOD13A1 is fill (65535)
# over the deep Dead Sea and absent over Antarctica, MOD09A1 is not.
WATER_SOURCES = {
    "MOD09A1": {"collection": "modis-09A1-061", "asset": "sur_refl_state_500m", "shift": 3,
                "label": "MOD09A1 v061 sur_refl_state_500m, bits 3-5 (land/water flag)"},
    "MOD13A1": {"collection": "modis-13A1-061", "asset": "500m_16_days_VI_Quality", "shift": 11,
                "label": "MOD13A1 v061 500m_16_days_VI_Quality, bits 11-13 (Land/Water Flag)"},
}
WATER_MAIN = ("MOD09A1", "2015-07-28", "A2015209")
WATER_CHECKS = [("MOD09A1", "2005-07-28", "A2005209"), ("MOD13A1", "2015-07-28", "A2015209")]
WATER_CODES = {0: "shallow ocean", 1: "land", 2: "ocean coastline or lake shoreline", 3: "shallow inland water",
               4: "ephemeral water", 5: "deep inland water", 6: "moderate or continental ocean", 7: "deep ocean"}
WATER_SET = {0, 3, 5, 6, 7}           # permanent water codes; 1 land, 2 shoreline and 4 ephemeral are not counted
POLAR_LAT = 66.56                     # polar circles (23.44 degrees from the poles)
MIN_SHARE = 0.5                       # 'fewClear' threshold and box/pixel validity threshold

# Scout's numbers (MOD21A2/MYD21A2 C6.1 via the same point API, QC 'standard', composites 2003-2020,
# computed 2026-10-10 by the LST scout: stats_<site>_21.json, key standard_common_2003_2020). Embedded so
# check (a) does not depend on the scout's scratch files. The scout's headline Terra numbers used 2001-2020.
SCOUT = {
    "harrat": {"terra": {"day": (36.96, 827), "night": (15.23, 827), "composites": 828, "vt": (10.83, 22.07)},
               "aqua": {"day": (40.61, 826), "night": (12.69, 826), "composites": 828, "vt": (13.14, 1.79)},
               "aquaMinNight": (-4.79, "2008-01-09"), "aquaP05Night": 1.2,
               "terra2001_2020": {"day": 37.09, "night": 15.29}},
    "wadi-rum": {"terra": {"day": (34.13, 827), "night": (17.19, 827), "composites": 828, "vt": (10.81, 22.17)},
                 "aqua": {"day": (37.62, 827), "night": (15.4, 826), "composites": 827, "vt": (13.21, 1.75)},
                 "aquaMinNight": (0.17, "2008-01-09"), "aquaP05Night": 4.61,
                 "terra2001_2020": {"day": 34.29, "night": 17.24}},
}

PRODUCT = {
    "names": ["MOD21A2 (Terra) - MODIS/Terra Land Surface Temperature/3-Band Emissivity 8-Day L3 Global 1km SIN Grid V061",
              "MYD21A2 (Aqua) - MODIS/Aqua Land Surface Temperature/3-Band Emissivity 8-Day L3 Global 1km SIN Grid V061"],
    "collection": "6.1 (version 061)",
    "algorithm": "MOD21 Temperature Emissivity Separation (TES); LST and emissivity retrieved together (suits bare rock and desert, where emissivity varies)",
    "dois": ["10.5067/MODIS/MOD21A2.061", "10.5067/MODIS/MYD21A2.061"],
    "citation": [
        "Hulley, G., & Hook, S. (2021). MODIS/Terra Land Surface Temperature/3-Band Emissivity 8-Day L3 Global 1km SIN Grid V061 [Dataset]. NASA Land Processes Distributed Active Archive Center. https://doi.org/10.5067/MODIS/MOD21A2.061",
        "Hulley, G. (2021). MODIS/Aqua Land Surface Temperature/3-Band Emissivity 8-Day L3 Global 1km SIN Grid V061 [Dataset]. NASA Land Processes Distributed Active Archive Center. https://doi.org/10.5067/MODIS/MYD21A2.061",
    ],
    "citationSource": ["https://www.earthdata.nasa.gov/data/catalog/lpcloud-mod21a2-061",
                       "https://www.earthdata.nasa.gov/data/catalog/lpcloud-myd21a2-061"],
    "licence": {
        "name": "CC0 (NASA-led mission data)",
        "quote": "Unless the content is marked with a use restriction or license, data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0).",
        "url": "https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance",
        "catalogNote": "Both LP DAAC catalog pages: 'This dataset is openly shared, without restriction, in accordance with the EOSDIS Data Use and Citation Guidance.'",
    },
    "userGuide": "MOD21 C6.1 user guide (Hulley et al.), Table 12 (MxD21A2 SDS) and Table 13 (QC_Day/QC_Night bits); the same QC legend is in each COG's GDAL metadata ('QA Legend').",
    "units": {"LST": "uint16, scale 0.02 K, fill 0, valid 7500-65535", "View_Time": "uint8, scale 0.1 h (local solar time), fill 255, valid 0-240", "QC": "uint8 bit field"},
}

ACCESS = {
    "route": "Microsoft Planetary Computer (NASA LP DAAC data mirrored as COGs)",
    "collection": "modis-21A2-061 (holds both MOD21A2 and MYD21A2; property 'platform' = terra / aqua)",
    "account": "none (anonymous)",
    "endpoints": {
        "stacSearch": "POST " + lc.STAC_SEARCH,
        "pointValue": "GET " + lc.POINT_API + "?collection=modis-21A2-061&item=<id>&assets=LST_Day_1KM&assets=LST_Night_1KM&assets=QC_Day&assets=QC_Night&assets=View_Time_Day&assets=View_Time_Night",
        "sasToken": "GET " + lc.SAS_URL,
        "cogs": "https://modiseuwest.blob.core.windows.net/modis-061-cogs/<MOD21A2|MYD21A2>/<h>/<v>/<YYYYDDD>/<id>_<asset>.tif (HTTP range reads of the header and the 512 x 512 internal tiles)",
        "landWaterMask": "modis-13A1-061 (MOD13A1 v061, 500 m), asset 500m_16_days_VI_Quality, bits 11-13 'Land/Water Flag'",
    },
    "sites": "point API, the 1 km pixel that holds the site's lat/lon",
    "boxes": "COG range reads of tiles h20v05, h21v05 and h21v06; only the internal tiles that hold Jordan; nothing stored but per-composite pixel values in a cache outside the project",
}


def rel(p):
    try:
        return str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def r(x, nd=2):
    return None if x is None else round(x, nd)


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def circ_mean_hours(hs):
    if not hs:
        return None
    s = sum(math.sin(2 * math.pi * h / 24) for h in hs)
    c = sum(math.cos(2 * math.pi * h / 24) for h in hs)
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return None
    return (math.atan2(s, c) * 24 / (2 * math.pi)) % 24


def platform_of(item_id):
    return {"MOD21A2": "terra", "MYD21A2": "aqua"}[item_id.split(".")[0]]


def start_of(item_id):
    a = item_id.split(".")[1]            # AYYYYDDD
    return (datetime.date(int(a[1:5]), 1, 1) + datetime.timedelta(days=int(a[5:8]) - 1)).isoformat()


def load_manifest():
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


MERGED_KEYS = ("sites", "tileItems")     # dicts merged entry by entry
OWN_KEYS = {"about", "collection", "period", "qcRule"}   # plus every key a step sets (boxes, checks)


def save_manifest(m):
    """Merge this process's changes into manifest.json under a lock file, so a --sites run and a
    --boxes run working at the same time do not overwrite each other's entries."""
    RAW.mkdir(parents=True, exist_ok=True)
    lock = MANIFEST.with_suffix(".lock")
    for _ in range(600):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 120:   # stale lock of a killed run
                lock.unlink(missing_ok=True)
            time.sleep(0.2)
    else:
        raise SystemExit("could not lock %s" % lock)
    try:
        cur = load_manifest()
        for k in MERGED_KEYS:
            if k in m:
                cur.setdefault(k, {}).update(m[k])
        have = {(r_.get("step"), r_.get("finished")) for r_ in cur.get("runs", [])}
        for r_ in m.get("runs", []):
            if (r_.get("step"), r_.get("finished")) not in have:
                cur.setdefault("runs", []).append(r_)
        for k in OWN_KEYS:
            if k in m:
                cur[k] = m[k]
        cur["generated"] = now_iso()
        order = ["about", "generated", "collection", "period", "qcRule", "sites", "boxes", "checks", "runs", "tileItems"]
        out = {k: cur[k] for k in order if k in cur}
        out.update({k: v for k, v in cur.items() if k not in out})
        txt = json.dumps(out, indent=1, ensure_ascii=False)
        tmp = MANIFEST.with_suffix(".json.tmp")
        tmp.write_text(txt + "\n", encoding="utf-8")
        os.replace(tmp, MANIFEST)
        m.clear()
        m.update(out)
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj, indent=1):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ==============================================================================================
# Sites

def load_sites():
    return json.loads(SITES_JSON.read_text(encoding="utf-8"))["sites"]


_SAS = None


def site_items(site):
    """Tile, pixel and STAC items of a site. The row/col reported is the one of the COG's own
    geotransform (the corner values stored in the MODIS files), i.e. the pixel the point API samples:
    Holuhraun's latitude 64.85 lies exactly on a pixel edge, where the ideal grid formula (modis_tile)
    and the files' corner values (which differ by < 1 mm) pick neighbouring rows."""
    global _SAS
    h, v, grow, gcol = lc.modis_tile(site["lat"], site["lon"])
    items = lc.stac_search_tile(lc.COLLECTION, h, v, "%d-01-01T00:00:00Z" % FIRST_YEAR, "%d-12-31T23:59:59Z" % LAST_YEAR)
    kept, dup = lc.select_items(items, h, v, FIRST_YEAR, LAST_YEAR)
    if _SAS is None:
        _SAS = lc.SasToken()
    one = lc.stac_search_tile(lc.COLLECTION, h, v, "2015-07-01T00:00:00Z", "2015-07-01T23:59:59Z", assets=["LST_Day_1KM"])
    cog = lc.RemoteCOG(one[0]["assets"]["LST_Day_1KM"]["href"], _SAS)
    row, col = cog.rowcol(site["lat"], site["lon"])
    if (row, col) != (grow, gcol):
        print("  %s: on a pixel edge; file geotransform gives r%d c%d, ideal grid formula r%d c%d" % (site["id"], row, col, grow, gcol), flush=True)
    return (h, v, row, col), kept, dup, len(items)


def read_series(path):
    rows = []
    if path.exists():
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    x = json.loads(line)
                    x["p"] = platform_of(x["id"])     # the id is authoritative (one STAC item has platform '')
                    rows.append(x)
    return rows


def row_from_answer(item, ans):
    vals = ans.get("values")
    if vals is None:
        raise ValueError("no values for %s" % item["id"])
    names = [b.rsplit("_b", 1)[0] for b in ans.get("band_names", [])]
    if names and names != ASSETS6:
        raise ValueError("unexpected band order %s" % names)
    v = [None if x is None else int(round(float(x))) for x in vals]
    p = item["properties"]
    return {"id": item["id"], "p": platform_of(item["id"]), "s": p["start_datetime"][:10], "e": p["end_datetime"][:10], "v": v}


def water_item(src, h, v, date, tag, with_asset=False):
    ws = WATER_SOURCES[src]
    items = lc.stac_search_tile(ws["collection"], h, v, date + "T00:00:00Z", date + "T23:59:59Z",
                                assets=[ws["asset"]] if with_asset else ())
    items = sorted([it for it in items if it["id"].startswith("%s.%s.h%02dv%02d." % (src, tag, h, v))], key=lambda x: x["id"])
    return items[-1] if items else None


def fetch_water_codes(spec, h, v, row, col):
    """Land/water flag codes (0-7, None = fill) of the four 500 m pixels inside 1 km pixel (row, col),
    in the order (2r,2c), (2r,2c+1), (2r+1,2c), (2r+1,2c+1). Returns (item id, codes) or (None, None)."""
    src, date, tag = spec
    ws = WATER_SOURCES[src]
    it = water_item(src, h, v, date, tag)
    if it is None:
        return None, None
    codes = []
    for dr in (0, 1):
        for dc in (0, 1):
            la, lo = lc.pixel_centre(h, v, 2 * row + dr, 2 * col + dc, n=2400)
            ans = lc.point_values(ws["collection"], it["id"], lo, la, [ws["asset"]])
            q = ans["values"][0]
            codes.append(None if q is None or int(q) == 65535 else (int(q) >> ws["shift"]) & 7)
    return it["id"], codes


def run_sites(args, manifest):
    t0 = time.time()
    s0 = lc.stats_snapshot()
    sites = load_sites()
    only = set(args.only.split(",")) if args.only else None
    cache = pathlib.Path(args.cache_dir) / "sites"
    cache.mkdir(parents=True, exist_ok=True)
    RAW_SITES.mkdir(parents=True, exist_ok=True)
    msites = manifest.setdefault("sites", {})
    mtiles = manifest.setdefault("tileItems", {})

    plan = {}
    print("STAC search for %d sites ..." % len(sites), flush=True)
    for s in sites:
        if only and s["id"] not in only:
            continue
        (h, v, row, col), items, dup, nraw = site_items(s)
        tile = lc.tile_name(h, v)
        final, partial = RAW_SITES / ("%s.jsonl.gz" % s["id"]), cache / ("%s.partial.jsonl" % s["id"])
        done = {}
        if args.resume:
            for rr in read_series(final) + read_series(partial):
                done[rr["id"]] = rr
        else:
            if partial.exists():
                partial.unlink()
        want = {it["id"] for it in items}
        done = {k: x for k, x in done.items() if k in want}
        todo = [it for it in items if it["id"] not in done]
        n_t = sum(1 for it in items if it["properties"]["platform"] == "terra")
        print("  %-22s %s r%4d c%4d  items %4d (terra %d, aqua %d; dup dropped %d; STAC answered %d)  to fetch %d" % (
            s["id"], tile, row, col, len(items), n_t, len(items) - n_t, dup, nraw, len(todo)), flush=True)
        plan[s["id"]] = {"site": s, "tile": tile, "h": h, "v": v, "row": row, "col": col, "items": items,
                         "done": done, "todo": todo, "partial": partial, "final": final, "dup": dup}
        mtiles[tile] = {"terra": sorted(it["id"] for it in items if it["properties"]["platform"] == "terra"),
                        "aqua": sorted(it["id"] for it in items if it["properties"]["platform"] == "aqua")}

    jobs = [(sid, it) for sid, p in plan.items() for it in p["todo"]]
    print("point-API requests to make: %d (threads %d)" % (len(jobs), args.threads), flush=True)
    handles = {sid: open(p["partial"], "a", encoding="utf-8") for sid, p in plan.items() if p["todo"]}
    errors = []
    t1 = time.time()

    def work(job):
        sid, it = job
        s = plan[sid]["site"]
        ans = lc.point_values(lc.COLLECTION, it["id"], s["lon"], s["lat"], ASSETS6)
        return sid, row_from_answer(it, ans)

    n_ok = 0
    if jobs:
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futs = {ex.submit(work, j): j for j in jobs}
            for f in as_completed(futs):
                sid, it = futs[f]
                try:
                    sid, row = f.result()
                except Exception as e:  # keep going; --resume fills the gaps
                    errors.append((sid, it["id"], repr(e)[:200]))
                    print("  ERR %s %s %s" % (sid, it["id"], repr(e)[:160]), flush=True)
                    continue
                handles[sid].write(json.dumps(row, separators=(",", ":")) + "\n")
                plan[sid]["done"][row["id"]] = row
                n_ok += 1
                if n_ok % 500 == 0:
                    el = time.time() - t1
                    snap = lc.stats_snapshot()
                    print("  %6d/%d  %6.0f s  %.2f req/s  retries %d  http errors %d" % (
                        n_ok, len(jobs), el, n_ok / el, snap["retries"], snap["http_errors"]), flush=True)
                    for h_ in handles.values():
                        h_.flush()
    for h_ in handles.values():
        h_.close()

    # land/water mask of each site pixel
    print("land/water flag (4 x 500 m per 1 km pixel): %s; checks %s" % (WATER_MAIN, WATER_CHECKS), flush=True)
    water = {}
    for sid, p in plan.items():
        res = []
        for spec in [WATER_MAIN] + WATER_CHECKS:
            try:
                res.append(fetch_water_codes(spec, p["h"], p["v"], p["row"], p["col"]))
            except Exception as e:
                print("  water flag %s %s failed: %r" % (sid, spec, e), flush=True)
                res.append((None, None))
        water[sid] = res
        print("  %-22s %s" % (sid, " | ".join("%s %s" % x for x in res)), flush=True)

    incomplete = []
    for sid, p in plan.items():
        rows = [p["done"][it["id"]] for it in p["items"] if it["id"] in p["done"]]
        if len(rows) != len(p["items"]):
            incomplete.append(sid)
            continue
        rows.sort(key=lambda x: (x["p"], x["s"]))
        with gzip.open(p["final"], "wt", encoding="utf-8", compresslevel=9) as f:
            for rr in rows:
                f.write(json.dumps(rr, separators=(",", ":")) + "\n")
        if p["partial"].exists():
            p["partial"].unlink()
        wres = water[sid]
        msites[sid] = {
            "lat": p["site"]["lat"], "lon": p["site"]["lon"], "tile": p["tile"], "row": p["row"], "col": p["col"],
            "items": {"terra": sum(1 for x in rows if x["p"] == "terra"), "aqua": sum(1 for x in rows if x["p"] == "aqua")},
            "duplicatesDropped": p["dup"],
            "series": rel(p["final"]),
            "seriesSha256": sha256_file(p["final"]),
            "landWater": {"source": WATER_SOURCES[WATER_MAIN[0]]["label"], "item": wres[0][0], "codes": wres[0][1],
                          "checks": [{"source": WATER_SOURCES[spec[0]]["label"], "item": x[0], "codes": x[1],
                                      "agreesWhereBothSet": None if x[1] is None or wres[0][1] is None else all(
                                          a == b for a, b in zip(x[1], wres[0][1]) if a is not None and b is not None)}
                                     for spec, x in zip(WATER_CHECKS, wres[1:])]},
        }
    el = time.time() - t0
    s1 = lc.stats_snapshot()
    manifest.setdefault("runs", []).append({
        "step": "sites" + (" --only " + args.only if args.only else ""), "finished": now_iso(), "seconds": round(el, 1),
        "requests": s1["requests"] - s0["requests"], "bytes": s1["bytes"] - s0["bytes"],
        "retries": s1["retries"] - s0["retries"], "httpErrors": s1["http_errors"] - s0["http_errors"],
        "connects": s1["connects"] - s0["connects"], "threads": args.threads, "pointRequests": n_ok, "errors": len(errors)})
    save_manifest(manifest)
    print("sites: %d point answers in %.0f s; errors %d; incomplete sites %s" % (n_ok, el, len(errors), incomplete), flush=True)
    if incomplete:
        raise SystemExit("some composites failed; rerun with --sites --resume to fetch only the missing ones")
    build_sites_json(manifest)


# ---------------------------------------------------------------------------------------------
# Site statistics

def series_stats(rows, plat, which):
    """which = 0 (day) or 1 (night). Returns dict(mean_C, n, viewTime, values[(start, C)])."""
    li, qi, ti = (0, 2, 4) if which == 0 else (1, 3, 5)
    vals, vts = [], []
    for x in rows:
        if x["p"] != plat:
            continue
        v = x["v"]
        if v[li] and v[qi] is not None and v[li] > 0 and lc.qc_ok(v[qi]):
            vals.append((x["s"], lc.lst_c(v[li])))
            if v[ti] is not None and 0 <= v[ti] <= 240:
                vts.append(v[ti] * lc.VIEW_TIME_SCALE)
    return {"mean": st.mean(t for _, t in vals) if vals else None, "n": len(vals),
            "viewTime": circ_mean_hours(vts), "values": vals, "viewTimes": vts}


def month_presence(rows, plat):
    """Calendar months (1-12) in which day / night LST was produced (not fill) at least once, any QC."""
    md, mn = set(), set()
    for x in rows:
        if x["p"] != plat:
            continue
        m = int(x["s"][5:7])
        if x["v"][0]:
            md.add(m)
        if x["v"][1]:
            mn.add(m)
    return md, mn


def qc_census(rows):
    cen = defaultdict(int)
    for x in rows:
        v = x["v"]
        for k, (lv, q) in (("day", (v[0], v[2])), ("night", (v[1], v[3]))):
            q = int(q or 0)
            cen["%s mand=%d%d lstAcc=%d%d %s" % (k, (q >> 1) & 1, q & 1, (q >> 7) & 1, (q >> 6) & 1,
                                                "fill" if not lv else ("pass" if lc.qc_ok(q) else "fail"))] += 1
    return dict(sorted(cen.items()))


def site_stats(site, rows, msite):
    out = {"lat": site["lat"], "lon": site["lon"], "tile": msite["tile"], "row": msite["row"], "col": msite["col"]}
    comp = {"terra": sum(1 for x in rows if x["p"] == "terra"), "aqua": sum(1 for x in rows if x["p"] == "aqua")}
    ser = {}
    for plat in ("terra", "aqua"):
        d, n = series_stats(rows, plat, 0), series_stats(rows, plat, 1)
        ser[plat] = (d, n)
        out[plat] = {"composites": comp[plat],
                     "day": {"mean_C": r(d["mean"]), "n": d["n"], "viewTime": r(d["viewTime"])},
                     "night": {"mean_C": r(n["mean"]), "n": n["n"], "viewTime": r(n["viewTime"])}}
    (td, tn), (ad, an) = ser["terra"], ser["aqua"]
    nvalid = td["n"] + tn["n"] + ad["n"] + an["n"]
    ncomp = comp["terra"] + comp["aqua"]
    share = nvalid / (2.0 * ncomp) if ncomp else 0.0
    flags, notes = [], []

    # polar: latitude beyond a polar circle, and months with no day (or no night) retrieval at all
    amd, amn = month_presence(rows, "aqua")
    tmd, tmn = month_presence(rows, "terra")
    no_day = sorted(set(range(1, 13)) - (amd | tmd))
    no_night = sorted(set(range(1, 13)) - (amn | tmn))
    polar = abs(site["lat"]) >= POLAR_LAT
    out["polarEvidence"] = {"absLatitude": round(abs(site["lat"]), 3), "monthsWithoutDayLST": no_day,
                            "monthsWithoutNightLST": no_night}
    if polar:
        flags.append("polar")
    if share < MIN_SHARE:
        flags.append("fewClear")
    wc = msite.get("landWater", {}).get("codes")
    if wc and all(c is not None for c in wc):
        wshare = sum(1 for c in wc if c in WATER_SET) / 4.0
        out["waterShare"] = wshare
        out["landWater500m"] = [WATER_CODES[c] for c in wc]
        if wshare > 0.5:
            flags.append("water")
    else:
        out["waterShare"] = None
        out["landWater500m"] = None

    mean4 = None
    if all(x["mean"] is not None for x in (td, tn, ad, an)):
        mean4 = (td["mean"] + tn["mean"] + ad["mean"] + an["mean"]) / 4
    swing = ad["mean"] - an["mean"] if ad["mean"] is not None and an["mean"] is not None else None
    cold = min(an["values"], key=lambda x: (x[1], x[0])) if an["values"] else None
    p5 = pct([t for _, t in an["values"]], 0.05)

    if polar:
        notes.append("Polar site (|latitude| %.2f >= %.2f): the sun stays up or down for days around the solstices, so "
                     "'day' and 'night' composites are not the ~10:30/13:30 and ~22:30/01:30 overpasses of lower "
                     "latitudes; months with no day LST at all: %s; months with no night LST at all: %s. "
                     "meanSurface_C and swingSurface_C are not computed (null): day values come only from the sunlit "
                     "season and night values mostly from the dark one, so their average and difference would not be a "
                     "mean or a daily range. coldSurface_C and nightP5_C are kept: in the polar night every overpass is "
                     "a night overpass, so the coldest Aqua night composite is a real 8-day mean of dark-sky surface "
                     "temperature." % (abs(site["lat"]), POLAR_LAT, no_day or "none", no_night or "none"))
        mean4, swing = None, None
    elif no_day or no_night:
        notes.append("Months with no day LST at all: %s; with no night LST at all: %s (sun too low at the overpass, or "
                     "persistent cloud); the means over-weight the other months." % (no_day or "none", no_night or "none"))
    if "fewClear" in flags:
        notes.append("Only %.0f %% of the %d day+night values pass QC (cloud, snow edge or poor retrievals): the means are "
                     "clear-sky means of the clear composites and over-weight the clearer season." % (100 * share, 2 * ncomp))
    if "water" in flags:
        notes.append("The 1 km pixel is mostly water in the MODIS land/water flag (%d of its 4 x 500 m sub-pixels are water): "
                     "the values are lake/sea (or lake-ice) surface temperature, not ground." % int(round(out["waterShare"] * 4)))
    if mean4 is None and not polar:
        notes.append("meanSurface_C is null because at least one of the four overpass series has no valid value.")

    out.update({
        "meanSurface_C": r(mean4), "swingSurface_C": r(swing),
        "coldSurface_C": r(cold[1]) if cold else None, "coldSurfaceStart": cold[0] if cold else None,
        "nightP5_C": r(p5), "nComposites": ncomp, "validShare": round(share, 3),
        "flags": flags, "note": " ".join(notes) if notes else None,
    })
    out["_raw"] = {"mean4": mean4, "swing": swing, "cold": cold[1] if cold else None,
                   "means": {"td": td["mean"], "tn": tn["mean"], "ad": ad["mean"], "an": an["mean"]},
                   "n": {"td": td["n"], "tn": tn["n"], "ad": ad["n"], "an": an["n"]},
                   "p5": p5, "qcCensus": qc_census(rows)}
    return out


DERIVED_RULES = {
    "perOverpass": "terra/aqua day/night: mean_C = arithmetic mean of every 8-day composite of 2003-2020 whose value passes the QC rule (no monthly weighting); n = number of those composites; viewTime = circular mean of View_Time (local solar time, hours) of those composites. 'composites' = 8-day composites of that satellite found for the tile in 2003-2020 (46 a year; a few are missing in the archive).",
    "meanSurface_C": "Mean of the four overpass means (Terra ~10:30 day, Terra ~22:30 night, Aqua ~13:30 day, Aqua ~01:30 night). Clear-sky only. It is NOT a 24-hour mean: in the scout's diurnal check (NASA POWER hourly MERRA-2 skin temperature, Harrat and Wadi Rum, 2015-2017) these four times average about +2.5 to +2.8 K warmer than the true 24 h mean (Harrat +2.54 K, Wadi Rum +2.83 K), i.e. roughly +2 to +3 K.",
    "swingSurface_C": "Aqua mean day minus Aqua mean night (~13:30 minus ~01:30), in kelvin (a difference, so K = degC). It captures about 88 % of the true daily range of skin temperature (scout's diurnal check: 0.88 +/- 0.07 at both Jordan test sites), so the real daily swing is roughly swingSurface / 0.88.",
    "coldSurface_C": "The coldest valid Aqua night 8-day composite of 2003-2020; coldSurfaceStart = first day of that composite. An 8-day mean of ~01:30 values: single nights get colder (scout: the coldest single night was on average 4.2 K colder than the coldest 8-day composite at Harrat, 18 winters), and ~01:30 is about 1.7 K warmer than the pre-dawn minimum.",
    "nightP5_C": "5th percentile (linear interpolation) of all valid Aqua night composites, for information.",
    "validShare": "share of the 2 x (Terra + Aqua composites) day and night values that pass QC.",
    "flags": {
        "polar": "|latitude| >= 66.56 deg (inside a polar circle): the sun stays up or down for days, so MODIS 'day' and 'night' are not the usual overpass times; checked against the data (months with no day or no night LST at all, listed in polarEvidence). meanSurface_C and swingSurface_C are set to null there; coldSurface_C and nightP5_C are kept (polar-night composites are true night).",
        "fewClear": "fewer than 50 % of the day and night values pass QC (validShare < 0.5): the means describe the clear composites only.",
        "water": "more than half of the 1 km pixel is water in the MODIS land/water flag: at least 3 of its 4 500 m sub-pixels have code 000 shallow ocean, 011 shallow inland water, 101 deep inland water, 110 moderate/continental ocean or 111 deep ocean (001 land, 010 ocean coastline/lake shoreline and 100 ephemeral water are not counted). Flag read from MOD09A1 v061 sur_refl_state_500m bits 3-5 (8-day composite starting 2015-07-28); the code table is the 'Land/Water Flag' legend stored in MOD13A1 v061 VI_Quality (bits 11-13), which carries the same flag; both are compared in data/raw/lst/manifest.json. waterShare = share of the 4 sub-pixels that are water; landWater500m lists their codes.",
    },
    "nulls": "A value is null when it is not measured or cannot be computed honestly (see each place's note).",
}


def build_sites_json(manifest):
    sites = load_sites()
    places, missing = {}, []
    for s in sites:
        ms = manifest.get("sites", {}).get(s["id"])
        path = RAW_SITES / ("%s.jsonl.gz" % s["id"])
        if not ms or not path.exists():
            missing.append(s["id"])
            continue
        rows = read_series(path)
        p = site_stats(s, rows, ms)
        p.pop("_raw")
        places[s["id"]] = p
    if missing:
        print("data/lst.json: no series yet for %s (run --sites)" % missing, flush=True)
    doc = {
        "about": ("Land surface (skin) temperature of each Earth site from NASA MODIS: MOD21A2 (Terra) and MYD21A2 (Aqua), "
                  "Collection 6.1, 8-day composites at 1 km, all composites that start in 2003-2020, at the 1 km pixel that "
                  "holds the site's coordinates. Clear-sky satellite measurements of the ground surface, not air "
                  "temperature (compare NASA POWER T2M = air at 2 m, TS = model skin temperature). Built by "
                  "scripts/fetch_lst.py; raw point answers in data/raw/lst/sites/ and every STAC item id in "
                  "data/raw/lst/manifest.json."),
        "product": PRODUCT,
        "access": ACCESS,
        "period": {"first": "2003-01-01", "last": "2020-12-31",
                   "rule": "every 8-day composite whose start date is in 2003-2020, Terra and Aqua (the common period: Aqua LST starts July 2002; both orbits drift after 2020)"},
        "qcRule": lc.QC_RULE,
        "derivedRules": DERIVED_RULES,
        "units": {"temperatures": "degC", "swingSurface_C": "K (difference)", "viewTime": "hours, local solar time"},
        "generated": now_iso(),
        "places": places,
    }
    write_json(OUT_SITES, doc)
    print("wrote %s (%d places, %.1f KB)" % (rel(OUT_SITES), len(places), OUT_SITES.stat().st_size / 1024), flush=True)
    return doc


# ==============================================================================================
# Jordan boxes

class BoxIndex:
    """1 km MODIS pixels of the Jordan screening grid, per MODIS tile, in a fixed order."""

    def __init__(self, grid_doc, extra_points):
        g = grid_doc["grid"]
        self.g = g
        self.boxes = grid_doc["boxes"]
        kept = {(b["row"], b["col"]): k for k, b in enumerate(self.boxes)}
        self.pix = {}       # tile -> list of (row, col)
        self.owner = {}     # tile -> list of box index (or -1)
        self.box_pixels = defaultdict(list)    # box index -> [(tile, i)]
        self.centre = {}    # box index -> (tile, i)
        self.extra = {}     # name -> (tile, i)
        need = defaultdict(set)
        for (h, v) in BOX_TILES:
            t = lc.tile_name(h, v)
            plist, own = [], []
            for row in range(1200):
                lat, _ = lc.pixel_centre(h, v, row, 0)
                if not (g["south"] <= lat < g["north"]):
                    continue
                brow = int((lat - g["south"]) // g["dlat"])
                for col in range(1200):
                    la, lon = lc.pixel_centre(h, v, row, col)
                    if not (g["west"] <= lon < g["east"]):
                        continue
                    k = kept.get((brow, int((lon - g["west"]) // g["dlon"])))
                    if k is None:
                        continue
                    plist.append((row, col))
                    own.append(k)
            self.pix[t], self.owner[t] = plist, own
        # centre pixels and extra (site) pixels: add when not already listed
        pos = {t: {rc: i for i, rc in enumerate(pl)} for t, pl in self.pix.items()}

        def ensure(lat, lon):
            h, v, row, col = lc.modis_tile(lat, lon)
            t = lc.tile_name(h, v)
            if t not in self.pix:
                raise SystemExit("point %.5f %.5f is in %s, not in the box tiles" % (lat, lon, t))
            i = pos[t].get((row, col))
            if i is None:
                i = len(self.pix[t])
                self.pix[t].append((row, col))
                self.owner[t].append(-1)
                pos[t][(row, col)] = i
            return t, i

        for k, b in enumerate(self.boxes):
            self.centre[k] = ensure(b["lat"], b["lon"])
        for name, (lat, lon) in extra_points.items():
            self.extra[name] = ensure(lat, lon)
        for t, own in self.owner.items():
            for i, k in enumerate(own):
                if k >= 0:
                    self.box_pixels[k].append((t, i))
        self.itiles = {}
        self.locs = {}
        for t, pl in self.pix.items():
            its = sorted({(row // 512, col // 512) for row, col in pl})
            self.itiles[t] = its
            self.locs[t] = [((row // 512, col // 512), (row % 512) * 512 + (col % 512)) for row, col in pl]
            need[t] = its
        h = hashlib.sha256(json.dumps({t: self.pix[t] for t in sorted(self.pix)}, separators=(",", ":")).encode()).hexdigest()
        self.hash = h

    def summary(self):
        return {t: {"pixels": len(self.pix[t]), "boxPixels": sum(1 for k in self.owner[t] if k >= 0),
                    "internalTiles512": [list(x) for x in self.itiles[t]]} for t in sorted(self.pix)}


def jordan_sites():
    return {s["id"]: (s["lat"], s["lon"]) for s in load_sites() if s.get("jordan")}


def tile_items(h, v):
    items = lc.stac_search_tile(lc.COLLECTION, h, v, "%d-01-01T00:00:00Z" % FIRST_YEAR, "%d-12-31T23:59:59Z" % LAST_YEAR,
                                assets=ASSETS4)
    return lc.select_items(items, h, v, FIRST_YEAR, LAST_YEAR)


def cache_file(cache, tile, item_id):
    return cache / "boxes" / tile / (item_id + ".bin")


def fetch_box_item(tile, item, idx, sas):
    """Read the 4 assets of one composite for the listed pixels; returns the packed bytes."""
    parts = []
    for a in ASSETS4:
        cog = lc.RemoteCOG(item["assets"][a]["href"], sas)
        if (cog.w, cog.h, cog.tw, cog.th) != (1200, 1200, 512, 512):
            raise ValueError("unexpected COG layout %s" % ((cog.w, cog.h, cog.tw, cog.th),))
        tiles = {it: cog.read_tile(*it) for it in idx.itiles[tile]}
        vals = array.array("H" if a.startswith("LST") else "B", (tiles[k][o] for k, o in idx.locs[tile]))
        if sys.byteorder == "big":
            vals.byteswap()
        parts.append(vals.tobytes())
    return zlib.compress(b"".join(parts), 6)


def unpack(buf, n):
    raw = zlib.decompress(buf)
    if len(raw) != 6 * n:
        raise ValueError("cache entry has %d bytes, expected %d" % (len(raw), 6 * n))
    ld, ln = array.array("H"), array.array("H")
    ld.frombytes(raw[:2 * n])
    ln.frombytes(raw[2 * n:4 * n])
    if sys.byteorder == "big":
        ld.byteswap()
        ln.byteswap()
    return ld, ln, raw[4 * n:5 * n], raw[5 * n:6 * n]


def fetch_water_tile(spec, h, v, idx, sas):
    """Land/water flag codes of the 4 x 500 m sub-pixels of every listed 1 km pixel, as a digit string
    (4 characters per pixel, '9' = fill)."""
    src, date, tag = spec
    ws = WATER_SOURCES[src]
    t = lc.tile_name(h, v)
    it = water_item(src, h, v, date, tag, with_asset=True)
    if it is None:
        raise SystemExit("no %s item %s %s" % (src, tag, t))
    cog = lc.RemoteCOG(it["assets"][ws["asset"]]["href"], sas)
    if (cog.w, cog.tw) != (2400, 512):
        raise ValueError("unexpected %s COG layout" % src)
    need = sorted({((2 * row + dr) // 512, (2 * col + dc) // 512) for row, col in idx.pix[t] for dr in (0, 1) for dc in (0, 1)})
    tiles = {k: cog.read_tile(*k) for k in need}
    out = []
    for row, col in idx.pix[t]:
        for dr in (0, 1):
            for dc in (0, 1):
                rr, cc = 2 * row + dr, 2 * col + dc
                q = tiles[(rr // 512, cc // 512)][(rr % 512) * 512 + (cc % 512)]
                out.append("9" if q == 65535 else str((q >> ws["shift"]) & 7))
    return it["id"], "".join(out)


def water_counts(codes):
    """number of permanent-water sub-pixels (0-4) per 1 km pixel from a digit string"""
    ws = {str(c) for c in WATER_SET}
    return [sum(1 for ch in codes[4 * i:4 * i + 4] if ch in ws) for i in range(len(codes) // 4)]


def run_boxes(args, manifest):
    t0 = time.time()
    s0 = lc.stats_snapshot()
    cache = pathlib.Path(args.cache_dir)
    grid_doc = json.loads(GRID_JSON.read_text(encoding="utf-8"))
    idx = BoxIndex(grid_doc, jordan_sites())
    print("pixel index: %s (%.1f s)" % (json.dumps(idx.summary()), time.time() - t0), flush=True)
    bdir = cache / "boxes"
    if not args.resume and bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True, exist_ok=True)
    ipath = bdir / "index.json"
    if ipath.exists():
        old = json.loads(ipath.read_text())
        if old.get("hash") != idx.hash:
            raise SystemExit("the cache in %s was made with a different pixel index; rerun --boxes without --resume" % bdir)
    else:
        ipath.write_text(json.dumps({"hash": idx.hash, "tiles": idx.pix}, separators=(",", ":")))

    sas = lc.SasToken()
    mt = manifest.setdefault("tileItems", {})
    jobs, per_tile = [], {}
    for (h, v) in BOX_TILES:
        t = lc.tile_name(h, v)
        items, dup = tile_items(h, v)
        per_tile[t] = {"items": items, "dup": dup}
        mt[t] = {"terra": sorted(it["id"] for it in items if it["properties"]["platform"] == "terra"),
                 "aqua": sorted(it["id"] for it in items if it["properties"]["platform"] == "aqua")}
        (bdir / t).mkdir(exist_ok=True)
        todo = [it for it in items if not cache_file(cache, t, it["id"]).exists()]
        print("  %s: %d items (terra %d, aqua %d; dup dropped %d), to fetch %d" % (
            t, len(items), len(mt[t]["terra"]), len(mt[t]["aqua"]), dup, len(todo)), flush=True)
        jobs += [(t, it) for it in todo]

    # land/water flag of the box pixels (500 m sub-pixels; main source + the MOD13A1 check; cached)
    wpath = bdir / "water.json"
    if wpath.exists():
        water = json.loads(wpath.read_text())
    else:
        water = {}
        for (h, v) in BOX_TILES:
            t = lc.tile_name(h, v)
            wid, codes = fetch_water_tile(WATER_MAIN, h, v, idx, sas)
            cid, ccodes = fetch_water_tile(WATER_CHECKS[1], h, v, idx, sas)
            hist = {k: codes.count(k) for k in sorted(set(codes))}
            both = [(a, b) for a, b in zip(codes, ccodes) if a != "9" and b != "9"]
            water[t] = {"item": wid, "codes": codes, "hist": hist, "checkItem": cid,
                        "checkHist": {k: ccodes.count(k) for k in sorted(set(ccodes))},
                        "checkCompared": len(both), "checkAgree": sum(1 for a, b in both if a == b)}
            print("  land/water %s: %s %s | check %s %s: %d of %d set sub-pixels agree" % (
                t, wid, hist, cid, water[t]["checkHist"], water[t]["checkAgree"], len(both)), flush=True)
        wpath.write_text(json.dumps(water, separators=(",", ":")))
    for t in water:
        water[t]["waterSubpixels"] = water_counts(water[t]["codes"])

    print("COG composites to fetch: %d (workers %d)" % (len(jobs), args.box_threads), flush=True)
    t1 = time.time()
    errors = []

    def work(job):
        t, it = job
        data = fetch_box_item(t, it, idx, sas)
        f = cache_file(cache, t, it["id"])
        tmp = f.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, f)
        return len(data)

    done = 0
    if jobs:
        with ThreadPoolExecutor(max_workers=args.box_threads) as ex:
            futs = {ex.submit(work, j): j for j in jobs}
            for f in as_completed(futs):
                t, it = futs[f]
                try:
                    f.result()
                except Exception as e:
                    errors.append((t, it["id"], repr(e)[:200]))
                    print("  ERR %s %s %s" % (t, it["id"], repr(e)[:160]), flush=True)
                    continue
                done += 1
                if done % 50 == 0:
                    el = time.time() - t1
                    snap = lc.stats_snapshot()
                    print("  %5d/%d composites  %6.0f s  %.0f MB  %d requests  %d retries" % (
                        done, len(jobs), el, (snap["bytes"] - s0["bytes"]) / 1e6, snap["requests"] - s0["requests"],
                        snap["retries"] - s0["retries"]), flush=True)
    el_fetch = time.time() - t1
    s1 = lc.stats_snapshot()
    run = {"step": "boxes", "finished": now_iso(), "seconds": None, "fetchSeconds": round(el_fetch, 1),
           "requests": s1["requests"] - s0["requests"], "bytes": s1["bytes"] - s0["bytes"],
           "retries": s1["retries"] - s0["retries"], "httpErrors": s1["http_errors"] - s0["http_errors"],
           "connects": s1["connects"] - s0["connects"], "workers": args.box_threads, "composites": done,
           "errors": len(errors), "sasTokenFetches": sas.fetches}
    if errors:
        run["seconds"] = round(time.time() - t0, 1)
        manifest.setdefault("runs", []).append(run)
        save_manifest(manifest)
        raise SystemExit("%d composites failed; rerun with --boxes --resume" % len(errors))
    print("fetch done: %d composites, %.0f s, %.0f MB" % (done, el_fetch, run["bytes"] / 1e6), flush=True)

    res = aggregate_boxes(idx, per_tile, cache, water, grid_doc)
    run["seconds"] = round(time.time() - t0, 1)
    run["aggregateSeconds"] = res["seconds"]
    manifest.setdefault("runs", []).append(run)
    OWN_KEYS.add("boxes")
    manifest["boxes"] = {"grid": grid_doc["grid"]["id"], "boxes": len(idx.boxes), "tiles": idx.summary(),
                         "pixelIndexSha256": idx.hash,
                         "items": {t: {"terra": len(mt[t]["terra"]), "aqua": len(mt[t]["aqua"]), "duplicatesDropped": per_tile[t]["dup"]} for t in per_tile},
                         "landWater": {t: {"source": WATER_SOURCES[WATER_MAIN[0]]["label"], "item": water[t]["item"],
                                           "codes500m": water[t]["hist"], "check": WATER_SOURCES[WATER_CHECKS[1][0]]["label"],
                                           "checkItem": water[t]["checkItem"], "checkCodes500m": water[t]["checkHist"],
                                           "subpixelsComparedWhereBothSet": water[t]["checkCompared"],
                                           "subpixelsAgreeing": water[t]["checkAgree"]} for t in water},
                         "cacheDir": "outside the project (default <system temp>/analog-atlas-lst-cache); %s" % ("default" if pathlib.Path(args.cache_dir) == DEFAULT_CACHE else "custom"),
                         "probePixels": res["probes"]}
    save_manifest(manifest)


def aggregate_boxes(idx, per_tile, cache, water, grid_doc):
    t0 = time.time()
    QT = lc.QC_TABLE
    pixstats = {}      # tile -> list of (mean4, swing, cold) per pixel (None when not valid)
    probe_raw = {}
    for t, info in per_tile.items():
        n = len(idx.pix[t])
        acc = {}
        comp = {"terra": 0, "aqua": 0}
        for plat in ("terra", "aqua"):
            acc[plat] = {"sd": [0] * n, "nd": [0] * n, "sn": [0] * n, "nn": [0] * n}
        mn = [0] * n          # coldest Aqua night (raw), 0 = none
        mk = [None] * n
        items = sorted(info["items"], key=lambda it: it["id"])
        probe_at = defaultdict(list)
        for name, (tt, ii) in idx.extra.items():
            if tt == t:
                probe_at[ii].append(name)
        for it in items:
            plat = it["properties"]["platform"]
            comp[plat] += 1
            ld, ln, qd, qn = unpack(cache_file(cache, t, it["id"]).read_bytes(), n)
            a = acc[plat]
            sd, nd, sn, nn = a["sd"], a["nd"], a["sn"], a["nn"]
            for i in range(n):
                x = ld[i]
                if x and QT[qd[i]]:
                    sd[i] += x
                    nd[i] += 1
            start = it["properties"]["start_datetime"][:10]
            if plat == "aqua":
                for i in range(n):
                    x = ln[i]
                    if x and QT[qn[i]]:
                        sn[i] += x
                        nn[i] += 1
                        m = mn[i]
                        if m == 0 or x < m or (x == m and start < mk[i]):
                            mn[i] = x
                            mk[i] = start
            else:
                for i in range(n):
                    x = ln[i]
                    if x and QT[qn[i]]:
                        sn[i] += x
                        nn[i] += 1
        print("  aggregated %s: %d pixels x %d composites (%.0f s)" % (t, n, len(items), time.time() - t0), flush=True)
        ps = []
        for i in range(n):
            means, ok = {}, {}
            for plat in ("terra", "aqua"):
                a = acc[plat]
                for key, s_, n_ in (("d", a["sd"][i], a["nd"][i]), ("n", a["sn"][i], a["nn"][i])):
                    means[plat[0] + key] = lc.lst_c(s_ / n_) if n_ else None
                    ok[plat[0] + key] = comp[plat] > 0 and n_ >= MIN_SHARE * comp[plat]
            mean4 = (sum(means[k] for k in ("td", "tn", "ad", "an")) / 4) if all(ok[k] for k in ("td", "tn", "ad", "an")) else None
            swing = means["ad"] - means["an"] if ok["ad"] and ok["an"] else None
            cold = lc.lst_c(mn[i]) if ok["an"] and mn[i] else None
            ps.append((mean4, swing, cold))
            for name in probe_at.get(i, ()):
                if True:
                    probe_raw[name] = {"tile": t, "row": idx.pix[t][i][0], "col": idx.pix[t][i][1],
                                       "means": means, "n": {"td": acc["terra"]["nd"][i], "tn": acc["terra"]["nn"][i],
                                                             "ad": acc["aqua"]["nd"][i], "an": acc["aqua"]["nn"][i]},
                                       "composites": dict(comp), "mean4": mean4, "swing": swing, "cold": cold,
                                       "coldStart": mk[i]}
        pixstats[t] = ps

    def b1(x):
        return None if x is None else round(x, 1)

    boxes, shares, flagcount = {}, [], defaultdict(int)
    for k, b in enumerate(idx.boxes):
        px = idx.box_pixels[k]
        npx = len(px)
        vals = [pixstats[t][i] for t, i in px]
        out = {}
        nvalid = []
        for j, key in enumerate(("meanSurface_C", "swingSurface_C", "coldSurface_C")):
            good = [v[j] for v in vals if v[j] is not None]
            nvalid.append(len(good))
            out[key] = b1(st.mean(good)) if npx and len(good) >= MIN_SHARE * npx else None
        all3 = sum(1 for v in vals if all(x is not None for x in v))
        out["validShare"] = round(all3 / npx, 2) if npx else 0.0
        out["nPix"] = npx
        ct, ci = idx.centre[k]
        c = pixstats[ct][ci]
        out["centre"] = {"meanSurface_C": b1(c[0]), "swingSurface_C": b1(c[1]), "coldSurface_C": b1(c[2])}
        wsub = [water[t]["waterSubpixels"][i] for t, i in px]
        wshare = sum(1 for w in wsub if w >= 3) / npx if npx else 0.0
        flags = []
        if wshare >= 0.5:
            flags.append("water")
        elif wshare >= 0.2:
            flags.append("partWater")
        if out["validShare"] < MIN_SHARE:
            flags.append("fewClear")
        if water[ct]["waterSubpixels"][ci] >= 3:
            flags.append("centreWater")
        out["waterShare"] = round(wshare, 2)
        out["flags"] = flags
        for f_ in flags:
            flagcount[f_] += 1
        boxes[b["id"]] = out
        shares.append(out["validShare"])

    def summ(key, sub=None):
        xs = [(bx[sub][key] if sub else bx[key]) for bx in boxes.values()]
        xs = [x for x in xs if x is not None]
        return {"n": len(xs), "min": min(xs) if xs else None, "median": r(st.median(xs), 1) if xs else None,
                "max": max(xs) if xs else None}

    counts = {"boxes": len(boxes), "flags": dict(flagcount),
              "meanSurface_C": summ("meanSurface_C"), "swingSurface_C": summ("swingSurface_C"),
              "coldSurface_C": summ("coldSurface_C"),
              "centre": {k: summ(k, "centre") for k in ("meanSurface_C", "swingSurface_C", "coldSurface_C")},
              "validShare": {"min": min(shares), "median": st.median(shares)},
              "pixels": {t: len(idx.pix[t]) for t in idx.pix},
              "composites": {t: {"terra": sum(1 for it in per_tile[t]["items"] if it["properties"]["platform"] == "terra"),
                                 "aqua": sum(1 for it in per_tile[t]["items"] if it["properties"]["platform"] == "aqua")} for t in per_tile}}
    doc = {
        "about": ("Land surface (skin) temperature for the Discover Jordan 10 km boxes (grid %s of data/screening_jordan.json) "
                  "from NASA MODIS MOD21A2 (Terra) + MYD21A2 (Aqua) Collection 6.1, 8-day, 1 km, composites starting "
                  "2003-2020: the same derived values as the sites in data/lst.json, computed for every 1 km MODIS pixel whose "
                  "centre lies in the box and averaged over the box, plus the single pixel at the box centre. Clear-sky "
                  "satellite measurements of the ground surface; not air temperature. Built by scripts/fetch_lst.py from COG "
                  "range reads (tiles h20v05, h21v05, h21v06); see data/raw/lst/README.txt." % grid_doc["grid"]["id"]),
        "generated": now_iso(),
        "product": {"ref": "data/lst.json#product", "names": ["MOD21A2 (Terra)", "MYD21A2 (Aqua)"], "collection": "6.1",
                    "dois": PRODUCT["dois"], "licence": PRODUCT["licence"]["name"], "licenceUrl": PRODUCT["licence"]["url"]},
        "period": {"first": "2003-01-01", "last": "2020-12-31", "rule": "every 8-day composite whose start date is in 2003-2020, Terra and Aqua"},
        "qcRule": lc.QC_RULE,
        "pixelRule": ("Each 1 km pixel gets the site statistics of data/lst.json (derivedRules there): mean of the four overpass means, "
                      "Aqua day mean minus Aqua night mean, and the coldest valid Aqua night composite. A series (Terra/Aqua x day/night) "
                      "counts for a pixel only when at least 50 % of that satellite's composites pass QC there; a statistic is valid "
                      "when all the series it needs count."),
        "boxRule": ("Box value = mean of the valid pixel values over all 1 km MODIS sinusoidal pixels whose centre falls inside the box "
                    "(row/col by the grid's pointToBox rule), kept only when at least 50 % of the box's pixels have a valid value for that "
                    "statistic (else null). validShare = share of the box's pixels valid for all three statistics. nPix = pixels in the box. "
                    "coldSurface_C of a box is the mean of each pixel's own coldest composite (dates differ between pixels). "
                    "centre = the same three values at the single 1 km pixel that holds the box centre (lat/lon of the box)."),
        "biases": {"meanSurface_C": "about +2 to +3 K warmer than a true 24 h mean (four fixed overpass times)",
                   "swingSurface_C": "captures about 88 % of the true daily range",
                   "coldSurface_C": "an 8-day mean of ~01:30 values; single nights get several K colder"},
        "flagRules": {"water": "50 % or more of the box's 1 km pixels are mostly water (at least 3 of their 4 500 m sub-pixels have a permanent-water code in the MODIS land/water flag, MOD09A1 v061 state bits 3-5; codes as in data/lst.json derivedRules.flags.water); the values mix water and land",
                      "partWater": "20 to 50 % of the box's pixels are mostly water",
                      "centreWater": "the centre pixel is mostly water",
                      "fewClear": "validShare below 0.5"},
        "landWaterFlag": {t: water[t]["item"] for t in water},
        "counts": counts,
        "boxes": boxes,
    }
    write_json(OUT_BOXES, doc, indent=None)
    el = time.time() - t0
    print("wrote %s (%d boxes, %.1f KB) in %.0f s" % (rel(OUT_BOXES), len(boxes), OUT_BOXES.stat().st_size / 1024, el), flush=True)
    print("box summary: %s" % json.dumps(counts), flush=True)
    return {"seconds": round(el, 1), "probes": {k: {kk: (r(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items() if kk != "means"} | {"means": {kk: r(vv, 3) for kk, vv in v["means"].items()}} for k, v in probe_raw.items()}}


# ==============================================================================================
# Validation

def run_validate(args, manifest):
    t0 = time.time()
    checks = {}
    ok_all = True
    sites = {s["id"]: s for s in load_sites()}
    lst = json.loads(OUT_SITES.read_text(encoding="utf-8")) if OUT_SITES.exists() else None

    def report(key, ok, lines):
        nonlocal ok_all
        ok_all = ok_all and ok
        checks[key] = {"ok": ok, "result": lines}
        print("[%s] %s" % ("PASS" if ok else "FAIL", key))
        for ln in lines:
            print("      " + ln)

    # (a) reproduce the scout's MOD21 numbers for Harrat and Wadi Rum
    lines, ok = [], True
    for sid, ref in SCOUT.items():
        ms = manifest.get("sites", {}).get(sid)
        if not ms:
            lines.append("%s: no series" % sid)
            ok = False
            continue
        p = site_stats(sites[sid], read_series(RAW_SITES / ("%s.jsonl.gz" % sid)), ms)
        raw = p["_raw"]
        pairs = [("terra day mean", raw["means"]["td"], ref["terra"]["day"][0]),
                 ("terra night mean", raw["means"]["tn"], ref["terra"]["night"][0]),
                 ("aqua day mean", raw["means"]["ad"], ref["aqua"]["day"][0]),
                 ("aqua night mean", raw["means"]["an"], ref["aqua"]["night"][0]),
                 ("coldSurface (aqua min night)", raw["cold"], ref["aquaMinNight"][0]),
                 ("nightP5", raw["p5"], ref["aquaP05Night"]),
                 ("meanSurface vs scout 4 means", raw["mean4"], sum([ref["terra"]["day"][0], ref["terra"]["night"][0], ref["aqua"]["day"][0], ref["aqua"]["night"][0]]) / 4),
                 ("swingSurface vs scout", raw["swing"], ref["aqua"]["day"][0] - ref["aqua"]["night"][0])]
        worst = 0.0
        for name, mine, theirs in pairs:
            d = None if mine is None else mine - theirs
            if d is None or abs(d) > 0.3:
                ok = False
            worst = max(worst, abs(d) if d is not None else 99)
            lines.append("%s %-30s mine %8.3f  scout %7.2f  diff %+.3f K" % (sid, name, mine if mine is not None else float("nan"), theirs, d if d is not None else float("nan")))
        ns = [("terra day n", raw["n"]["td"], ref["terra"]["day"][1]), ("terra night n", raw["n"]["tn"], ref["terra"]["night"][1]),
              ("aqua day n", raw["n"]["ad"], ref["aqua"]["day"][1]), ("aqua night n", raw["n"]["an"], ref["aqua"]["night"][1]),
              ("terra composites", p["terra"]["composites"], ref["terra"]["composites"]), ("aqua composites", p["aqua"]["composites"], ref["aqua"]["composites"])]
        lines.append("%s counts mine/scout: %s" % (sid, ", ".join("%s %d/%d" % (a, b, c) for a, b, c in ns)))
        lines.append("%s coldest date mine %s scout %s; view times mine T %.2f/%.2f A %.2f/%.2f, scout T %.2f/%.2f A %.2f/%.2f" % (
            sid, p["coldSurfaceStart"], ref["aquaMinNight"][1], p["terra"]["day"]["viewTime"], p["terra"]["night"]["viewTime"],
            p["aqua"]["day"]["viewTime"], p["aqua"]["night"]["viewTime"], ref["terra"]["vt"][0], ref["terra"]["vt"][1], ref["aqua"]["vt"][0], ref["aqua"]["vt"][1]))
        lines.append("%s period note: scout's headline Terra numbers were 2001-2020 (day %.2f, night %.2f); 2003-2020 used here gives day %.2f, night %.2f (%+.2f / %+.2f K)" % (
            sid, ref["terra2001_2020"]["day"], ref["terra2001_2020"]["night"], raw["means"]["td"], raw["means"]["tn"],
            raw["means"]["td"] - ref["terra2001_2020"]["day"], raw["means"]["tn"] - ref["terra2001_2020"]["night"]))
        lines.append("%s max |diff| %.3f K (limit 0.3 K)" % (sid, worst))
    report("a_scout_reproduction", ok, lines)

    # (b) point API vs COG range read, same pixel and composite, 3 random composites
    lines, ok = [], True
    rng = random.Random(20261010)
    sas = lc.SasToken()
    pool = []
    for sid in sorted(manifest.get("sites", {})):
        for x in read_series(RAW_SITES / ("%s.jsonl.gz" % sid)):
            pool.append((sid, x))
    picks = rng.sample(pool, 3) if len(pool) >= 3 else []
    if not picks:
        ok = False
        lines.append("no site series to sample")
    for sid, x in picks:
        s = sites[sid]
        ms = manifest["sites"][sid]
        th, tv = int(ms["tile"][1:3]), int(ms["tile"][4:6])
        items = lc.stac_search_tile(lc.COLLECTION, th, tv, x["s"] + "T00:00:00Z", x["s"] + "T23:59:59Z", assets=ASSETS6)
        it = [i for i in items if i["id"] == x["id"]]
        if not it:
            ok = False
            lines.append("%s %s: item not found again" % (sid, x["id"]))
            continue
        it = it[0]
        cogv, rcs = [], set()
        for a in ASSETS6:
            cog = lc.RemoteCOG(it["assets"][a]["href"], sas)
            row, col = cog.rowcol(s["lat"], s["lon"])
            rcs.add((row, col))
            cogv.append(int(cog.pixel(row, col)))
        ms = manifest["sites"][sid]
        same_rc = rcs == {(ms["row"], ms["col"])}
        fresh = lc.point_values(lc.COLLECTION, x["id"], s["lon"], s["lat"], ASSETS6)
        fresh_v = [int(round(float(v))) for v in fresh["values"]]
        good = cogv == x["v"] == fresh_v and same_rc
        ok = ok and good
        lines.append("%s %s pixel r%d c%d (grid formula r%d c%d): stored point %s | fresh point %s | COG %s -> %s" % (
            sid, x["id"], list(rcs)[0][0], list(rcs)[0][1], ms["row"], ms["col"], x["v"], fresh_v, cogv, "IDENTICAL" if good else "DIFFERENT"))
    report("b_point_api_vs_cog", ok, lines)

    # (c) Jordan sites vs the box that holds them
    lines, ok = [], True
    sl = json.loads(OUT_BOXES.read_text(encoding="utf-8")) if OUT_BOXES.exists() else None
    grid_doc = json.loads(GRID_JSON.read_text(encoding="utf-8"))
    g = grid_doc["grid"]
    byrc = {(b["row"], b["col"]): b for b in grid_doc["boxes"]}
    probes = manifest.get("boxes", {}).get("probePixels", {})
    if sl is None or lst is None:
        ok = False
        lines.append("run --sites and --boxes first")
    else:
        for sid, (lat, lon) in jordan_sites().items():
            b = byrc.get((int((lat - g["south"]) // g["dlat"]), int((lon - g["west"]) // g["dlon"])))
            pl = lst["places"].get(sid)
            if b is None or pl is None:
                ok = False
                lines.append("%s: no box or no site values" % sid)
                continue
            sp = lc.modis_tile(lat, lon)
            cp = lc.modis_tile(b["lat"], b["lon"])
            bx = sl["boxes"][b["id"]]
            same = sp == cp
            dd = {k: (None if pl[k] is None or bx["centre"][k] is None else round(bx["centre"][k] - pl[k], 2))
                  for k in ("meanSurface_C", "swingSurface_C", "coldSurface_C")}
            if same and any(v is not None and abs(v) > 0.051 for v in dd.values()):
                ok = False
            lines.append("%s in %s: site pixel %s r%d c%d, box-centre pixel %s r%d c%d -> %s; box centre minus site (rounded 0.1 vs 0.01): %s; box mean: %s/%s/%s" % (
                sid, b["id"], lc.tile_name(sp[0], sp[1]), sp[2], sp[3], lc.tile_name(cp[0], cp[1]), cp[2], cp[3],
                "SAME PIXEL" if same else "different pixel (%.2f km apart)" % (
                    math.hypot((sp[2] - cp[2]), (sp[3] - cp[3])) * lc.PIX_1KM / 1000 if sp[:2] == cp[:2] else float("nan")),
                dd, bx["meanSurface_C"], bx["swingSurface_C"], bx["coldSurface_C"]))
            # the site's own pixel inside the COG pipeline must equal the point-API result exactly
            pr = probes.get(sid)
            raw = site_stats(sites[sid], read_series(RAW_SITES / ("%s.jsonl.gz" % sid)), manifest["sites"][sid])["_raw"]
            if pr is None:
                ok = False
                lines.append("   %s: no probe pixel in the box run" % sid)
                continue
            nmatch = pr["n"] == raw["n"]
            dmax = max(abs(pr["means"][k] - raw["means"][k]) for k in ("td", "tn", "ad", "an"))
            cmatch = pr["cold"] is not None and raw["cold"] is not None and abs(pr["cold"] - raw["cold"]) < 0.0006
            good = nmatch and dmax < 0.0015 and cmatch and pr["coldStart"] == pl["coldSurfaceStart"]
            ok = ok and good
            lines.append("   %s pixel via COG pipeline vs point API: n %s vs %s, max |mean diff| %.4f K, coldest %.3f (%s) vs %.3f (%s) -> %s" % (
                sid, pr["n"], raw["n"], dmax, pr["cold"], pr["coldStart"], raw["cold"], pl["coldSurfaceStart"], "IDENTICAL" if good else "DIFFERENT"))
    report("c_jordan_site_vs_box", ok, lines)

    # (d) plausibility: no -999 / NaN / inf; ranges
    lines, ok = [], True
    bad = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, path + "." + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(o, float):
            if math.isnan(o) or math.isinf(o) or o <= -900:
                bad.append(path)
        elif isinstance(o, int) and not isinstance(o, bool) and o <= -900:
            bad.append(path)

    for name, doc in (("lst.json", lst), ("screening_lst.json", sl)):
        if doc is None:
            ok = False
            lines.append("%s missing" % name)
            continue
        walk(doc, name)
    txt = (OUT_SITES.read_text(encoding="utf-8") if OUT_SITES.exists() else "") + (OUT_BOXES.read_text(encoding="utf-8") if OUT_BOXES.exists() else "")
    for tok in ("NaN", "Infinity", "-999"):
        if tok in txt:
            bad.append("text contains %s" % tok)
    if bad:
        ok = False
        lines.append("bad values: %s" % bad[:20])
    else:
        lines.append("no NaN / Infinity / -999 in data/lst.json and data/screening_lst.json")
    rng_fail = []
    if lst:
        for sid, p in lst["places"].items():
            for plat in ("terra", "aqua"):
                for dn in ("day", "night"):
                    q = p[plat][dn]
                    if q["mean_C"] is not None and not (-80 <= q["mean_C"] <= 75):
                        rng_fail.append("%s %s %s mean %s" % (sid, plat, dn, q["mean_C"]))
                    if q["n"] > p[plat]["composites"]:
                        rng_fail.append("%s %s %s n > composites" % (sid, plat, dn))
                    if q["viewTime"] is not None and not (0 <= q["viewTime"] < 24):
                        rng_fail.append("%s viewTime" % sid)
            if p["meanSurface_C"] is not None and not (-60 <= p["meanSurface_C"] <= 50):
                rng_fail.append("%s meanSurface %s" % (sid, p["meanSurface_C"]))
            if p["swingSurface_C"] is not None and not (0 <= p["swingSurface_C"] <= 60):
                rng_fail.append("%s swing %s" % (sid, p["swingSurface_C"]))
            if p["coldSurface_C"] is not None and not (-90 <= p["coldSurface_C"] <= 35):
                rng_fail.append("%s cold %s" % (sid, p["coldSurface_C"]))
            if p["coldSurface_C"] is not None and p["nightP5_C"] is not None and p["coldSurface_C"] > p["nightP5_C"]:
                rng_fail.append("%s cold > p5" % sid)
            if p["coldSurface_C"] is not None and p["aqua"]["night"]["mean_C"] is not None and p["coldSurface_C"] > p["aqua"]["night"]["mean_C"]:
                rng_fail.append("%s cold > aqua night mean" % sid)
            # Aqua night view time should be near 01:30 outside the polar regions
            vt = p["aqua"]["night"]["viewTime"]
            if "polar" not in p["flags"] and vt is not None and not (vt >= 23 or vt <= 4):
                rng_fail.append("%s aqua night view time %.2f" % (sid, vt))
        lines.append("sites: %d places; all means in -80..75 C, swing 0..60 K, cold <= p5 <= night mean, n <= composites, non-polar Aqua night view times 23-04 h: %s" % (
            len(lst["places"]), "yes" if not rng_fail else "NO"))
    if sl:
        for bid, bx in sl["boxes"].items():
            for k, lo, hi in (("meanSurface_C", 5, 45), ("swingSurface_C", 0, 50), ("coldSurface_C", -20, 30)):
                for v, wet in ((bx[k], "water" in bx["flags"]), (bx["centre"][k], "centreWater" in bx["flags"])):
                    # open water (Dead Sea, Gulf of Aqaba) can be a little warmer at 01:30 than at 13:30
                    if v is not None and not ((lo - 3 if wet and k == "swingSurface_C" else lo) <= v <= hi):
                        rng_fail.append("%s %s %s" % (bid, k, v))
            if not (0 <= bx["validShare"] <= 1):
                rng_fail.append("%s validShare" % bid)
        nnull = sum(1 for bx in sl["boxes"].values() if bx["meanSurface_C"] is None)
        lines.append("boxes: %d; Jordan ranges meanSurface 5..45 C, swing 0..50 K (-3..50 K over water), cold -20..30 C (box and centre): %s; boxes with null meanSurface: %d" % (
            len(sl["boxes"]), "yes" if not [x for x in rng_fail if x.startswith("jo-")] else "NO", nnull))
        if len(sl["boxes"]) != len(grid_doc["boxes"]):
            rng_fail.append("box count %d != %d" % (len(sl["boxes"]), len(grid_doc["boxes"])))
    if rng_fail:
        ok = False
        lines.append("out of range: %s" % rng_fail[:30])
    report("d_plausible_values", ok, lines)

    OWN_KEYS.add("checks")
    manifest["checks"] = {"run": now_iso(), "allPass": ok_all, "seconds": round(time.time() - t0, 1), **checks}
    save_manifest(manifest)
    print("checks: %s" % ("ALL PASS" if ok_all else "SOME FAILED"), flush=True)
    return ok_all


# ==============================================================================================

README = """MODIS land surface temperature (LST): raw files and how to rebuild them
=========================================================================

What this is
------------
data/lst.json (19 Earth sites) and data/screening_lst.json (886 Discover Jordan boxes) hold land
surface (skin) temperature statistics from NASA MODIS:
  MOD21A2 (Terra) and MYD21A2 (Aqua), Collection 6.1, 8-day composites, 1 km sinusoidal grid,
  every composite that starts in 2003-2020 (the period both satellites share before orbit drift).
  DOIs 10.5067/MODIS/MOD21A2.061 and 10.5067/MODIS/MYD21A2.061 (LP DAAC; NASA-led mission data, CC0).
The files are read from Microsoft Planetary Computer's mirror of the LP DAAC files (Cloud Optimized
GeoTIFFs), anonymously: no account, no key, no password.

The app does not load anything in this folder.

What is in this folder
----------------------
  README.txt            this file
  manifest.json         every STAC item id used (per MODIS tile, Terra and Aqua), counts, the site
                        pixels (tile/row/col), land/water mask codes, request totals and run times of
                        each run, and the results of the checks (a)-(d)
  sites/<id>.jsonl.gz   one line per composite for each site: the point-API answer at the site's
                        pixel, unchanged except rounded to integers:
                          {"id": STAC item id, "p": "terra"|"aqua", "s": start date, "e": end date,
                           "v": [LST_Day_1KM, LST_Night_1KM, QC_Day, QC_Night, View_Time_Day, View_Time_Night]}
                        raw MODIS integers: LST x 0.02 = kelvin (0 = fill), View_Time x 0.1 = hours of
                        local solar time (255 = fill), QC = bit field (see qcRule in data/lst.json)

The box pipeline stores nothing here except its summary in manifest.json: it reads only the
internal 512 x 512 tiles of the COGs that hold Jordan (tiles h20v05, h21v05, h21v06), keeps the
values of the 103,130 pixels of the grid in a cache OUTSIDE the project (default:
<system temp>/analog-atlas-lst-cache, about 0.45 GB; delete it when you are done) and writes only
the per-box results.

How to rebuild
--------------
From the project folder, Python 3.12, standard library only:
    python -I scripts/fetch_lst.py --sites --boxes --validate
    (after an interruption add --resume: finished composites are not fetched again)
  --sites     19 sites x ~1,656 composites = ~31,500 point-API requests (16 threads, keep-alive
              connections; ~17 requests/s): about 30 minutes; writes sites/, manifest.json and
              data/lst.json
  --boxes     3 tiles x ~1,656 composites, 4 assets each (LST and QC, day and night): header +
              1-2 internal tiles per asset: 2.96 GB and 46,393 requests in the last run, 14 minutes
              with 8 workers, plus 5 minutes of aggregation; writes data/screening_lst.json
  --validate  checks (a)-(d) below; prints them and stores them in manifest.json
Numbers in the last run: see manifest.json "runs".

Checks (--validate)
-------------------
  (a) Harrat and Wadi Rum reproduce the LST scout's MOD21 numbers (same API, same QC rule,
      2003-2020) within 0.3 K
  (b) for 3 random composites, the stored point-API answer, a fresh point-API answer and a direct
      COG range read of the same pixel are identical (all 6 assets)
  (c) each Jordan site's box: is the box-centre pixel the site's pixel? (report the difference if
      not); and the site's own pixel computed through the box (COG) pipeline equals the
      point-API result exactly
  (d) no NaN / Infinity / -999 anywhere, values in plausible ranges

Notes
-----
* New TCP connections to the Planetary Computer hosts often timed out from the build machine;
  the scripts keep one connection per thread alive and retry.
* The COG SAS token comes from /api/sas/v1/token/modiseuwest/modis-061-cogs (NOT the collection
  token, which is for the HDF container); it is refreshed before it expires.
* Terra/Aqua is taken from the product name in the item id (MOD21A2 = Terra, MYD21A2 = Aqua):
  one STAC item, MOD21A2.A2003041.h29v11 (Pilbara), has an empty 'platform' property.
* The water flag uses the MODIS land/water flag at 500 m from MOD09A1 v061 (sur_refl_state_500m,
  bits 3-5; composite A2015209). Checks: the same product in A2005209 (sites) and MOD13A1 v061
  VI_Quality bits 11-13 (whose in-file legend defines the codes; it is fill over the deep Dead Sea
  and absent over Antarctica, so it is only the check).
"""


def write_readme():
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "README.txt").write_text(README, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", action="store_true")
    ap.add_argument("--boxes", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--box-threads", type=int, default=6)
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--only", default=None)
    ap.add_argument("--rebuild-json", action="store_true", help="rebuild data/lst.json from the saved series (no network)")
    args = ap.parse_args()
    if not (args.sites or args.boxes or args.validate or args.rebuild_json):
        ap.print_help()
        return 2
    write_readme()
    manifest = load_manifest()
    manifest.setdefault("about", "Run record of scripts/fetch_lst.py (MODIS MOD21A2/MYD21A2 C6.1 LST via Microsoft Planetary Computer).")
    manifest["collection"] = lc.COLLECTION
    manifest["period"] = {"first": "%d-01-01" % FIRST_YEAR, "last": "%d-12-31" % LAST_YEAR}
    manifest["qcRule"] = lc.QC_RULE
    t0 = time.time()
    if args.sites:
        run_sites(args, manifest)
    elif args.rebuild_json:
        build_sites_json(manifest)
    if args.boxes:
        run_boxes(args, manifest)
    ok = True
    if args.validate:
        ok = run_validate(args, manifest)
    s = lc.stats_snapshot()
    print("total %.0f s; requests %d, %.1f MB, retries %d, connects %d" % (
        time.time() - t0, s["requests"], s["bytes"] / 1e6, s["retries"], s["connects"]), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
