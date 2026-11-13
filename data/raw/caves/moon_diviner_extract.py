# Usage: python -I moon_diviner_extract.py <download_dir> <out_json>
# Extracts MEASURED LRO Diviner temperatures around the Mare Tranquillitatis pit (8.3355 N, 33.222 E)
# from two PDS products (Diviner derived bundle 1, PDS Geosciences Node), using HTTP Range requests:
#  1) GCP  global_cumul_avg_cyl_00n10n_002.tab  (Williams et al. 2017, Icarus 283, 300-325):
#     bolometric brightness temperature binned 0.5 deg x 0.5 deg x 0.25 h local time, all nadir data 2009-07-05..2015-04-01.
#     Fixed 113-byte ASCII records; row = ilon*1920 + ilat*96 + ilt (checked by probing rows 0, 96, 1920, last).
#  2) GHRM dghrm_tbol_m_70s70n_img.img etc. (128 px/deg = 236.9 m, float32 LE, 17920 x 46080, 70N..70S, 0..360E):
#     "bolometric temperature at midnight", "... at slope-adjusted midnight", "... anomaly at slope-adjusted midnight".
# Python 3.12 stdlib only.
import sys, os, json, math, hashlib, struct, time, urllib.request

DL, OUT = sys.argv[1], sys.argv[2]
os.makedirs(DL, exist_ok=True)
PIT = (8.3355, 33.222)  # LROC Lunar Pit Atlas, pit 3
B = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1"
GCP = B + "/data_derived_gcp/global_cumul_avg_cyl_00n10n_002.tab"
GHRM = {k: B + f"/data_derived_ghrm/img/dghrm_{k}_70s70n_img.img" for k in ("tbol_m", "tbol_sam", "tbol_anom", "ra_sam")}

def rng(url, start, length, tries=5):
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{start+length-1}", "User-Agent": "analog-atlas-research/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                assert r.status == 206, r.status
                data = r.read()
            assert len(data) == length, (len(data), length)
            return data
        except Exception as e:
            print("retry", url, start, e, file=sys.stderr); time.sleep(3 * (t + 1))
    raise SystemExit("download failed")

def sha(b): return hashlib.sha256(b).hexdigest()
R = 1737.4
def dist(a1, o1, a2, o2):
    a1, o1, a2, o2 = map(math.radians, (a1, o1, a2, o2))
    return R * math.acos(min(1, math.sin(a1)*math.sin(a2) + math.cos(a1)*math.cos(a2)*math.cos(o1-o2)))

out = {"pit": {"lat": PIT[0], "lonE": PIT[1]}, "gcp": {}, "ghrm": {}}

