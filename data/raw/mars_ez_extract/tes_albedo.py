# Usage: python -I tes_albedo.py <path/to/global_albedo_8ppd.img> '{"id":[lat, lonE(-180..180), radius_km]}'
# Source: https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-special-v1/global_albedo_8ppd.img (+ .lbl), MGS TES Lambert/bolometric albedo, Christensen et al. 2001
import sys, struct, math, json
img = sys.argv[1]; sites = json.loads(sys.argv[2])
L, S = 1440, 2880
data = open(img, "rb").read()
assert len(data) == L*S*4
def val(line, samp):  # 0-based
    return struct.unpack_from("<f", data, (line*S + samp)*4)[0]
R = 3396.0
def dist(a1,o1,a2,o2):
    a1,o1,a2,o2 = map(math.radians,(a1,o1,a2,o2))
    return R*math.acos(min(1, math.sin(a1)*math.sin(a2)+math.cos(a1)*math.cos(a2)*math.cos(o1-o2)))
out = {}
for sid,(la,lo,rad) in sites.items():
    lo = ((lo+180) % 360) - 180
    # PDS: line = LINE_PROJECTION_OFFSET - lat*res ; sample = SAMPLE_PROJECTION_OFFSET + lon*res (1-based)
    line = int(math.floor(720.5 - la*8 + 0.5)) - 1
    samp = int(math.floor(1440.5 + lo*8 + 0.5)) - 1
    v = val(line, samp)
    clat = (720.5 - (line+1))/8; clon = ((samp+1) - 1440.5)/8
    vals = []
    dl = int(rad/59.27*8)+2
    for i in range(line-dl, line+dl+1):
        plat = (720.5-(i+1))/8
        dsm = int(dl/max(0.05, math.cos(math.radians(plat))))+2
        for j in range(samp-dsm, samp+dsm+1):
            jj = j % S; plon = ((jj+1)-1440.5)/8
            if dist(la,lo,plat,plon) <= rad:
                x = val(i, jj)
                if x > 0 and x < 1: vals.append(x)
    vals.sort()
    out[sid] = {"pixel": {"line0": line, "sample0": samp, "lat": clat, "lon": clon, "albedo": round(v,4)},
                f"within_{rad}km": {"n": len(vals), "mean": round(sum(vals)/len(vals),4), "median": round(vals[len(vals)//2],4), "min": round(vals[0],4), "max": round(vals[-1],4)} if vals else None}
print(json.dumps(out, indent=1))
