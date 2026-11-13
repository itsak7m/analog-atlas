# Usage: python -I mcs_extract.py <dir with Figure_08/11/13.map> '{"id":[lat, lonE(0..360), radius_km]}'
# Source: Harvard Dataverse doi:10.7910/DVN/YCNFQL (Piqueux et al., Icarus 419, 115851), MCS channel B1 surface temperature maps, 1/3-degree grid
import sys, math, json
D = sys.argv[1]
def load(name):
    rows = []
    with open(f"{D}/{name}") as fh:
        for line in fh:
            if line.strip():
                rows.append([float(x) for x in line.split()])
    return rows
# analytic 1/3-degree grid (the 539-row backplanes are one row short of the 540-row maps)
lat = [[90 - (i+0.5)/3]*1080 for i in range(540)]
lon = [[(j+0.5)/3 for j in range(1080)] for i in range(540)]
maps = {k: load(f) for k, f in [("min","Figure_08.map"),("max","Figure_11.map"),("avg","Figure_13.map")]}
print("shape", len(lat), len(lat[0]), len(maps["min"]), len(maps["min"][0]))
print("lat rows 0..2", lat[0][0], lat[1][0], lat[2][0], "last", lat[-1][0], "lon first/last", lon[0][0], lon[0][-1])
R = 3389.5
def dist(a1, o1, a2, o2):
    a1, o1, a2, o2 = map(math.radians, (a1, o1, a2, o2))
    return R * math.acos(min(1, math.sin(a1)*math.sin(a2) + math.cos(a1)*math.cos(a2)*math.cos(o1-o2)))
sites = json.loads(sys.argv[2])
out = {}
for sid, (la, loE, rad) in sites.items():
    loE = loE % 360
    best = None; vals = {k: [] for k in maps}
    for i in range(len(lat)):
        if abs(lat[i][0] - la) > rad/59.0 + 1: continue
        for j in range(len(lat[i])):
            d = dist(la, loE, lat[i][j], lon[i][j])
            if best is None or d < best[0]: best = (d, i, j)
            if d <= rad:
                for k in maps:
                    v = maps[k][i][j]
                    if v != 999.99: vals[k].append(v)
    d, i, j = best
    res = {"nearest_pixel": {"row": i, "col": j, "lat": round(lat[i][j],3), "lonE": round(lon[i][j],3), "dist_km": round(d,1)}}
    for k in maps:
        v = maps[k][i][j]
        res[k+"_pixel_K"] = None if v == 999.99 else v
        L = vals[k]
        res[k+f"_within_{rad}km"] = None if not L else {"n": len(L), "mean_K": round(sum(L)/len(L),2), "min_K": min(L), "max_K": max(L)}
    out[sid] = res
print(json.dumps(out, indent=1))
