#!/usr/bin/env python3
"""Measured surface-composition indicators for the 19 Earth sites and the 886 Jordan boxes.

DISPLAY-ONLY evidence: nothing here is used in any score.

  MODIS MOD21A2 v061 (Terra, 1 km, 8-day)  band-29 (8.55 um) emissivity, plus bands 31 and 32
      sites: 3 x 3 pixel window, mean over all sampled composites (daytime LST >= 0 C only)
      boxes: mean of all 1 km pixels whose centre is inside the 10 km box (band 29 only)
  Sentinel-2 L2A (AWS Earth Search, 10-20 m)  iron-oxide ratio B4/B2, 2.2 um ratio B11/B12,
      brightness, NDVI; 3 x 3 pixels of 20 m (60 m) median, clearest 2-3 scenes of 2023-2024
  ASTER L1T TIR (Planetary Computer, 90 m, 2000-2006)  silica index from clear daytime scenes
      (not atmospherically corrected: relative only)

Outputs: data/composition.json, data/screening_composition.json, and raw extracts, manifest and
README in data/raw/composition/. No login, no account, nothing is uploaded. Python 3.12 standard
library only:

  python -I scripts/fetch_composition.py                 # everything (about 50 minutes; MODIS ~38)
  python -I scripts/fetch_composition.py --sites         # site indicators only (MODIS, S2, ASTER)
  python -I scripts/fetch_composition.py --boxes         # Jordan boxes only (MODIS band 29)
  python -I scripts/fetch_composition.py --sites --only s2      # one site source (modis, s2, aster)
  python -I scripts/fetch_composition.py --check2023     # check (a) only
  python -I scripts/fetch_composition.py --assemble      # rebuild the two outputs from the raw extracts
  add --resume to continue an interrupted run (finished composites / sites are kept)

Printed checks: (a) the scout's 2023 MOD21 e29 at the 5 Jordan sites is reproduced; (b) no NaN in
the outputs; (c) every site has at least one indicator, and every missing indicator has a flag
saying why.
"""
import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:             # python -I does not add the script's folder
    sys.path.insert(0, HERE)

import comp_aster as ca              # noqa: E402
import comp_cog as cc                # noqa: E402
import comp_modis as cm              # noqa: E402
import comp_pc as pc                 # noqa: E402
import comp_s2 as cs                 # noqa: E402

ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw", "composition")
OUT_SITES = os.path.join(DATA, "composition.json")
OUT_BOXES = os.path.join(DATA, "screening_composition.json")

E29_LOW, E29_HIGH = 0.88, 0.95
NDVI_VEG = 0.3
WATER_FOOT_PCT = 20.0
COLD_PCT = 25.0
READ_SILICA = "quartz- or sulfate-rich surface"
READ_MIXED = "mixed"
READ_LOW = "low-silica surface (basalt-like, clay or carbonate)"
ASTER_NOTE = "not atmospherically corrected — relative only"

SOURCES = [
    {"id": "mod21a2", "label": "MODIS/Terra Land Surface Temperature/3-Band Emissivity 8-Day L3 Global 1km SIN Grid V061 (MOD21A2), via Microsoft Planetary Computer (collection modis-21A2-061)",
     "url": "https://planetarycomputer.microsoft.com/dataset/modis-21A2-061", "doi": "10.5067/MODIS/MOD21A2.061",
     "licence": "NASA open data: no restrictions on use, sale or redistribution (LP DAAC data policy)",
     "licenceUrl": "https://lpdaac.usgs.gov/data/data-citation-and-policies/",
     "credit": "Hulley, G., & Hook, S. (2021). MOD21A2 v061 [Data set]. NASA EOSDIS Land Processes DAAC. https://doi.org/10.5067/MODIS/MOD21A2.061. Accessed through Microsoft Planetary Computer."},
    {"id": "aster-l1t", "label": "ASTER Level 1 Precision Terrain Corrected Registered At-Sensor Radiance V003 (AST_L1T), thermal bands 10-14, via Microsoft Planetary Computer (collection aster-l1t, 2000-2006)",
     "url": "https://planetarycomputer.microsoft.com/dataset/aster-l1t", "doi": "10.5067/ASTER/AST_L1T.003",
     "licence": "Public domain (USGS data policy; NASA LP DAAC data policy)",
     "licenceUrl": "https://www.usgs.gov/core-science-systems/hdds/data-policy",
     "credit": "NASA LP DAAC (2015). ASTER Level 1 Precision Terrain Corrected Registered At-Sensor Radiance V003 [Data set]. NASA/METI/AIST/Japan Spacesystems and U.S./Japan ASTER Science Team. https://doi.org/10.5067/ASTER/AST_L1T.003. Accessed through Microsoft Planetary Computer."},
    {"id": "sentinel-2-l2a", "label": "Copernicus Sentinel-2 MSI Level-2A surface reflectance, Cloud-Optimized GeoTIFFs on AWS Open Data (Element 84 Earth Search v1, collection sentinel-2-l2a)",
     "url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/", "doi": "10.5270/S2_-742ikth",
     "licence": "Copernicus Sentinel data terms (free, full and open; legal notice)",
     "licenceUrl": "https://sentinel.esa.int/documents/247904/690755/Sentinel_Data_Legal_Notice",
     "credit": None},   # filled with the years of the scenes used
]
REFERENCES = [
    {"id": "salisbury1992", "citation": "Salisbury, J.W. & D'Aria, D.M. (1992). Emissivity of terrestrial materials in the 8-14 µm atmospheric window. Remote Sensing of Environment 42, 83-106.", "doi": "10.1016/0034-4257(92)90092-X"},
    {"id": "hulley2015", "citation": "Hulley, G.C., Hook, S.J., Abbott, E., Malakar, N., Islam, T. & Abrams, M. (2015). The ASTER Global Emissivity Dataset (ASTER GED): Mapping Earth's emissivity at 100 meter spatial scale. Geophysical Research Letters 42, 7966-7976.", "doi": "10.1002/2015GL065564"},
    {"id": "hulley2011", "citation": "Hulley, G.C. & Hook, S.J. (2011). Generating consistent land surface temperature and emissivity products between ASTER and MODIS data for Earth science research. IEEE Transactions on Geoscience and Remote Sensing 49, 1304-1315.", "doi": "10.1109/TGRS.2010.2063034"},
    {"id": "gillespie1998", "citation": "Gillespie, A., Rokugawa, S., Matsunaga, T., Cothern, J.S., Hook, S. & Kahle, A.B. (1998). A temperature and emissivity separation algorithm for Advanced Spaceborne Thermal Emission and Reflection Radiometer (ASTER) images. IEEE Transactions on Geoscience and Remote Sensing 36, 1113-1126.", "doi": "10.1109/36.700995"},
    {"id": "ninomiya2005", "citation": "Ninomiya, Y., Fu, B. & Cudahy, T.J. (2005). Detecting lithology with ASTER multispectral thermal infrared 'radiance-at-sensor' data. Remote Sensing of Environment 99, 127-139.", "doi": "10.1016/j.rse.2005.06.009"},
    {"id": "vandermeer2014", "citation": "van der Meer, F.D., van der Werff, H.M.A. & van Ruitenbeek, F.J.A. (2014). Potential of ESA's Sentinel-2 for geological applications. Remote Sensing of Environment 148, 124-133.", "doi": "10.1016/j.rse.2014.03.022"},
]

