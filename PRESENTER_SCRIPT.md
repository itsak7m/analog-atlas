# Analog Atlas – presenter script (live demo)

Team Cosmic Cats · NASA Space Apps 2026 · Amman. About 4 minutes. The lines in quotes are what you say (English); the notes in *italics* are for you.

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

## B. The demo, step by step

**1. Open (globe of Earth)**
"Hi, we are Cosmic Cats from Amman. To go to the Moon and Mars, NASA first tests everything on Earth, in places called analogs. Analog Atlas finds those places with real NASA data, not guesses."

**2. Pick a target: Jezero Crater (Mars)**
*Compare with → Jezero Crater. Point at the ranking.*
"We compare 19 Earth sites with 13 Moon and Mars targets on five pillars: climate, terrain, landing zone, rock type and resources. For Jezero, where Perseverance drives, the best Earth twin is Harrat al-Shaam, the black basalt desert in Jordan, at 71 percent."

**3. Fly down to Harrat al-Shaam**
*Click Harrat al-Shaam → Fly down.*
"Every number has a source. When a value is not measured, the app says 'not measured'. We never invent a number."

**4. Base plan at Harrat al-Shaam (the future)**
*Click **Base plan**. The 3D test base appears on the real satellite image.*
"This is our idea for the future: a test base on the best twin. A habitat, a hydroponic greenhouse, a communication room and solar power. The app says which pillars match well here, so this is where to practise for Jezero, and it says clearly what Earth cannot test: low gravity, vacuum and radiation."

**5. Go to Mars itself**
*Exit base → Compare with Jezero → the Mars chip ⓘ → Base plan.*
"And this is the same base on Mars, at Jezero. Plan details shows each problem with its measured value and the part of the base that solves it."

**6. The greenhouse**
*Plan details → scroll to Hydroponic greenhouse; move the potato slider.*
"Martian soil has toxic perchlorate, measured by Phoenix, so we grow food in water: hydroponics. Potato for energy, soybean for protein, lettuce for vitamins. NASA grew all three without soil. The numbers are from USDA, and you can build a daily plate."

**7. The communication room: talking to family**
*Scroll to Communication room → type a message → Send.*
"People on Mars want to talk to their families. But today a signal to Mars takes about 11 minutes each way; we compute it live from JPL planet positions. So families send video messages, not calls. Every two years the Sun blocks the signal for about two weeks; the app shows when the next one is."

**8. Ask Atlas (SI)**
*Close → **? Ask** → click 'Is potato a good crop for Mars?'*
"You can also ask the atlas in plain words. With a key, Claude answers using only the app's facts; without internet it answers from our data with fixed rules, and it always says which."

**9. Field kit and close**
*Point at the field kit bar.*
"Our ESP32 field kit measures the ground on site and compares it with the target. Next: a real 24-hour log in Jordan. Analog Atlas: find the Moon and Mars on Earth. Thank you!"

---

## C. Talking points: future features (for the mic)

- **Base plan:** we found the place; next we plan what to test there. Problem → solution, every number with a source.
- **Hydroponic greenhouse:** potato (carbohydrates), soybean (protein and fat), lettuce (vitamins); grown without soil by NASA (Biomass Production Chamber, 1996; lettuce eaten on the space station in 2015).
- **Communication room:** Moon 1.2–1.4 s (live calls work); Mars 3–22 min each way (video messages); about two weeks without contact at each solar conjunction.
- **Super Intelligence (SI):** Ask Atlas explains the results in plain words; it only uses the app's facts, so it cannot invent numbers.
- **Field kit:** real measurements on the ground, compared with NASA data.

---

## D. Likely questions from the judges (short, honest answers)

- **"Is the base real?"** "No, it is a concept for future work. The layout is ours; the facts and numbers under it are sourced."
- **"Why is potato a good crop?"** "It gives carbohydrates and vitamin C, and NASA grew it hydroponically. The nutrients come from USDA."
- **"How do you know the delay to Mars?"** "We compute the distance from JPL's planet positions and divide by the speed of light. It matches NASA's 2023 conjunction dates."
- **"What can Earth not test?"** "Low gravity, vacuum or the thin Martian air, and radiation. We do not score them; every analog breaks there."
- **"Did you use AI?"** "Yes, Claude helped write the code and research. The data is not SI-generated; images made by code carry an SI-assisted mark."
- **"Is the field kit data real?"** "Not yet: today it is simulated and labelled so. The next step is a real 24-hour log."