# ---------------- GCP diurnal curves (3x3 bins of 0.5 deg) ----------------
REC = 113
hdr = rng(GCP, 0, REC).decode()
out["gcp"]["url"] = GCP
out["gcp"]["header"] = hdr.strip()
ilat0 = int((PIT[0] - 0.0) // 0.5); ilon0 = int((PIT[1] + 180.0) // 0.5)
raw_all = b""
bins = {}
for di in (-1, 0, 1):
    for dj in (-1, 0, 1):
        ilat, ilon = ilat0 + di, ilon0 + dj
        row0 = ilon * 1920 + ilat * 96
        raw = rng(GCP, REC + row0 * REC, 96 * REC)
        raw_all += raw
        rows = []
        for k in range(96):
            f = raw[k*REC:(k+1)*REC].decode().split(",")
            clon, clat, lt, tbol = float(f[0]), float(f[1]), float(f[2]), float(f[10])
            rows.append((clon, clat, lt, tbol))
        clon, clat = rows[0][0], rows[0][1]
        assert all(r[0] == clon and r[1] == clat for r in rows), "row order assumption broken"
        valid = [(r[2], r[3]) for r in rows if r[3] > 0]
        tmax = max(valid, key=lambda x: x[1]); tmin = min(valid, key=lambda x: x[1])
        # diurnal mean: linear interpolation over empty 15-min bins (periodic), then mean of 96 bins
        vals = [r[3] if r[3] > 0 else None for r in rows]
        idx = [i for i, v in enumerate(vals) if v is not None]
        filled = []
        for i in range(96):
            if vals[i] is not None: filled.append(vals[i]); continue
            prev = max([j for j in idx if j < i], default=idx[-1] - 96)
            nxt = min([j for j in idx if j > i], default=idx[0] + 96)
            vp, vn = vals[prev % 96], vals[nxt % 96]
            filled.append(vp + (vn - vp) * (i - prev) / (nxt - prev))
        # night-only stats (local time 18h..6h) and pre-dawn (5-6h)
        night = [v for (lt, v) in valid if lt >= 18 or lt < 6]
        predawn = [v for (lt, v) in valid if 5.0 <= lt < 6.0]
        key = f"{clat:+.2f}_{clon:+.2f}"
        bins[key] = {
            "center_lat": clat, "center_lonE": clon, "row_first": row0,
            "dist_center_to_pit_km": round(dist(PIT[0], PIT[1], clat, clon), 2),
            "contains_pit": (clat - 0.25 <= PIT[0] < clat + 0.25) and (clon - 0.25 <= PIT[1] < clon + 0.25),
            "n_localtime_bins_with_data": len(valid),
            "max_K": tmax[1], "max_localtime_h": tmax[0],
            "min_K": tmin[1], "min_localtime_h": tmin[0],
            "mean_interp_K": round(sum(filled) / 96, 2),
            "mean_of_filled_bins_only_K": round(sum(v for _, v in valid) / len(valid), 2),
            "night_mean_K": round(sum(night) / len(night), 2) if night else None,
            "predawn_5to6h_mean_K": round(sum(predawn) / len(predawn), 2) if predawn else None,
            "empty_bins_localtimes_h": [r[2] for r in rows if r[3] <= 0],
            "curve": [[r[2], r[3]] for r in rows],
        }
open(os.path.join(DL, "gcp_00n10n_pit_3x3_rows.txt"), "wb").write(hdr.encode() + raw_all)
out["gcp"]["raw_file"] = "gcp_00n10n_pit_3x3_rows.txt"
out["gcp"]["raw_sha256"] = sha(hdr.encode() + raw_all)
out["gcp"]["bins"] = bins

# ---------------- GHRM midnight mosaics (128 ppd) ----------------
NS, NL, PPD = 46080, 17920, 128
L0 = int((70.0 - PIT[0]) * PPD); S0 = int(PIT[1] * PPD)
W = 24  # +-24 px (~5.7 km)
out["ghrm"]["pit_pixel"] = {"line": L0, "sample": S0,
    "lat_range": [70 - (L0 + 1) / PPD, 70 - L0 / PPD], "lon_range": [S0 / PPD, (S0 + 1) / PPD],
    "pixel_size_m": 236.901175188667821}
for k, url in GHRM.items():
    raw_all = b""; grid = []
    for li in range(L0 - W, L0 + W + 1):
        raw = rng(url, (li * NS + (S0 - W)) * 4, (2 * W + 1) * 4)
        raw_all += raw
        grid.append(list(struct.unpack("<%df" % (2 * W + 1), raw)))
    fn = f"ghrm_{k}_pit_window_{2*W+1}x{2*W+1}.f32"
    open(os.path.join(DL, fn), "wb").write(raw_all)
    c = grid[W][W]
    ring = lambda r: [grid[W+a][W+b] for a in range(-r, r+1) for b in range(-r, r+1) if max(abs(a), abs(b)) == r]
    def stats(vs):
        vs = sorted(v for v in vs if not math.isnan(v))
        if not vs: return None
        return {"n": len(vs), "mean": round(sum(vs)/len(vs), 2), "median": round(vs[len(vs)//2], 2), "min": round(vs[0], 2), "max": round(vs[-1], 2)}
    # background: pixels 4..24 px away (~1-5.7 km), i.e. excluding the pit and its funnel neighbourhood
    bg = [grid[W+a][W+b] for a in range(-W, W+1) for b in range(-W, W+1) if max(abs(a), abs(b)) >= 4]
    near = [[round(grid[W+a][W+b], 2) for b in range(-3, 4)] for a in range(-3, 4)]
    allv = [(grid[W+a][W+b], a, b) for a in range(-W, W+1) for b in range(-W, W+1) if not math.isnan(grid[W+a][W+b])]
    mx = max(allv)
    out["ghrm"][k] = {"url": url, "raw_file": fn, "raw_sha256": sha(raw_all), "window": f"lines {L0-W}..{L0+W}, samples {S0-W}..{S0+W}",
        "pit_pixel": None if math.isnan(c) else round(c, 2),
        "ring1": stats(ring(1)), "ring2": stats(ring(2)), "background_4to24px": stats(bg),
        "window_max": {"value": round(mx[0], 2), "dline": mx[1], "dsample": mx[2]},
        "center_7x7": near}
json.dump(out, open(OUT, "w"), indent=1)
print(json.dumps({k: (v if k != "gcp" else {kk: {x: y for x, y in vv.items() if x != "curve"} for kk, vv in v["bins"].items()}) for k, v in out.items()}, indent=1))
