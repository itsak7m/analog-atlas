Cave targets (tranquillitatis-pit on the Moon, arsia-skylight on Mars): research record and extraction.
- moon_diviner_extract.py: reads the LRO Diviner Global Cumulative Product (Williams et al. 2017, NASA PDS) bin with the pit
  by HTTP range requests and writes moon_diviner_out.json (day-night curve, mean, min, max). Run: python -I data/raw/caves/moon_diviner_extract.py
- moon_lola_albedo.py: reads the LOLA 1064 nm normal albedo map at the pit (shown as a fact only, not scored).
- mars_mcs_out.txt / mars_tes_out.txt: output of data/raw/mars_ez_extract/mcs_extract.py and tes_albedo.py (unchanged scripts)
  for the Arsia Mons skylight (-5.5332, 241.3931 E).
- caves_proposal.json: the full research record (quotes, sources, measured vs modelled, decisions).
Lead decisions 2026-10-10: Moon albedo not scored (LOLA 1064 nm normal albedo is a different quantity);
Mars 'regolith' tag dropped (weak source); THEMIS brightness temperatures we read ourselves are not shown (the spot sits
about 0.3 km from the catalogue position), only the published THEMIS statement.
