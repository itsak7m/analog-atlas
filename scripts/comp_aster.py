"""comp_aster: ASTER L1T thermal infrared (bands 10-14, 90 m, 2000-2006) silica index at the sites.

Helper for scripts/fetch_composition.py. Data: Microsoft Planetary Computer collection aster-l1t
(TIR COG asset, 5 bands of uint16 DN), read with HTTP range requests, no login. Same method as the
no-login scout prototype (aster_tir_prototype.py + summarize.py):

  scenes  : all aster-l1t items with a TIR asset that contain the site, eo:cloud_cover <= 5 %,
            sat:orbit_state 'descending' (Terra's daytime pass), sun elevation > 20 deg; sorted by
            (cloud cover, date); the first 6 are read; a scene with fewer than 5 valid pixels is dropped
  window  : 5 x 5 pixels (about 450 m) around the site; a pixel is valid when all 5 DN > 1 and < 4095
  radiance: L_i = (DN_i - 1) * UCC_i  (ASTER unit conversion coefficients, W m-2 sr-1 um-1 per DN)
  NEM     : normalized emissivity method with eps_max = 0.97: T = max_i Tb_i(L_i / 0.97),
            eps_i = L_i / Planck(lambda_i, T). No atmospheric correction: relative only.
  silica index SI = (e13 + e14) / 2 - (e10 + e12) / 2, from the median (over all valid pixels of all
            used scenes) of each band's NEM emissivity. Quartz and other silica-rich minerals have
            their strongest emissivity low (reststrahlen) in bands 10-12 (8.1-9.3 um); bands 13-14
            (10.3-11.6 um) stay high, so a larger SI means a more silica-rich surface.
  quartz index QI (Ninomiya et al. 2005) = L11^2 / (L10 * L12), median over pixels, kept for reference.
"""
import math
import statistics

import comp_cog as cc
import comp_pc as pc

COLL = "aster-l1t"
UCC = [6.822e-3, 6.780e-3, 6.590e-3, 5.693e-3, 5.225e-3]   # bands 10-14
WL = [8.291, 8.634, 9.075, 10.657, 11.318]                  # band centres, um
C1, C2 = 1.191042e8, 1.4387752e4
MAXSCENES = 6
HALF = 2
EPS_MAX = 0.97


def planck(wl, t):
    return C1 / (wl ** 5 * (math.exp(C2 / (wl * t)) - 1.0))


def inv_planck(wl, rad):
    return C2 / (wl * math.log(C1 / (wl ** 5 * rad) + 1.0))


def pixel_metrics(dn):
    if min(dn) <= 1 or max(dn) >= 4095:
        return None
    L = [(d - 1) * u for d, u in zip(dn, UCC)]
    t = max(inv_planck(w, l / EPS_MAX) for w, l in zip(WL, L))
    eps = [l / planck(w, t) for w, l in zip(WL, L)]
    return {"QI": L[1] * L[1] / (L[0] * L[2]), "T": t, "e": eps}


def silica_index(e):
    return (e[3] + e[4]) / 2.0 - (e[0] + e[2]) / 2.0


def search(lat, lon):
    feats = pc.search(pc.PC_STAC, COLL, intersects={"type": "Point", "coordinates": [lon, lat]}, max_items=1000,
                      fields={"include": ["id", "properties.datetime", "properties.eo:cloud_cover",
                                          "properties.sat:orbit_state", "properties.view:sun_elevation",
                                          "assets.TIR.href"],
                              "exclude": ["geometry", "links", "bbox"]})
    return feats


def clear_day(feats):
    good = []
    for f in feats:
        p = f.get("properties", {})
        cl = p.get("eo:cloud_cover")
        cl = 100 if cl is None else cl
        if "TIR" in f.get("assets", {}) and cl <= 5 and p.get("sat:orbit_state") == "descending" \
                and (p.get("view:sun_elevation") or 0) > 20:
            good.append(f)
    good.sort(key=lambda f: (f["properties"].get("eo:cloud_cover") or 0, f["properties"]["datetime"]))
    return good


def site_values(site, log):
    feats = search(site["lat"], site["lon"])
    good = clear_day(feats)
    with_tir = sum(1 for f in feats if "TIR" in f.get("assets", {}))
    scenes, allpix, nbytes = [], [], 0
    tried = []
    for f in good[:MAXSCENES]:
        p = f["properties"]
        rec = {"id": f["id"], "date": p["datetime"][:10], "cloud": p.get("eo:cloud_cover"),
               "sunElev": round(p.get("view:sun_elevation") or 0, 1)}
        try:
            src = pc.pc_source(f["assets"]["TIR"]["href"])
            cog = cc.COG(src, header_bytes=32768)
            x, y = cc.project_for(cog, site["lat"], site["lon"])
            win = cog.window(x, y, HALF)
            nbytes += src.nbytes
        except Exception as e:  # noqa: BLE001
            rec["why"] = "read failed: %s" % str(e)[:120]
            tried.append(rec)
            continue
        m = [pm for pm in (pixel_metrics(px[2]) for px in win) if pm]
        rec["n"] = len(m)
        if len(m) < 5:
            rec["why"] = "only %d valid pixels in the 5 x 5 window" % len(m)
            tried.append(rec)
            continue
        e_med = [statistics.median(pm["e"][b] for pm in m) for b in range(5)]
        rec["e"] = [round(v, 4) for v in e_med]
        rec["QI"] = round(statistics.median(pm["QI"] for pm in m), 4)
        rec["SI"] = round(silica_index(e_med), 4)
        rec["T_K"] = round(statistics.median(pm["T"] for pm in m), 1)
        rec["used"] = True
        tried.append(rec)
        scenes.append(rec)
        allpix.extend(m)
    res = {"candidates": len(feats), "withTIR": with_tir, "clearDay": len(good), "tried": tried,
           "MB": round(nbytes / 1e6, 1)}
    if allpix:
        e_all = [statistics.median(pm["e"][b] for pm in allpix) for b in range(5)]
        res["e"] = [round(v, 4) for v in e_all]
        res["SI"] = round(silica_index(e_all), 4)
        res["QI"] = round(statistics.median(pm["QI"] for pm in allpix), 4)
        res["nPix"] = len(allpix)
    log("  ASTER %-20s candidates %3d (TIR %d), clear day %d, used %d, SI %s  %.1f MB" % (
        site["id"], len(feats), with_tir, len(good), len(scenes), res.get("SI"), nbytes / 1e6))
    return res