# expected thermal reading class per app rock type (silica / mixed / low)
EXPECT = {"sandstone": {"silica"}, "granite": {"silica", "mixed"}, "chert": {"silica"}, "basalt": {"low"},
          "carbonate": {"low"}, "mudstone": {"low", "mixed"}, "evaporite": {"silica", "low"}}
VENEER_ROCKS = {"carbonate", "mudstone"}
CONCLUDE = {
    ("sandstone", "silica"): "fits quartz sandstone",
    ("sandstone", "mixed"): "sandstone mixed with other material (clay, carbonate or dark rock)",
    ("sandstone", "low"): "not what quartz sandstone gives",
    ("basalt", "low"): "fits basalt",
    ("basalt", "mixed"): "basalt mixed with sand or silica-rich soil",
    ("basalt", "silica"): "a silica-rich surface, not what basalt gives",
    ("carbonate", "low"): "fits carbonate",
    ("carbonate", "mixed"): "carbonate mixed with silica-rich material (chert or sand)",
    ("carbonate", "silica"): "likely chert (flint) gravel or blown quartz sand covering the carbonate",
    ("mudstone", "low"): "fits clay-rich mud",
    ("mudstone", "mixed"): "fits clay mixed with quartz silt or sand",
    ("mudstone", "silica"): "likely blown quartz sand or chert gravel on the mud",
    ("evaporite", "low"): "fits halite, aragonite or clay-rich marl rather than gypsum",
    ("evaporite", "silica"): "fits gypsum (sulfate)",
    ("evaporite", "mixed"): "a mix of sulfate with other salts or mud",
}


def log(msg):
    print(msg, flush=True)


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def dump(path, obj, indent=1):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False, allow_nan=False,
                  separators=(",", ":") if indent is None else (",", ": "))
        f.write("\n")
    os.replace(tmp, path)


def load_sites():
    sites = load_json(os.path.join(DATA, "sites.json"))["sites"]
    meta = {s["id"]: s for s in load_json(os.path.join(DATA, "sites_meta.json"))["sites"]}
    out = []
    for s in sites:
        out.append({"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "jordan": bool(s.get("jordan")),
                    "rock": meta[s["id"]]["geology"]["primary"]})
    return out


def record_run(step, started, extra):
    path = os.path.join(RAW, "run_%s.json" % step)
    d = load_json(path, {"runs": []})
    d["runs"].append({"started": started, "finished": now(), "requests": json.loads(json.dumps(cc.STATS)),
                      "sasTokenCalls": pc.TOKEN_CALLS[0], **extra})
    dump(path, d)


# ============================================================================ fetch steps
def step_modis(args, sites, do_sites, do_boxes):
    started = now()
    scr = load_json(os.path.join(DATA, "screening_jordan.json"))
    _, stats = cm.run(RAW, sites if do_sites else [], scr["grid"], scr["boxes"], args.y0, args.y1, args.stride,
                      do_sites, do_boxes, args.resume, args.workers, log)
    record_run("modis", started, {"years": [args.y0, args.y1], "stride": args.stride, "sites": do_sites,
                                  "boxes": do_boxes, "compositeReads": stats["done"], "MB": round(stats["bytes"] / 1e6, 1),
                                  "failed": stats["failed"], "seconds": stats["seconds"]})
    if stats["failed"]:
        log("MOD21A2: %d composite reads failed; run again with --resume" % len(stats["failed"]))


