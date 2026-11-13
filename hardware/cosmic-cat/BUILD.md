# Cosmic Cat · field-kit case (3D print)

The team mascot as a real field kit: the **ESP32 sits in the body**, the **tail** carries the wires and the **BME280** (air), and the **tail tip** holds the sky sensors on top and the ground sensors underneath.

- Files: `stl/` (5 parts). Made by `make_cat.py` (`python -I make_cat.py`; change a size at the top of the file and run it again).
- Preview: run `start.bat`, open `http://localhost:8080/hardware/cosmic-cat/preview.html` (drag to turn, **Exploded view**).
- **Not test-printed yet.** Before the big parts, measure your ESP32 board (DevKit V1 is about 52 × 28 mm, but boards differ) and print the tail tube first to check the socket fit.

## 1. Print

White **PETG** (it takes the Jordan sun; PLA softens in a hot car or in the sun, and a dark colour heats up and spoils the air temperature). Layer 0.2 mm, walls are already 2.5 mm thick (6 perimeters at 0.4 mm), infill 15 %, **no supports needed**.

| File | Part | Size (mm) | Print as it is |
|---|---|---|---|
| `1_body_base.stl` | body, legs, tail root | 122 × 50 × 54 | legs on the bed |
| `2_lid_head.stl` | lid plate + head + ears | 81 × 48 × 63 | plate on the bed |
| `3_tail_tube.stl` | tail tube (wires, BME280 vents) | 28 × 28 × 110 | standing up |
| `4_tailtip_shell.stl` | tail tip, sky windows | 66 × 42 × 30 | already upside down: top on the bed |
| `5_tailtip_plate.stl` | tail tip plate, ground windows, collar | 66 × 42 × 15 | plate on the bed, collar up |

All parts fit a 220 × 220 mm bed. Total about 290 cm³ of solid (with 15 % infill, roughly 150–250 g of filament; the slicer gives the exact number).

## 2. Hardware

- 6 × M3 self-tapping screws, about 10 mm (2 for the lid, 4 for the tail-tip plate)
- 2 × M3 bolts 40 mm with nuts (they lock the tail tube: one through the tail root, one through the tail-tip collar)
- 1 × 1/4"-20 hex nut (camera tripod thread), dropped into the pocket in the belly from inside
- double-sided foam tape, hot glue, 2 small cable ties
- wires: 5 thin wires about 30 cm long up the tail (3V3, GND, SDA, SCL, UV signal)

## 3. Where each part goes

| Part | Place | Why |
|---|---|---|
| ESP32 DevKit V1 | body floor, **upside down** (pins up), USB end at the chest hole, on foam tape | pins up = the jumper wires plug in from above; USB cable to the power bank through the chest |
| 4.7 kΩ resistor, wire joints | body | |
| DS18B20 soil probe | cable out through the small hole low on the right side | the metal tip goes into the soil |
| **BME280** (air) | inside the tail tube, at the vent slots, hanging on its wires (not touching the wall) | far from the ESP32's heat, in moving air, shaded by the tail tip above |
| **BH1750 UP** (address 0x23) | under the first sky window of the tail tip, sensor chip centred in the window, hot glue | sees the sky |
| **GUVA-S12SD** (UV) | under the second sky window | sees the sky. Leave the window open: most clear plastics block UV |
| **BH1750 DOWN** (0x5C) | on the plate, over the first ground window | sees the ground |
| **MLX90614** | on the plate, its metal can through the 10 mm window | sees the ground surface |

The ground windows sit beyond the tube, so the down sensors look at the ground, not at the cat. Wiring is the same as in `firmware/WIRING.md` section 2 (all I2C boards share SDA = GPIO21, SCL = GPIO22).

## 4. Assembly

1. Drop the 1/4" nut into the belly pocket from inside the body.
2. Stick the ESP32 in (upside down, USB at the chest hole). Run the probe cable out of the side hole.
3. Pull the 5 tail wires up through the tail root channel and the tube. Put the tube into the root socket and lock it with an M3 × 40 bolt.
4. Glue the BME280 at the vent slots. Glue the sky sensors in the tail tip and the ground sensors on the plate. Push the plate collar over the tube top, lock it with the second bolt, close the tail tip with 4 screws.
5. Put the lid on (it drops into the body and rests on the four corner columns) and screw the two rear screws.
6. Screw the cat onto a camera tripod (1/4" screw into the belly). Put the power bank on the tripod and plug it into the chest.

## 5. In the field

- Stand it 1–1.5 m high, on open ground, the tail tip level (a phone level app works).
- Do the albedo calibration (`firmware/WIRING.md`, test 4) **after** the sensors are glued in, because the windows change the light a little.
- Rain: the windows are open. Bring it in, or tape a clear cover over the **BH1750 windows only** (not the UV one) and calibrate again.
- The case is a first version. If the air temperature reads high in the sun, add the white shield plates from `WIRING.md` around the tail vents.
