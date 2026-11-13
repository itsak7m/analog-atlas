Jordan screening layer ("Discover Jordan"): raw and stage files
===============================================================

What this folder is
-------------------
The "Discover Jordan" layer covers Jordan with 10 km boxes and scores every
box against each Moon and Mars target with the same method as the
hand-picked sites. The app loads only data/screening_jordan.json. That file is
built from the files in this folder, so every number in it can be traced back
to a file here, or to a cached download named here with its sha256.

The app does not load anything in this folder.

Every box is a "Screening candidate — found by data, not field-checked".

What is in it
-------------
  boundary/jordan_ne10m_v5.1.1.json  Jordan's polygon from Natural Earth (364 vertices),
                                     its attributes, the zip's sha256, bbox and area
  stages/grid.json                   the grid constants and the 886 boxes
                                     (scripts/screening_grid.py)
  power/                             NASA POWER regional answers, unchanged, and
                                     manifest.json (URL, bytes, sha256, time)
  stages/power.json                  climate cell of each box (scripts/screening_power.py)
  dem/                               tiles.json (Copernicus DEM tiles: URL, bytes, sha256)
                                     and samples_jordan.json.gz (441 elevations per box)
  stages/terrain.json                terrain statistics of each box (scripts/screening_terrain.py)
  geology/                           samples_jordan.json (25 IGME5000 unit codes per box)
  stages/geology.json                main rock of each box (scripts/screening_geology.py)

Every stage file has the same frame: stage, generated, script,
grid ("jordan-10km-v1"), sources, network (every URL fetched in that run),
boxes (by box id) and controls (the 5 Jordan sites; the climate stage also
checks Amman).

