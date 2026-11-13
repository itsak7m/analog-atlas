# Analog Atlas field kit - parts, wiring, mounting and tests

This guide is for building, testing and using the field kit. The data format for the
app is in `PROTOCOL.md`.

**Golden rules**
- Switch the power off (unplug USB) before you change any wire.
- The ESP32 pins work with **3.3 V only**. Never connect 5 V to SDA, SCL, GPIO4 or GPIO34.
- Use a USB **data** cable. Many cheap cables only charge: then no COM port appears.

---

## 1. Parts list

| Qty | Part | Notes |
|---|---|---|
| 3 | ESP32 DevKit V1 (ESP32-WROOM-32) | 1 field kit + 1 base station for ESP-NOW + 1 spare |
| 1 | BME280 board (I2C) | air temperature, humidity, pressure. Many boards sold as "BME280" are really a **BMP280** (no humidity) - `tests/bme280_test` tells you which one you got |
| 1 | MLX90614 board "GY-906" | infrared surface thermometer. **Buy the 3 V version "MLX90614ESF-BAA"**, see section 5 |
| 2 | BH1750 board "GY-302" | light sensors: one facing up, one facing down |
| 1 | DS18B20 waterproof probe (metal tip, about 1 m cable) | soil temperature |
| 1 | 4.7 kOhm resistor | pull-up for the DS18B20 |
| 1 | GUVA-S12SD UV board | UV index |
| 2 | breadboards | the DevKit is wide: put it across two breadboards, one pin row on each |
| 1 set | jumper wires (male-male and male-female) | |
| 3 | USB **data** cables | micro-USB on most DevKit V1 boards (check yours) |
| 1 | USB power bank | about 10 000 mAh is plenty for 24 h; a "low current" / "always on" mode helps (section 5) |
| | for mounting | pole or tripod (about 1.5 m), an arm, cable ties, small box, white plastic plates for the radiation shield, a bubble level (a phone level app works) |
| | optional | USB power meter (shows the current), multimeter (for the MLX90614 check) |

---

## 2. Wiring table

All sensors get their power from the ESP32 **3V3** pin and **GND**. The four I2C boards
share the same two signal wires (a "bus"): every SDA to GPIO21, every SCL to GPIO22.

| Part | Part pin | ESP32 pin |
|---|---|---|
| BME280 | VIN or VCC | 3V3 |
| | GND | GND |
| | SDA | GPIO21 (D21) |
| | SCL | GPIO22 (D22) |
| | CSB (only 6-pin boards) | 3V3 (selects I2C) |
| | SDO (only 6-pin boards) | GND (address 0x76) - or 3V3 for 0x77 |
| MLX90614 (GY-906) | VIN | 3V3 (BAA version) |
| | GND | GND |
| | SDA | GPIO21 |
| | SCL | GPIO22 |
| BH1750 **UP** (GY-302) | VCC | 3V3 |
| | GND | GND |
| | SDA | GPIO21 |
| | SCL | GPIO22 |
| | ADDR | **GND** (address 0x23) |
| BH1750 **DOWN** (GY-302) | VCC | 3V3 |
| | GND | GND |
| | SDA | GPIO21 |
| | SCL | GPIO22 |
| | ADDR | **3V3** (address 0x5C) |
| DS18B20 probe | red (VDD) | 3V3 |
| | black (GND) | GND |
| | yellow (DATA) | GPIO4 (D4) |
| 4.7 kOhm resistor | one leg / other leg | GPIO4 / 3V3 |
| GUVA-S12SD | + (VCC) | 3V3 |
| | - (GND) | GND |
| | OUT (SIG) | GPIO34 (D34) |
| on-board LED | - | GPIO2 (blinks at every reading) |

The DS18B20 wire colours above are the usual ones; some probes use other colours
(for example white or blue for data). Check the seller's description.

---

## 3. Diagram

ESP32 DevKit V1 (30 pins), seen from the top, USB at the bottom. Pin positions differ
between board versions: **always follow the labels printed on your board**.

```
                  +--------------------+
                  | EN            D23  |
                  | VP            D22  |----> SCL bus (SCL of all 4 I2C boards)
                  | VN            TX0  |
   GUVA OUT ----->| D34           RX0  |
                  | D35           D21  |----> SDA bus (SDA of all 4 I2C boards)
                  | D32           D19  |
                  | D33           D18  |
                  | D25            D5  |
                  | D26           TX2  |
                  | D27           RX2  |
                  | D14            D4  |----> DS18B20 DATA (+ 4.7 kOhm to 3V3)
                  | D12            D2  |      (blue LED on the board)
                  | D13           D15  |
   GND rail <-----| GND           GND  |
                  | VIN           3V3  |----> 3V3 rail (VCC of every sensor)
                  +-------[USB]--------+
```

