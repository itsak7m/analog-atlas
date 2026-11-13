"""comp_modis: MODIS MOD21A2 v061 (Terra, 8-day, 1 km) emissivity at the sites and the Jordan boxes.

Helper for scripts/fetch_composition.py. Data: Microsoft Planetary Computer COGs (collection
modis-21A2-061), read with HTTP range requests, no login.

Raw extracts written here (data/raw/composition/):
  modis_items.json         the sampled composites per MODIS tile (file stems; the STAC id when it differs)
  modis_sites.jsonl        one line per (tile, composite): the 3 x 3 pixel window of raw DNs of
                           Emis_29, Emis_31, Emis_32 and LST_Day_1KM around each site in that tile
  modis_boxes.json         per Jordan box and year: [sum of Emis_29 DNs, number of valid pixels]
                           over all 1 km pixels whose centre is inside the box; plus the list of
                           composites already added (for --resume)
  check2023.json           check (a): the scout's 2023 site values reproduced
Scale: emissivity = DN * 0.002 + 0.49 (DN 0 = no data); LST (K) = DN * 0.02 (DN 0 = no data).
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import statistics
import threading
import time
from collections import defaultdict

import comp_cog as cc
import comp_pc as pc

COLL = "modis-21A2-061"
E_SCALE, E_OFFSET = 0.002, 0.49
LST_SCALE = 0.02
LST_MIN_K = 273.15
SITE_BANDS = ["Emis_29", "Emis_31", "Emis_32", "LST_Day_1KM"]
SHORT = {"Emis_29": "e29", "Emis_31": "e31", "Emis_32": "e32", "LST_Day_1KM": "lst"}
HEADER = 16384
MONTH_STARTS = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
JORDAN_TILES = [(21, 5), (21, 6)]
# Published by the scout (scratchpad out/mod21_sites_2023.json): 12 Terra composites of 2023 that
# start nearest the 1st of each month, pooled median of the 3 x 3 window, no LST screen.
SCOUT_2023 = {"wadi-rum": 0.864, "harrat": 0.976, "waqf-as-suwwan": 0.87, "lisan-dead-sea": 0.966,
              "qa-al-jafr": 0.97}


def emis(dn):
    return None if not dn else dn * E_SCALE + E_OFFSET


def item_date(item_id):
    a = item_id.split(".")[1]          # A2018001
    y, d = int(a[1:5]), int(a[5:8])
    return y, d, (dt.date(y, 1, 1) + dt.timedelta(days=d - 1)).isoformat()


def tile_name(h, v):
    return "h%02dv%02d" % (h, v)


# ----------------------------------------------------------------------------- item lists
def search_tile(h, v, y0, y1, bands):
    feats = pc.search(pc.PC_STAC, COLL, datetime="%d-01-01T00:00:00Z/%d-12-31T23:59:59Z" % (y0, y1),
                      query={"modis:horizontal-tile": {"eq": h}, "modis:vertical-tile": {"eq": v},
                             "platform": {"eq": "terra"}},
                      fields={"include": ["id"] + ["assets.%s.href" % b for b in bands],
                              "exclude": ["geometry", "links", "bbox", "properties"]})
    feats = [f for f in feats if f["id"].startswith("MOD21A2.")]
    feats.sort(key=lambda f: f["id"])
    prefix = None
    stems, mismatch = [], {}
    for f in feats:
        stem = None
        for b in bands:
            hr = f["assets"][b]["href"]
            p, folder, name = hr.rsplit("/", 2)
            st = name[:-len("_%s.tif" % b)]
            prefix = prefix or p
            stem = stem or st
            # the file name (stem) can carry another production time than the STAC id
            if not name.endswith("_%s.tif" % b) or p != prefix or st != stem or folder != st.split(".")[1][1:]                     or st.split(".")[:4] != f["id"].split(".")[:4]:
                raise RuntimeError("unexpected MOD21A2 href layout: " + hr)
        stems.append(stem)
        if stem != f["id"]:
            mismatch[stem] = f["id"]
    return prefix, stems, mismatch


def href(prefix, stem, band):
    """Blob URL of one band of one composite; stem = file name without '_<band>.tif'."""
    return "%s/%s/%s_%s.tif" % (prefix, stem.split(".")[1][1:], stem, band)


def sample_items(ids, stride):
    """Systematic sample: every `stride`-th composite in date order (stride 1 = all)."""
    return ids[::stride]


def load_items(raw, tiles, y0, y1, stride, bands, resume, log):
    path = os.path.join(raw, "modis_items.json")
    cache = {}
    if resume and os.path.exists(path):
        cache = json.load(open(path, encoding="utf-8"))
        if cache.get("years") != [y0, y1] or cache.get("stride") != stride:
            cache = {}
    tiles_out = cache.get("tiles", {})
    changed = False
    for (h, v) in tiles:
        name = tile_name(h, v)
        if name in tiles_out:
            continue
        prefix, ids, mismatch = search_tile(h, v, y0, y1, bands)
        sel = sample_items(ids, stride)
        tiles_out[name] = {"prefix": prefix, "found": len(ids), "ids": sel,
                           "stacIdWhenDifferent": {k: v for k, v in mismatch.items() if k in sel}}
        log("  %s: %d Terra composites found %d-%d, %d sampled" % (name, len(ids), y0, y1, len(sel)))
        changed = True
    if changed or not cache:
        cache = {"collection": COLL, "years": [y0, y1], "stride": stride, "platform": "terra",
                 "searched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tiles": tiles_out}
        _dump(path, cache, indent=None)
    return cache


def _dump(path, obj, indent=None):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, separators=(",", ":") if indent is None else None, allow_nan=False)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- pixel geometry
def tile_grid(h, v):
    """(x0, px, y0) of the 1200 x 1200 MODIS tile in sinusoidal metres (upper-left corner)."""
    px = cc.MODIS_TILE / 1200.0
    return cc.MODIS_X0 + h * cc.MODIS_TILE, px, cc.MODIS_Y0 - v * cc.MODIS_TILE


def site_window(h, v, lat, lon):
    """3 x 3 (row, col) pixels around the pixel that holds the site (row-major)."""
    x0, px, y0 = tile_grid(h, v)
    x, y = cc.sinusoidal(lat, lon)
    r0, c0 = int(math.floor((y0 - y) / px)), int(math.floor((x - x0) / px))
    return [(r, c) for r in range(r0 - 1, r0 + 2) for c in range(c0 - 1, c0 + 2)]


def box_pixels(h, v, grid, box_index):
    """{block_idx: [(offset in 512x512 block, box index)]} for all pixels of tile h/v whose centre
    is inside a box (box_index maps (row, col) of the Jordan grid -> index)."""
    x0, px, y0 = tile_grid(h, v)
    south, west, dlat, dlon = grid["south"], grid["west"], grid["dlat"], grid["dlon"]
    out = defaultdict(list)
    for row in range(1200):
        y = y0 - (row + 0.5) * px
        lat = math.degrees(y / cc.R_SIN)
        if not (grid["south"] <= lat < grid["north"]):
            continue
        br = int((lat - south) // dlat)
        coslat = math.cos(math.radians(lat))
        for col in range(1200):
            x = x0 + (col + 0.5) * px
            lon = math.degrees(x / (cc.R_SIN * coslat))
            if not (west <= lon < grid["east"]):
                continue
            bc = int((lon - west) // dlon)
            bi = box_index.get((br, bc))
            if bi is None:
                continue
            blk = (row // 512) * 3 + col // 512
            out[blk].append(((row % 512) * 512 + col % 512, bi))
    return dict(out)


def read_values(cog, pixels):
    vals = []
    for r, c in pixels:
        p = cog.pixel(r, c)
        vals.append(None if p is None else int(p[0]))
    return vals


# ----------------------------------------------------------------------------- one composite
def process_item(prefix, item_id, site_px, box_px, nboxes, site_bands):
    """Read one composite of one tile. Returns ({sid: {short: [DN]}}, box sums, box counts, nbytes)."""
    sites = {sid: {} for sid in site_px}
    sums = counts = None
    nbytes = 0
    bands = list(site_bands) if site_px else []
    if box_px is not None and "Emis_29" not in bands:
        bands.append("Emis_29")
    for band in bands:
        need_boxes = band == "Emis_29" and box_px is not None
        src = pc.pc_source(href(prefix, item_id, band))
        cog = cc.COG(src, header_bytes=HEADER)
        if cog.width != 1200 or cog.tw != 512:
            raise RuntimeError("unexpected MOD21A2 layout %s %s" % (item_id, band))
        for sid, pxl in site_px.items():
            sites[sid][SHORT[band]] = read_values(cog, pxl)
        if need_boxes:
            sums = [0] * nboxes
            counts = [0] * nboxes
            for blk, lst in box_px.items():
                vals = cog.block(blk)
                for off, bi in lst:
                    dn = vals[off]
                    if dn:
                        sums[bi] += dn
                        counts[bi] += 1
        nbytes += src.nbytes
    return sites, sums, counts, nbytes


# ----------------------------------------------------------------------------- main runs
def run(raw, sites, grid, boxes, y0, y1, stride, do_sites, do_boxes, resume, workers, log):
    """Sample all composites; append raw extracts; resumable."""
    t_start = time.time()
    tiles_sites = defaultdict(list)
    for s in sites:
        tiles_sites[cc.modis_tile(s["lat"], s["lon"])].append(s)
    tiles = set(tiles_sites) if do_sites else set()
    if do_boxes:
        tiles |= set(JORDAN_TILES)
    tiles = sorted(tiles)
    log("MOD21A2: %d tiles, years %d-%d, stride %d" % (len(tiles), y0, y1, stride))
    items = load_items(raw, tiles, y0, y1, stride, SITE_BANDS, resume, log)

    sites_path = os.path.join(raw, "modis_sites.jsonl")
    boxes_path = os.path.join(raw, "modis_boxes.json")
    done_sites = set()
    if do_sites:
        if resume and os.path.exists(sites_path):
            good = []
            for line in open(sites_path, encoding="utf-8"):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue                 # a line cut by an interrupted run
                done_sites.add((rec["tile"], rec["item"]))
                good.append(line if line.endswith("\n") else line + "\n")
            with open(sites_path, "w", encoding="utf-8") as f:
                f.writelines(good)
        else:
            open(sites_path, "w").close()
    box_ids = [b["id"] for b in boxes]
    box_index = {(b["row"], b["col"]): i for i, b in enumerate(boxes)}
    bstate = {"years": [y0, y1], "stride": stride, "done": {}, "acc": {}}
    if do_boxes and resume and os.path.exists(boxes_path):
        old = json.load(open(boxes_path, encoding="utf-8"))
        if old.get("years") == [y0, y1] and old.get("stride") == stride:
            bstate = old
    acc = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for bid, yrs in bstate.get("acc", {}).items():
        for y, sn in yrs.items():
            acc[bid][y] = list(sn)
    done_boxes = {(t, i) for t, lst in bstate.get("done", {}).items() for i in lst}

    tasks = []
    box_px_cache = {}
    for (h, v) in tiles:
        name = tile_name(h, v)
        info = items["tiles"][name]
        spx = {s["id"]: site_window(h, v, s["lat"], s["lon"]) for s in tiles_sites.get((h, v), [])} if do_sites else {}
        bpx = None
        if do_boxes and (h, v) in JORDAN_TILES:
            bpx = box_px_cache.setdefault((h, v), box_pixels(h, v, grid, box_index))
            log("  %s: %d box pixels in %d blocks" % (name, sum(len(x) for x in bpx.values()), len(bpx)))
        for iid in info["ids"]:
            need_s = bool(spx) and (name, iid) not in done_sites
            need_b = bpx is not None and (name, iid) not in done_boxes
            if need_s or need_b:
                tasks.append((name, info["prefix"], iid, spx if need_s else {}, bpx if need_b else None))
    log("MOD21A2: %d composite reads to do (%d already done)" % (len(tasks), len(done_sites) + len(done_boxes)))

    lock = threading.Lock()
    stats = {"done": 0, "bytes": 0, "failed": []}
    fsites = open(sites_path, "a", encoding="utf-8") if do_sites else None

    def work(t):
        name, prefix, iid, spx, bpx = t
        last = None
        for k in range(4):
            try:
                return t, process_item(prefix, iid, spx, bpx, len(boxes), SITE_BANDS)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 + 10 * k)
        return t, last

    last_save = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, t) for t in tasks]
        for fu in cf.as_completed(futs):
            t, res = fu.result()
            name, prefix, iid, spx, bpx = t
            if isinstance(res, Exception):
                stats["failed"].append({"tile": name, "item": iid, "error": str(res)[:200]})
                log("  FAILED %s %s: %s" % (name, iid, res))
                continue
            site_vals, sums, counts, nb = res
            y, d, date = item_date(iid)
            with lock:
                stats["bytes"] += nb
                if spx:
                    fsites.write(json.dumps({"tile": name, "item": iid, "date": date, "sites": site_vals},
                                            separators=(",", ":")) + "\n")
                    fsites.flush()
                if bpx is not None and sums is not None:
                    for i, bid in enumerate(box_ids):
                        if counts[i]:
                            a = acc[bid][str(y)]
                            a[0] += sums[i]
                            a[1] += counts[i]
                    done_boxes.add((name, iid))
                stats["done"] += 1
                if bpx is not None and (time.time() - last_save > 20 or stats["done"] == len(tasks)):
                    _save_boxes(boxes_path, y0, y1, stride, done_boxes, acc)
                    last_save = time.time()
                if stats["done"] % 25 == 0 or stats["done"] == len(tasks):
                    el = time.time() - t_start
                    log("  %d/%d composite reads, %.0f MB, %.0f s, PC requests %s" % (
                        stats["done"], len(tasks), stats["bytes"] / 1e6, el,
                        cc.STATS.get("modiseuwest.blob.core.windows.net", {}).get("requests")))
    if fsites:
        fsites.close()
    if do_boxes:
        _save_boxes(boxes_path, y0, y1, stride, done_boxes, acc)
    stats["seconds"] = round(time.time() - t_start, 1)
    return items, stats


def _save_boxes(path, y0, y1, stride, done_boxes, acc):
    done = defaultdict(list)
    for t, i in sorted(done_boxes):
        done[t].append(i)
    _dump(path, {"about": "Per Jordan box and year: [sum of MOD21A2 Emis_29 DNs, number of valid 1 km pixel "
                          "samples] over all pixels whose centre is inside the box. Emissivity = DN * 0.002 + 0.49.",
                 "years": [y0, y1], "stride": stride, "done": dict(done),
                 "acc": {b: dict(sorted(v.items())) for b, v in sorted(acc.items())}})


# ----------------------------------------------------------------------------- summaries
def site_summary(raw, site_ids):
    """Multi-year values per site from modis_sites.jsonl (LST screen: daytime LST >= 0 C)."""
    path = os.path.join(raw, "modis_sites.jsonl")
    pooled = {sid: {"e29": [], "e31": [], "e32": [], "valid": 0, "cold": 0, "nolst": 0,
                    "composites": set(), "years": set()} for sid in site_ids}
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue                     # a line still being written or cut by an interrupted run
        y = int(rec["date"][:4])
        for sid, b in rec["sites"].items():
            if sid not in pooled:
                continue
            P = pooled[sid]
            for k in range(9):
                e29 = b["e29"][k]
                if not e29:
                    continue
                P["valid"] += 1
                lst = b["lst"][k]
                if not lst:
                    P["nolst"] += 1
                    continue
                if lst * LST_SCALE < LST_MIN_K:
                    P["cold"] += 1
                    continue
                P["e29"].append(emis(e29))
                for key in ("e31", "e32"):
                    if b[key][k]:
                        P[key].append(emis(b[key][k]))
                P["composites"].add(rec["item"])
                P["years"].add(y)
    out = {}
    for sid, P in pooled.items():
        r = {"n": len(P["e29"]), "valid": P["valid"], "cold": P["cold"], "nolst": P["nolst"],
             "composites": len(P["composites"]), "years": sorted(P["years"])}
        for key in ("e29", "e31", "e32"):
            r[key] = round(statistics.fmean(P[key]), 4) if P[key] else None
            r[key + "_sd"] = round(statistics.pstdev(P[key]), 4) if len(P[key]) > 1 else None
        out[sid] = r
    return out


def box_summary(raw):
    st = json.load(open(os.path.join(raw, "modis_boxes.json"), encoding="utf-8"))
    out = {}
    for bid, yrs in st["acc"].items():
        s = sum(v[0] for v in yrs.values())
        n = sum(v[1] for v in yrs.values())
        out[bid] = (round(s / n * E_SCALE + E_OFFSET, 4) if n else None, n)
    ncomp = sum(len(v) for v in st["done"].values())
    return out, st, ncomp


# ----------------------------------------------------------------------------- check (a)
def check2023(raw, sites, log):
    """Reproduce the scout's 2023 e29 at the 5 Jordan sites (scout's sample and statistic), and
    show this script's own method (all 46 composites, LST screen, mean) for 2023 next to it."""
    jsites = [s for s in sites if s["id"] in SCOUT_2023]
    by_tile = defaultdict(list)
    for s in jsites:
        by_tile[cc.modis_tile(s["lat"], s["lon"])].append(s)
    res = {sid: {"scout": SCOUT_2023[sid]} for sid in SCOUT_2023}
    for (h, v), group in sorted(by_tile.items()):
        prefix, ids, _ = search_tile(h, v, 2023, 2023, ["Emis_29", "LST_Day_1KM"])
        # newest first, as the STAC API returned them to the scout: a tie (e.g. day 213 between
        # composites 209 and 217) goes to the later composite
        by_doy = {item_date(i)[1]: i for i in sorted(ids, reverse=True)}
        scout_sel = []
        for target in MONTH_STARTS:
            doy = min(by_doy, key=lambda d: abs(d - target))
            if by_doy[doy] not in scout_sel:
                scout_sel.append(by_doy[doy])
        spx = {s["id"]: site_window(h, v, s["lat"], s["lon"]) for s in group}
        pooled_scout = {sid: [] for sid in spx}
        own = {sid: [] for sid in spx}
        for iid in ids:
            e = {}
            for band in ("Emis_29", "LST_Day_1KM"):
                cog = cc.COG(pc.pc_source(href(prefix, iid, band)), header_bytes=HEADER)
                e[band] = {sid: read_values(cog, p) for sid, p in spx.items()}
            for sid in spx:
                for k in range(9):
                    d29, dl = e["Emis_29"][sid][k], e["LST_Day_1KM"][sid][k]
                    if iid in scout_sel and d29:
                        pooled_scout[sid].append(emis(d29))
                    if d29 and dl and dl * LST_SCALE >= LST_MIN_K:
                        own[sid].append(emis(d29))
        for sid in spx:
            ps = pooled_scout[sid]
            r = res[sid]
            r["reproduced"] = round(statistics.median(ps), 4) if ps else None
            r["n_scout_method"] = len(ps)
            r["composites_scout_method"] = len(scout_sel)
            r["own_method_2023_mean"] = round(statistics.fmean(own[sid]), 4) if own[sid] else None
            r["n_own_method"] = len(own[sid])
            r["composites_2023"] = len(ids)
            r["ok"] = r["reproduced"] is not None and abs(r["reproduced"] - r["scout"]) <= 0.0005
    ok = all(r.get("ok") for r in res.values())
    out = {"check": "(a) scout's 2023 MOD21A2 e29 at the 5 Jordan sites, reproduced with the scout's sample "
                    "(the 12 Terra composites of 2023 that start nearest the 1st of each month, ties to the later one) and statistic "
                    "(median of all valid 3 x 3 window pixels, no LST screen); tolerance 0.0005",
           "ok": ok, "sites": res,
           "run": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    _dump(os.path.join(raw, "check2023.json"), out, indent=1)
    for sid, r in res.items():
        log("  check2023 %-16s scout %.4f  reproduced %s (n=%s)  own method 2023 mean %s (n=%s)  %s" % (
            sid, r["scout"], r.get("reproduced"), r.get("n_scout_method"), r.get("own_method_2023_mean"),
            r.get("n_own_method"), "OK" if r.get("ok") else "MISMATCH"))
    return out