The app file: data/screening_jordan.json
----------------------------------------
scripts/build_screening.py joins the four stage files into the one file the
app loads (format 1, about 700 KB). It holds:
  label, about       the exact label "Screening candidate — found by data,
                     not field-checked" and what the layer is
  grid               the grid constants and rules (row 0 = south, col 0 = west)
  boundary           the Natural Earth source, its sha256 and licence, and the ring
  climate            API, version, NASA's period label, the period check
                     ("values equal the project's 2001–2020 point files,
                     1092/1092, <date>"), the cell rule, the raw files and the
                     59 cells used (annual values only; the raw files keep the
                     months)
  terrain            dataset, pixel rule, method, the samples file, the 19 tiles
  geology            citation, DOI, sampling, rules and the 30 map units
  flagRules          what each flag means
  controls           the 5 Jordan sites run through the same steps as a box
  sources            every source with URL, licence, credit, notice, version,
                     access date and sha256
  stages, counts, checks, network
  boxes              one record per box: id, row, col, lat, lon, inJordan,
                     borderKm, climate {merra, syn, straddles}, terrain (10
                     statistics), geology (main rock, unit, share, certainty),
                     terrainExclude (water boxes only), cellGap_m, flags,
                     containsSite, nearestSite {id, km, dir}, sameUnitAs

Flags of a box
  border                    part of the box is outside the boundary (inJordan < 1)
  cellGap                   the POWER cell is more than 400 m higher or lower than
                            the ground at the box centre (as cellGap() in js/util.js)
  climateCellMostlyOutside  less than half of the box's MERRA-2 cell is in Jordan
  straddlesCellEdge         a POWER cell edge runs through the box
  partWater / water         20-50 % / 50 % or more of the box is one flat water
                            surface; a water box has terrainExclude
  lowCertaintyGeology       the map unit has low certainty, so no rock is scored
  noGeology                 the map has no rock type here (water)
containsSite is the id of the hand-picked site inside the box (or null).
nearestSite is the nearest hand-picked site and the box's direction from it.

The build does not trust the stage files. It works out every number again
from the raw files in this folder and stops (exit code 1, nothing written)
if anything differs: one record per box in every stage; grid constants,
centres, bounds and the 0.02 deg coverage lattice; every climate value
against the saved POWER answers, and the cells of the 5 sites and Amman
against data/raw/power/*.json (1,092 values); every terrain statistic again
from the samples with compute_terrain.compute_point(), and the 5 sites
against data/terrain.json; the main rock of every box again from the 25
unit codes and the rock table; every sha256; no Open-Meteo URL in any
network list; no NaN or missing value; water and terrainExclude agree; the
file is under 1 MB.

The grid
--------
- South-west corner 29.18 N, 34.95 E. 47 rows x 42 columns.
  Row 0 is the south row, column 0 the west column.
- Row step dlat = degrees(10000 / 6371008.8) = 0.0899320363724538 deg (10 km).
- Column step dlon = dlat / cos(31.28 deg) = 0.10522795946422789 deg
  (10 km at 31.28 N).
- Box id "jo-rRRcCC", for example jo-r12c13 (row 12, column 13).
- A box is kept when its centre is inside the Natural Earth Jordan polygon.
  That gives 886 boxes. grid.json also holds each box's share inside Jordan
  (inJordan), the distance from its centre to the border (borderKm) and the
  results of the coverage and area checks.
- The boundary is Natural Earth's de facto, generalised one. It is indicative
  only, and it does not include the West Bank.

Rebuild (from the project folder, in this order)
------------------------------------------------
  python -I scripts/screening_grid.py
  python -I scripts/screening_power.py
  python -I scripts/screening_terrain.py
  python -I scripts/screening_geology.py
  python -I scripts/build_screening.py

Python 3.12 standard library only; nothing to install. About 1 minute when
the big files are already in the cache or given with --ne-zip, --dem-dir and
--igme-zip (the terrain step takes most of it). A first run also downloads
about 141 MB.

Options: --ne-zip (grid), --power-dir, --refresh (power), --dem-dir (terrain),
--igme-zip, --crosscheck (geology), --cache-dir (grid, terrain, geology, build)
and --offline (all four stages).
build_screening.py never uses the network. Give it --dem-dir, --igme-zip and
--ne-zip to re-hash the big files too; without them it checks the sha256
values the stages recorded. --out writes the app file somewhere else.
Run again on the same inputs, every raw file comes out byte for byte the
same; only the stage files and the app file change, in their run times.

Big downloads are kept outside the project, in the cache folder
%LOCALAPPDATA%\analog-atlas\screening-cache (elsewhere
~/.cache/analog-atlas/screening; change it with --cache-dir). They are about
141 MB in all: Copernicus DEM tiles 88.0 MB, IGME5000.zip 47.5 MB and the
Natural Earth zip 4.9 MB. Every file is checked against its sha256. --offline
uses the cache only. --ne-zip, --dem-dir and --igme-zip reuse copies you
already have.

No script calls api.open-meteo.com. The elevations are read straight from the
Copernicus DEM tiles on AWS, with Open-Meteo's pixel rule re-implemented.

Licences and required notices
-----------------------------
NASA POWER (climate)
  NASA open data.
  Required citation: "The data was obtained from National Aeronautics and
  Space Administration (NASA) Langley Research Center's Prediction Of
  Worldwide Energy Resources (POWER) project funded through the NASA Earth
  Science Division."
  Also name the service, version and access date, for example:
  POWER Climatology API v2.10.1, regional, accessed 2026/10/10
  (the exact version and dates are in power/manifest.json).
  NASA asks to be told about published uses: larc-power-project@mail.nasa.gov
  https://power.larc.nasa.gov/api/temporal/climatology/regional
  https://power.larc.nasa.gov/docs/referencing/
  https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-information-policy

Copernicus DEM GLO-90-F (terrain)
  Free and open (licence Articles 3 to 5).
  Art. 6(b) notice (the same as DATASETS['earth']['credit'] in
  scripts/compute_terrain.py): "Produced using Copernicus WorldDEM-90 (c) DLR
  e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided
  under COPERNICUS by the European Union and ESA; all rights reserved."
  Art. 6(c), required because dem/samples_jordan.json.gz redistributes
  derived data: "The organisations in charge of the Copernicus programme by
  law or by delegation do not incur any liability for any use of the
  Copernicus WorldDEM™-90".
  No official endorsement is implied.
  https://copernicus-dem-90m.s3.amazonaws.com/<NAME>/<NAME>.tif
  https://copernicus-dem-90m.s3.amazonaws.com/tileList.txt
  https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf
  (licence on pages 19-21)
  https://doi.org/10.5270/ESA-c5d3d65

IGME5000, BGR (geology)
  GeoNutzV: any use, with source notes and a note of modification.
  Credit: "IGME5000, © BGR, Hannover, 2005, https://doi.org/10.25928/igme-5000,
  modified: reclassified to Analog Atlas rock ids"
  https://download.bgr.de/bgr/Geologie/IGME5000/shp/IGME5000.zip
  https://metadata.europe-geology.eu/record/full/9FD6624C-0AA7-46D4-9DA3-955E558CD5F1
  https://sg.geodatenzentrum.de/web_public/gdz/lizenz/geonutzv.pdf

Natural Earth 10m Admin 0 - Countries v5.1.1 (boundary)
  Public domain; "Made with Natural Earth" is optional.
  https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip
  https://www.naturalearthdata.com/about/terms-of-use/

Open-Meteo pixel rule (how a DEM pixel is picked)
  Only the index arithmetic is re-implemented; no code is copied.
  Source: https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Dem/DownloadDem.swift

Macrostrat (optional geology cross-check, off by default)
  CC-BY 4.0
  https://macrostrat.org/api/v2/geologic_units/map