The four I2C boards, all in parallel on the same four wires:

```
             +-- BME280 ...... VIN  GND  SDA  SCL    (6-pin board: CSB -> 3V3, SDO -> GND)
             +-- MLX90614 .... VIN  GND  SDA  SCL
             +-- BH1750 UP ... VCC  GND  SDA  SCL    ADDR -> GND
             +-- BH1750 DOWN . VCC  GND  SDA  SCL    ADDR -> 3V3
                                |    |    |    |
                  ESP32 pin:   3V3  GND  D21  D22
```

The two other sensors:

```
   DS18B20 probe:  red -> 3V3    black -> GND    yellow -> D4
                                                 D4 --[ 4.7 kOhm ]-- 3V3

   GUVA-S12SD:     + -> 3V3      - -> GND        OUT -> D34
```

---

## 4. I2C addresses

| Address | Device | How it is set |
|---|---|---|
| 0x23 | BH1750 UP | ADDR pin to GND |
| 0x5C | BH1750 DOWN | ADDR pin to 3V3 |
| 0x5A | MLX90614 | factory setting |
| 0x76 | BME280 / BMP280 | SDO to GND (most cheap boards) |
| 0x77 | BME280 / BMP280 | SDO to 3V3 (e.g. Adafruit boards) |

If both BH1750 have the same ADDR connection they get the same address and only one
works. The field kit looks for the BME280 at 0x76 and 0x77 by itself.

The chip ID tells BME280 from BMP280: **0x60 = BME280**, **0x58 = BMP280** (no
humidity: the kit then simply leaves out `rh`).

---

## 5. Power

**3V3 or 5 V?** Power every sensor from **3V3**. The **VIN** pin carries the USB
5 V when the board runs from USB; do not use it for the sensors (exception below).

**MLX90614: "BAA" (3 V) or "AAA" (5 V)?** The letters after "MLX90614ESF-" are printed
on the sensor's metal can and are usually in the shop listing.
- **BAA** = 3 V version: connect VIN to 3V3. This is the one to buy.
- **AAA** = 5 V version: it needs 4.5 .. 5.5 V. On 3.3 V it may not work or may give
  wrong temperatures. The risk with 5 V: if the board's SDA/SCL pull-up resistors go to
  5 V, they put 5 V on the ESP32 pins, which are **not 5 V tolerant**.
  If you only have an AAA board: power its VIN from the ESP32 **VIN** pin (5 V from USB)
  and, BEFORE connecting SDA/SCL to the ESP32, measure with a multimeter between the
  board's SDA pin and GND while it is powered:
  - about 3.3 V: the board has its own 3.3 V pull-ups - you may connect it;
  - about 5 V: **do not connect it directly**; use a 2-channel I2C level shifter
    (BSS138 type) or get a BAA board.
  Note: many GY-906 boards have a small 3.3 V regulator (marked "662K"). On such a board
  the chip always gets 3.3 V, so an AAA chip is under-powered even with 5 V on VIN -
  another reason to get the BAA version.

