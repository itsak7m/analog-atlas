# Analog Atlas · presenter script

Team Cosmic Cats · NASA Space Apps Challenge 2026 · Amman

About 6 minutes of talk, then questions. Four speakers. **Ameer** drives the laptop the whole time; the others stand near the screen. No video on stage: the app runs live. If the app fails, play the 30-second video and keep talking from this script.

**Before you start:** open https://itsak7m.github.io/analog-atlas/ (or `start.bat`, then http://localhost:8080) in Chrome or Edge, on a phone hotspot if the venue Wi-Fi is slow. Run **Story** once and open the **Moon base ⭐** once, so the pictures are loaded. Then reload the page. Story keys: **Space** pause, **→** next, **Esc** stop.

Every number below is what the app shows with its default settings. Say "about" if you are not sure of a number; never guess one.

| Time | Who | Do (Ameer) | Say |
|---|---|---|---|
| 0:00–0:30 | **Moath** | Home screen. | "Before anyone lives on the Moon or Mars, they practise on Earth. NASA already does this: crews live for weeks in closed habitats on Earth to learn how isolation affects them. Our question: where on Earth is the best place to practise, and could it be here in Jordan?" |
| 0:30–1:45 | **Ameer**, Moath | Press **▶ Story** (top bar). Press **Space** to pause on a scene if someone is still talking. | Let the Story run. On the Jezero scene, Ameer: "This match is computed live from NASA data: Harrat al-Shaam, Jordan's black basalt desert, is the closest of our 19 Earth sites to Jezero Crater, where Perseverance drives." On the message scene, Moath: "From Mars a message takes minutes to arrive, so families send recorded videos, not calls." Press **Esc** at the end. Story leaves Harrat al-Shaam open: point at the short table (**The match in short**). Ameer: "Four pillars side by side, one match each. Every number and its source is one press away, under *Full data and sources*." |
| 1:45–3:00 | **Mohammad** | Open **Method & data** and stay on **In short** (do not open the full method), then close it. Press **See the Shackleton terrain comparison** (under the Moon base button); the panel shows the slope comparison. | "How do we compare? Four pillars: climate, ground slope, rock type and the resources a base needs. Every value comes from NASA or other open data, and if a value was not measured, the app says *not measured*, it does not invent one. We compared 19 Earth sites with 13 Moon and Mars targets, and we split all of Jordan into 886 areas of 10 km. One area 37 km northwest of Wadi Rum has a median slope of 8.44 degrees; the Shackleton connecting ridge on the Moon has 8.56. That is a satellite result. Nobody has checked it on the ground yet." |
| 3:00–4:15 | **Ameer**, then **Moath** | Press **Moon base** (top left). Show the ⭐ next to Mare Tranquillitatis pit in the target name. Show the outside, then **Enter habitat**, then **View on Moon**. Then **Plan details** and scroll to **Crew wellbeing**. | Ameer: "We put the base only where Jordan matches best: on each world, the target with the strongest Jordan match gets the star. On the Moon that is a lava-tube pit in Mare Tranquillitatis, and its closest Earth twin is Harrat al-Shaam in Jordan, 71 percent. On Mars it is a cave skylight on Arsia Mons, again Harrat al-Shaam, 84 percent. This is a concept base, not an engineering design: two homes, a greenhouse, a communication room and solar power, joined by pressurised tunnels so nobody needs a spacesuit to go from room to room. The same base, in the same room, on Earth and on the Moon." Moath: "The hardest part is the people. On the space station astronauts sleep just over 6 hours a night. In the 520-day Mars-500 simulation the crew moved less and less. So the base has private bunks, a fixed routine, a greenhouse, because working with plants may help the mind, and a room to talk to family." |
| 4:15–5:15 | **Abd** | Scroll to **Lessons from past missions**. | "Why rehearse on Earth? In 1999 NASA lost the Mars Climate Orbiter because one team used English units and another used metric. In 1997, when Mars Pathfinder kept resetting on Mars, engineers made the same fault happen on a copy on Earth, found the bug and sent the fix by radio. Testing on Earth is how missions survive. Our next step is a real field day at the Wadi Rum area and at Harrat al-Shaam, to check on the ground what the satellites tell us." |
| 5:15–5:45 | **Moath** | Back to the globe. | "Analog Atlas finds where on Earth to practise for the Moon and Mars, with real data, honest limits, and the human side included. Thank you." |

## Questions: who answers

**Mohammad (science and numbers)**
- *"Why is the base at the Tranquillitatis pit and not at the south pole?"* On each world we star the target with the strongest Jordan match (default screening score), and only that pair gets the base: Moon, Tranquillitatis pit with Harrat al-Shaam 71 %; Mars, Arsia Mons skylight with Harrat al-Shaam 84 %. A pit is a natural shelter from radiation and temperature swings. The south-pole sites stay in the app with their own rankings.
- *"For Arsia, Craters of the Moon in the USA is 85 %. Why star Harrat al-Shaam?"* Our goal is a rehearsal site in Jordan, so the star picks the best Jordan match. Craters of the Moon is first in the app's ranking, one point ahead, and one point is within the resolution of the data.
- *"Your old slides said 71 % for Jezero, the app says 66 %."* The app opens with a stricter setting: it only uses target values measured at the site itself and compares temperature measured the same way. The older **Reference settings** are still in **Tune factors** and give 71 %. Harrat al-Shaam is first with both.
- *"Is 66 % a strong match?"* It is a screening score for a shortlist, not a proof. For Jezero the top 3 are within 2 points, so we say "one of the closest", and a field check decides.
- *"Why is the flat landing zone not scored?"* It comes from the same slope map as the terrain pillar, so it would count slope twice. It is shown as context.
- *"What can't you test on Earth?"* Low gravity, vacuum or the thin Martian air, and space radiation. The app says this in the base plan.
- *"How long is the Mars delay?"* About 3 to 22 minutes each way, depending on where the planets are. The app computes today's value.

**Moath (human side)**
- *"Is the plant effect proven?"* No. It comes from a review of research (Odeh and Guy, 2017), so we say "may help".
- *"How does the base help the crew?"* Private space, a fixed routine with light and exercise, the greenhouse, and family contact from the communication room. The sources are in **Plan details**.

**Abd (engineering)**
- *"Did you build hardware?"* We planned an ESP32 field kit but cancelled it on 14 November for lack of time. No number in the app comes from it.
- *"Why tunnels?"* So the crew moves between rooms without suits, and a fault in one room can be closed off from the others.

**Ameer (the app)**
- *"Where does the data come from?"* NASA POWER, LRO, MODIS, the Copernicus DEM and the sources listed in **Method & data**. On any place page, open **Full data & sources**: each value links to its source.
- *"Did you use SI?"* Yes, for coding help and the base concept picture, and it is marked SI-assisted. The data and calculations use cited sources.

## If something fails

- **3D or globe is slow:** reload with `?no3d` at the end of the address. The data, Story and base still work.
- **Story stops or freezes:** press **Esc** and go straight to **Moon base**. Keep talking from the table above.
- **Nothing works:** play the 30-second video from the submission page and do the talk without the app.
