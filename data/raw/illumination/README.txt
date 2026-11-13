Base-site sunlight data added on 2026-10-23 (second judging round): research record.
- Values: python -I scripts/extract_illumination.py [--dl DIR]. It downloads the NASA PDS LOLA illumination
  maps (Mazarico et al. 2011, release 201608: AVGVISIB sun, AVGVISIB_EARTH, LPSR; 60 m and 120 m south-pole
  grids) into DIR, not the repo, and writes data/illumination.json plus the 5x5 windows here.
- Projection check: the permanent-shadow map is 1 at the centres of Shackleton, Haworth, Faustini, Shoemaker
  and Cabeus, and the Shackleton crater floor pin has 0 % sunlight. The sunniest 60 m pixel of the whole map
  (88.4 %) is on the Shackleton connecting ridge, 275 m from our pin; in the 120 m map a pixel with 84.5 %
  (among the 8 sunniest) is 148 m from the Malapert pin.
- The values change fast with position (see the 5x5 windows), so the pin pixel is used and the window range is
  quoted next to it in data/targets.json.
- Scoring: these LOLA shares are facts, not scored. Every Earth site in our list has the Sun up 50.5-51.7 % of the
  year (scripts/check_scores.py), so the share does not separate them. The scored factor is "Sun height"
  (js/scoring.js): 90 - |latitude| + tilt, Moon tilt 1.54 deg (NASA PIA13720), Earth tilt 23.44 deg (NSSDC).
- Permanent shadow is where ice can stay; it is not detected ice, so no ice resource tag was added.
- sources.json: every quote with its URL, checked by script against the page, abstract or PDS label that day.
