"""Rebuild the rover comparison from cached Copernicus DEM and lunar LOLA elevations."""

import gzip
import json
import math
from pathlib import Path
from statistics import median, quantiles

from compute_terrain import GRID_N, SPACING_M, elevations_from_cache


ROOT = Path(__file__).resolve().parents[1]
EARTH = "data/raw/screening/dem/samples_jordan.json.gz"
MOON = "data/raw/terrain/shackleton-ridge.json"


def terrain_metrics(elevations, step):
    baseline = 2 * step * SPACING_M
    slopes = []
    for row in range(step, GRID_N - step):
        for col in range(step, GRID_N - step):
            n, s = (elevations[(row + offset) * GRID_N + col] for offset in (step, -step))
            e, w = (elevations[row * GRID_N + col + offset] for offset in (step, -step))
            if None not in (n, s, e, w):
                slopes.append(math.degrees(math.atan(math.hypot(n - s, e - w) / baseline)))
    return {
        "baselineKm": baseline / 1000,
        "samples": len(slopes),
        "medianDeg": round(median(slopes), 2),
        "p90Deg": round(quantiles(slopes, n=10, method="inclusive")[8], 2),
        "under10Pct": round(100 * sum(slope < 10 for slope in slopes) / len(slopes), 1),
    }


def main():
    with gzip.open(ROOT / EARTH, "rt", encoding="utf-8") as f:
        earth = json.load(f)
    with (ROOT / MOON).open(encoding="utf-8") as f:
        moon, _ = elevations_from_cache(json.load(f))

    places = [
        ("jo-r06c01", earth["boxes"]["jo-r06c01"], EARTH),
        ("shackleton-ridge", moon, MOON),
        ("wadi-rum", earth["controls"]["wadi-rum"], EARTH),
        ("harrat", earth["controls"]["harrat"], EARTH),
    ]
    output = {
        "targetId": "shackleton-ridge",
        "boxId": "jo-r06c01",
        "places": {
            place: {"source": source, "metrics": [terrain_metrics(elevations, step) for step in (1, 2)]}
            for place, elevations, source in places
        },
    }
    (ROOT / "data/rover_case.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