def step_s2(args, sites):
    started = now()
    path = os.path.join(RAW, "s2_sites.json")
    d = load_json(path, None) if args.resume else None
    if not d or d.get("dates") != [args.s2_d0, args.s2_d1]:
        d = {"about": "Sentinel-2 L2A raw extracts per site: every scene tried, its SCL 3 x 3 window, DNs of the 20 m bands (3 x 3) "
                      "and of the 10 m bands (2 x 2 per 20 m pixel), per-scene medians, and SCL class percentages in the ~2.8 km MODIS footprint. "
                      "Reflectance = DN * 0.0001 (boa offset already applied in these COGs).",
             "stac": cs.pc.ES_STAC, "collection": cs.COLL, "dates": [args.s2_d0, args.s2_d1], "sites": {}}
    for s in sites:
        if s["id"] in d["sites"] and args.resume:
            continue
        try:
            d["sites"][s["id"]] = cs.site_values(s, args.s2_d0, args.s2_d1, log)
        except Exception as e:  # noqa: BLE001
            log("  S2 %s failed: %s" % (s["id"], e))
            continue
        dump(path, d, indent=None)
    record_run("s2", started, {"dates": [args.s2_d0, args.s2_d1]})


def step_aster(args, sites):
    started = now()
    path = os.path.join(RAW, "aster_sites.json")
    d = load_json(path, None) if args.resume else None
    if not d:
        d = {"about": "ASTER L1T TIR raw extracts per site: candidate counts, every scene read (5 x 5 window): per-scene medians of "
                      "the NEM emissivities e10..e14 (eps_max 0.97, no atmospheric correction), silica index SI, Ninomiya quartz index QI, "
                      "and the site values over all pixels of all used scenes.",
             "collection": ca.COLL, "sites": {}}
    for s in sites:
        if s["id"] in d["sites"] and args.resume:
            continue
        try:
            d["sites"][s["id"]] = ca.site_values(s, log)
        except Exception as e:  # noqa: BLE001
            log("  ASTER %s failed: %s" % (s["id"], e))
            continue
        dump(path, d, indent=None)
    record_run("aster", started, {})


def step_check(args, sites):
    started = now()
    res = cm.check2023(RAW, sites, log)
    record_run("check2023", started, {"ok": res["ok"]})
    return res


# ============================================================================ assembly
def reading_class(e29):
    if e29 < E29_LOW:
        return "silica"
    if e29 > E29_HIGH:
        return "low"
    return "mixed"


READING_TEXT = {"silica": READ_SILICA, "mixed": READ_MIXED, "low": READ_LOW}


