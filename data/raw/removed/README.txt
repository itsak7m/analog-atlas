Removed sites: raw files kept for traceability
===============================================

These files belong to two places that were on our site list and were then
removed. The app does not load anything in this folder. The files are kept
so anyone can check why each place was removed.

  power/<id>.json     the NASA POWER climatology response (2001-2020), unchanged
  terrain/<id>.json   the Copernicus DEM elevation samples (Open-Meteo), unchanged
  terrain_summary.json  the data/terrain.json entry for Mauna Kea at the time it
                      was removed

Mauna Kea (19.82 N, 155.47 W), from the team brief's original list
------------------------------------------------------------------
Removed because its NASA POWER grid cell does not describe the summit.

- NASA POWER grid-cell elevation: 635.57 m
  (power/mauna-kea.json, geometry.coordinates[2])
- Ground elevation at the site point: 4,169 m
  (Copernicus DEM centre sample, terrain/mauna-kea.json;
  centre_elev_m in terrain_summary.json)
- Gap: about 3,533 m. Our flag rule for Earth sites is a gap of more than
  400 m (js/util.js CELL_GAP_LIMIT_M), so this gap is almost nine times the
  limit. Sites over the limit normally stay in the ranking with a flag; this
  gap was so large that we removed the site instead.
- The cell's climate therefore describes much lower ground, not the summit:
  mean air temperature 20.9 C, relative humidity 82.05 %, rain 4.41 mm/day
  (T2M, RH2M and PRECTOTCORR, annual values in power/mauna-kea.json).
- The brief also says that its POWER cell includes ocean.

Al-Fahda Cave (32.3 N, 37.117 E), a Jordan candidate site
---------------------------------------------------------
Removed from the site list. The facts below come from the files in this
folder and the other data files:

- The point lies in the Harrat al-Shaam basalt field, about 11 km from our
  Harrat al-Shaam site point (32.2 N, 37.13 E).
- The cave is still part of the app: the Harrat al-Shaam site
  describes it (data/sites_meta.json) and its sourced "shelter" tag comes
  from the same cave survey (data/resources.json).
- NASA POWER describes the air above the ground, not the inside of a cave.
- For reference: NASA POWER grid-cell elevation 1,062.42 m
  (power/al-fahda-cave.json), ground elevation at the point 792 m
  (Copernicus DEM centre sample, terrain/al-fahda-cave.json).