**Power banks that switch off.** Many power banks switch themselves off when the current
is small for a while, because they think nothing is connected. The ESP32 with Wi-Fi off
uses only a modest current (the ESP32 datasheet gives about 30-68 mA for the chip at
240 MHz without radio, plus the board's own parts), so some power banks will switch off.
- Use a power bank with a "low current" / "trickle" / "always on" mode (see its manual,
  often a double press or long press of the button).
- **Test it at home** before the field: run the kit from the power bank for 1-2 hours
  with `LOG START 10`, then `LOG DUMP`. If rows stop early, the power bank switched off.
- A USB power meter shows the real current of your kit.
- Possible fixes: a different power bank; switching on ESP-NOW (`ESPNOW_SEND 1`, the
  radio draws more current); a small USB lamp in the power bank's second port as extra
  load (this shortens the run time).

**Brownout.** A weak cable or power bank can make the voltage drop and reset the ESP32.
After such a reset the kit prints `# WARNING: the last reset was a BROWNOUT` and INFO
shows `"reset":"brownout"`. The `boot` number in the log also jumps. Use a short, thick
USB cable.

---

## 6. Mounting outdoors

```
     [radiation shield with BME280]  <- top of the pole, 1.25-2 m high if possible
               ||
               ||
               ||=====================[ GUVA (up) + BH1750 UP (up) / BH1750 DOWN (down) ]
               ||     arm about 1 m above the ground, sensors 30-50 cm from the pole,
               ||     on the SOUTH side (in Jordan the midday sun is in the south,
               ||     so the shadow of the pole falls to the north, away from the spot)
       [box: ESP32]   (on the pole below the arm, in shade)
               ||
               ||=============[ MLX90614 pointing straight down ]  <- 20-50 cm high
               ||                          |
  =============||==========================v=================== natural ground
               ||                   spot it sees
                  DS18B20 in the soil (e.g. 5 cm deep), a little away from the pole
```

### Air temperature: DIY radiation shield for the BME280

**Why:** in sunshine the sensor and its circuit board absorb sunlight and get warmer
than the air. Without a shield it can read several degrees too warm, and the error
changes with sun and wind - so the data is not valid air temperature. Weather stations
measure air temperature in a white, ventilated, shaded housing, 1.25-2 m above the
ground (World Meteorological Organization standard).

**How to build one ("plate stack"):**
1. Take 6-10 **white** plastic plates or plant saucers (about 15-20 cm wide).
2. Drill 3 holes near the edge of each and stack them on 3 threaded rods with nuts or
   spacers, about 1.5-2 cm between the plates, all facing down like little roofs. The
   top plate is solid and closes the stack.
3. Hang the BME280 in the middle of the stack on its cable; it must not touch the plates.
4. Air must flow freely through the sides. Keep the shield white and clean.
5. Mount it on the pole, in the open, above natural ground (not concrete, not near a
   wall), about 1.25-2 m high if possible.
6. Keep the ESP32, the box and the power bank **outside** the shield (they make heat):
   at least 30 cm away and not directly above the box (warm air rises).

Quick check: on a sunny day compare an unshielded BME280, the shielded one and a good
thermometer in proper shade. The shielded one must be much closer to the thermometer.

### Light sensors (BH1750 UP and DOWN) for albedo

- Put both on the end of the arm, **30-50 cm away from the pole**, about **1 m above
  the ground**, on the **south side** of the pole so the shadow of the pole falls
  away from the measured spot.
- **UP** sensor facing straight up, **DOWN** sensor facing straight down, close
  together (back to back). Use a bubble level: a tilted UP sensor gives wrong values,
  most of all when the sun is low.
- What the DOWN sensor sees: for a sensor with a cosine response at height h, half of
  the signal comes from a circle of radius h under it and about 90 % from radius 3h.
  At 1 m height, keep an area of about **3 m radius** uniform (same surface) and free of
  people, bags, tripod legs and shadows.
- Nothing (box, cables, you) may shade the UP sensor or the ground spot.
- If you protect the sensors (rain, dust), use **the same** clear or white material on
  both and repeat the pair calibration (section 9, test 4).
- Range: the firmware sets the BH1750 "measurement time" register MTreg to 31, so each
  sensor measures up to **121 557 lux** (the library default stops at 54 612 lux, too
  little for full sun). If a sensor is still at its ceiling the kit sends `"sat_up":1` or
  `"sat_down":1` instead of a number - never a wrong value. If this happens often at
  midday in summer, put the same piece of white translucent plastic (diffuser) over
  BOTH sensors and repeat the pair calibration.
- The BH1750 measures visible light (weighted like the human eye), so the result is a
  "visible albedo".

### Ground surface temperature (MLX90614)

Same principle as the ground temperature sensor of Curiosity's REMS and the thermal
infrared sensor (TIRS) of Perseverance's MEDA: it measures the thermal infrared light
(about 5.5-14 um) that the ground gives off.
- Point it **straight down** at natural ground, **20-50 cm** above it.
- Field of view of the standard BAA version: **90 degrees**, so the spot diameter is
  about 2 x the height (30 cm high -> about 60 cm spot). Everything in that cone
  counts: no pole, no shadow of the kit, no cables in it. Choose the same kind of
  surface that the DOWN light sensor sees.
- Keep direct sun off the sensor body if you can (mount it under the arm), because
  fast changes of its own temperature (`amb`) disturb the measurement.
- The emissivity setting is the factory value 1.0. Natural ground is a little below 1,
  so `surf` can read slightly low. Do not change the setting.

### Soil temperature (DS18B20)

Dig a small hole, push the metal tip **sideways into undisturbed soil at a fixed depth**
(for example 5 cm), fill the hole again and **write the depth down**. Leave some slack
in the cable so nobody pulls the probe out.

### UV sensor (GUVA-S12SD)

On top of the arm or box, facing straight up, never shaded. **No glass or normal plastic
over it**: they block much of the UV.

### The ESP32 box

A small white box on the pole, in the shade of the arm if possible, with a few holes for
air. Keep the I2C cables as short as practical: at 100 kHz the bus usually works with a
few metres of wire in total, but every extra metre adds risk. For cables longer than
about 50 cm, twist SDA together with a GND wire and SCL together with a 3V3 wire (or use
a 4-core cable). If the kit often prints `... stopped giving valid data`, make the I2C
cables shorter. The DS18B20 (1-Wire) has no problem with its 1 m cable.

---

## 7. Upload in the Arduino IDE

1. Arduino IDE 2: **Boards Manager** -> "esp32 by Espressif Systems" version 3.3.x
   (installed on this computer: 3.3.11).
2. **Library Manager** (installed on this computer): Adafruit BME280 Library 2.3.0,
   Adafruit Unified Sensor 1.1.15, Adafruit BusIO 1.17.4, OneWire 2.3.8,
   DallasTemperature 4.0.6, Adafruit MLX90614 Library 2.1.6, BH1750 1.3.0 (Christopher Laws).
3. Open `firmware/field_kit/field_kit.ino` (or a test, or `base_station/base_station.ino`).
4. **Tools -> Board -> esp32 -> "ESP32 Dev Module"**.
5. **Tools -> Port**: the COM port of the board (shown as "Silicon Labs CP210x" or
   "USB-SERIAL CH340"). No port? Try another (data!) cable, or install the CP210x or
   CH340 driver.
6. Leave the other Tools settings at their defaults, especially:
   - **Partition Scheme: "Default 4MB with spiffs (1.2MB APP/1.5MB SPIFFS)"** - the log
     file lives in that 1.5 MB area;
   - **Erase All Flash Before Sketch Upload: "Disabled"** - "Enabled" would delete the
     log. (A normal upload of new firmware keeps the log.)
7. Click **Upload**. If it hangs at `Connecting....____`, hold the **BOOT** button on the
   board until the upload starts.
8. **Serial Monitor**: 115200 baud, line ending **"Newline"**. Type `HELP` + Enter.
9. Close the Serial Monitor before you use the web app: only one program can use the port.

Optional settings at the top of `field_kit.ino`:
- `WIFI_SSID` / `WIFI_PASS`: Wi-Fi (e.g. a phone hotspot) only to get the time at
  power-up (max 15 s, then Wi-Fi goes off). Do not share the file with your password in it.
- `ESPNOW_SEND 1`: also send the data by radio to the base station.
- `UV_SENSOR_FITTED 0`: if no UV sensor is connected.

---

## 8. Using it with the app

1. Start the app and open **http://localhost:8080** in **Chrome or Edge** (the Web Serial
   API that talks to USB works only there).