def ordinal(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def site_point_water(s2raw):
    """True when more tried scenes show open water (>= 5 of the 9 SCL pixels at the site) than show
    land (>= 5 pixels bare or vegetation); snow- or cloud-covered scenes do not count either way
    (a frozen lake looks like snow)."""
    tried = [t for t in s2raw.get("tried", []) if t.get("scl")]
    wet = sum(1 for t in tried if t["scl"].count(6) >= 5)
    land = sum(1 for t in tried if sum(t["scl"].count(k) for k in cs.SCL_OK) >= 5)
    return wet > 0 and wet > land


def assemble(args, sites):
    t0 = time.time()
    items = load_json(os.path.join(RAW, "modis_items.json"))
    s2raw = load_json(os.path.join(RAW, "s2_sites.json"), {"sites": {}})
    asraw = load_json(os.path.join(RAW, "aster_sites.json"), {"sites": {}})
    check = load_json(os.path.join(RAW, "check2023.json"))
    missing = [n for n, v in (("modis_items.json", items), ("modis_sites.jsonl", os.path.exists(os.path.join(RAW, "modis_sites.jsonl"))),
                              ("modis_boxes.json", os.path.exists(os.path.join(RAW, "modis_boxes.json"))),
                              ("s2_sites.json", s2raw.get("sites")), ("aster_sites.json", asraw.get("sites")),
                              ("check2023.json", check)) if not v]
    if missing:
        log("assemble: raw extracts missing: %s (run the fetch steps first)" % ", ".join(missing))
        return False
    y0, y1 = items["years"]
    years_txt = "%d-%d" % (y0, y1) if y1 > y0 else str(y0)
    msum = cm.site_summary(RAW, [s["id"] for s in sites])
    ncomp_tile = {t: len(v["ids"]) for t, v in items["tiles"].items()}

    # ASTER ranks (highest silica index = 1st)
    si_vals = sorted(((v["SI"], k) for k, v in asraw["sites"].items() if v.get("SI") is not None), reverse=True)
    si_rank = {k: i + 1 for i, (_, k) in enumerate(si_vals)}

    s2_years = set()
    places = {}
    for s in sites:
        sid = s["id"]
        flags = []
        P = {}
        # ---- MODIS
        m = msum.get(sid)
        if m and m["e29"] is not None:
            P["modis"] = {"e29": round(m["e29"], 3), "e31": None if m["e31"] is None else round(m["e31"], 3),
                          "e32": None if m["e32"] is None else round(m["e32"], 3), "n": m["n"], "years": years_txt,
                          "composites": m["composites"], "coldExcluded": m["cold"]}
            if m["valid"] and 100.0 * m["cold"] / m["valid"] > COLD_PCT:
                flags.append({"id": "coldSeason", "why": "%d %% of the valid MODIS samples had daytime LST below 0 °C and were left out: values are from the snow-free season only" % round(100.0 * m["cold"] / m["valid"])})
        else:
            P["modis"] = None
            why = "no valid MOD21A2 band-29 sample in the 3 x 3 window"
            if m and m["valid"]:
                why = "all %d valid MOD21A2 samples had daytime LST below 0 °C or missing (snow, ice or frozen ground)" % m["valid"]
            flags.append({"id": "noModis", "why": why})
        # ---- Sentinel-2
        r2 = s2raw["sites"].get(sid)
        s2 = cs.summary(r2) if r2 else None
        point_water = bool(r2) and site_point_water(r2)
        if s2:
            P["s2"] = s2
            for sc in s2["scenes"]:
                s2_years.add(sc["date"][:4])
            if len(s2["scenes"]) == 1:
                flags.append({"id": "oneS2Scene", "why": "only 1 usable Sentinel-2 scene (%d tried)" % len(r2["tried"])})
            if s2["ndviMax"] > NDVI_VEG:
                flags.append({"id": "vegetation", "why": "Sentinel-2 NDVI at the site is above %.1f (up to %.2f): the composition indicators are not interpreted" % (NDVI_VEG, s2["ndviMax"])})
            if s2["waterPct"] > WATER_FOOT_PCT:
                flags.append({"id": "waterNearby", "why": "water covers up to %.0f %% of the ~2.8 km MODIS window in Sentinel-2's scene classification; water raises e29" % s2["waterPct"]})
        else:
            P["s2"] = None
            if r2 is None:
                why = "Sentinel-2 step did not run for this site"
            elif r2["candidates"] == 0:
                why = "no Sentinel-2 L2A scene with < 20 %% cloud in %s to %s" % (s2raw["dates"][0], s2raw["dates"][1])
            elif point_water:
                why = "the site point is open water in Sentinel-2's scene classification"
            else:
                reasons = sorted(set(t.get("why", "?").split(" (")[0] for t in r2["tried"]))
                why = "none of the %d scenes tried had at least 5 of 9 land pixels at the site (%s)" % (len(r2["tried"]), "; ".join(reasons))
            flags.append({"id": "noS2", "why": why})
            if point_water:
                flags.append({"id": "water", "why": "the site point is open water in Sentinel-2's scene classification: not interpreted"})
        # ---- ASTER
        ra = asraw["sites"].get(sid)
        if ra and ra.get("SI") is not None:
            used = [t for t in ra["tried"] if t.get("used")]
            P["aster"] = {"scenes": [{"id": t["id"], "date": t["date"], "cloud": t["cloud"]} for t in used],
                          "silicaIndex": round(ra["SI"], 3), "quartzIndex": round(ra["QI"], 3),
                          "rank": si_rank[sid], "of": len(si_rank), "note": ASTER_NOTE}
            if len(used) == 1:
                flags.append({"id": "oneAsterScene", "why": "only 1 clear daytime ASTER scene"})
        else:
            P["aster"] = None
            if ra is None:
                why = "ASTER step did not run for this site"
            elif ra.get("withTIR", 0) == 0:
                why = "no ASTER L1T scene with thermal bands on Planetary Computer covers this point (%d scenes found)" % ra.get("candidates", 0)
            elif ra.get("clearDay", 0) == 0:
                why = "%d ASTER L1T scenes with thermal bands cover this point, none clear (<= 5 %% cloud) and daytime" % ra["withTIR"]
            else:
                why = "%d clear daytime ASTER scenes, none with 5 valid pixels at the site" % ra["clearDay"]
            flags.append({"id": "noAster", "why": why})
        # ---- reading
        cls = None
        if P["modis"] is None:
            reading = "no thermal data"
        elif any(f["id"] == "vegetation" for f in flags):
            reading = "not interpreted: vegetation at the site"
        elif point_water:
            reading = "not interpreted: water at the site"
        else:
            cls = reading_class(P["modis"]["e29"])
            reading = READING_TEXT[cls]
            if P["s2"] is None:
                flags.append({"id": "vegetationUnchecked", "why": "no usable Sentinel-2 scene, so vegetation at the site could not be checked"})
        P["reading"] = reading
        P["flags"] = flags
        # ---- Jordan check
        if s["jordan"]:
            rock = s["rock"]
            if cls is None:
                P["jordanCheck"] = {"rock": rock, "verdict": "not checked", "reason": reading}
            else:
                exp = EXPECT.get(rock, set())
                if cls in exp:
                    verdict = "agrees"
                elif cls == "mixed" or (cls == "silica" and rock in VENEER_ROCKS):
                    verdict = "partly"
                else:
                    verdict = "differs"
                ev = "MODIS e29 %.3f (%s)" % (P["modis"]["e29"], {"silica": "silica-rich", "mixed": "mixed", "low": "low-silica"}[cls])
                if P["aster"]:
                    rk = P["aster"]["rank"]
                    ev += ", ASTER silica index %.3f (%s of %d sites)" % (P["aster"]["silicaIndex"], "highest" if rk == 1 else ordinal(rk) + " highest", P["aster"]["of"])
                concl = CONCLUDE.get((rock, cls), "")
                P["jordanCheck"] = {"rock": rock, "verdict": verdict,
                                    "reason": "%s: %s on the map; %s → %s" % (verdict, rock, ev, concl)}
        places[sid] = P

    # ---- sources and rules
    sources = json.loads(json.dumps(SOURCES))
    yrs = sorted(s2_years)
    yr_txt = yrs[0] if len(yrs) == 1 else ("%s-%s" % (yrs[0], yrs[-1]) if yrs else "")
    for src in sources:
        if src["id"] == "sentinel-2-l2a":
            src["credit"] = "Contains modified Copernicus Sentinel data %s" % yr_txt
    ncomp = sorted(set(ncomp_tile.values()))
    ncomp_txt = "/".join(map(str, ncomp))
    sample_txt = ("all %s Terra 8-day composites of %s (46 per year)" % (ncomp_txt, years_txt) if args_stride(items) == 1
                  else "every %d. Terra 8-day composite of %s (%s composites per tile)" % (args_stride(items), years_txt, ncomp_txt))
    rules = {
        "displayOnly": "These indicators are display-only evidence. They are never used in any score or ranking.",
        "modis": "MODIS MOD21A2 v061 (Terra, 1 km). Band-29 emissivity e29 at 8.55 µm: quartz and sulfate (gypsum) have strong emissivity lows (reststrahlen bands) near 8.5-9 µm, so e29 is low on quartz- or sulfate-rich surfaces and high on low-silica rock (basalt), clay, carbonate, vegetation and water. "
                 "Bands 31 (11 µm) and 32 (12 µm) are stored for reference; they stay near 0.96-0.98 on most land. "
                 "Site value: mean of all valid pixels of the 3 x 3 pixel window (about 2.8 km x 2.8 km) around the site over %s; samples with daytime LST missing or below 0 °C are left out (snow, ice or frozen ground raise emissivity). n = number of pixel samples (pixels x composites)." % sample_txt,
        "s2": {
            "feRatio": "Iron-oxide ratio B4/B2 (red / blue surface reflectance): ferric iron oxides (hematite, goethite) absorb blue light, so a higher ratio means a redder, more iron-stained surface (van der Meer et al. 2014).",
            "swirRatio": "2.2 µm ratio B11/B12 (1.6 / 2.2 µm): clay (Al-OH), carbonate and sulfate minerals absorb in the B12 range (about 2.1-2.3 µm), so a higher ratio means more of these minerals (van der Meer et al. 2014).",
            "brightness": "Unweighted mean of B2, B3, B4, B8, B11 and B12 surface reflectance (0-1), a broadband-like brightness (not a calibrated albedo): dark basalt and varnished rock are low; salt, gypsum, chalk and sand are high.",
            "ndvi": "NDVI = (B8 - B4) / (B8 + B4); flags vegetation. When NDVI at the site is above 0.3 in any used scene, the site is not interpreted.",
            "method": "3 x 3 pixels of 20 m (60 m) around the site; the 10 m bands are averaged to 20 m first; only pixels that the L2A scene classification (SCL) calls bare (5) or vegetation (4) are used, and a scene needs 5 of 9. Per scene the median of the pixels; site value = median of the scene values. Scenes from %s to %s: clearest first (cloud cover <= 5 %%, the clearest scene of each season first, then up to 20 %%); the first 3 usable scenes are kept. Reflectance = DN x 0.0001 (Earth Search COGs with boa_offset_applied = true; the offset is not applied again). waterPct = largest share of water (SCL 6) in the ~2.8 km MODIS window among the used scenes." % (s2raw["dates"][0], s2raw["dates"][1])},
        "aster": "ASTER L1T thermal bands 10-14 (90 m, 2000-2006). Clear daytime scenes (cloud cover <= 5 %, descending = daytime pass, sun elevation > 20°) that contain the site; the first 6 by (cloud cover, date) are read; 5 x 5 pixels (about 450 m) around the site. Radiance L = (DN - 1) x unit conversion coefficient; emissivity e10..e14 by the normalized emissivity method (maximum emissivity 0.97). "
                 "Silica index = (e13 + e14) / 2 - (e10 + e12) / 2, from the median of each band's emissivity over all valid pixels of all used scenes: silica minerals pull bands 10-12 (8.1-9.3 µm) down while bands 13-14 stay high, so a larger index means a more silica-rich surface. quartzIndex = L11² / (L10 x L12) (Ninomiya et al. 2005). " + ASTER_NOTE.capitalize() + ": water vapour also lowers bands 10-12, so compare sites with each other, not with laboratory values. rank = position from the highest silica index among the sites with ASTER data.",
        "reading": "From the MODIS band-29 mean e29 only: e29 < %.2f → '%s'; e29 > %.2f → '%s'; otherwise '%s'. Not interpreted when Sentinel-2 shows vegetation (NDVI > 0.3) or open water at the site. A reading describes the top surface (thermal bands see the top fraction of a millimetre); it never names a rock." % (E29_LOW, READ_SILICA, E29_HIGH, READ_LOW, READ_MIXED),
        "thresholds": "Physics: quartz- and sulfate-rich materials have deep emissivity lows at 8-9.5 µm, while basalt, carbonate, clay, vegetation and water stay high there (laboratory spectra: Salisbury & D'Aria 1992; global ASTER emissivity: Hulley et al. 2015; MODIS band-29 emissivity from the same temperature-emissivity separation: Gillespie et al. 1998, Hulley & Hook 2011). The cut values %.2f and %.2f are ours, placed between those ranges; we looked at these same 19 sites and the scout's 2023 values when fixing them, so the readings and the Jordan checks are illustrations, not independent tests." % (E29_LOW, E29_HIGH),
        "jordanCheck": "Only for the 5 Jordan sites: the reading is compared with the app's rock type (data/sites_meta.json geology.primary). Expected reading: sandstone → quartz- or sulfate-rich; basalt and carbonate → low-silica; mudstone → low-silica or mixed; evaporite → quartz- or sulfate-rich (gypsum) or low-silica (halite, aragonite, clay), so for evaporite the check is weak. "
                       "'agrees' = the reading is the expected one; 'partly' = the reading is 'mixed', or it is silica-rich over a mapped carbonate or mudstone (thermal bands see only the top surface, and in deserts a lag of chert (flint) gravel or blown quartz sand often covers soft sedimentary rock); 'differs' = otherwise. The reason quotes e29 and, when available, the ASTER silica index and its rank among the sites.",
        "flags": {"vegetation": "Sentinel-2 NDVI > 0.3 at the site in at least one used scene: not interpreted.",
                  "water": "the site point is open water in Sentinel-2's scene classification: not interpreted.",
                  "waterNearby": "water covers more than 20 % of the ~2.8 km MODIS window in at least one used Sentinel-2 scene; water raises e29, so read e29 with care.",
                  "coldSeason": "more than 25 % of the valid MODIS samples were left out because daytime LST was below 0 °C: the mean is from the snow-free season only.",
                  "vegetationUnchecked": "no usable Sentinel-2 scene, so vegetation could not be checked.",
                  "oneS2Scene": "only one usable Sentinel-2 scene.", "oneAsterScene": "only one clear daytime ASTER scene.",
                  "noModis": "no MODIS value (why given).", "noS2": "no Sentinel-2 value (why given).", "noAster": "no ASTER value (why given)."},
    }
    out = {
        "about": "Measured surface-composition indicators at the 19 Earth sites: MODIS thermal emissivity (1 km), Sentinel-2 reflectance ratios (60 m) and an ASTER thermal silica index (90 m). DISPLAY-ONLY evidence, never scored. Each indicator is a measurement of the top surface, not a rock identification. Built by scripts/fetch_composition.py from the raw extracts in data/raw/composition/. Do not edit by hand.",
        "generated": now(),
        "sources": sources,
        "references": REFERENCES,
        "rules": rules,
        "sample": {"modis": sample_txt, "modisYears": [y0, y1], "s2Dates": s2raw["dates"], "asterYears": [2000, 2006]},
        "places": places,
    }
    dump(OUT_SITES, out, indent=1)

    # ---- boxes
    bsum, bstate, ncomp_boxes = cm.box_summary(RAW)
    scr = load_json(os.path.join(DATA, "screening_jordan.json"))
    boxes = {}
    nulls = []
    for b in scr["boxes"]:
        v = bsum.get(b["id"])
        if v and v[0] is not None:
            boxes[b["id"]] = {"e29": round(v[0], 3), "n": v[1]}
        else:
            boxes[b["id"]] = {"e29": None, "n": 0}
            nulls.append(b["id"])
    by_rock = {}
    for b in scr["boxes"]:
        rock = b["geology"].get("primary") or "none"
        e = boxes[b["id"]]["e29"]
        if e is not None:
            by_rock.setdefault(rock, []).append(e)
    rock_stats = {}
    for rock, vals in sorted(by_rock.items(), key=lambda kv: -len(kv[1])):
        vals.sort()
        q = statistics.quantiles(vals, n=10) if len(vals) >= 10 else None
        rock_stats[rock] = {"boxes": len(vals), "mean": round(statistics.fmean(vals), 3),
                            "p10": round(q[0], 3) if q else None, "median": round(statistics.median(vals), 3),
                            "p90": round(q[8], 3) if q else None,
                            "silicaRich": sum(1 for v in vals if v < E29_LOW), "mixed": sum(1 for v in vals if E29_LOW <= v <= E29_HIGH),
                            "lowSilica": sum(1 for v in vals if v > E29_HIGH)}
    bout = {
        "about": "MODIS MOD21A2 v061 band-29 emissivity (8.55 µm) per 10 km Jordan box (grid of data/screening_jordan.json): mean of all valid 1 km pixel samples whose pixel centre lies inside the box, over %s. n = number of pixel samples (pixels x composites; about 117 pixels per box). Band 29 only, no LST screen (snow is rare in Jordan). Low e29 = quartz- or sulfate-rich surface; high = low-silica (basalt-like) or clay/carbonate; cut values %.2f / %.2f as in data/composition.json rules. DISPLAY-ONLY evidence, never scored." % (sample_txt, E29_LOW, E29_HIGH),
        "generated": now(),
        "source": {"id": "mod21a2", "doi": "10.5067/MODIS/MOD21A2.061", "credit": SOURCES[0]["credit"], "licenceUrl": SOURCES[0]["licenceUrl"], "details": "data/composition.json"},
        "years": [y0, y1],
        "composites": min((len(v) for v in bstate["done"].values()), default=0),
        "byRock": rock_stats,
        "boxes": boxes,
    }
    dump(OUT_BOXES, bout, indent=None)

    # ---- checks
    ok_all = True
    log("\nCHECKS")
    a_ok = bool(check and check.get("ok"))
    log("(a) scout's 2023 MOD21 e29 at the 5 Jordan sites reproduced: %s" % ("OK" if a_ok else "FAILED"))
    for sid, r in (check or {}).get("sites", {}).items():
        log("      %-16s scout %.3f  reproduced %s  (n=%s)  own method 2023 %s" % (sid, r["scout"], r.get("reproduced"), r.get("n_scout_method"), r.get("own_method_2023_mean")))
    ok_all &= a_ok
    nan_ok = True
    for path in (OUT_SITES, OUT_BOXES):
        txt = open(path, encoding="utf-8").read()
        try:
            json.loads(txt, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        except ValueError:
            nan_ok = False
        if any(tok in txt for tok in ("NaN", "Infinity")):
            nan_ok = False
    log("(b) no NaN / Infinity in the outputs: %s" % ("OK" if nan_ok else "FAILED"))
    ok_all &= nan_ok
    c_bad = []
    for sid, P in places.items():
        have = [k for k in ("modis", "s2", "aster") if P[k] is not None]
        fl = {f["id"] for f in P["flags"]}
        miss_flag = [k for k in ("modis", "s2", "aster") if P[k] is None and ("no" + {"modis": "Modis", "s2": "S2", "aster": "Aster"}[k]) not in fl]
        if miss_flag:
            c_bad.append(sid)
        if not have:
            log("    note: %s has no indicator at all; flags: %s" % (sid, "; ".join(f["why"] for f in P["flags"])))
    log("(c) every site has at least one indicator or a flag saying why not (every missing one has a flag): %s%s" % ("OK" if not c_bad else "FAILED ", c_bad or ""))
    ok_all &= not c_bad
    log("    boxes: %d, with e29: %d, without: %d %s" % (len(boxes), len(boxes) - len(nulls), len(nulls), nulls[:10]))
    log("    sizes: composition.json %.1f KB, screening_composition.json %.1f KB" % (os.path.getsize(OUT_SITES) / 1024, os.path.getsize(OUT_BOXES) / 1024))

    # ---- table
    log("\n%-20s %-12s %6s %5s %6s %6s %6s %6s %6s %5s  %-28s %s" % ("site", "rock", "e29", "e31", "Fe", "B11/12", "bright", "ndvi", "ASTER", "rank", "reading", "flags"))
    for s in sites:
        P = places[s["id"]]
        M, S, A = P["modis"] or {}, P["s2"] or {}, P["aster"] or {}
        log("%-20s %-12s %6s %5s %6s %6s %6s %6s %6s %5s  %-28s %s" % (
            s["id"], s["rock"], M.get("e29", "-"), M.get("e31", "-"), S.get("feRatio", "-"), S.get("swirRatio", "-"),
            S.get("brightness", "-"), S.get("ndvi", "-"), A.get("silicaIndex", "-"), A.get("rank", "-"),
            P["reading"][:28], ",".join(f["id"] for f in P["flags"])))
    log("")
    for s in sites:
        jc = places[s["id"]].get("jordanCheck")
        if jc:
            log("JORDAN %-16s %s" % (s["id"], jc["reason"]))
    log("\nBoxes by mapped rock (IGME5000 primary): boxes, mean, p10, median, p90, silica-rich/mixed/low-silica")
    for rock, r in rock_stats.items():
        log("  %-10s %4d  %.3f  %s  %.3f  %s   %d / %d / %d" % (rock, r["boxes"], r["mean"], r["p10"], r["median"], r["p90"], r["silicaRich"], r["mixed"], r["lowSilica"]))

    write_manifest(items, bstate, s2raw, asraw, check, places, sample_txt, ok_all, rock_stats)
    write_readme(sample_txt)
    log("\nassemble: %s (%.1f s)" % ("all checks OK" if ok_all else "SOME CHECKS FAILED", time.time() - t0))
    return ok_all


def args_stride(items):
    return items.get("stride", 1)


def write_manifest(items, bstate, s2raw, asraw, check, places, sample_txt, ok_all, rock_stats):
    runs = {}
    totals = {}
    for step in ("modis", "s2", "aster", "check2023"):
        d = load_json(os.path.join(RAW, "run_%s.json" % step), {"runs": []})
        runs[step] = d["runs"]
        for r in d["runs"]:
            for host, st in r.get("requests", {}).items():
                t = totals.setdefault(host, {"requests": 0, "bytes": 0, "errors": 0})
                for k in t:
                    t[k] += st.get(k, 0)
    nlines = sum(1 for _ in open(os.path.join(RAW, "modis_sites.jsonl"), encoding="utf-8"))
    man = {
        "generated": now(),
        "outputs": {"data/composition.json": os.path.getsize(OUT_SITES), "data/screening_composition.json": os.path.getsize(OUT_BOXES)},
        "checksOk": ok_all,
        "modis": {"collection": cm.COLL, "sample": sample_txt, "years": items["years"], "stride": items["stride"],
                  "searched": items["searched"],
                  "tiles": {t: {"found": v["found"], "sampled": len(v["ids"]), "first": v["ids"][0] if v["ids"] else None,
                                "last": v["ids"][-1] if v["ids"] else None} for t, v in items["tiles"].items()},
                  "siteRecords": nlines,
                  "boxCompositesAdded": {t: len(v) for t, v in bstate["done"].items()},
                  "itemIds": "data/raw/composition/modis_items.json"},
        "s2": {s: {"used": [{"id": t["id"], "date": t["date"], "cloud": t["cloud"]} for t in r["tried"] if t.get("usable")],
                   "tried": len(r["tried"]), "candidates": r["candidates"], "MB": r["MB"]} for s, r in s2raw["sites"].items()},
        "aster": {s: {"used": [{"id": t["id"], "date": t["date"], "cloud": t["cloud"]} for t in r["tried"] if t.get("used")],
                      "tried": len(r["tried"]), "clearDay": r["clearDay"], "withTIR": r["withTIR"], "candidates": r["candidates"], "MB": r["MB"]}
                  for s, r in asraw["sites"].items()},
        "check2023": {"ok": check.get("ok"), "file": "data/raw/composition/check2023.json"},
        "requestTotals": totals,
        "runs": runs,
        "nulls": {sid: [f["why"] for f in P["flags"] if f["id"] in ("noModis", "noS2", "noAster")] for sid, P in places.items()
                  if any(f["id"] in ("noModis", "noS2", "noAster") for f in P["flags"])},
    }
    dump(os.path.join(RAW, "manifest.json"), man, indent=1)


def write_readme(sample_txt):
    txt = """Surface-composition indicators (display-only evidence, never scored)
=====================================================================

What
  Raw extracts behind data/composition.json (19 Earth sites) and data/screening_composition.json
  (886 Jordan 10 km boxes). Built by scripts/fetch_composition.py (helpers scripts/comp_*.py),
  Python 3.12 standard library only, no login, no account. No imagery is kept here, only the few
  pixel values that were used.

  MODIS MOD21A2 v061 (Terra, 1 km, 8-day), Microsoft Planetary Computer, doi:10.5067/MODIS/MOD21A2.061
      sample: {sample}
      modis_items.json    the composite ids sampled per MODIS tile
      modis_sites.jsonl   per (tile, composite): raw DNs of Emis_29, Emis_31, Emis_32 and LST_Day_1KM
                          in the 3 x 3 pixel window of each site (row-major; null = outside the tile)
                          emissivity = DN * 0.002 + 0.49 (0 = no data); LST K = DN * 0.02 (0 = no data)
      modis_boxes.json    per box and year: [sum of Emis_29 DNs, number of valid pixel samples] over the
                          1 km pixels whose centre is inside the box; "done" lists the composites added
      check2023.json      check (a): the scout's 2023 e29 at the 5 Jordan sites reproduced
  Sentinel-2 L2A (AWS Open Data, Element 84 Earth Search v1, no token)
      s2_sites.json       per site: every scene tried, its SCL 3 x 3 window, raw DNs (20 m bands 3 x 3,
                          10 m bands 2 x 2 per 20 m pixel), per-scene medians, SCL class % in the
                          ~2.8 km MODIS footprint. Reflectance = DN * 0.0001 (offset already applied).
  ASTER L1T TIR (bands 10-14, 90 m, 2000-2006), Planetary Computer, doi:10.5067/ASTER/AST_L1T.003
      aster_sites.json    per site: candidate counts, per-scene NEM emissivity medians, silica index,
                          quartz index; not atmospherically corrected (relative only)
  manifest.json           items and scenes used, request counts per host, run times, nulls and why
  run_*.json              one entry per run of each step (time, requests, bytes)

How to rerun (from the project folder; about 50 minutes in total: MODIS ~38 min, Sentinel-2 ~8, ASTER ~2, check ~2)
  python -I scripts/fetch_composition.py                      everything
  python -I scripts/fetch_composition.py --sites --only modis  one step (modis, s2 or aster)
  python -I scripts/fetch_composition.py --boxes               Jordan boxes (MODIS band 29)
  python -I scripts/fetch_composition.py --check2023           check (a)
  python -I scripts/fetch_composition.py --assemble            rebuild the outputs, no network
  add --resume to continue an interrupted run; --years 2003-2020 --stride 1 for the full record
  Planetary Computer SAS tokens are requested for the storage account/container in the file URL
  (e.g. /api/sas/v1/token/modiseuwest/modis-061-cogs). Requests are throttled (default 8 per second).

Last built: {time}
""".format(sample=sample_txt, time=now())
    with open(os.path.join(RAW, "README.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sites", action="store_true", help="site indicators (MODIS, Sentinel-2, ASTER)")
    ap.add_argument("--boxes", action="store_true", help="Jordan boxes (MODIS band 29)")
    ap.add_argument("--only", default="modis,s2,aster", help="site sources to run with --sites (comma list)")
    ap.add_argument("--check2023", action="store_true", help="check (a) only")
    ap.add_argument("--assemble", action="store_true", help="only build the outputs from the raw extracts")
    ap.add_argument("--resume", action="store_true", help="continue an interrupted run")
    ap.add_argument("--no-assemble", action="store_true", help="fetch only; do not build the outputs")
    ap.add_argument("--years", default="2018-2020", help="MODIS years, e.g. 2018-2020")
    ap.add_argument("--stride", type=int, default=1, help="use every n-th MODIS composite (1 = all)")
    ap.add_argument("--s2-dates", default="2023-01-01:2024-12-31", help="Sentinel-2 date range start:end")
    ap.add_argument("--workers", type=int, default=2, help="parallel MODIS reads")
    ap.add_argument("--rate", type=float, default=8.0, help="max HTTP requests per second (all threads)")
    args = ap.parse_args()
    try:                                  # Windows consoles may not print arrows or degree signs
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    y = args.years.split("-")
    args.y0, args.y1 = int(y[0]), int(y[-1])
    args.s2_d0, args.s2_d1 = args.s2_dates.split(":")
    cc.MAX_RATE = args.rate
    os.makedirs(RAW, exist_ok=True)
    sites = load_sites()
    everything = not (args.sites or args.boxes or args.check2023 or args.assemble)
    only = set(x.strip() for x in args.only.split(","))
    t0 = time.time()
    if everything or args.check2023:
        step_check(args, sites)
    do_modis_sites = (everything or args.sites) and "modis" in only
    do_boxes = everything or args.boxes
    if do_modis_sites or do_boxes:
        step_modis(args, sites, do_modis_sites, do_boxes)
    if (everything or args.sites) and "s2" in only:
        step_s2(args, sites)
    if (everything or args.sites) and "aster" in only:
        step_aster(args, sites)
    ok = True
    if not args.no_assemble:
        ok = assemble(args, sites)
    log("total %.0f s; requests %s" % (time.time() - t0, json.dumps(cc.STATS)))
    sys.exit(0 if ok or not everything else 1)


if __name__ == "__main__":
    main()
