# Analog Atlas live demo

Team Cosmic Cats · NASA Space Apps Challenge · Amman

Open Analog Atlas in Chrome or Edge. For a local rehearsal, run `start.bat`, open `http://localhost:8080`, and check `http://localhost:8080/tests/`. Rehearse both world swaps once. `?no3d` uses the cached globe imagery and still renders the 3D base when WebGL is available.

| Time | Do | Say |
|---|---|---|
| 0:00–0:15 | Open the Atlas. | “If you needed to rehearse a lunar rover traverse in Jordan, where would you start? We screened 886 areas to find a place worth testing.” |
| 0:15–0:40 | Open **See the Shackleton terrain comparison**, then **Compare slope statistics and sources**. | “A candidate northwest of Wadi Rum and the Shackleton connecting ridge have median slopes of 8.44 and 8.56 degrees at the same one-kilometre baseline. At two kilometres they're still close. Look at the upper tail, though. The Jordan box has steeper terrain on the finer baseline.” |
| 0:40–1:05 | Press **Explore base in 3D**, enter the habitat, then press **View on Moon**. | “The same concept habitat follows you between the two sites. We keep the camera and room so you can compare the setting at the same scale.” |
| 1:05–1:30 | Go back outside. Switch to **View on Earth**, then exit to the rover case. | “We would survey a real slope and a flat track with similar soil. Then we would repeat rover passes with the same payload and speed, record voltage and current, and compare wheel turns with independently measured distance.” |
| 1:30–1:50 | Close the detail panel. Choose **Mars base**, then **View on Mars**. | “The Mars route starts in Harrat al-Shaam and compares it with Jezero. The map links to the individual factors and their sources.” |
| 1:50–2:00 | Point to **Method & data**. | “Use the Atlas to shortlist a place and design the first field test. The downloadable data make the decision reproducible.” |

## Questions during judging

- **Can you land there?** The comparison uses terrain slopes averaged over kilometre-scale baselines. It helps plan a mobility rehearsal, and landing hazards need site-specific data at finer scales.
- **Do the two regions have similar temperature and gravity?** Local lunar gravity, regolith, temperature and the light cycle need separate test facilities. The proposed Jordan rehearsal addresses a terrain property.
- **Have you tested the box in the field?** This case is a satellite-based screening result. Field access, ground roughness and traction are pending. Show the rover protocol and any labelled bench data the team collects.
- **How do you calculate the energy and slip?** For a drive, integrate voltage × current over time and divide by independently measured distance. Slip for a straight powered pass is 1 minus measured distance divided by the distance inferred from calibrated wheel turns.
- **Why does a ranking change in Tune factors?** The default uses strict target readings, pairs temperature media and gives the slope grid one weight. The reference preset reproduces the original scoring inputs. The factor tables show coverage, time window and data source.
