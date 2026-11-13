MODIS land surface temperature (LST): raw files and how to rebuild them
=========================================================================

What this is
------------
data/lst.json (19 Earth sites) and data/screening_lst.json (886 Discover Jordan boxes) hold land
surface (skin) temperature statistics from NASA MODIS:
  MOD21A2 (Terra) and MYD21A2 (Aqua), Collection 6.1, 8-day composites, 1 km sinusoidal grid,
  every composite that starts in 2003-2020 (the period both satellites share before orbit drift).
  DOIs 10.5067/MODIS/MOD21A2.061 and 10.5067/MODIS/MYD21A2.061 (LP DAAC; NASA-led mission data, CC0).
The files are read from Microsoft Planetary Computer's mirror of the LP DAAC files (Cloud Optimized
GeoTIFFs), anonymously: no account, no key, no password.

The app does not load anything in this folder.

What is in this folder
----------------------
  README.txt            this file
  manifest.json         every STAC item id used (per MODIS tile, Terra and Aqua), counts, the site
                        pixels (tile/row/col), land/water mask codes, request totals and run times of
                        each run, and the results of the checks (a)-(d)
  sites/<id>.jsonl.gz   one line per composite for each site: the point-API answer at the site's
                        pixel, unchanged except rounded to integers:
                          {"id": STAC item id, "p": "terra"|"aqua", "s": start date, "e": end date,
                           "v": [LST_Day_1KM, LST_Night_1KM, QC_Day, QC_Night, View_Time_Day, View_Time_Night]}
                        raw MODIS integers: LST x 0.02 = kelvin (0 = fill), View_Time x 0.1 = hours of
                        local solar time (255 = fill), QC = bit field (see qcRule in data/lst.json)

The box pipeline stores nothing here except its summary in manifest.json: it reads only the
internal 512 x 512 tiles of the COGs that hold Jordan (tiles h20v05, h21v05, h21v06), keeps the
values of the 103,130 pixels of the grid in a cache OUTSIDE the project (default:
<system temp>/analog-atlas-lst-cache, about 0.45 GB; delete it when you are done) and writes only
the per-box results.

How to rebuild
--------------
From the project folder, Python 3.12, standard library only:
    python -I scripts/fetch_lst.py --sites --boxes --validate
    (after an interruption add --resume: finished composites are not fetched again)
  --sites     19 sites x ~1,656 composites = ~31,500 point-API requests (16 threads, keep-alive
              connections; ~17 requests/s): about 30 minutes; writes sites/, manifest.json and
              data/lst.json
  --boxes     3 tiles x ~1,656 composites, 4 assets each (LST and QC, day and night): header +
              1-2 internal tiles per asset: 2.96 GB and 46,393 requests in the last run, 14 minutes
              with 8 workers, plus 5 minutes of aggregation; writes data/screening_lst.json
  --validate  checks (a)-(d) below; prints them and stores them in manifest.json
Numbers in the last run: see manifest.json "runs".

Checks (--validate)
-------------------
  (a) Harrat and Wadi Rum reproduce the LST scout's MOD21 numbers (same API, same QC rule,
      2003-2020) within 0.3 K
  (b) for 3 random composites, the stored point-API answer, a fresh point-API answer and a direct
      COG range read of the same pixel are identical (all 6 assets)
  (c) each Jordan site's box: is the box-centre pixel the site's pixel? (report the difference if
      not); and the site's own pixel computed through the box (COG) pipeline equals the
      point-API result exactly
  (d) no NaN / Infinity / -999 anywhere, values in plausible ranges

Notes
-----
* New TCP connections to the Planetary Computer hosts often timed out from the build machine;
  the scripts keep one connection per thread alive and retry.
* The COG SAS token comes from /api/sas/v1/token/modiseuwest/modis-061-cogs (NOT the collection
  token, which is for the HDF container); it is refreshed before it expires.
* Terra/Aqua is taken from the product name in the item id (MOD21A2 = Terra, MYD21A2 = Aqua):
  one STAC item, MOD21A2.A2003041.h29v11 (Pilbara), has an empty 'platform' property.
* The water flag uses the MODIS land/water flag at 500 m from MOD09A1 v061 (sur_refl_state_500m,
  bits 3-5; composite A2015209). Checks: the same product in A2005209 (sites) and MOD13A1 v061
  VI_Quality bits 11-13 (whose in-file legend defines the codes; it is fill over the deep Dead Sea
  and absent over Antarctica, so it is only the check).
