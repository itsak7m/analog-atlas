"""Build data/sites.json from the curated site list and the raw NASA POWER files.

Usage (from the project folder):
    python -I scripts/build_data.py

Numbers are copied straight from NASA's responses (no rounding, no editing),
so the app always shows exactly what the POWER API returned.
"""
import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "power"
META = ROOT / "data" / "sites_meta.json"
OUT = ROOT / "data" / "sites.json"

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
POWER_PAGE = "https://power.larc.nasa.gov/"


def power_block(point_id, lat, lon):
    raw_path = RAW / f"{point_id}.json"
    doc = json.loads(raw_path.read_text(encoding="utf-8"))
    params = doc["properties"]["parameter"]
    fill = doc.get("header", {}).get("fill_value", -999.0)
    annual, monthly = {}, {}
    for name, series in params.items():
        value = series.get("ANN")
        annual[name] = None if value is None or value == fill else value
        monthly[name] = [None if series.get(m) in (None, fill) else series.get(m) for m in MONTHS]
    lon_r, lat_r, elev = doc["geometry"]["coordinates"]
    header = doc.get("header", {})
    units = {name: info.get("units") for name, info in doc.get("parameters", {}).items()}
    return {
        "source": "NASA POWER climatology API, community RE",
        "period": header.get("range", "January 2001 - December 2020"),
        "apiVersion": header.get("api", {}).get("version") if isinstance(header.get("api"), dict) else None,
        "request": {"lat": lat_r, "lon": lon_r},
        "gridElevation_m": elev,
        "rawFile": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
        "fetched": datetime.date.fromtimestamp(raw_path.stat().st_mtime).isoformat(),
        "page": POWER_PAGE,
        "units": units,
        "annual": annual,
        "monthly": monthly,
    }


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    sites = []
    for site in meta["sites"]:
        entry = dict(site)
        entry["power"] = power_block(site["id"], site["lat"], site["lon"])
        sites.append(entry)
    out = {
        "generated": datetime.date.today().isoformat(),
        "about": "Built by scripts/build_data.py from data/sites_meta.json and data/raw/power/*.json. Do not edit by hand.",
        "statusLegend": meta["statusLegend"],
        "sites": sites,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} with {len(sites)} sites")


if __name__ == "__main__":
    main()
