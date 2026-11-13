Surface-composition indicators (display-only evidence, never scored)
=====================================================================

What
  Raw extracts behind data/composition.json (19 Earth sites) and data/screening_composition.json
  (886 Jordan 10 km boxes). Built by scripts/fetch_composition.py (helpers scripts/comp_*.py),
  Python 3.12 standard library only, no login, no account. No imagery is kept here, only the few
  pixel values that were used.

  MODIS MOD21A2 v061 (Terra, 1 km, 8-day), Microsoft Planetary Computer, doi:10.5067/MODIS/MOD21A2.061
      sample: all 138 Terra 8-day composites of 2018-2020 (46 per year)
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

Last built: 2026-10-10T15:48:54Z
