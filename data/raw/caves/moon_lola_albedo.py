# Usage: python -I moon_lola_albedo.py <download_dir>
# LOLA normal albedo at 1064 nm (LDAM_10_FLOAT / LDAM_4_FLOAT, PDS LRO-L-LOLA-4-GDR-V1.0, Lemelin et al. 2016 calibration)
# at the Mare Tranquillitatis pit (8.3355 N, 33.222 E). HTTP Range requests on the PDS file; 5x5 window saved raw.
# PDS3 SIMPLE CYLINDRICAL: line0 = LINE_PROJECTION_OFFSET - lat*res ; sample0 = SAMPLE_PROJECTION_OFFSET + (lon - 180)*res
import sys, os, json, struct, hashlib, urllib.request
DL = sys.argv[1]; os.makedirs(DL, exist_ok=True)
U = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/float_img/"
PIT = (8.3355, 33.222)
PROD = {"ldam_10_float": (10, 1800, 3600, 899.5, 1799.5), "ldam_4_float": (4, 720, 1440, 359.5, 719.5)}
out = {}
for name, (res, NL, NS, LPO, SPO) in PROD.items():
    lbl = urllib.request.urlopen(U + name + ".lbl", timeout=60).read().decode("latin-1")
    for key in ("LINES", "LINE_SAMPLES", "LINE_PROJECTION_OFFSET", "SAMPLE_PROJECTION_OFFSET", "MAP_RESOLUTION"):
        pass
    assert f"LINES                 = {NL}" in lbl and f"LINE_SAMPLES          = {NS}" in lbl, "label mismatch"
    l0 = int(round(LPO - PIT[0] * res)); s0 = int(round(SPO + (PIT[1] - 180) * res))
    W = 2; grid = []; raw_all = b""
    for li in range(l0 - W, l0 + W + 1):
        start = (li * NS + s0 - W) * 4; n = (2 * W + 1) * 4
        req = urllib.request.Request(U + name + ".img", headers={"Range": f"bytes={start}-{start+n-1}"})
        raw = urllib.request.urlopen(req, timeout=120).read(); assert len(raw) == n
        raw_all += raw; grid.append([round(v, 4) for v in struct.unpack("<%df" % (2 * W + 1), raw)])
    open(os.path.join(DL, f"{name}_pit_5x5.f32"), "wb").write(raw_all)
    open(os.path.join(DL, f"{name}.lbl"), "w", encoding="latin-1").write(lbl)
    flat = [v for r in grid for v in r]
    out[name] = {"pixel_line0": l0, "pixel_sample0": s0,
                 "pixel_center_lat": (LPO - l0) / res, "pixel_center_lonE": 180 + (s0 - SPO) / res,
                 "pixel_size_km": round(2 * 3.141592653589793 * 1737.4 / 360 / res, 2),
                 "pit_pixel": grid[W][W], "window5x5_mean": round(sum(flat) / len(flat), 4),
                 "window5x5_min": min(flat), "window5x5_max": max(flat), "grid": grid,
                 "raw_sha256": hashlib.sha256(raw_all).hexdigest(), "url": U + name + ".img"}
print(json.dumps(out, indent=1))
json.dump(out, open(os.path.join(DL, "lola_albedo_out.json"), "w"), indent=1)
