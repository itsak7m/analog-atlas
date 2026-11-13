# Analog Atlas – presenter script (live demo)

Team Cosmic Cats · NASA Space Apps 2026 · Amman. About 4 minutes, four speakers. The lines in quotes are what you say (English); the notes in *italics* are for you.

**Roles**

| Role | Field | Speaks in |
|---|---|---|
| **Human side** (main speaker) | psychology | steps 1, 6, 7 |
| **Demo driver** (tech lead) | mechatronics | steps 2–4, 8; drives the laptop the whole time |
| **Science** | physics | step 5 |
| **Hardware** | robotics | step 9 |

---

## A. Before you go on stage (so nothing stops or lags)

1. **Do not rely on the venue Wi-Fi.** Use your phone hotspot if you can. If the internet is weak, use **`start_offline.bat`**: everything works except the 3D terrain.
2. **Start 15 minutes early:** double-click `start.bat`, open http://localhost:8080 in Chrome.
3. **Warm up the places you will show:** press **▶ Tour** once and let it run to the end, then open **Jezero → Base plan** and **Malapert → Base plan** once. The map tiles are then in the browser's cache, so on stage they appear at once.
4. Check http://localhost:8080/tests/ says **All 72 tests passed**.
5. Laptop on the charger, notifications off, sleep off, screen zoom 100 %, the browser in full screen (F11).
6. **Backup:** the 30 s video `pitch/analog-atlas-pitch-promo30.webm` and the deck `pitch/AnalogAtlas_CosmicCats.pptx` open in another window. If anything freezes, switch to them and keep talking.
7. Never show `config.js`, `earthdata_token.txt` or `anthropic_key.txt` on screen.

---

## B. The demo, step by step (about 4 minutes)

**1. Hook (Human side, 30 s)** *(globe of Earth)*
"Before anyone lives on the Moon or Mars, NASA tests everything here on Earth, in places that behave like them. They are called analogs. But which place on Earth is the best one? We are Cosmic Cats from Amman, and we built Analog Atlas to answer that with real NASA data."

**2. Pick a target: Jezero Crater (Demo driver, 40 s)**
*Compare with → Jezero Crater. Point at the ranking.*
"We compare 19 Earth sites with 13 Moon and Mars targets on five pillars: climate, terrain, landing zone, rock type and resources. For Jezero, where Perseverance drives, the best Earth twin is Harrat al-Shaam, the black basalt desert in Jordan, at 71 percent."

**3. Fly down to Harrat al-Shaam (Demo driver, 20 s)**
*Click Harrat al-Shaam → Fly down.*
"Every number has a source. When a value is not measured, the app says 'not measured'. We never invent a number."

**4. Base plan at Harrat al-Shaam (Demo driver, 30 s)**
*Click **Base plan**. The 3D test base appears on the real satellite image.*
"This is our idea for the future: a test base on the best twin. A habitat, a hydroponic greenhouse, a communication room and solar power. The app says which pillars match well here, so this is where to practise for Jezero."

**5. Why Mars is hard (Science, 40 s)**
*Exit base → Compare with Jezero → the Mars chip ⓘ → Base plan → Plan details.*
"On Mars the air is 95 percent carbon dioxide and about 0.6 percent of Earth's pressure. It is about minus 60 degrees on average, and the sunlight is less than half of ours. The soil holds toxic perchlorate, measured by Phoenix. And some things Earth cannot test at all: low gravity, vacuum and radiation. We do not score them, because every analog breaks there."

**6. The greenhouse (Human side, 25 s)**
*Scroll to Hydroponic greenhouse; move the potato slider.*
"So we grow food in water, not soil: hydroponics. Potato for energy, soybean for protein, lettuce for vitamins. NASA grew all three without soil. The numbers are from USDA, and you can build a daily plate."

**7. The communication room and the crew's mind (Human side, 30 s)**
*Scroll to Communication room → type a message → Send.*
"NASA lists isolation as one of the five hazards of human spaceflight. A crew far from home needs their families. But today a signal to Mars takes about 11 minutes each way, computed live from JPL planet positions, so families send video messages, not calls. And NASA already tests isolation on Earth, in its HERA analog habitat."

**8. Ask Atlas (Demo driver, 20 s)**
*Close → **? Ask** → click 'Is potato a good crop for Mars?'*
"You can also ask the atlas in plain words. It only uses the app's facts, and it always says whether the answer came from SI or from fixed rules."

**9. Field kit and close (Hardware, 30 s)**
*Hold up the kit or point at the field kit bar.*
"Our ESP32 field kit measures the ground on site: air, ground temperature, soil, albedo and UV. It sends the readings live to the app, so a team at the site can compare where they stand with Mars. Next: a long field log in Jordan. Analog Atlas: find the Moon and Mars on Earth. Thank you!"

---

## C. Talking points: future features (for the mic)

- **Base plan:** we found the place; next we plan what to test there. Problem → solution, every number with a source.
- **Hydroponic greenhouse:** potato (carbohydrates), soybean (protein and fat), lettuce (vitamins); grown without soil by NASA (Biomass Production Chamber, 1996; lettuce eaten on the space station in 2015).
- **Communication room:** Moon 1.2–1.4 s (live calls work); Mars 3–22 min each way (video messages); about two weeks without contact at each solar conjunction.
- **Crew mind:** isolation and confinement are one of NASA's five hazards; NASA studies them on Earth in HERA. Analog sites can test the crew, not only the machines.
- **Super Intelligence (SI):** Ask Atlas explains the results in plain words; it only uses the app's facts, so it cannot invent numbers.
- **Field kit:** real measurements on the ground, compared with NASA data.

---

## D. Likely questions from the judges (short, honest answers)

- **"Is the base real?"** "No, it is a concept for future work. The layout is ours; the facts and numbers under it are sourced."
- **"Why is potato a good crop?"** "It gives carbohydrates and vitamin C, and NASA grew it hydroponically. The nutrients come from USDA."
- **"How do you know the delay to Mars?"** "We compute the distance from JPL's planet positions and divide by the speed of light. It matches NASA's 2023 conjunction dates."
- **"What can Earth not test?"** "Low gravity, vacuum or the thin Martian air, and radiation. We do not score them; every analog breaks there."
- **"How does isolation affect a crew?"** "NASA lists it as one of five hazards: small crews far from Earth in a small space react to it, so crews are chosen, trained and supported as a team. That is why our base has a communication room and private space."
- **"Did you use AI?"** "Yes, Claude helped write the code and research. The data is not SI-generated; images made by code carry an SI-assisted mark."
- **"Is the field kit data real?"** Say exactly what you measured: how many hours, where, and which sensors. If a reading is simulated, say so.