2. Click **"Connect kit (USB)"** and choose the COM port of the kit (or of the base station).
3. The app switches DTR/RTS off (so the board runs normally), sends the time
   (`TIME ...`) and `INFO`. From then on a line arrives every second; the LED blinks.
   If the kit restarts while it is connected, the app sends the time again.
4. Messages starting with `#` (missing sensors, warnings) appear in the app under
   "Messages from the kit". A missing sensor is reported once, not every 10 s.
5. If no line arrives for more than 5 s, the kit bar says "No data for N s".

With ESP-NOW: field kit with `ESPNOW_SEND 1` on a power bank, base station on the
computer's USB, connect the app to the **base station's** port. Logging commands
(`LOG ...`) only work through the kit's own USB port, so the app switches its log
buttons off while it talks to the base station.

**Pair the base station with your kit (once).** At an event other teams' ESP32 boards
may also send on channel 1. Open the Serial Monitor on the base station (115200 baud),
switch your field kit on and type `PAIR`. The base station answers
`# base station: paired with the field kit <MAC>` and from then on forwards only that
kit (it remembers it after a restart; `UNPAIR` forgets it). Instead of `PAIR` you can
type the kit's MAC address (the `"mac"` in its INFO line) into `FIELD_KIT_MAC` at the
top of `base_station.ino`. Close the Serial Monitor before you connect the app.

