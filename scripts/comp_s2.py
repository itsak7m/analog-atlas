"""comp_s2: Sentinel-2 L2A surface-reflectance indicators at the sites (AWS Open Data, no token).

Helper for scripts/fetch_composition.py. STAC: Element 84 Earth Search v1 (sentinel-2-l2a), COGs in
the public sentinel-cogs bucket, read with HTTP range requests.

Reflectance = DN * 0.0001. Earth Search items with earthsearch:boa_offset_applied = true already had
the processing-baseline-04.00 offset (-1000 DN) removed from the pixels, so the -0.1 offset listed in
raster:bands is NOT applied again (scout's check: Dead Sea water B12 DN ~490 would turn negative).
Only such items are used.

Per site: the 20 m pixel that holds the site and its 8 neighbours (3 x 3 = 60 m). The 10 m bands
(B02, B03, B04, B08) are averaged over the 2 x 2 10 m pixels inside each 20 m pixel. A 20 m pixel is
used only when the scene classification (SCL) calls it vegetation (4) or not-vegetated (5) and all
bands are > 0. A scene is used only when at least 5 of the 9 pixels pass.
Per scene the SCL classes are also counted over about 2.8 km x 2.8 km around the site (the
footprint of the 3 x 3 MODIS window) to see how much water, snow or vegetation it holds.
"""
import datetime as dt
import statistics

import comp_cog as cc
import comp_pc as pc

COLL = "sentinel-2-l2a"
B10 = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08"}
B20 = {"swir16": "B11", "swir22": "B12"}
SCL_OK = (4, 5)
SCL_NAMES = {0: "nodata", 1: "saturated", 2: "dark", 3: "shadow", 4: "vegetation", 5: "bare", 6: "water",
             7: "unclassified", 8: "cloud-med", 9: "cloud-high", 10: "cirrus", 11: "snow"}
NEED_SCENES = 3
MAX_TRIES = 10
FOOT_HALF_M = 1390.0         # half side of the 3 x 3 MODIS window (3 x 926.6 m / 2)


def search(lat, lon, d0, d1):
    feats = pc.search(pc.ES_STAC, COLL, intersects={"type": "Point", "coordinates": [lon, lat]},
                      datetime="%sT00:00:00Z/%sT23:59:59Z" % (d0, d1),
                      query={"eo:cloud_cover": {"lt": 20}}, limit=200, max_items=1000)
    out = []
    for f in feats:
        p = f["properties"]
        if not p.get("earthsearch:boa_offset_applied"):
            continue
        a = f["assets"]
        if not all(k in a for k in list(B10) + list(B20) + ["scl"]):
            continue
        out.append({"id": f["id"], "date": p["datetime"][:10], "cloud": round(float(p["eo:cloud_cover"]), 2),
                    "baseline": p.get("s2:processing_baseline"),
                    "hrefs": {k: a[k]["href"] for k in list(B10) + list(B20) + ["scl"]}})
    return out


def order_candidates(cands):
    """Clearest first; one scene per date. Among scenes with <= 5 % cloud the clearest scene of each
    season (quarter) comes first, so the 3 scenes spread over the year; scenes above 5 % come last."""
    best = {}
    for c in sorted(cands, key=lambda c: (c["cloud"], c["id"])):
        best.setdefault(c["date"], c)
    cands = sorted(best.values(), key=lambda c: (c["cloud"], c["date"]))
    low = [c for c in cands if c["cloud"] <= 5]
    high = [c for c in cands if c["cloud"] > 5]
    first, rest, seen = [], [], set()
    for c in low:
        q = (int(c["date"][5:7]) - 1) // 3
        if q in seen:
            rest.append(c)
        else:
            seen.add(q)
            first.append(c)
    return first + rest + high


def _cog(href):
    return cc.COG(pc.public_source(href), header_bytes=65536)


