EMIT L2B mineral identification - raw-side files for Analog Atlas
=================================================================

What
----
data/emit.json            per-site results (15 sites inside EMIT's +/-52 deg coverage; Haughton, Dry Valleys,
                          Holuhraun and Mistastin are outside), product/citation/licence, rules, mineral table.
data/screening_emit.json  compact per-box results for the Jordan 10 km screening grid (data/screening_jordan.json).
data/raw/emit/manifest.json      every granule read: id, CMR concept id, version, data URLs (no credentials),
                                 matching L2A mask granule, bytes read, seconds.
data/raw/emit/site_windows.json  raw mineral-id counts per site window and granule (audit trail).
data/raw/emit/dmrpp/*.dmrpp.gz   cached LP DAAC DMR++ sidecars (public chunk maps; no credentials).
data/raw/emit/mineral_grouping_matrix_20230503.csv
                          EMIT SDS mineral grouping matrix, copied unchanged from
                          https://github.com/emit-sds/emit-sds-l2b/blob/develop/data/mineral_grouping_matrix_20230503.csv
                          (emit-sds-l2b repository, Apache License 2.0).

Data products (NASA LP DAAC, openly shared without restriction - EOSDIS Data Use and Citation Guidance)
  EMIT L2B Estimated Mineral Identification and Band Depth and Uncertainty 60 m
    V001  doi:10.5067/EMIT/EMITL2BMIN.001  (Green, 2023)
    V002  doi:10.5067/EMIT/EMITL2BMIN.002  (Brodrick et al., 2026)  - used where an acquisition was reprocessed
  EMIT L2A Masks 60 m V002 (doi:10.5067/EMIT/EMITL2AMASK.002, V001-era granule names) and
                      V003 (doi:10.5067/EMIT/EMITL2AMASK.003, V002 names) - cloud and water screening

How it works
------------
scripts/fetch_emit.py (Python 3.12 standard library only; helpers scripts/emit_http.py, emit_dmrpp.py,
emit_minerals.py). Granules are found with the public NASA CMR search API. For each granule the LP DAAC
DMR++ sidecar (<file>.nc.dmrpp) gives the byte offset of every HDF5 chunk, so only the chunks under the
window are downloaded with HTTP Range requests (shuffle + deflate decoded with zlib). Rules (masks,
window, aggregation) are written out in plain English in data/emit.json -> "rules".

How to rerun with your own token
--------------------------------
1. Create a free NASA Earthdata Login account and generate a user token
   (https://urs.earthdata.nasa.gov -> Generate Token). Tokens expire after ~60 days.
2. Save only the token string in a text file, e.g. earthdata_token.txt in the project root (gitignored).
   Never commit it. The scripts never print it or write it to any file; it is sent only as an
   "Authorization: Bearer" header to *.earthdata.nasa.gov / *.earthdatacloud.nasa.gov.
3. From the project root:
     python -I scripts/fetch_emit.py                       (sites + all 886 Jordan boxes)
     python -I scripts/fetch_emit.py --sites-only           (sites only)
     python -I scripts/fetch_emit.py --boxes-only           (boxes; reuses sites in data/emit.json)
     python -I scripts/fetch_emit.py --token-file D:\secret\token.txt
   If the token check prints HTTP 401/403, renew the token and make sure LP DAAC data access is
   authorised on your Earthdata profile.

Run time (2026-10-10 run, home connection, ~1-2 MB/s effective with 12 parallel range requests):
  sites 1218 s (15 sites, 86 granule windows read, 75 used), Jordan boxes 1408 s (886 boxes, 44 granules, 47 reads),
  total 2626 s (~44 min), 2.45 GB read in 2196 HTTP requests. Details in manifest.json "runSeconds".
  The DMR++ cache (data/raw/emit/dmrpp, ~2.8 MB) makes reruns skip the sidecar downloads; delete it to refetch.
