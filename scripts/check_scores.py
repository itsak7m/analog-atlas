"""Independent check of the similarity score (written separately from js/scoring.js).

Usage (from the project folder):
    python -I scripts/check_scores.py

It recomputes the climate match from data/sites.json and data/targets.json and
compares it with the reference rankings in section 6 of the brief.

It also checks the base-site sunlight data (added 2026-10-23):
  * "Sun height" (highest Sun above a flat horizon in a year) = 90 - |latitude| + tilt,
    capped at 90, with the Moon tilt 1.54 deg (NASA Photojournal PIA13720) for the three
    moon-base targets; no other target has this factor;
  * the share of the year with the Sun up at each Earth site, from the standard formula
    (solar declination from a circular orbit with the 23.44 deg tilt, sunrise/sunset when the
    top of the Sun is at -0.833 deg, the usual refraction + half-disc value), which the
    'Sunlight (LOLA)' facts quote as 50.5-51.7 %;
  * the regolith rule: no Earth site has a regolith tag (SP Crater's nearby-simulant tag was removed);
  * the place rule (added 2026-10-26): resources.json has rules.place, no tag is both given and listed
    under notTagged, and the McMurdo Dry Valleys ice tag (sourced in Beacon Valley, about 50 km away)
    stays removed, with its reason under notTagged.
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACTORS = [  # (target key, POWER parameter, R)
    ("meanTemp", "T2M", 100),
    ("swing", "T2M_RANGE", 100),
    ("coldGround", "TS_MIN", 100),
    ("rain", "PRECTOTCORR", 3),
    ("albedo", "ALLSKY_SRF_ALB", 0.5),
]
ORIGINAL_SITES = ["wadi-rum", "harrat", "atacama", "haughton", "death-valley",
                  "dry-valleys", "holuhraun", "rio-tinto", "mdrs"]  # brief section 4, Mauna Kea removed
EXPECTED = {  # percent for each site, from the brief
    "jezero": {"dry-valleys": 60, "harrat": 57, "atacama": 57, "death-valley": 57, "mdrs": 57,
               "haughton": 56, "wadi-rum": 55, "rio-tinto": 52, "holuhraun": 33},
    "southpole": {"atacama": 51, "harrat": 50, "death-valley": 50, "wadi-rum": 47},
    "apollo11": {"atacama": 44, "harrat": 43, "death-valley": 43, "wadi-rum": 40},
}
EXPECTED_ORDER = {  # first places, in order
    "jezero": ["dry-valleys"],
    "southpole": ["atacama", "harrat", "death-valley", "wadi-rum"],
    "apollo11": ["atacama", "harrat", "death-valley", "wadi-rum"],
}


def score(site, target):
    num = den = 0.0
    for key, param, r in FACTORS:
        t = target["values"][key]["value"]
        e = site["power"]["annual"][param]
        if t is None or e is None:
            continue
        num += max(0.0, 1 - abs(e - t) / r)
        den += 1
    return num / den


MOON_TILT = 1.54   # NASA Photojournal PIA13720
EARTH_TILT = 23.44  # NASA NSSDC Earth fact sheet
SUN_UP_RANGE = (0.505, 0.517)  # the 'Sunlight (LOLA)' facts say "50.5-51.7 % of the year"


def sun_up_share(lat, tilt=EARTH_TILT, h0=-0.833, steps=3650):
    """Share of the year with any part of the Sun above a flat horizon (standard sunrise equation)."""
    total = 0.0
    for i in range(steps):
        dec = math.asin(math.sin(math.radians(tilt)) * math.sin(2 * math.pi * i / steps))
        p = math.radians(lat)
        c = (math.sin(math.radians(h0)) - math.sin(p) * math.sin(dec)) / (math.cos(p) * math.cos(dec))
        total += (math.pi if c <= -1 else 0.0 if c >= 1 else math.acos(c)) / math.pi
    return total / steps


def check_sunlight(sites, targets):
    failures = 0
    print("\nSun height (highest Sun above a flat horizon in a year)")
    for t in targets.values():
        v = t["values"].get("sunHeight")
        if t["group"] != "moon-base":
            if v is not None:
                failures += 1
                print(f"  FAIL {t['id']} must not have sunHeight")
            continue
        want = 90 - abs(t["lat"]) + MOON_TILT
        ok = v is not None and abs(v["value"] - want) <= 0.006
        failures += not ok
        print(f"  {t['id']:18s} {v and v['value']} deg (formula {want:.3f})  {'ok' if ok else 'FAIL'}")
    shares = {sid: sun_up_share(s["lat"]) for sid, s in sites.items()}
    lo, hi = min(shares.values()), max(shares.values())
    ok = round(lo, 3) >= SUN_UP_RANGE[0] and round(hi, 3) <= SUN_UP_RANGE[1]
    failures += not ok
    print(f"  Earth sites, share of the year with the Sun up: {lo * 100:.1f}-{hi * 100:.1f} %  {'ok' if ok else 'FAIL'}")
    return failures


def check_regolith(sites):
    places = json.loads((ROOT / "data/resources.json").read_text(encoding="utf-8"))["places"]
    tagged = [sid for sid in sites if "regolith" in places.get(sid, {}).get("tags", {})]
    print(f"\nRegolith rule: Earth sites with a regolith tag: {tagged or 'none'}  {'ok' if not tagged else 'FAIL'}")
    return 1 if tagged else 0


def check_place_rule():
    doc = json.loads((ROOT / "data/resources.json").read_text(encoding="utf-8"))
    failures = 0
    print("\nPlace rule (all four resource tags)")
    if not doc.get("rules", {}).get("place"):
        failures += 1
        print("  FAIL rules.place is missing")
    both = [f"{pid}:{tag}" for pid, p in doc["places"].items() for tag in p.get("tags", {}) if tag in p.get("notTagged", {})]
    failures += bool(both)
    print(f"  tags both given and listed under notTagged: {both or 'none'}  {'ok' if not both else 'FAIL'}")
    dv = doc["places"].get("dry-valleys", {})
    ok = "ice" not in dv.get("tags", {}) and "ice" in dv.get("notTagged", {})
    failures += not ok
    print(f"  McMurdo Dry Valleys: no ice tag, reason under notTagged  {'ok' if ok else 'FAIL'}")
    return failures


def main():
    sites = {s["id"]: s for s in json.loads((ROOT / "data/sites.json").read_text(encoding="utf-8"))["sites"]}
    targets = {t["id"]: t for t in json.loads((ROOT / "data/targets.json").read_text(encoding="utf-8"))["targets"]}
    failures = 0
    for tid, expected in EXPECTED.items():
        ranked = sorted(((score(sites[sid], targets[tid]), sid) for sid in ORIGINAL_SITES), reverse=True)
        print(f"\n{targets[tid]['name']} (original sites from the brief, Mauna Kea removed)")
        for s, sid in ranked:
            got = round(s * 100)
            want = expected.get(sid)
            mark = "" if want is None else ("ok" if got == want else f"FAIL (expected {want}%)")
            failures += mark.startswith("FAIL")
            print(f"  {sid:14s} {s * 100:7.3f}%  -> {got:3d}%  {mark}")
        order = [sid for _, sid in ranked][: len(EXPECTED_ORDER[tid])]
        if order != EXPECTED_ORDER[tid]:
            failures += 1
            print(f"  ORDER FAIL: {order} != {EXPECTED_ORDER[tid]}")
    failures += check_sunlight(sites, targets)
    failures += check_regolith(sites)
    failures += check_place_rule()
    print("\nALL OK" if failures == 0 else f"\n{failures} problem(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