def scene_values(sc, lat, lon):
    """Returns (record, nbytes). record['usable'] says whether the scene passed the SCL test."""
    nbytes = 0
    scl = _cog(sc["hrefs"]["scl"])
    x, y = cc.project_for(scl, lat, lon)
    r0, c0 = scl.rowcol(x, y)
    win = [(r, c) for r in range(r0 - 1, r0 + 2) for c in range(c0 - 1, c0 + 2)]
    scl_win = [None if scl.pixel(r, c) is None else int(scl.pixel(r, c)[0]) for r, c in win]
    # SCL class counts in the ~2.8 km MODIS footprint
    half = int(round(FOOT_HALF_M / scl.gt[1]))
    counts = {}
    for r in range(r0 - half, r0 + half + 1):
        for c in range(c0 - half, c0 + half + 1):
            p = scl.pixel(r, c)
            if p is not None:
                counts[int(p[0])] = counts.get(int(p[0]), 0) + 1
    nbytes += scl.src.nbytes
    tot = sum(v for k, v in counts.items() if k != 0) or 1
    foot = {SCL_NAMES.get(k, str(k)): round(100.0 * v / tot, 1) for k, v in sorted(counts.items()) if k != 0}
    rec = {"id": sc["id"], "date": sc["date"], "cloud": sc["cloud"], "scl": scl_win, "footprintPct": foot}
    ok = [i for i, s in enumerate(scl_win) if s in SCL_OK]
    if len(ok) < 5:
        rec["usable"] = False
        rec["why"] = "only %d of 9 pixels are land in SCL (%s)" % (
            len(ok), ", ".join("%s %d" % (SCL_NAMES.get(s, s), scl_win.count(s)) for s in sorted(set(x for x in scl_win if x is not None))))
        return rec, nbytes
    dn = {}
    for key in B20:
        cog = _cog(sc["hrefs"][key])
        xx, yy = cc.project_for(cog, lat, lon)
        rr, c2 = cog.rowcol(xx, yy)
        if (rr, c2) != (r0, c0):
            raise RuntimeError("20 m grids differ in %s" % sc["id"])
        dn[key] = [None if cog.pixel(r, c) is None else int(cog.pixel(r, c)[0]) for r, c in win]
        nbytes += cog.src.nbytes
    x0s, ps, y0s, _ = scl.gt
    for key in B10:
        cog = _cog(sc["hrefs"][key])
        x0, p10, y0, _ = cog.gt
        vals = []
        for r, c in win:
            xu, yu = x0s + c * ps, y0s - r * ps            # upper-left corner of the 20 m pixel
            sub = []
            for dy in (0.25, 0.75):
                for dx in (0.25, 0.75):
                    rr = int((y0 - (yu - dy * ps)) // p10)
                    cc_ = int(((xu + dx * ps) - x0) // p10)
                    p = cog.pixel(rr, cc_)
                    sub.append(None if p is None else int(p[0]))
            vals.append(sub)
        dn[key] = vals
        nbytes += cog.src.nbytes
    rec["dn"] = dn
    px = []
    for i in range(9):
        if scl_win[i] not in SCL_OK:
            continue
        refl = {}
        bad = False
        for key in B20:
            v = dn[key][i]
            if not v or v >= 65535:
                bad = True
                break
            refl[key] = v * 1e-4
        for key in B10:
            sub = dn[key][i]
            if bad or any((not v) or v >= 65535 for v in sub):
                bad = True
                break
            refl[key] = sum(sub) / 4.0 * 1e-4
        if bad:
            continue
        px.append({"fe": refl["red"] / refl["blue"], "swir": refl["swir16"] / refl["swir22"],
                   "bright": (refl["blue"] + refl["green"] + refl["red"] + refl["nir"] + refl["swir16"] + refl["swir22"]) / 6.0,
                   "ndvi": (refl["nir"] - refl["red"]) / (refl["nir"] + refl["red"])})
    if len(px) < 5:
        rec["usable"] = False
        rec["why"] = "only %d of 9 pixels have valid reflectance in all bands" % len(px)
        return rec, nbytes
    rec["usable"] = True
    rec["n"] = len(px)
    for k in ("fe", "swir", "bright", "ndvi"):
        rec[k] = round(statistics.median(p[k] for p in px), 4)
    return rec, nbytes


def site_values(site, d0, d1, log):
    t = dt.datetime.now()
    cands = order_candidates(search(site["lat"], site["lon"], d0, d1))
    used, tried, nbytes = [], [], 0
    for sc in cands[:MAX_TRIES]:
        try:
            rec, nb = scene_values(sc, site["lat"], site["lon"])
        except Exception as e:  # noqa: BLE001
            rec, nb = {"id": sc["id"], "date": sc["date"], "cloud": sc["cloud"], "usable": False,
                       "why": "read failed: %s" % str(e)[:120]}, 0
        nbytes += nb
        tried.append(rec)
        if rec.get("usable"):
            used.append(rec)
            if len(used) >= NEED_SCENES:
                break
    res = {"candidates": len(cands), "tried": tried, "MB": round(nbytes / 1e6, 1),
           "seconds": round((dt.datetime.now() - t).total_seconds(), 1)}
    log("  S2 %-20s candidates %3d, tried %d, used %d (%s)  %.1f MB" % (
        site["id"], len(cands), len(tried), len(used), ", ".join(u["date"] for u in used), nbytes / 1e6))
    return res


def summary(rec):
    """Site values from the raw record: median over the used scenes of the per-scene medians."""
    used = [t for t in rec["tried"] if t.get("usable")]
    if not used:
        return None
    out = {"scenes": [{"id": u["id"], "date": u["date"], "cloud": u["cloud"]} for u in used]}
    for k, name in (("fe", "feRatio"), ("swir", "swirRatio"), ("bright", "brightness"), ("ndvi", "ndvi")):
        out[name] = round(statistics.median(u[k] for u in used), 3)
    out["ndviMax"] = round(max(u["ndvi"] for u in used), 3)
    out["waterPct"] = round(max(u["footprintPct"].get("water", 0.0) for u in used), 1)
    return out
