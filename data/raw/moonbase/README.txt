South-pole base-site targets added on 2026-10-14 (group moon-base, next to Malapert): research record.
- mons-mouton: pin = centre of Mons Mouton in the USGS Gazetteer (-84.60, 31.00). NASA lists Mons Mouton and
  Mons Mouton Plateau as Artemis III candidate regions (NTRS 20250011660). The pin is not a NASA landing-site point.
- shackleton-ridge: pin = the Shackleton Connecting Ridge point of a NASA Langley study (NTRS 20240009936,
  -89.46752, -138.012788, 1,937.83 m). Connecting Ridge was an Artemis III candidate region in NASA's 2022 list.
- Temperatures: python -I scripts/extract_diviner.py (same LRO Diviner polar maps as Malapert; values in
  data/diviner_malapert.json "base_points"; 5x5 windows in data/raw/diviner/<point>_5x5_windows.json).
- Terrain: python -I scripts/compute_terrain.py --only mons-mouton --only shackleton-ridge (NASA Moon Trek, LOLA).
  The two points are listed in sources.json "terrainPoints" (they belong in data/terrain_points.json).
- Albedo, rock type and resource tags: not measured / no source, as for Malapert.
- sources.json: every new quote with its URL; each quote was checked by script against the page fetched that day.
