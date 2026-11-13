# Analog Atlas

**Places on Earth that behave like the Moon and Mars.**

NASA Space Apps Challenge 2026, Amman (13–14 November 2026). Challenge: *Identify Earth Locations that Analog the Permanent Moon Base Locations and Mars*.

Analog Atlas is a web app with a 3D globe of Earth, the Moon and Mars. It ranks 19 places on Earth by how closely their climate (NASA data), ground and rocks match 13 places on the Moon and Mars: three permanent Moon base sites near the south pole (Malapert Massif, Mons Mouton and the Shackleton connecting ridge, each one an Artemis III candidate landing region in a NASA list), the shadowed floor of Shackleton crater, two cave openings (the Mare Tranquillitatis pit on the Moon and the Arsia Mons skylight on Mars), four human landing zones proposed at NASA's 2015 workshop on Mars (including the Jezero and Gale rover sites), and three reference sites where missions landed (the Phoenix lander, Apollo 11 and Apollo 17). You can fly down into each place in 3D and stand there, and an **ESP32 field kit** can send live ground measurements into the app. The app focuses on Jordan: Wadi Rum, the black basalt and lava tubes of Harrat al-Shaam, an impact crater, a dry lake and the Dead Sea. **Discover Jordan** goes one step further: it covers Jordan with 886 boxes of 10 km and scores every box with the same method. For most targets this confirms our hand-picked Jordan sites and maps the ground around them; the best boxes are screening candidates, not field-checked (section 7).

The data is real and sourced: measured where possible, and shown as "not measured" where it is not. Every value names its source.

