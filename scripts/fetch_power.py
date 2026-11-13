"""Download NASA POWER climatology for every Earth site (and any extra points).

Usage (from the project folder):
    python -I scripts/fetch_power.py            # only sites that have no file yet
    python -I scripts/fetch_power.py --refresh  # download every site in sites_meta.json again
    python -I scripts/fetch_power.py --point amman 31.95 35.93  # one extra point (the field
                                                             # kit's Amman file; --refresh skips it)

Each raw API response is saved unchanged in data/raw/power/<id>.json so every
number in the app can be traced back to NASA's own answer.
"""
import argparse
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "power"
META = ROOT / "data" / "sites_meta.json"

PARAMETERS = [
    "T2M", "T2M_MAX", "T2M_MIN", "T2M_RANGE", "RH2M", "PRECTOTCORR",
    "ALLSKY_SFC_UV_INDEX", "ALLSKY_SFC_SW_DWN", "WS2M", "PS",
    "TS", "TS_MAX", "TS_MIN", "ALLSKY_SRF_ALB",
]
URL = ("https://power.larc.nasa.gov/api/temporal/climatology/point"
       "?parameters={params}&community=RE&longitude={lon}&latitude={lat}&format=JSON")


def fetch(point_id, lat, lon, refresh):
    out = RAW / f"{point_id}.json"
    if out.exists() and not refresh:
        print(f"skip {point_id} (already downloaded)")
        return
    url = URL.format(params=",".join(PARAMETERS), lat=lat, lon=lon)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                body = resp.read()
            json.loads(body)  # fail early if NASA sent something that is not JSON
            out.write_bytes(body)
            print(f"saved {out.relative_to(ROOT)}")
            return
        except Exception as err:  # network hiccups: wait and try again
            print(f"{point_id}: attempt {attempt + 1} failed: {err}")
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"could not download {point_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="download again even if a file exists")
    parser.add_argument("--point", nargs=3, metavar=("ID", "LAT", "LON"), help="download one extra point")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    if args.point:
        point_id, lat, lon = args.point
        fetch(point_id, float(lat), float(lon), True)
        return
    for site in json.loads(META.read_text(encoding="utf-8"))["sites"]:
        fetch(site["id"], site["lat"], site["lon"], args.refresh)
        time.sleep(1)  # be gentle with NASA's server


if __name__ == "__main__":
    main()