---

## 9. Tests - one sensor at a time

Upload each test from `firmware/tests/<name>/`, open the Serial Monitor (115200 baud)
and follow the PASS criteria. Do them in this order:

| # | Test sketch | PASS when |
|---|---|---|
| 1 | `i2c_scanner` | 0x23, 0x5C, 0x5A and 0x76 or 0x77 are found; SDA and SCL show "pull-up present" |
| 2 | `bme280_test` | chip ID 0x60 (BME280) or 0x58 (BMP280); "driver check PASS" (BME280); air within about 1 C of a good thermometer next to it (after 10 min, away from the ESP32 and the sun); humidity jumps up when you breathe on it and falls back; pressure plausible (Amman about 88-95 kPa). **Pressure check:** set `MY_ELEVATION_M` to the height of the place (map or GPS) and compare the printed QNH with the current QNH of the Amman airport weather report (METAR "Q1013" = 1013 hPa): within about 3 hPa. Each 10 m of elevation error is about 1 hPa. |
| 3 | `mlx90614_test` | found at 0x5A, "PEC ok", ambient near room temperature; palm of your hand at 2-5 cm about 30-36 C; glass of ice water from above about 0-5 C. **Same surface:** DS18B20 in a bowl of stirred water and the MLX90614 pointing at the water surface from about 5 cm agree within about 2 C. |
| 4 | `bh1750_test` | both found; covering one with a finger gives almost 0 lux; lamp/window gives hundreds to thousands of lux. **Pair calibration (important for albedo):** outdoors, both sensors side by side and BOTH facing up, open sky, no shadow: the printed ratio UP/DOWN should be between about 0.8 and 1.25 (single sensors may differ by up to 20 % by the datasheet). Write the ratio down and type it into the app: field kit panel, "Albedo calibration k" (k = 1 means not calibrated). |
| 5 | `ds18b20_test` | pull-up present, exactly 1 sensor, ROM starts with 28, CRC ok; room temperature plausible, never -127 or 85; **ice water** (cup full of crushed ice + a little water, stirred, wait 2 min): 0.0 C +- 0.5 C |
| 6 | `guva_s12sd_test` | indoors away from windows: below 100 mV (UV index < 1); outdoors in sunshine clearly above 100 mV; covering it with your hand drops it below 100 mV; spread stays small |
| 7 | `espnow_test` (on both boards) | at your planned distance at least 90 % of the pings are answered |

Then the whole kit: upload `field_kit`, type `INFO`: every sensor must show `ok`. Watch
the data lines for a few minutes: no `#` errors, values steady and plausible.

---

## 10. The 24-hour logging test

Goal: one row per minute for 24 hours from a power bank (about 1440 rows).

**The time problem.** The kit forgets the time at every power cut. When you move it from
the computer to the power bank it restarts, so rows logged on the power bank have an
empty `unix` column unless you use one of these:
- **Option A (best): Wi-Fi time.** Put a Wi-Fi name/password (e.g. your phone hotspot)
  into `WIFI_SSID` / `WIFI_PASS`, upload, and keep the hotspot on near the kit for the
  first 15 seconds after you plug in the power bank. Then every row has `unix`.
- **Option B: write the start time down.** Note the exact clock time (to the second)
  when you plug in the power bank. After reading the log, the app shows a field
  "Boot N started at" for every boot without the kit clock: type that time there and
  the app rebuilds the times from the `ms` column of that boot (see PROTOCOL.md,
  section 7). Without it, those rows stay "time unknown" and are not used.

**Steps**
1. At home, kit on USB: check in the app (or Serial Monitor + `INFO`) that all sensors
   are ok.
2. If old rows are still in the kit and you have saved them: `LOG CLEAR`.
3. `LOG START 60`. The status line must show `"log":true,"interval":60`. Note the
   `boot` number N from the status line.
4. Unplug USB and plug in the power bank (note the time for option B). The kit starts
   again (boot N+1) and **continues logging by itself**: the setting is saved in its
   flash memory. The blue LED blinks every second.
5. Mount the kit outdoors (section 6) and leave it for 24 hours.
6. Bring it back and connect it to the computer (this is boot N+2; logging continues).
   Send `LOG STOP`.
7. In the app: **"Read log from kit"** (or `LOG DUMP` in the Serial Monitor), type the
   start time of boot N+1 if you used option B, then **"Save log as CSV"**. A saved file
   can be loaded again later with **"Import CSV file"**.