> **Live app:** https://itsak7m.github.io/analog-atlas/ (GitHub Pages, full 3D: it uses its own public Cesium ion key in `config.site.js`, which works only on itsak7m.github.io and can only read map assets)
> **30-second demo video:** https://itsak7m.github.io/analog-atlas/pitch/analog-atlas-pitch-promo30.webm · **7-slide deck:** [pitch/AnalogAtlas_CosmicCats.pptx](pitch/AnalogAtlas_CosmicCats.pptx) · **Code:** https://github.com/itsak7m/analog-atlas
> Run it on your own computer for the full 3D globe: `start.bat` (http://localhost:8080), see section 1.
>
> **Also here:** `JUDGE_GUIDE_AR.md`, a short guide for the jury (in Arabic), `pitch/`, with the deck, the 30 s and 60 s promo videos and the video guide, and `hardware/cosmic-cat/`, a 3D-printed case for the field kit (section 8).

## The short answer

Full analog match, default weights, computed by the app (the same table, live, is the first part of **Method & data**). Equal percentages share a rank. A match says where to test first; it is not proof. ⚑ after a site: its NASA POWER cell is more than 400 m above or below the real ground (section 9).

| Challenge question | Target | Closest Earth twins (top 3) | Read with care |
|---|---|---|---|
| **Permanent Moon base sites** | **All 3 base sites together** (our answer) | **Haughton Crater**: the only Earth site in the top 5 for all three (#3 Malapert 42 %, #3 Mons Mouton 66 %, #4 ridge 53 %) | Each base site alone has a different #1, because each ranking rests mainly on one slope number. No site reaches 50 % for all three. |
| | Malapert Massif | McMurdo Dry Valleys ⚑ 62 %, Wadi Rum (Jordan) 45 % (slope match), Haughton Crater 42 % | Only 1 site reaches 50 %. Rests mainly on slope. |
| | Mons Mouton | Rio Tinto 69 %, Atacama 68 %, Haughton Crater 66 % | Rests mainly on slope: 17 of 19 sites reach 50 %, the top 10 lie within 8 points. |
| | Shackleton connecting ridge | Wadi Rum (Jordan) 56 % and Rio Tinto 56 % (shared 1st, slope match), Atacama 55 % | Rests mainly on slope: the top 10 lie within 8 points. |
| Moon ice | Shackleton crater floor | Mistastin crater 46 %, Tso Kar ⚑ 41 %, Haughton Crater 38 % | No site reaches 50 %. Mistastin's terrain box is on the dry west side of the crater (its centre is a lake). |
| **Mars landing sites** | Jezero Crater | **Harrat al-Shaam (Jordan) 71 %**, Haughton Crater 70 %, North Pole Dome (Pilbara) 69 % | The top 3 lie within 2 points. |
| | Gale Crater | Dalangtan playa 72 %; **Lisan Peninsula (Jordan)** ⚑, MDRS and **Qa' al-Jafr (Jordan)** 69 % (shared 2nd) | Lisan has a ⚑. |
| | Deuteronilus Mensae | Tso Kar ⚑ 64 %, Haughton Crater 58 %, Dalangtan playa 51 % | Tso Kar has a ⚑. |
| | Erebus Montes | Tso Kar ⚑ 63 %, **Harrat al-Shaam (Jordan) 59 %**, Haughton Crater 57 % | Tso Kar has a ⚑. |
| | Phoenix (lander) | Dalangtan playa 71 %, Tso Kar ⚑ 70 %, **Lisan Peninsula (Jordan) ⚑ 68 %** | Tso Kar and Lisan have a ⚑. |
| **Caves** | Mare Tranquillitatis pit (Moon) | **Harrat al-Shaam (Jordan) 75 %**, Craters of the Moon 65 %, Holuhraun 63 % | Nobody has measured inside the caves. |
| | Arsia Mons skylight (Mars) | **Harrat al-Shaam (Jordan) 88 %**, Craters of the Moon 82 %, North Pole Dome 67 % | |
| Apollo sites | Apollo 11 | **Harrat al-Shaam (Jordan) 69 %**, North Pole Dome 67 %, Holuhraun 60 % | Apollo 11 has a ⚑: only 1 of its 5 factors is measured at the site. |
| | Apollo 17 | **Harrat al-Shaam (Jordan) 64 %**, North Pole Dome 63 %, Craters of the Moon 62 % | |

The three base sites use only 3 of 5 pillars (their rock type and resources are not documented at the pins), so read their percentages with care (section 3). The "all 3 together" row is computed live by the app (Method & data, and one line in the ranking panel of each base site): the Earth sites whose rank is 5 or better for every base site (equal percentages share a rank).

**Next user and next step (a plan, not done yet).** The first users we have in mind are students and teachers in Jordan who want to run a field day at a real analog site, and later teams that plan analog missions. We have not contacted any organisation yet. Our next step is a real 24-hour log with the ESP32 field kit at Harrat al-Shaam, the #1 Earth twin of Jezero, and, once access is checked, at the best Discover box for Jezero, 25 km to its south-west. We then compare both days with NASA POWER (section 6) and ask a geologist to review the Jordan rock table (section 7).

---

## 1. Start the app (Windows)

1. Python 3 must be installed (`python --version`). Nothing else is needed: no Node.js, no build step.
2. Double-click **`start.bat`**, or run `python serve.py --open` in this folder.
3. Use **Chrome or Edge** at **http://localhost:8080**. The USB field kit only works there.
4. To stop the app, close the black window or press `Ctrl+C`.

The server only listens on this computer (127.0.0.1), so nothing is shared on the network. It only answers requests addressed to `localhost` or `127.0.0.1` on its own port, it never lists the files in a folder, and it never sends secret or developer files (`earthdata_token.txt` and the other `.txt` files in the top folder, `.git`, `.claude`, Python files, firmware build folders). Every reply also tells the browser not to show the page inside another website's frame. If port 8080 is already in use, the server checks who holds it and stops: either the app is already running (open http://localhost:8080; a second `start.bat` opens it in the browser for you), or another program uses the port, and then it prints how to find that program (`netstat -ano | findstr :8080`; the last number is its process id, which Task Manager > Details shows). `start.bat` (`serve.py --open`) opens the app in Chrome or Edge: in the default browser when that is Chrome or Edge, else in Chrome, else in Edge. Opening `index.html` directly as a file does not work, and the page says so.

### Add your free Cesium ion token (for real 3D terrain)

Without a token the app still works: the globes, data, field kit and photos all run. The close-ups are flat, though.

1. Create a free account at https://ion.cesium.com/signup (Community plan).
2. In **Asset Depot**, press **Add to my assets** for **Cesium Moon** and **Cesium Mars**. Nothing else is needed.
3. In **Access Tokens**, choose **Create token**. Set the name to `analog-atlas-local`, keep only the scope `assets:read`, and under **Allowed URLs** add both `http://localhost:8080` and `http://127.0.0.1:8080` (the same app opens at either address).
4. Easiest: in the app press the **3D off** button (top right), paste the token and press **Save**. The token is then saved in this browser only. To use it in every browser on this computer, open the same box again and press **Save it for all browsers (config.js)**, or put it in **`config.js`** yourself (`cesiumIonToken: "…"`, see `config.example.js`) and reload the page.

**Which keys are in this folder?** Two, and both must stay on this computer:
- `config.js` holds the Cesium ion token. It is the only key the browser sees, and anyone who opens the page can read it, whether it is in `config.js` or saved in the browser. That is how every browser app with a Cesium token works, so keep it limited to `assets:read` and the two local addresses above.
- `earthdata_token.txt` holds a NASA Earthdata Login token. Only `scripts/fetch_emit.py` uses it (to download the EMIT mineral data); the app does not need it, and the server refuses to send it.

Before you copy, zip or share this folder, leave out `config.js`, `earthdata_token.txt`, `.claude/`, `__pycache__/` and the `firmware/**/build/` folders (`config.example.js` is the empty template). `.gitignore` lists most of them, but that only helps if you use git. **After the event, delete both tokens:** the Cesium token in your Cesium ion account (Access Tokens), and the Earthdata token in your NASA Earthdata Login profile (https://urs.earthdata.nasa.gov). Make new ones if you need them again. Never put a secret key (for example a Claude API key) in `config.js`.

**Turn 3D off for one visit:** add `?no3d` to the address (http://localhost:8080/?no3d). The app then does not use Cesium ion at all, even with a token, so it never waits for the internet. The globe shows NASA pictures without 3D terrain. The 3D dialog has the same link, and a banner has a link to turn 3D back on. The **3D** button says **3D on**, **3D off** (no token, or `?no3d`) or **3D failed** (Cesium ion did not answer or did not accept the token; the 3D dialog gives the reason).

### Demo day checklist

1. **The day before:** start the app, open http://localhost:8080/tests/ (it must say "All 68 tests passed"), then run the **▶ Tour** once and open the Earth, Moon and Mars views and **Discover Jordan**, to check that everything loads.
2. **Start:** double-click `start.bat` once (a second copy only says that the port is in use). Use **Chrome or Edge** at **http://localhost:8080**. The Cesium token works only there (or at http://127.0.0.1:8080), because its Allowed URLs list only these two addresses with port 8080. If `start.bat` says that **another program** is using port 8080, close that program (`netstat -ano | findstr :8080` shows its process id) and start again; do not move the app to another port.
3. **If the Wi-Fi is slow or stops:** double-click **`start_offline.bat`** (or open **http://localhost:8080/?no3d**). The app then never waits for Cesium ion, and the globe shows the offline pictures in `textures/`; the data, Discover Jordan, the photos and panoramas and the field kit all work. Street View, 3D terrain and the NASA map tiles need internet. Try this once with the Wi-Fi switched off before the event.
4. **Backup if the browser or the laptop fails:** the deck `pitch/AnalogAtlas_CosmicCats.pptx`, the videos `pitch/analog-atlas-pitch-promo30.webm` and `promo60.webm`, and the screenshots in `pitch/shots/`. In `pitch/promo.html`, use **Play 30 s** only: **Save 30 s** and **Save 60 s** record the video again and replace the file (they ask first, and if a save fails the old video stays).
5. **Field kit:** bring the USB data cable. Without a working kit the panel shows simulated values, always labelled "Simulated".
6. **Laptop:** on the charger, sleep and notifications off.
7. **Secrets:** never show or share `config.js` or `earthdata_token.txt` (no screenshots, no zip). After the event, delete both tokens (see above).

### What the app contacts on the internet

- **NASA GIBS** (Earth pictures for the far view) and **NASA Solar System Treks** (Moon and Mars mosaics). No key.
- **Cesium ion** (3D terrain, Bing Maps aerial imagery, Cesium Moon and Cesium Mars), only when a token is set and the address has no `?no3d`. The app also asks Cesium ion for NASA's Artemis III candidate landing regions (asset 2683531). For our token Cesium ion answered "not found" (error 404) on 14 October 2026, so the Moon view says once that the regions are not shown. They appear only if your Cesium ion account has this asset.
- **Google Street View**, only when you open it: **Stand here · Street View**, or **Twin view** at Haughton Crater, MDRS or SP Crater. Links marked ↗ open Google Maps in a new tab, only when you click them.
- **NASA POWER** (power.larc.nasa.gov), only when you give the field kit a location other than Amman. The position is rounded to about 1 km.

CesiumJS, Pannellum and the fonts are local copies in `vendor/`.

---

## 2. What you can do

| Feature | How |
|---|---|
| **3D globe** | Drag to rotate; use the wheel, pinch or `+`/`−` to zoom. Arrow keys rotate. It spins slowly until you touch it. |
| **Earth / Moon / Mars** | Buttons in the top bar. Earth uses NASA Blue Marble with NASA Black Marble city lights at night. The Moon uses LRO data, Mars uses Viking/MOLA data, and both have real 3D terrain with the token. Without 3D (no token, `?no3d`, or no internet) the globes show NASA pictures and the offline pictures in `textures/`. For the Moon base sites and the Shackleton crater floor the Moon opens on a tilted view of the south pole, seen from the Mons Mouton side, so all four pins have labels; the Apollo sites and the pit open on the whole Moon. The darker, less sharp square around the pole and the straight seam near it are in the Cesium Moon imagery itself (photos taken in low sunlight; the seam is the 0°/180° line of the mosaic), not added by the app. |
| **Compare with** | Pick the target from a menu with two columns, **Moon** and **Mars**, each split into groups. The seven groups: **Moon · permanent base sites (south pole)**: Malapert Massif, Mons Mouton and the Shackleton connecting ridge (LRO Diviner temperatures and LOLA terrain at each pin; each one is an Artemis III candidate landing region in NASA's 2022 or 2024 list). **Moon · cave shelter (lava-tube pit)**: the Mare Tranquillitatis pit, an opening into a probable lava tube (LRO Diviner surface temperatures around the pit; Mini-RF radar shows a cave passage). **Moon · south-pole ice (shadowed crater floor)**: Shackleton crater floor (the brief calls it the "Lunar South Pole"). **Mars · proposed human landing zones (NASA, 2015)**: Jezero Crater, Gale Crater, Deuteronilus Mensae and Erebus Montes in Arcadia Planitia (the last two are ice-rich, measured from orbit by Mars Climate Sounder and TES). **Mars · cave skylight (lava-flow pit)**: the Arsia Mons skylight 'Jeanne' (Mars Climate Sounder and TES around the pit; a candidate cave entrance seen by THEMIS and HiRISE). **Mars · lander site**: the Phoenix site, measured there by the lander. **Moon · Apollo sites**: the Apollo 11 and Apollo 17 sites, as reference sites. Apollo 11 has a ⚑: only 1 of its 5 factors is measured at the site itself. The app starts with Jezero; the Moon button switches to Malapert. Picking a Mars target while the Moon is on screen (or the reverse) switches to that world. The chip next to the list opens the target's data and its 3 closest Earth twins. |
| **Ranking** | Earth sites sorted by score. Only the **strong twins** (50 % or more) are listed and pinned on the globe at first; **Show all 19 sites** opens the rest, so nothing is hidden. When no site reaches 50 % (for example the Shackleton crater floor in the full match), the list says so: Earth has no strong twin of that place in our list. The globe then pins the closest site, marked "· closest". When only one or two sites reach 50 % (Malapert has one), the next 3 sites are listed in grey under a **Weaker twins** line (list only, no pins). If no twin is on screen after you pick a target on Earth, the globe turns to the #1 site. Equal percentages share a rank (`=6`); ranks always count all 19 sites. In the full match each row has a **C T L G R** strip: one small bar per pillar (climate, terrain, landing zone, geology, resources); grey means not used. A line under the list explains the ⚑. Click a row to fly there. |
| **Discover Jordan** | The second tab of the ranking panel. 886 boxes of 10 km over Jordan, scored with the same method as the sites (without resources), shown as a Top 10 list and as coloured squares on the globe. Each Top 10 row is named after the nearest Atlas site (for example "25 km SW of Harrat al-Shaam"), and the line above the list gives the best hand-picked Jordan site scored the same way. While Discover is on, the globe pins only the five Jordan sites, with their score without resources. Each box has its own page with **Fly down**, **Stand here** and **N / E / S / W** to step to the next box. **All boxes** opens a table of every box with a CSV download. Every box is a "Screening candidate — found by data, not field-checked" (section 7). |
| **Full analog match / Climate match** | The app opens in **Full analog match**: climate plus terrain slope, landing zone, rock type and resources (section 3). **Climate match** uses NASA POWER only and reproduces the reference rankings of the brief. |
| **Fly down** | The camera flies from space to the site, tilts towards the horizon and slowly orbits it. **Back to globe** (or `Esc`) returns. |
| **Stand here** | The buttons say what you get. **360° photo**: a real photo all the way round (7 places). **N° panorama**: a real photo that covers only part of the circle; the button gives its width, for example "124° panorama" at Harrat al-Shaam (7 places, 120–170° wide). **Photo**: an ordinary real photo, not 360° (18 places); for Qa' al-Jafr, Mistastin crater, Malapert, Mons Mouton, the Shackleton connecting ridge, the Shackleton crater floor, the Mare Tranquillitatis pit, Deuteronilus Mensae, Erebus Montes and the Arsia Mons skylight it is taken from orbit, looking straight down. **Street View**: Google Street View at Haughton Crater, MDRS and SP Crater; the imagery is © Google and its contributors and needs internet. **3D terrain**: every place; with 3D on, an eye-level view rendered from elevation data and labelled that way; without 3D, a flat view, and the banner says so. `Esc` or **Back to globe** works during the flight down too. Every photo viewer shows the place, the photographer, the licence and the source page; the camera position and field of view are under **Photo notes**. |
| **Every place has a photo** | Each of the 19 Earth sites and 13 targets has at least one real photo of its own (the browser tests check this). For the Shackleton crater floor we did not use LROC's orbital view of the rim, because LROC's terms say the images on its website are copyrighted; its photo is cut from LROC's mosaic in the NASA PDS instead. |
| **Twin view** | Real photos of an Earth site and its target side by side. The button appears only when at least one of the two places has a real photo. When both are panoramas, **Link views** turns them together. At Haughton Crater, MDRS and SP Crater, **Show our local photo instead** switches from Street View to our own photo; without internet, or when Google cannot be reached, the local photo comes first. |
| **Twin of** | On each Earth site's page: the targets for which this site is in the top 3, with its rank and %, computed live with your settings. Click one to compare with that target. |
| **What crews can test here** | On each Earth site's page: real tests and training done there (44 items, each with who did it, the year when known, and a source link whose tooltip shows the exact quote), then our own ideas, marked **Our proposal** (9 items, all at Jordan sites, each with the evidence it rests on). Nothing is documented as tested yet at Harrat al-Shaam, Waqf as Suwwan or Qa' al-Jafr. |
| **Tune factors** | One slider per climate factor and per pillar re-weights the score live. **Strict data** uses only target values measured at the site itself. **Stability check** shows how often each site stays in the top 3 under 1,000 random weightings (fixed seed 2026, so it is repeatable). |
| **Earth temperature** | A switch at the top of Tune factors: **Air 2 m · NASA POWER (~50 km)** (the default, used by the reference rankings) or **Ground surface · MODIS (1 km)**, the ground temperature NASA's MODIS satellites measured at each site in 2003–2020. Ground surface is closer to how most Moon and Mars targets are measured. It changes the three temperature factors only (rain and albedo stay NASA POWER), for the sites and the Discover boxes; the ranking then says "· surface temperature (MODIS)" and every site page says which source each temperature row uses. |
| **Measured from orbit** | A card on every site page and box page: the MODIS ground surface temperature (mean, day-night swing, coldest 8-day night with its date), and what the top of the ground is made of: MODIS emissivity e29 with a plain-words reading, Sentinel-2 iron and clay/carbonate ratios with the picture dates, the ASTER silica index (relative only), flags such as plants or water, and for the five Jordan sites a check against our rock map. NASA EMIT minerals are shown where `data/emit.json` has them. Composition and minerals are display only: never used in the score. |
| **Method & data** | The formula, every value with its source, a self-check of the reference rankings, all sites against all targets (with a CSV download), credits, limits and the AI-use note. |
| **▶ Tour** | A guided mission tour of about 2 minutes ("Play the 2-minute mission tour"): 14 steps, from the targets to Jezero, the full match, Jordan's closest twin of the Apollo 17 site, the Moon base site Malapert, the Jordan corridor, photos, the field kit and the method. Every number in it is computed from the data when the step is shown. It uses the default settings and puts yours back at the end. While it runs, the button reads **■ Stop tour**; **Next**, **Back** and `Esc` act at once, even during a camera flight. |
| **◆ Jordan** | The Jordan Analog Corridor: five Jordan sites as one story (Harrat al-Shaam, Waqf as Suwwan, Lisan Peninsula at the Dead Sea, Qa' al-Jafr, Wadi Rum), with a route line on the globe. All five are pinned while it runs, and each card gives the site's best computed rank over all targets. While it runs, the button reads **■ Stop**. |
| **Field kit** | Live ESP32 readings and charts, "this spot right now vs the target", the kit location, and a 24-hour log compared with NASA POWER (section 6). A clearly labelled simulation runs when no kit is connected: the panel says **Simulated snapshot score** and the charts say SIMULATED. The kit bar at the bottom shows "Kit vs ‹target› N%", with "· far apart" below 20 % (a wording choice); its tooltip says whether the reading is simulated or live, and that it is a snapshot, not a 20-year average. |

The app works on phone width: the mission brief opens short (title, **Play the tour** and **More**), and the ranking opens as a low sheet at the bottom (**Show more of the list** makes it taller), so the globe shows first. Pin labels move to the left, below or above a pin when there is no room on the right, and keep clear of the map credits and the panels. The app can be used with the keyboard (focus goes back to a sensible place when the tour, the Jordan corridor or **Show all** ends), and respects the system "reduce motion" setting (no spin, instant camera moves).

---

## 3. How the score works

For every factor whose target value was measured:

```
factor score  = max(0, 1 − |Earth value − target value| / R)
climate match = Σ(weight × factor score) / Σ weight      (weights start at 1)
```

| Factor | Earth value (NASA POWER) | R |
|---|---|---|
| Mean temperature | T2M | 100 °C |
| Daily temperature swing | T2M_RANGE | 100 °C |
| Coldest ground temperature | TS_MIN | 100 °C |
| Rainfall (target 0) | PRECTOTCORR | 3 mm/day |
| Surface brightness (albedo) | ALLSKY_SRF_ALB | 0.5 |
| Sun height (only the three Moon base sites) | computed from the site latitude | 90° |

A target value that was not measured is stored as `null` and left out ("not measured").

**Sun height** is part of the climate match only for the three permanent Moon base sites, because long sunlight is what makes these places base sites. It is the highest the Sun gets above a flat horizon in a year: 90° − |latitude| + axial tilt, at most 90°. Both sides use the same formula: the Moon tilt is 1.54° (NASA Photojournal PIA13720) and the Earth tilt 23.44° (NASA NSSDC Earth fact sheet). The targets get Malapert 5.58°, Mons Mouton 6.94° and the Shackleton connecting ridge 2.07°; Earth sites range from 36.0° (McMurdo Dry Valleys) and 38.1° (Haughton) to 90° in the tropics, and the Jordan sites get 81–84°. R = 90° (the whole possible range) is our choice. The other ten targets do not use it, so their scores did not change. The real LRO LOLA sunlight, Earth-in-view and permanent-shadow values at the three pins (Mazarico et al. 2011) are shown as facts on each target page, but not scored (see Limits).

**Mean temperature is approximate.** On Earth it is NASA POWER T2M, the air 2 m above the ground. On a target it is the reference value for that place (for Gale it is the Mars-wide average, see Strict data). Perseverance measured the air at Jezero (its coldest value, −83 °C, is air too). The Moon has no air, so the Moon values (the three base sites, the Shackleton crater floor, the Mare Tranquillitatis pit, Apollo 17) are surface temperatures, and the Mars values measured from orbit (Mars Climate Sounder at Deuteronilus Mensae and Erebus Montes) are ground temperatures. The note next to each target value says which. Earth air and target ground are not the same thing.

**Surface temperature switch.** In Tune factors, **Earth temperature** can be set to **Ground surface · MODIS**. The Earth side of mean temperature, daily swing and coldest ground then comes from NASA MODIS land surface temperature (MOD21A2 Terra + MYD21A2 Aqua, Collection 6.1, 8-day, 1 km, 2003–2020, clear-sky values with an estimated error of 2 K or less) at the 1 km pixel of the site (`data/lst.json`), or the mean of the box's 1 km pixels for a Discover box (`data/screening_lst.json`). Mean = average of the four passes (about 10:30, 13:30, 22:30, 01:30), about 2–3 K warmer than a true 24 h mean; swing = Aqua 13:30 minus 01:30, about 88 % of the full daily range; coldest = the coldest 8-day mean of 01:30 values. Polar sites (Haughton, McMurdo Dry Valleys) have no mean or swing (the sun stays up or down for days), so in surface mode their climate rests on fewer factors; a pixel that is mostly water (Mistastin) gives no temperature factors at all ("not measured", with the reason). Rain and albedo stay NASA POWER. The default stays **Air 2 m**, so the reference rankings and every check below are unchanged. With all weights ×1 in the full match, surface mode keeps the same sites in the top 3 (equal percentages share a rank) for 12 of the 13 targets, among them Arsia Mons, the Mare Tranquillitatis pit, Apollo 11 and Apollo 17 (scores move by 0–1 point); Jezero keeps Harrat al-Shaam first (Haughton ties it at 71 %); Malapert's McMurdo Dry Valleys rises from 62 % to 68 %, and Haughton moves from third to second; for Mons Mouton, Haughton moves from third to first (72 %). Only the Shackleton connecting ridge changes its top 3: Haughton (59 %) replaces Atacama. For Gale, the Lisan Peninsula, MDRS and Qa' al-Jafr stay tied at 69 % behind Dalangtan playa (only their hidden decimals change order). **Method & data** shows this table for every target, live.

**Check:** `python -I scripts/check_scores.py` and http://localhost:8080/tests/ (68 tests, including the Jordan screening checks of section 7, the Sun height formula, the LOLA facts against their raw windows, the regolith and place rules, the Moon base sites taken together, the #1 twin's pin label, the checks of the surface temperature switch and the composition file, the headline results of this section and the offline and `?no3d` start) both reproduce every reference value from section 6 of the brief, with the brief's original sites (without Mauna Kea, see below). Examples: Jezero gives Dry Valleys 60 %; MDRS, Death Valley, Harrat al-Shaam and Atacama 57 %; Haughton 56 %; Wadi Rum 55 %; Rio Tinto 52 %; Holuhraun 33 %. The Shackleton crater floor (the brief's "Lunar South Pole") gives Atacama 51 %, Harrat 50 %, Death Valley 50 % and Wadi Rum 47 %. Apollo 11 gives Atacama 44 %, Harrat 43 %, Death Valley 43 % and Wadi Rum 40 %. The same check runs inside the app under **Method & data**.

**Mauna Kea.** The brief also listed Mauna Kea. We removed it because its NASA POWER grid cell does not describe the summit: the cell is at 635.57 m, but the ground at the site point is at 4,169 m (Copernicus DEM), a gap of about 3,533 m, almost nine times our 400 m ⚑ limit (see below). The cell's climate (mean air 20.9 °C, humidity 82.05 %, rain 4.41 mm/day) describes much lower ground. The brief also says the cell includes ocean. Sites over the 400 m limit normally stay in the ranking with a ⚑; this gap was so large that we removed the site instead. Its raw files are kept in `data/raw/removed/` (see `README.txt` there).

**Strict data.** We checked every target value against its source on 9 and 10 October 2026. A few reference values are not measurements at the site itself: the Moon-wide albedo, the Mars-wide mean used for Gale, the midpoints of measured ranges, and general NASA statements for the south pole. Each one is labelled in the app. **Strict data** (in Tune factors) replaces them with site measurements or leaves them out. Examples: Gale albedo becomes the measured 0.22 and Jezero albedo the measured 0.15; the Shackleton crater floor gets LRO Diviner values at the pin itself (mean −213.95 °C, coldest −232.83 °C). In strict mode a target needs at least 2 measured factors to get a climate score; in the full analog match its other pillars are still used. The reference rankings above use the normal values.

**Full analog match** = weighted average of five pillars (weights start at 1). A pillar that cannot be computed is left out, and the ranking shows how many were used (for example 3/5). **A site needs at least 3 of the 5 pillars to get a full score**; with fewer it shows "not enough data", so no rank rests on one or two pillars. No site needs this rule today. Until 3 November 2026 Mistastin had no score for the three Moon base sites (its terrain box was the lake, and the base sites have no rock type or resources, so only climate was left).
- **Climate**: as above.
- **Terrain**: median ground slope in a 10 km × 10 km box. We read the ground height on a 500 m grid and measure the slope over 1 km, in the same way on all three worlds. Terrain match = max(0, 1 − |slope difference| / 10°). See `data/terrain.json` and `scripts/compute_terrain.py`.
- **Landing zone**: a crew needs one flat place, not a flat region. We find the largest square in the box where every grid point has a slope under 10°, from 0.5 to 9.5 km in 500 m steps. NASA's Artemis landing rule is a slope under 10° measured over 100 m (NASA NTRS 20250009323); our slopes use a 1 km baseline, so this is an approximation. Landing match = min(1, site zone ÷ target zone). Mountains elsewhere in the box only affect the terrain pillar. Terrain and landing zone come from the same slope grid, so for flat targets they often agree (see Limits).
- **Geology**: main rock type. 1 for the same rock, 0.5 for related rocks (same family, or one place's main rock also found at the other), 0 otherwise. The rock types are in `data/sites_meta.json` and `data/targets.json`. Each Earth site lists the sources that name its rock types, with an exact quote (`geology.sources`); the main rock has a source at all 19 sites (MDRS and SP Crater were added on 3 November 2026). Other rock types found at a site also count for the 0.5 level; at 10 sites at least one of them has no source yet, and `geology.unsourced` in `data/sites_meta.json` names them. The match levels are a method choice, not a measurement. A target whose rock type is not known (the three Moon base sites) has no geology pillar.
- **Resources**: four tags a permanent base needs: water ice, natural shelter (lava tubes, caves, pits), regolith for building, salts and brines. Every tag in `data/resources.json` has a source and an exact quote. Resources match = share of the target's tags that the site also has. A site where we found no source scores 0; a target with no tag (the three Moon base sites) has no resources pillar. This is a sourced classification, not a measurement. **One rule for the regolith tag** (`rules.regolith` in `data/resources.json`): a target gets it when the source documents regolith (the loose layer of rock dust and soil) at the target itself; an Earth site gets it when the source documents the site's own material as a regolith simulant or as building material. A quote that only shows dust, rock or a nearby place does not count. We checked every regolith tag against this rule again on 23 October 2026. SP Crater lost its tag: its source documents the JSC-1 simulant from Merriam Crater, about 40 km away, not SP Crater's own material. So no Earth site has a regolith tag now. The Shackleton crater floor tag is now sourced at the crater itself (Thomson et al. 2012, LRO Mini-RF radar of Shackleton: "less mature regolith present on the crater wall slopes"). **One place rule for all four tags** (`rules.place`): the source must document the resource at our point or in the named feature our point is in (its crater, cone, valley, lava field, mare, basin or park). A different feature in the same region is a nearby place and does not count, and a record at our point that says the opposite wins. So the Shackleton crater wall counts for the crater floor pin, and Mare Tranquillitatis for the pit. On 26 October 2026 the McMurdo Dry Valleys lost their ice tag under this rule: its source was about Beacon Valley, about 50 km away, a different valley, and the two soil pits at Bull Pass, about 3 km from our point, record their frozen ground as "Dry frozen", not ice-cemented (New Zealand Antarctic Soils Explorer, sites 414 and 415). Their salts tag stays (Don Juan Pond is in Wright Valley, the valley of our point). The other ice, shelter and salts tags are still to be re-checked against the place rule (section 9). The three base sites have no regolith tag, because no source documents regolith at their pins; general south-polar statements do not count.

**Key findings** (full analog match, default weights, normal data):
- **Climate alone barely separates the desert sites.** For Jezero, Harrat al-Shaam, Atacama, Death Valley and MDRS all score 57 %. On climate alone, the high, cold Tso Kar basin (Ladakh) leads for every Mars target: Jezero 68 %, Gale 67 %, Deuteronilus Mensae 63 %, Erebus Montes 63 %, the Arsia Mons skylight 57 % and Phoenix 76 %. Tso Kar has a ⚑: its NASA POWER cell sits 521 m above the ground there, so the cell is probably colder than the real basin floor.
- **Jezero:** Jordan's **Harrat al-Shaam** comes first (71 %), just ahead of Haughton (70 %) and Pilbara's North Pole Dome (69 %). Holuhraun is fourth (66 %). The lead is 1 point, so read "first" with care; in the Stability check Harrat al-Shaam stays in the top 3 in 76 % of the runs.
- **Gale and Phoenix:** Qaidam's **Dalangtan** playa comes first (72 % and 71 %). For Gale, the Lisan Peninsula (Dead Sea), MDRS and Qa' al-Jafr share second place (69 %). For Phoenix, Tso Kar is second (70 %) and Lisan third (68 %), the best in Jordan.
- **Cave targets**: Jordan's **Harrat al-Shaam**, with its 14 surveyed lava caves, comes first for both: **75 %** for the Mare Tranquillitatis pit (Moon) and **88 %** for the Arsia Mons skylight (Mars). Craters of the Moon (Idaho, lava tubes) is second (65 % and 82 %). The climate values are the measured ground around each opening; nobody has measured inside these caves (the ~17 °C inside the Moon cave is a model and is shown only as a fact).
- **Deuteronilus Mensae and Erebus Montes** (ice-rich Mars landing zones): **Tso Kar** comes first (64 % and 63 %). For Deuteronilus, Haughton is second (58 %), Dalangtan third (51 %) and Harrat fourth (49 %). For Erebus Montes, Harrat is second (59 %) and Haughton third (57 %).
- **Apollo 11 and Apollo 17:** Jordan's **Harrat al-Shaam** comes first (69 % and 64 %), with Pilbara's North Pole Dome second (67 % and 63 %). Holuhraun is third for Apollo 11 (60 %) and Craters of the Moon for Apollo 17 (62 %). SP Crater, which led both before its regolith tag was removed (see Resources above), is now fifth (54 % and 56 %). Harrat al-Shaam stays in the top 3 in 100 % (Apollo 11) and 96 % (Apollo 17) of the Stability runs. Apollo 11 has a ⚑: only 1 of its 5 factors is measured at the site itself.
- **Permanent Moon base sites** (the first part of the challenge): all three use only 3 of 5 pillars, because no source documents their rock type or a resource at the pins. Their climate match is 33 % or less at every Earth site: the three temperature factors score under 10 % everywhere, so climate comes down to rainfall and Sun height. Sun height gives the polar Earth sites (Dry Valleys, Haughton) the best climate match. The rankings still rest mostly on slope and the flat landing zone.
  - **Malapert Massif:** the McMurdo **Dry Valleys** come first (62 %), **Wadi Rum** second (45 %), the best in Jordan, and Haughton third (42 %). Only the Dry Valleys reach 50 %. Malapert's largest flat zone is 2 km and every Earth site with terrain data has at least that much, so the landing pillar is 100 % for all of them. Wadi Rum's slope match is only 14 % (median slope 10.46° against 19.04°), and every site except the Dry Valleys and Wadi Rum scores 0 % on slope. Stability check: Dry Valleys 100 %, Wadi Rum 91 %, Haughton 71 % of the runs in the top 3.
  - **Mons Mouton:** **Rio Tinto** comes first (69 %), then Atacama (68 %) and Haughton (66 %). 16 of the 19 sites reach 50 % and the top 10 lie within 8 points, so this target separates the sites very little. Jordan's best are Harrat al-Shaam, Waqf as Suwwan and the Lisan Peninsula (61 %).
  - **Shackleton connecting ridge:** Jordan's **Wadi Rum** and Rio Tinto share first place (56 %), then Atacama (55 %). Wadi Rum scores high because its median slope (10.46°) is close to the ridge's (8.56°): a terrain match of 81 %. The top 10 lie within 8 points.
  - **All three together:** each base site has a different #1, because their slopes differ (median slope 19.04° at Malapert, 4.66° at Mons Mouton, 8.56° on the ridge). **Haughton Crater** is the only Earth site in the top 5 for all three (#3, #3 and #4; 42 %, 66 % and 53 %), so it is the steadiest Earth analog of the base sites as a group. Next by mean rank: Atacama (#8, #2, #3) and Rio Tinto (#13, #1, #1). Rio Tinto's two wins are mostly a slope match.
- **Shackleton crater floor:** all scores are low. Mistastin comes first (46 %; same anorthosite rock as the crater, a full landing zone, but no ice tag and a climate match of 29 %), then Tso Kar (41 %), Haughton (38 %) and the Dry Valleys (37 %). Jordan's best is Harrat al-Shaam at 30 %. Until 26 October the Dry Valleys were first (47 %); that rested on an ice tag sourced 50 km away, which the place rule removed (Resources above).
- Harrat would score higher for the Moon if a source documented its regolith as building material; we found none, so it gets no credit for it. Its lava tubes carry a sourced "shelter" tag, which counts only for the two cave targets (the Mare Tranquillitatis pit and the Arsia Mons skylight).

Terrain, geology and resources are what tell the desert sites apart. Real field measurements with the kit are still to be made (section 6).

---

## 4. Data sources

**Earth sites (NASA):** the [NASA POWER](https://power.larc.nasa.gov/) climatology API (v2.10.0), 2001–2020 annual and monthly values, community RE, fetched 9 October 2026. Every raw answer is kept unchanged in `data/raw/power/<id>.json`, and `scripts/build_data.py` copies the numbers into `data/sites.json`. The official parameter definitions are in `data/power_parameters.json`. To re-download everything:

```
python -I scripts/fetch_power.py --refresh
python -I scripts/fetch_power.py --point amman 31.95 35.93
python -I scripts/build_data.py
```

`--refresh` downloads every site in `data/sites_meta.json` again, but not `data/raw/power/amman.json`, which the field kit uses for its default location (Amman). That file needs the `--point` line.

API template:
`https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=T2M,T2M_MAX,T2M_MIN,T2M_RANGE,RH2M,PRECTOTCORR,ALLSKY_SFC_UV_INDEX,ALLSKY_SFC_SW_DWN,WS2M,PS,TS,TS_MAX,TS_MIN,ALLSKY_SRF_ALB&community=RE&longitude={lon}&latitude={lat}&format=JSON`

**Why each site is listed:** each site in `data/sites_meta.json` has its sources (NASA, ESA, USGS, peer-reviewed papers). The app shows them under "Why it matters" and in **Method & data**. Sites are labelled honestly:
- **NASA/ESA analog** (9 sites): used by NASA or ESA for analog fieldwork, tests or astronaut training.
- **Published analog** (7 sites): used for analog missions, or used or proposed as an analog in published research.
- **Candidate** (3 sites: Harrat al-Shaam, Waqf as Suwwan, Qa' al-Jafr): our proposal, with geology sources but no paper that calls it an analog yet.

"What crews can test here" (the `tests` list of each site in `data/sites_meta.json`) also links every item to its source, with an exact quote.

**Targets (Moon and Mars):** every value in `data/targets.json` names its source, together with a note on what the value is. The brief gave reference values for four targets (Jezero, Gale, the Shackleton crater floor and Apollo 11); the other nine use our own sourced values. Sources include:
- NASA NSSDC Moon and Mars fact sheets; Perseverance MEDA; Curiosity REMS; Martínez et al. 2017 (Space Science Reviews); Phoenix (NASA PIA11003; Smith et al. 2009); Golombek et al. 2017 (landing-site albedo); the Apollo 17 heat-flow experiment (Keihm & Langseth 1973).
- **LRO Diviner polar temperature maps** (Williams et al. 2019, JGR Planets; Schorghofer & Williams 2020, PSJ) for Malapert, Mons Mouton, the Shackleton connecting ridge and the Shackleton crater floor. `scripts/extract_diviner.py` reads them into `data/diviner_malapert.json` (raw windows in `data/raw/diviner/`).
- **LRO LOLA illumination maps** (Mazarico et al. 2011, Icarus, doi 10.1016/j.icarus.2010.10.030; NASA PDS release 201608, 60 m and 120 m south-pole grids): the share of time in sunlight, the share of time with Earth above the horizon, and the permanently shadowed regions, at the three base-site pins. `scripts/extract_illumination.py` downloads them into a folder outside the project and writes `data/illumination.json` (5 × 5 windows, the PDS label text, the exact quotes and a README in `data/raw/illumination/`). Malapert: in sunlight 68.4 % of the time, Earth in view 90.7 %; Mons Mouton: 31.6 % and 61.4 %; Shackleton connecting ridge: 39.6 % and 33.0 % (the sunniest 60 m pixel of the whole map, 88.4 %, is on this ridge, 275 m from our pin). The Shackleton crater floor pin is never sunlit. These values are a model from LOLA heights, change fast within about 120 m, and are shown as facts, not scored.
- **Sun height** tilts: NASA Photojournal PIA13720 (Moon, 1.54°) and the NASA NSSDC Earth fact sheet (23.44°).
- **Shackleton crater floor regolith:** Thomson et al. 2012 (GRL, doi 10.1029/2012GL052119), the first orbital radar (LRO Mini-RF) measurements of Shackleton crater.
- **Moon base pins:** Malapert is the summit point used for the Diviner extraction; Mons Mouton is the centre of the mountain in the USGS Gazetteer of Planetary Nomenclature (Feature 16070); the Shackleton connecting ridge is the point of a NASA Langley study (NTRS 20240009936). NASA's Artemis III candidate regions: 13 regions in the NASA news release of 19 August 2022 (with "Connecting Ridge") and 9 regions in NTRS 20250011660 (with Malapert Massif and Mons Mouton). Notes and exact quotes: `data/raw/moonbase/`.
- **MRO Mars Climate Sounder** surface temperatures (Piqueux et al. 2024, dataset doi 10.7910/DVN/YCNFQL) and the **MGS TES** Lambert albedo map (NASA PDS) for Deuteronilus Mensae and Erebus Montes. The extraction scripts are in `data/raw/mars_ez_extract/`, and the research notes in `data/raw/mars_ez_research.json`.
- The **NASA 2015 Exploration Zone workshop** for human Mars landings: Bussey & Hoffman 2016 (NASA NTRS 20160001040) and the workshop abstracts 1011, 1020, 1033, 1034 and 1044. Ice evidence: Plaut et al. 2009, Bramson et al. 2015, Morgan et al. 2021.
- The USGS Gazetteer of Planetary Nomenclature, the NASA NSSDC Apollo landing coordinates, and NASA NTRS (Artemis III candidate landing regions; the Artemis landing slope rule, NTRS 20250009323). The Artemis landing regions near the south pole were identified for Artemis III; since NASA's 27 February 2026 update, Artemis III is a test flight in Earth orbit and the first landing is planned as Artemis IV (2028).

**Resources:** every tag in `data/resources.json` has a source link and an exact quote.

**Measured from orbit (Earth):**
- **Surface temperature:** NASA MODIS MOD21A2 (Terra) and MYD21A2 (Aqua) v061, 8-day, 1 km, 2003–2020 (NASA LP DAAC, read through Microsoft Planetary Computer without an account; doi [10.5067/MODIS/MOD21A2.061](https://doi.org/10.5067/MODIS/MOD21A2.061) and [10.5067/MODIS/MYD21A2.061](https://doi.org/10.5067/MODIS/MYD21A2.061)). Built by `scripts/fetch_lst.py` into `data/lst.json` (sites) and `data/screening_lst.json` (boxes); raw answers and every item id in `data/raw/lst/` (see `README.txt` there). Licence: CC0, per the [NASA Earthdata data use guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance) for NASA-led mission data.
- **Surface composition** (display only, never scored), built by `scripts/fetch_composition.py` into `data/composition.json` and `data/screening_composition.json` (raw extracts in `data/raw/composition/`): MODIS MOD21A2 v061 band-29 emissivity, 2018–2020 (same DOI and licence as above); Copernicus Sentinel-2 L2A from Earth Search on AWS Open Data, 2023–2024 scenes (doi 10.5270/S2_-742ikth; [Sentinel data legal notice](https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice): free, full and open; *Contains modified Copernicus Sentinel data 2023–2024*); ASTER L1T v003 thermal bands, 2000–2006 (NASA/METI/AIST/Japan Spacesystems and U.S./Japan ASTER Science Team; doi [10.5067/ASTER/AST_L1T.003](https://doi.org/10.5067/ASTER/AST_L1T.003); its [Earthdata catalog page](https://www.earthdata.nasa.gov/data/catalog/lpcloud-ast-l1t-003) says it is openly shared without restriction). The reading uses e29 cut values 0.88 and 0.95, which we set while looking at these same sites: an illustration, not an independent test.
- **Minerals (when present):** NASA EMIT L2B minerals and L2A masks (`data/emit.json`, `scripts/fetch_emit.py`; to download again, the script needs a NASA Earthdata Login token in `earthdata_token.txt`, a secret, see section 1), doi 10.5067/EMIT/EMITL2BMIN.001 / .002 and 10.5067/EMIT/EMITL2AMASK.002 / .003, CC0 per the same NASA guidance.

**Terrain:**
- Earth: Copernicus DEM GLO-90 (ESA) via the Open-Meteo elevation API (about 90 m).
- Moon: LRO LOLA via NASA Solar System Treks (about 237 m).
- Mars: MGS MOLA via NASA Solar System Treks (about 463 m).

See `data/terrain.json` for the exact services, resolutions, licences and method.

**Challenge resources used.** The challenge page lists these resources (Resources tab, read on 13 November 2026). What we use, and how:

| Challenge resource | Used? | How Analog Atlas uses it |
|---|---|---|
| NASA Earthdata Search | Yes, its catalog | NASA EMIT minerals are found through NASA CMR, the search service behind Earthdata Search, and downloaded with an Earthdata Login token (`scripts/fetch_emit.py`). MODIS land surface temperature (MOD21A2/MYD21A2, NASA LP DAAC, listed in Earthdata) is read from Microsoft Planetary Computer's copy of the same files (`scripts/fetch_lst.py`). |
| NASA Worldview | Its image service | Not the Worldview app itself: the Earth globe uses NASA GIBS, the image service Worldview runs on (Blue Marble and Black Marble). |
| NASA Planetary Data System (PDS) | Yes | LRO LROC NAC mosaics (photos of the three Moon base sites and the Shackleton crater floor), LRO LOLA illumination maps, LRO Diviner polar temperature maps, the MGS TES albedo map and the USGS Mars cave catalog (MGC3). |
| NASA Lunar Reconnaissance Orbiter (LRO) | Yes | LOLA elevation (Moon terrain and landing zone, through NASA Solar System Treks), LOLA illumination (Sun height and sunlight of the base sites), LROC photos, Diviner temperatures. LEND and Mini-RF data are not used. |
| NASA LRO Diviner Lunar Data | Yes | Diviner polar temperatures for Malapert, Mons Mouton, the Shackleton connecting ridge and the Shackleton crater floor (`scripts/extract_diviner.py`, `data/diviner_malapert.json`). |
| CSA RADARSAT Constellation Mission, RADARSAT-1 and the SAR Python tutorial | No | Not used. |
| ESA Copernicus Data Space Ecosystem | The same data, another route | Copernicus DEM GLO-90 (Earth terrain, through Open-Meteo and the AWS copy; its licence is on the Data Space site) and Sentinel-2 (ground colour, through Microsoft Planetary Computer). |
| ESA Open Science Catalog | No | Not used. |
| JAXA G-Portal | No | Not used. |

Climate on Earth comes from NASA POWER, which is not on the list.

---

## 5. Imagery, 3D data and credits

- **CesiumJS 1.145** (Apache 2.0), in `vendor/cesium/`. 3D data streamed from **Cesium ion**: Cesium World Terrain, Bing Maps Aerial, **Cesium Moon** (LOLA + Kaguya elevation, LROC imagery; NASA and USGS Astrogeology) and **Cesium Mars** (MOLA + HRSC elevation, Viking/CTX/HiRISE imagery; NASA and USGS Astrogeology). Credits are shown on screen, at the bottom right of the globe ("Data attribution").
- **NASA Blue Marble Next Generation** and **NASA Black Marble** (VIIRS 2016) via [NASA GIBS](https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api).
- **NASA Solar System Treks** mosaics: LRO WAC (NASA/GSFC/Arizona State University) and Viking MDIM 2.1 (NASA/JPL/USGS).
- **Offline globe pictures** in `textures/`: the credits, licences and processing for each file are in `data/assets.json`.
- **Photos and panoramas** in `panoramas/` (32 files, the same set as in `data/panoramas.json`, `data/assets.json` and `LICENSE`): each photo's photographer, licence, source page and any changes we made are in `data/panoramas.json` and `data/assets.json`, and are shown in the viewer and in **Method & data**. Several are CC BY or CC BY-SA, so keep the credit if you share them. The Mars and Moon ground panoramas are NASA/JPL-Caltech (with MSSS and ASU), NASA/JPL-Caltech/University of Arizona/Texas A&M University (Phoenix) and NASA Apollo photographs. The ten photos taken from orbit are public domain: the Malapert, Mons Mouton, Shackleton connecting ridge and Shackleton crater floor mosaics and the Mare Tranquillitatis pit image are LRO LROC NAC data products from the NASA PDS (NASA/GSFC/Arizona State University; the Mons Mouton mosaic also credits Intuitive Machines), the Deuteronilus Mensae, Erebus Montes and Arsia Mons skylight images are MRO HiRISE (NASA/JPL-Caltech/UArizona), and Mistastin crater and Qa' al-Jafr are Landsat 8 and Landsat 9 images (NASA Earth Observatory, U.S. Geological Survey). LROC's terms say PDS data products are public domain but the images on the LROC website are copyrighted, so we use no LROC website image.
- **Pitch material** in `pitch/`: the deck and the promo videos use some of these photos, cropped, darkened or colour-graded, with drawings added. Their credits are on the slides and on the video end card (see `LICENSE`).
- **Google Street View** (Haughton Crater, MDRS, SP Crater; listed in `data/streetview.json`): shown with Google's own keyless Maps embed. The imagery stays © Google and its contributors (the MDRS and SP Crater photospheres by Paolo Sartori and Ron Gray) and is never copied into this app. It needs internet.
- **Pannellum 2.5.7** (MIT) for the 360° viewer. **IBM Plex** fonts (SIL Open Font License 1.1), in `vendor/fonts/`.

`LICENSE` lists the licence of every third-party file.

---

## 6. ESP32 field kit

See **`firmware/WIRING.md`** for parts, wiring, a test for each sensor and the 24-hour test. See **`firmware/PROTOCOL.md`** for the serial format.

| Part | Measures | What the app does with it |
|---|---|---|
| BME280 | air temperature, humidity, pressure | Air temperature now is compared with the target's mean temperature. In the log it gives each day's mean air and daily range (compared with NASA POWER T2M and T2M_RANGE) and the kit's daily swing. Humidity is shown live; pressure is saved in the log. Neither is scored or compared with NASA POWER. |
| MLX90614 (infrared) | ground **surface** temperature, the same principle as Curiosity REMS and Perseverance MEDA | Shown live. The lowest value in the full log days is compared with the target's coldest ground temperature. |
| DS18B20 probe | soil temperature | Shown live. Used for the coldest ground only when the infrared sensor is missing in more than 1 of 10 log readings, and then labelled, because a probe reads warmer than the surface at night. |
| GUVA-S12SD | UV index (≈ volts ÷ 0.1) | Shown live only. UV is not a score factor and is not compared with NASA POWER. |
| 2 × BH1750 (up and down) | albedo = reflected × k ÷ incoming light | Albedo now (the median of the last minute) is compared with the target albedo. It needs daylight (more than 1,000 lux on the up sensor) and the Sun at least 20° above the horizon. |

- **Connect**: open the app in Chrome/Edge → **Field kit** → **Connect kit (USB)**.
- **Snapshot score**: the same formula with the kit's values: air temperature and albedo now; daily swing and coldest ground once a log with a full 24-hour day is loaded. The kit does not measure rain. It is labelled as a snapshot and kept separate from the 20-year NASA averages: **Live snapshot score** with a connected kit, **Simulated snapshot score** without one. The kit bar calls the DS18B20 reading **Soil probe**.
- **Albedo calibration k**: the up/down ratio of the two light sensors side by side, both facing up (WIRING.md, test 4). Type it in the kit panel (between 0.5 and 2). k = 1 means "not calibrated", and the panel says so.
- **24-hour log**: **Start logging (60 s)** in the kit panel (it sends `LOG START 60`: one reading per minute, stored on the kit) → power bank → **Read log from kit** (or **Import CSV file**). The app cuts the log into 24-hour windows counted from the first reading with a known time, not at midnight. A window counts as a full day when it has at least 20 hours of air readings with no gap over 1 hour; shorter windows are not compared. For each full day the app shows the kit's mean air and daily range next to NASA POWER for the same month at the kit location. **Save log as CSV** keeps the kit-clock time (`unix`) and any time the app had to estimate (`est_unix`) in separate columns.
- **Kit location**: Amman by default. Its NASA POWER cell is at 164 m, while the ground there is at 829 m (Copernicus DEM GLO-90), so the kit panel shows a ⚑ and warns that a working kit will read cooler than that cell. A location you set is sent to NASA POWER, rounded to about 1 km.
- **Simulation**: without a kit, values are simulated from NASA POWER monthly averages for the kit location and **always labelled "Simulated"**.
- **Still to do**: no real field log is stored in this project yet. Every kit number you see without a connected kit is simulated. One real 24-hour log at a Jordan site is the next step.

**Which link is most reliable at the event?** **USB** is the main link: no Wi-Fi, no setup, and the laptop keeps its internet for the 3D maps. If the sensors must be outside (sun, real ground), use the optional **ESP-NOW radio link**. A second ESP32 on USB acts as a base station and the field node runs on a power bank. ESP-NOW does not use the venue Wi-Fi, which often blocks devices from talking to each other. We do not recommend a Wi-Fi/WebSocket link at the event for that reason.

---

## 7. Jordan screening layer (Discover)

The 19 sites were chosen by hand first and then scored. **Discover Jordan** turns this around for one country: it covers Jordan with 10 km boxes, measures every box the way a site is measured, and scores it against the chosen target with the same formula (`scoreSite()` in `js/scoring.js`, unchanged). The best boxes are screening candidates: places the data says are worth a closer look, not analogs that anyone has checked in the field. Every box page carries the label **"Screening candidate — found by data, not field-checked"**. Boxes are never added to the site list and have no pins.

**Use it**
- Press **Discover Jordan** in the ranking panel. On the Moon or Mars this switches to Earth. The first press loads `data/screening_jordan.json` (about 700 KB), then the camera looks at Jordan.
- The list shows the **Top 10** for the target. Touching boxes with the same % are one row ("+N nearby"). Click a row, or a square on the globe, to open the box page; the camera looks at the box from 120 km. **Fly down** and **Stand here · 3D terrain** work as for a site, and **N / E / S / W** step to the next box.
- **All boxes · table and CSV** lists every box with its rank, %, main rock, flags and the reason when it is not listed.
- Climate or full match, strict data and **Tune factors** apply to the boxes too (the resources slider has no effect on them). Switching to the Moon or Mars, the tour and the Jordan corridor turn Discover off. While Discover is on, the globe pins only the five Jordan sites, labelled with their score without resources (for example "Harrat al-Shaam 88% · no resources" for Jezero), so the pins and the boxes use the same method.

**How a box is measured** (the numbers come from the built file)
- **Grid:** south-west corner 29.18° N, 34.95° E. A row is 0.0899320363724538° of latitude (10 km) and a column 0.10522795946422789° of longitude (10 km at 31.28° N): 47 rows × 42 columns = 1,974 boxes. A box is kept when its centre is inside Jordan's polygon in Natural Earth 1:10m v5.1.1: **886 boxes**, of which 97 cross the border. This boundary is Natural Earth's de facto, generalised one; it is indicative only and does not include the West Bank.
- **Climate:** NASA POWER regional climatology (API v2.10.1, community RE). Each box takes the cells that hold its centre, the rule the POWER point API uses for the sites: 43 MERRA-2 cells (0.5° × 0.625°) and 16 CERES SYN1deg cells (1° × 1°, sunlight and albedo). Check: the 5 Jordan sites and Amman run through the same steps give exactly `data/raw/power/*.json` (1,092 of 1,092 values, 6 of 6 cell elevations). NASA labels the regional product "January 2001 - December 2025", but its values are the 2001–2020 numbers; the build stops if they ever differ.
- **Terrain:** 441 elevation samples per box from 19 Copernicus DEM GLO-90 tiles (AWS open-data copy), picked with Open-Meteo's own pixel rule (only the index arithmetic is re-implemented; the Open-Meteo API is not called), and the statistics of `scripts/compute_terrain.py`. Check: the 5 Jordan sites give exactly the numbers in `data/terrain.json` (2,205 of 2,205 samples). 4 boxes are mostly water (Dead Sea) and get no terrain or landing score; 2 are part water.
- **Geology:** the IGME5000 map (BGR, 1:5 million), read at 25 points per box. `data/screening_rockmap_igme5000.json` gives each of the 30 map units found a rock type and a certainty. A low-certainty unit gives no rock type (shown on the box page, not scored); another unit under at least 5 of the 25 points adds its rock as a second rock, unless its certainty is low. Main rock: limestone/dolomite 590 boxes, basalt 141, sandstone 68, mudstone 22, granite 14, none 51. **The rock table still awaits a row-by-row review by a team member.**
- **Score:** boxes have no resources data, so that pillar is left out. Leaving a pillar out changes a score, so a box % can only be compared with a site % that also leaves resources out. Every box page shows the five Jordan sites scored that way, and the line above the Top 10 names the best of them.

**Top 10 rules.** A box is listed only when it has a score, is not mostly water, does not hold a hand-picked site (that site has its own page), has no ⚑ (a ⚑ means its NASA POWER cell is more than 400 m above or below the ground at the box centre), and has data for every pillar the target has, apart from resources (a missing pillar is left out of the average, which can raise a score). The order is: %, then fewer flags, then a larger share of the box in its main rock unit, then a smaller cell height gap, then the box id. Rows with equal percentages share a rank (`=1`); a box page also gives the box's own rank among all listed boxes. **Differences of 1–2 points are within the resolution of the data.** Boxes that are not listed stay in the table and on the globe (faded), except the 4 mostly-water boxes, which are not drawn. **Box colours are stretched for each target:** the grey-blue end is the 5th percentile of the listed boxes and the amber end is the best listed box (at least 4 points apart), and the legend shows those two numbers. Without this, most targets would paint almost every box the same colour (for Jezero, 740 of 882 scored boxes are 70 % or more; for Malapert almost all are 40–41 %). For Jezero (full match): 760 boxes are listed; not listed: 5 hold a site, 73 ⚑, 44 have no mapped rock, 4 are water (each box is counted once, under the first reason in the order water, site, ⚑, rock; 78 boxes carry a ⚑ in all).

**What it finds** (full analog match, default weights, computed by the app from the built file):

| Target | First row of the list (box, % × boxes in its cluster) | Best hand-picked Jordan site, resources left out |
|---|---|---|
| Jezero Crater | Box r32 c18, 89 % × 12, basalt, 25 km SW of Harrat al-Shaam (3 clusters tie at 89 %) | Harrat al-Shaam 88 % |
| Gale Crater | Box r13 c13, 87 % × 3, mudstone, 10 km NE of Qa' al-Jafr (3 clusters tie at 87 %) | Qa' al-Jafr 86 % |
| Deuteronilus Mensae | Box r35 c22, 62 % × 49, basalt, 26 km NE of Harrat al-Shaam (2 clusters tie at 62 %) | Harrat al-Shaam 61 % (Waqf as Suwwan also 61 %) |
| Erebus Montes | Box r38 c27, 75 % × 2, basalt, 83 km NE of Harrat al-Shaam (5 clusters tie at 75 %) | Harrat al-Shaam 73 % |
| Arsia Mons skylight | Box r28 c27, 87 % × 1, basalt, 84 km SE of Harrat al-Shaam | Harrat al-Shaam 85 % |
| Malapert Massif | Box r25 c7, 48 % × 1, limestone, 35 km NE of the Lisan Peninsula (3 pillars) | Wadi Rum 45 % |
| Mons Mouton | Box r5 c6, 74 % × 1, sandstone, 23 km NE of Wadi Rum (3 pillars) | Harrat al-Shaam, Waqf as Suwwan and the Lisan Peninsula 61 % |
| Shackleton connecting ridge | Box r6 c1, 73 % × 1, mudstone, 37 km NW of Wadi Rum (3 pillars) | Wadi Rum 56 % |
| Shackleton crater floor | Box r4 c3, 49 % × 6, granite, 10 km W of Wadi Rum | Harrat al-Shaam 38 % |
| Mare Tranquillitatis pit | Box r33 c28, 83 % × 2, basalt, 77 km E of Harrat al-Shaam (3 clusters tie at 83 %) | Harrat al-Shaam 81 % |
| Apollo 11 | Box r32 c16, 86 % × 7, basalt, 43 km W of Harrat al-Shaam (2 clusters tie at 86 %) | Harrat al-Shaam 86 % |
| Apollo 17 | Box r33 c18, 82 % × 4, basalt, 22 km W of Harrat al-Shaam (5 clusters tie at 82 %) | Harrat al-Shaam 80 % |
| Phoenix | Box r35 c22, 67 % × 17, basalt, 26 km NE of Harrat al-Shaam (4 clusters tie at 67 %) | Lisan Peninsula 77 % |

When clusters tie, the first row is decided by the tie-break order above, not by a higher score. The list in the app names a row by the nearest Atlas site; the box id is on the box page. **What the data shows:** for 8 of the 13 targets the best boxes score 0 to 2 points above the best hand-picked Jordan site, mostly on the Harrat basalt, and a 1–2 point lead means nothing at this resolution. For Malapert the best box is 3 points above Wadi Rum, but every listed Jordan box and every Jordan site stays at 48 % or less. So for these targets Discover confirms our hand-picked sites and shows that the Harrat basalt is a whole plain, not one point. The basalt boxes stand out mainly through the geology pillar: where basalt is the target's main rock, a basalt box gets 1 where a limestone box gets 0.5 (for Jezero the middle basalt box scores 88 %, the middle limestone/dolomite box 74 %). Four targets differ more. For the Moon base sites Mons Mouton and the Shackleton connecting ridge, single mountain boxes in south-west Jordan lead by 13 and 17 points: their median slopes (4.51° and 8.44°) are close to the targets' (4.66° and 8.56°), while the hand-picked Jordan sites are flat, except Wadi Rum. Their climate match stays under 25 % (Sun height in Jordan is far from the lunar pole's), so these two lists rest on slope and flat zone. For the Shackleton crater floor, the granite boxes next to Wadi Rum lead by 11 points only because granite is in the same rock family as the target's anorthosite (geology 0.5, a method choice); Wadi Rum's own main rock is sandstone. For Phoenix, the Lisan Peninsula stays 10 points ahead: its evaporite cannot be seen on a 1:5 million map. For the ice targets Deuteronilus Mensae and Phoenix, every mapped box scores 0 on geology, so their lists come down to climate, slope and flat zone, and the rock in the table is only the rock of that box.

**Files**
- `data/screening_jordan.json`: the one file the app loads (700,096 bytes): label, grid, boundary, climate cells, terrain and geology method, flag rules, the 5 Jordan controls, sources and the 886 boxes.
- `data/screening_rockmap_igme5000.json`: IGME5000 map unit → rock type, with certainty and reason.
- `data/raw/screening/` (2.3 MB): the Natural Earth polygon, the 17 NASA POWER answers with `manifest.json`, the DEM tile list and the gzipped 441 samples per box, the 25 map units per box, and one stage file per step. `data/raw/screening/README.txt` explains every file.
- Scripts: `screening_grid.py`, `screening_power.py`, `screening_terrain.py` (with `geotiff_lite.py`), `screening_geology.py` (with `shp_lite.py`) and `build_screening.py`.
- App code: `js/screening.js` (loading, scoring, Top 10), `js/globe/boxes.js` (the squares on the globe), `js/ui/discover.js` (the tab, list and table) and `js/ui/screening-detail.js` (the box page).

**Rebuild** (Python 3.12 standard library only; nothing to install), from this folder and in this order:

```
python -I scripts/screening_grid.py
python -I scripts/screening_power.py
python -I scripts/screening_terrain.py
python -I scripts/screening_geology.py
python -I scripts/build_screening.py
```

- The big downloads stay outside the project, in the cache folder `%LOCALAPPDATA%\analog-atlas\screening-cache` (elsewhere `~/.cache/analog-atlas/screening`; change it with `--cache-dir`). They are about 140 MB: Copernicus DEM tiles 88.0 MB, `IGME5000.zip` 47.5 MB and the Natural Earth zip 4.9 MB. If you already have copies, pass them with `--ne-zip`, `--dem-dir` and `--igme-zip` instead of downloading again.
- Every file is checked against its sha256. `--offline` uses the cache only. The NASA POWER requests run one at a time with pauses. No script calls the Open-Meteo API.
- `build_screening.py` never uses the network. It works out every number again from the raw files (28 checks: one record per box in every step, the 5 sites and Amman, every sha256, the coverage of Jordan, no missing value, no Open-Meteo URL, the size limit of 1 MB) and writes nothing if one fails. With everything cached the five steps take about one minute.

**Licences and required notices** (also shown on every box page, in **Method & data** and in the globe's data credits while Discover is on)
- **NASA POWER** (climate): NASA open data. Required citation: "The data was obtained from National Aeronautics and Space Administration (NASA) Langley Research Center's Prediction Of Worldwide Energy Resources (POWER) project funded through the NASA Earth Science Division." Service: POWER Climatology API v2.10.1, regional, accessed 2026/10/10. NASA asks to be told about published uses: larc-power-project@mail.nasa.gov. https://power.larc.nasa.gov/docs/referencing/
- **Copernicus DEM GLO-90-F** (terrain): free and open. Art. 6(b) notice: "Produced using Copernicus WorldDEM-90 (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved." Art. 6(c), because `samples_jordan.json.gz` passes on derived data: "The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM™-90". No official endorsement is implied. Licence: pages 19–21 of https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf · https://doi.org/10.5270/ESA-c5d3d65
- **IGME5000** (geology): GeoNutzV, any use with source notes and a note of modification. Credit: "IGME5000, © BGR, Hannover, 2005, https://doi.org/10.25928/igme-5000, modified: reclassified to Analog Atlas rock ids". https://sg.geodatenzentrum.de/web_public/gdz/lizenz/geonutzv.pdf
- **Natural Earth** 1:10m Admin 0 v5.1.1 (boundary): public domain; "Made with Natural Earth" is optional.
- **Open-Meteo pixel rule**: only the index arithmetic is re-implemented, no code is copied. Source: https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Dem/DownloadDem.swift
- **Macrostrat** (optional geology cross-check, `--crosscheck`, off by default): CC-BY 4.0.

**Tests.** http://localhost:8080/tests/ has a "Jordan screening" block of 9 tests: (1) every box scores exactly like a site built by hand from its record, for 13 targets × climate/full × strict off/on (46,072 comparisons); (2) the 5 Jordan controls equal `sites.json` and `terrain.json`, and score like the site without resources; (3) the grid covers Jordan on a 0.02° lattice, ids and bounds match the grid; (4) every box has its cells, raw files, 441 samples and map unit, every source a URL and a licence, and the label is exact; (5) no −999 or NaN, temperatures and slopes in range, known flags; (6) the ⚑ flag equals `cellGap()`; (7) the Top 10 rules, a fixed order and clusters; (8) box colours use the pin colour scale, stretched to each target's range; (9) the site ranking still has the 19 sites and no box.

---

## 8. Project folder

```
index.html          the app
config.example.js   template for config.js (your Cesium token)
config.js           your Cesium ion token (secret: leave it out when you share the folder)
earthdata_token.txt your NASA Earthdata Login token for scripts/fetch_emit.py (secret: never share it)
README.md           this file
JUDGE_GUIDE_AR.md   a short guide for the jury, in Arabic
css/app.css         theme "Mission Control"
js/                 app code (globe/, ui/, kit/, scoring.js, …); Discover Jordan: screening.js,
                    globe/boxes.js, ui/discover.js, ui/screening-detail.js; "Measured from orbit"
                    card: ui/orbit.js
data/               sites, targets, terrain, resources, photos, Street View, credits (JSON)
data/screening_jordan.json          the Discover Jordan boxes (built by scripts/build_screening.py)
data/screening_rockmap_igme5000.json  IGME5000 map unit → rock type, for the boxes
data/lst.json, data/screening_lst.json  MODIS ground surface temperature (sites, boxes)
data/composition.json, data/screening_composition.json  surface composition (display only)
data/emit.json      NASA EMIT minerals per site (when present)
data/screening_emit.json  NASA EMIT minerals per Discover box (1 km window at the box centre)
data/raw/           raw answers kept unchanged: NASA POWER, terrain samples, Diviner windows,
                    Mars landing-zone research and its extraction scripts
data/raw/screening/ raw and step files of Discover Jordan (boundary, NASA POWER regional answers,
                    DEM samples, map units), with README.txt
data/raw/lst/, data/raw/composition/  raw MODIS, Sentinel-2 and ASTER extracts, with README.txt
data/raw/removed/   files of the two removed sites (Mauna Kea, Al-Fahda cave), with README.txt
data/raw/moonbase/  research notes and exact quotes for the base sites Mons Mouton and the
                    Shackleton connecting ridge, with README.txt
data/illumination.json  LRO LOLA sunlight, Earth in view and permanent shadow at the base-site pins
data/raw/illumination/  5 x 5 LOLA windows, PDS label text and exact quotes, with README.txt
textures/           offline globe pictures
panoramas/          real photos and panoramas
vendor/             CesiumJS, Pannellum and IBM Plex (local copies, so the app starts without internet)
scripts/            Python scripts: fetch NASA POWER, build data, check scores, compute terrain,
                    extract Diviner temperatures and LOLA illumination (extract_illumination.py);
                    Discover Jordan: screening_grid.py,
                    screening_power.py, screening_terrain.py (+ geotiff_lite.py),
                    screening_geology.py (+ shp_lite.py), build_screening.py; measured from
                    orbit: fetch_lst.py (+ lst_common.py), fetch_composition.py (+ comp_*.py),
                    fetch_emit.py (+ emit_*.py)
tests/              browser tests (http://localhost:8080/tests/, 68 tests), including the Jordan
                    screening checks, the surface temperature switch, Sun height, the LOLA facts,
                    the regolith rule and the headline results
firmware/           ESP32 sketches: field_kit, base_station, tests per sensor, WIRING.md, PROTOCOL.md
                    (the build/ folders are local build output: leave them out when you share)
hardware/cosmic-cat/ the Cosmic Cat field-kit case to 3D-print: 5 STL parts in stl/, made by
                    make_cat.py, a 3D preview (preview.html) and BUILD.md (print and assembly steps)
design/             early design draft (theme previews); not the app and not kept up to date
pitch/              pitch material: the deck AnalogAtlas_CosmicCats.pptx (built from deck/slides.json
                    by deck/build_deck.ps1, with deck/preview/ pictures), the 30 s and 60 s videos
                    analog-atlas-pitch-promo30.webm and analog-atlas-pitch-promo60.webm (made by
                    promo.html), app screenshots in shots/, VIDEO_GUIDE.md and subtitles_en.srt
serve.py, start.bat local web server (start_offline.bat: the same, opened at ?no3d)
LICENSE             MIT for our code and data, plus the licence of every third-party file
```

The Al-Fahda cave was a Jordan candidate site. We removed it from the list: it lies in the Harrat al-Shaam basalt field, about 11 km from our Harrat point, and the Harrat site still describes the cave and carries its "shelter" tag (`data/raw/removed/README.txt`).

**Without internet:** the app, the data (including Discover Jordan), the photos and panoramas, the field kit and the offline globe pictures all work, with or without a token (the 3D button then says **3D failed**). For a demo without internet, open http://localhost:8080/?no3d, so the app does not wait for Cesium ion at all. Detailed 3D terrain, the NASA map tiles and Street View need internet. The big downloads for rebuilding Discover Jordan (about 140 MB) are kept outside this folder, in the cache folder of section 7.

---

## 9. Limits

- **Moon base sites.** Three are scored: Malapert Massif, Mons Mouton and the Shackleton connecting ridge. All three use only 3 of 5 pillars (their rock type, albedo and resources are not documented at the pins), and their climate match is 33 % or less at every Earth site (the three temperature factors score under 10 % everywhere), so their rankings come down to slope, the flat landing zone, rainfall and Sun height. For Malapert the landing pillar is 100 % for every site. For Mons Mouton and the ridge the top 10 sites lie within 8 points, so small gaps mean little; the ranking panel says this in one line under its title, and so does **Method & data** (The short answer). The Mons Mouton pin is the centre of a mountain 130 km across, not a NASA landing point. NASA's other Artemis III candidate regions (Haworth, Nobile Rim 1 and 2, de Gerlache Rim 2, Slater Plain, Peak near Cabeus B, Mons Mouton Plateau) are named in the data but not scored: we found no NASA or USGS point for these regions.
- **Base-site sunlight is shown, not scored.** The LOLA sunlit share, Earth visibility and distance to permanent shadow are shown as facts but not scored: every Earth site has the Sun up 50.5–51.7 % of the year (standard sunrise equation, top of the Sun at −0.833°, computed in `scripts/check_scores.py`), Earth visibility has no Earth counterpart, and shadow is not detected ice. Sun height is the scored stand-in, and it is a formula from latitude (flat horizon), not a measurement.
- **Artemis III regions on the globe:** the app can draw NASA's candidate landing regions from Cesium ion, but for our token Cesium ion answered "not found" (error 404) on 14 October 2026, so they are not drawn and the Moon view says so.
- **Mean temperature and daily swing** compare Earth air (T2M, T2M_RANGE) with surface or ground values on the Moon and at the Mars targets measured from orbit (for example LRO Diviner at the Moon base sites). For Jezero the coldest value is also air (MEDA, a typical pre-dawn air value), not ground.
- **Terrain and landing zone** both come from the same 500 m slope grid. For the flat targets (largest flat zone 9.5 km: Jezero, Gale, Deuteronilus Mensae, Erebus Montes, the Arsia Mons skylight, the Mare Tranquillitatis pit, Apollo 11 and Phoenix), 10 of the 18 sites with terrain data get 100 % on landing and at least 80 % on terrain, so flat ground counts in two of the five pillars. This can decide a result: with the landing weight set to 0 in Tune factors, the top of Jezero's list becomes Craters of the Moon (64 %), then Harrat al-Shaam and Haughton (both 63 %). The Stability check shows how often each site stays in the top 3 when the weights change.
- **McMurdo Dry Valleys:** the 10 km terrain box around our point is mostly steep ground (median slope 14.16°, largest flat zone 2.0 km). Against the flat Mars ice targets (Deuteronilus Mensae, Erebus Montes, Phoenix) its terrain match is 0 % and its landing match 21 %, so it ranks 18th of 19 for all three (it also has no ice tag since 26 October, see Resources in section 3). **Method & data** computes these ranks live. These two pillars describe the steep ground in the box, not the flat valley floors, and we have not measured a point on a valley floor. The site page says this.
- **Resource tags and the place rule:** the place rule (section 3) was applied to every regolith tag, to the McMurdo Dry Valleys tags (ice tag removed on 26 October 2026) and to the Tso Kar tags (kept: on 26 October their quotes were replaced by quotes about Tso Kar Lake itself from the same paper; the old salts quote came from a test at Khardung La). The Atacama salts quote names perchlorate deposits 'in the Atacama desert' as a whole, not at our point; we have not yet found a source at our point, so this tag is weak (without it, Atacama would score 37 % for Jezero, 46 % for Gale and 48 % for Phoenix, and no top 3 would change). The other ice, shelter and salts tags have a source with an exact quote, but we have not yet re-checked each one for distance from our point.
- **Rock-type sources:** the main rock of all 19 sites has a source. MDRS (clay-rich mudstone and channel sandstone) quotes Clarke & Stoker 2011 (NASA NTRS 20110023235), and SP Crater (basalt) quotes the USGS field guide to S P Mountain (Open-File Report 2021-1072), which also notes the eruptions as basaltic; some other descriptions call the lava basaltic andesite. The McMurdo Dry Valleys granite (and sandstone) quote the soil record of site 415 at Bull Pass, about 3 km from our point (glacial till of granite, sandstone and dolerite). The Dry Valleys 'ice' rock type lost its source on 3 November 2026 under the place rule (the paper was about Beacon Valley, about 50 km away), as its ice resource tag did on 26 October. At 10 sites at least one of the other rock types (used for the 0.5 match level) has no source yet: Wadi Rum, Atacama, Death Valley, McMurdo Dry Valleys (basalt, ice), Rio Tinto, Waqf as Suwwan, Qa' al-Jafr, Nördlinger Ries, Mistastin and Dalangtan playa (`geology.unsourced`).
- **Surface temperature (MODIS)** is clear-sky only and sampled at four fixed times: its mean is about 2–3 K warmer than a 24 h mean, its swing catches about 88 % of the daily range, and its coldest value is an 8-day mean (single nights get colder). Polar sites have no mean or swing and a water pixel (Mistastin) has no temperature factors, so in surface mode their climate match uses fewer factors, which can raise it. The reference rankings use air.
- **Surface composition** (MODIS e29, Sentinel-2, ASTER, EMIT) sees only the top millimetres of the ground and is display only. Its reading cut values were chosen while looking at the same 19 sites, so the readings and the Jordan checks illustrate rather than test. The ASTER silica index is not corrected for the air: relative only.
- **Shackleton crater floor**: the pin is a permanently shadowed crater floor, but the brief's reference values are general figures (sunlit polar rims for the mean temperature, shadowed craters in general for the coldest ground, the whole Moon for albedo). Strict data uses only the Diviner values measured at the pin. Its ice tag rests on Zuber et al. 2012, which says surface ice on the floor is possible, not proven. Its regolith tag rests on Thomson et al. 2012 (radar of Shackleton crater itself; the quote is about the crater wall slopes, which the place rule accepts because the pin is inside that crater, but it is not a measurement on the floor).
- **Data-quality flag ⚑ for targets:** a target gets a ⚑ when fewer than 3 of its 5 factors are measured at the site itself (rain counts, because it is physically zero). Today this applies to Apollo 11, whose other values are generic Moon figures or not measured.
- **Data-quality flag ⚑ for Earth sites:** NASA POWER cells are about 50 km wide, and small places (a crater floor, a cave, the Dead Sea shore) have their own microclimate. When a site's cell is more than 400 m higher or lower than the real ground (about 2.6 °C), the site gets a ⚑ in the ranking and a warning, and stays in the ranking. Today: Death Valley (904 m), Tso Kar (521 m), the Lisan Peninsula at the Dead Sea (511 m) and the McMurdo Dry Valleys (435 m). The NASA POWER albedo of the Holuhraun and Dry Valleys cells is high for bare rock (0.63 and 0.56 for the year), probably because the cells include ice or snow.
- POWER "maximum/minimum" values are the extreme hourly values of 2001–2020, while the other values are averages. Target values come from missions with different instruments and durations.
- Some reference target values are Moon-wide or Mars-wide averages or midpoints. They are labelled, and **Strict data** replaces them with site measurements or leaves them out.
- **Geology** match levels (1, 0.5 or 0) and the rock families are our method choice, not a measurement. The 10° slope scale is also a method choice. Resource tags often describe a whole region rather than the exact pin.
- **Caves count only for the two cave targets.** The Mare Tranquillitatis pit and the Arsia Mons skylight have a "shelter" tag, so lava tubes (Harrat al-Shaam, Craters of the Moon) raise the resources pillar for those two targets only. Their climate values are the measured ground around each opening; nobody has measured inside these caves (the ~17 °C inside the Moon cave is a model and is shown only as a fact).
- Terrain boxes that are mostly lake get no terrain or landing-zone score. Mistastin's crater centre is a lake, so its box was moved on 3 November 2026 to the dry west side of the crater (centre 55.88° N, 63.5° W, the Discovery Hill side; `coordSource` in `data/terrain.json`); the pin, the NASA POWER cell and the MODIS pixel stay at the crater centre. Since then Mistastin has a score for every target (for example #8 of 19 for Mons Mouton, 62 %, and #9 for the ridge, 48 %). Salt flats and playas (Qa' al-Jafr, Death Valley, the Dead Sea) are flat ground and are scored, with a note.
- Slope depends on grid size; we use one 500 m grid for all worlds, but the elevation data underneath is sharper on Earth than on the Moon and Mars. Our 1 km slope baseline is coarser than the Artemis 100 m rule.
- The Earth sites come from published analog research plus our own proposals (marked Candidate). They were chosen first and then scored, so this is not a search of the whole Earth. **Discover Jordan** scores every box by data, but only inside Jordan, and for most targets its best boxes are on the same basalt plain as a hand-picked site, or close to one, and score within 2 points of it (section 7).
- **Discover Jordan boxes are screening candidates**, found by data and not field-checked. Not assessed: access, protected or military areas, border zones and landmines. The elevation model is a surface model, so buildings raise the slopes in towns. "Found by data" still rests on our choices: the grid, the weights, the R values and the listing rules.
- **Discover Jordan has no resources data**, so it cannot look for shelter (lava tubes), ice or salts, and a box % is comparable only with a site % that also leaves resources out.
- **Discover Jordan geology is coarse.** At 1:5 million the map gives only limestone/dolomite, basalt, sandstone, mudstone and granite as a box's main rock. It cannot show evaporite (Lisan), impact breccia (Waqf as Suwwan), small playas (Azraq), ice, anorthosite or acid sulfates, so analogs that depend on them cannot be discovered. 46 boxes have a low-certainty map unit and get no rock type. The rock table still awaits a row-by-row review.
- **Discover Jordan climate is blocky.** A typical MERRA-2 cell holds 24 boxes (the median), so neighbouring boxes often have the same climate and seams follow the cell edges. 78 boxes have a ⚑, 110 take their climate from a cell that lies mostly outside Jordan, and 382 cross a cell edge. Downscaling with a lapse rate would be a model, not data, so we did not do it.
- **Discover Jordan terrain separates little:** 725 of the 886 boxes have every slope under 10°.
- **The Jordan boundary** is Natural Earth's indicative, generalised one; 97 boxes cross it. The NASA POWER regional product is labelled 2001–2025, but its values are the 2001–2020 numbers (checked, 1,092 of 1,092); `fetch_power.py --refresh` today would put that label into the site files too.
- **Regolith and resources:** no Earth site has a regolith tag now, because we found no source that documents an Earth site's own material as a simulant or building material (SP Crater's simulant comes from Merriam Crater, about 40 km away). The base sites have no resource tag at all: the LOLA maps show where ice could stay cold, not where ice was found.
- **Imagery:** 7 of the 14 panoramas are partial (120–170° wide), and their button gives the width. Every place has a real photo, but for 10 of the 32 places it is a photo taken from orbit, looking straight down, not a ground view (the button says "Photo" and the viewer says "taken from orbit"). The Shackleton connecting ridge photo (1400 x 1400 pixels, 16 m per pixel, 22.4 km across) is about half in shadow; the dark area is real shadow, not missing data. Street View needs internet.
- **Field kit:** the live score is a single moment and cannot be compared one-to-one with 20-year averages. No real field log has been recorded yet; all kit data so far is simulated.
- Lighting is a display choice (the far view puts the Sun at 13:00 local time over Jordan; Earth close-ups show the satellite photos as taken; Moon and Mars close-ups use a fixed Sun). The darker square and the seam around the lunar south pole are in the Cesium Moon imagery, not added by the app.

---

## 10. Use of Super Intelligence (SI)

Space Apps 2026 uses the term Super Intelligence (SI) for what is often called AI. We used one SI tool: **Claude (Anthropic)**, a large language model.

- **Code (SI-assisted):** the app, the scripts, the tests and the field-kit firmware were written with help from Claude and reviewed and run by the team. The page `index.html` says this in its metadata (`<meta name="si-use">`).
- **Research and text (SI-assisted):** Claude helped find and read sources and draft this README and the guides. Every source is cited, so it can be checked.
- **Data: not SI-generated.** Every number comes from the cited data files and sources (NASA, ESA and published papers), not from the SI. A value with no source shows "not measured".
- **Images and video:** the photos are real photos with their licences (`data/assets.json`). The drawings, the pixel cat, the slide backgrounds and the music of the promo video were made by code written with Claude, so the promo video and the slides carry a visible "SI-assisted" mark.
- **No NASA logos** or other agency branding are used in anything we made.

## 11. Licence

Code: **MIT** (see `LICENSE`). Third-party libraries, images and data keep their own licences (see sections 4, 5 and 7, `LICENSE`, `data/assets.json` and `data/panoramas.json`).