8. Check: about 1440 rows with boot N+1; no big jumps in `ms` (60 000 ms per row).
   The app shows one line per boot with its rows, kit timer and largest gap.
   If the rows of boot N+1 end early, the power bank switched off (section 5).
   The app compares the log with NASA POWER in 24-hour windows that start at the first
   row with a time; a window counts when it has at least 20 h of data with no gap over 1 h.
9. Only when the data is safely saved: `LOG CLEAR`.

---

## 11. A one-day field test plan

- **Day -1, at home (bench):** run the tests of section 9. Do the light sensor pair
  calibration (test 4) outdoors at midday and type k into the app. Run the kit 1-2 hours
  from the power bank with `LOG START 10` to check that the power bank does not switch
  off. For Wi-Fi time (option A), use a 2.4 GHz hotspot (the ESP32 has no 5 GHz Wi-Fi).
- **Day 0:** set the kit up on natural ground (soil, not a concrete roof), mounted as in
  section 6. Write down the probe depth, the coordinates and the elevation (phone GPS or
  a map), and type them into the app ("Type coordinates"). `LOG CLEAR` (after saving old
  rows), `LOG START 60`, and note the exact time you plug in the power bank (option B).
  Check the LED and take a photo every few hours.
- **Day +1, after 24 hours or more:** connect, `LOG STOP`, "Read log from kit", type the
  boot start time, "Save log as CSV". Check about 1440 rows in one boot with no gaps.
  Compare with NASA POWER, keeping the cell-elevation warning (⚑) in mind.
- **Optional surface comparison (midday, 2-3 hours, kit live on the laptop USB):** measure
  albedo, surface temperature and UV on two different nearby surfaces (for example dark
  basalt and a light mudflat), about 10 minutes each, with photos. This shows whether the
  sensors can tell the surfaces apart.

Possible later upgrade (the firmware does not support it yet): a DS3231 real-time clock
module on the same I2C bus (address 0x68; the EEPROM on ZS-042 boards is at 0x57) would
keep the time across the computer-to-power-bank swap. The kit has no other part at 0x68
today; if you ever add an MPU6050 motion sensor as well (also 0x68 by default), set its
AD0 pin high so it moves to 0x69.

---

## 12. Troubleshooting

| Message or symptom | What to check |
|---|---|
| no COM port | data cable (not charge-only), driver (CP210x / CH340), other USB port |
| upload stops at `Connecting....` | hold the BOOT button until writing starts |
| `# BME280 not found at 0x76/0x77 ...` | 3V3, GND, SDA=21, SCL=22; 6-pin board: CSB to 3V3, SDO to GND; run `i2c_scanner` |
| `# BMP280 found ...` | your board is a BMP280: no humidity. Fine for air temperature and pressure. |
| `# MLX90614 ... data fails the check (PEC)` | loose or long I2C wires, missing GND, AAA (5 V) version on 3.3 V |
| `# BH1750 UP not found at 0x23 ...` | ADDR pin of the UP board to GND (DOWN board: ADDR to 3V3) |
| `# BH1750 ... is saturated` / `sat_up` | very bright sun: see section 6 (diffuser on both) |
| `# DS18B20 not found on GPIO4 ...` | the 4.7 kOhm resistor between GPIO4 and 3V3, the 3 wires |
| `# UV reading unstable ...` | GUVA OUT wire to GPIO34; set `UV_SENSOR_FITTED 0` if no UV sensor |
| `"uv_lt":1.0` all the time outdoors in sun | GUVA power (3V3, GND), cover (glass/plastic blocks UV) |
| `# WARNING: the last reset was a BROWNOUT` | weak power bank or cable |
| `# LOG STOPPED: the flash memory is full` | `LOG DUMP`, save, `LOG CLEAR`, `LOG START` |
| rows with empty `unix` | the kit did not know the time: section 10, option A or B |
| "No data for N s" in the app's kit bar | USB cable and power; a restart of the kit (start-up lines under "Messages from the kit"); with the base station: the kit is off, out of range or not paired |
| `# base station: forwarding EVERY sender` | pair the base station with your kit: section 8 |
| albedo "sun too low" or "needs daylight" in the app | the app needs more than 1000 lux on the UP sensor and the sun 20 degrees or more above the horizon: measure nearer midday |
| albedo "UP sensor saturated" in the app | very bright sun: see section 6 (diffuser on both, then repeat test 4) |
