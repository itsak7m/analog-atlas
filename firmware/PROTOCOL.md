# Analog Atlas field kit - serial protocol

Firmware version **1.0.1** (`field_kit.ino`) and base station **1.0.1** (`base_station.ino`).
This file is for the people who write the web app. Wiring and tests: see `WIRING.md`.

---

## 1. Connection

| Setting | Value |
|---|---|
| Port | USB serial of the ESP32 DevKit (CP210x or CH340 chip) |
| Speed | **115200 baud**, 8 data bits, no parity, 1 stop bit, no flow control |
| Text | ASCII, one message per line |
| Line end (kit to app) | `\r\n`. Rows inside a LOG DUMP end with `\n` only. **Always split on `\n` and remove a trailing `\r`.** |
| Line end (app to kit) | `\n` (also `\r` or `\r\n` are accepted) |

### What the web app does after opening the port

1. `await port.open({ baudRate: 115200 })`
2. **Set DTR and RTS low (off):**
   `await port.setSignals({ dataTerminalReady: false, requestToSend: false })`
   so the board boots and runs normally.
3. Send `TIME <unix seconds>\n`, then `INFO\n`.

Why step 2: the ESP32 DevKit has an "auto-reset" circuit: the USB chip's DTR and RTS
lines drive the ESP32's EN (reset) and IO0 (boot mode) pins through two transistors.

| `dataTerminalReady` | `requestToSend` | Effect on the ESP32 |
|---|---|---|
| false | false | EN and IO0 released: **normal boot / normal running** (what the app must use) |
| true | true | also released (no effect) |
| false | true | EN pulled low: the board is **held in reset** (no output at all) |
| true | false | IO0 pulled low: after a reset the board starts the **ROM download mode** instead of the firmware |

("low"/off here means the Web Serial value `false`, i.e. the signal is not asserted.)

Opening a port can reset some boards (the operating system may toggle DTR/RTS while
opening). After a reset the kit needs about 1 second to start, and with Wi-Fi time
sync (optional) up to 15 seconds more. Bytes that arrive in the first fraction of a
second after a reset (before the program has opened its serial port) are lost; later
ones wait in a 256-byte receive buffer until the start-up is finished. To be safe:

- When the app sees the start-up banner `# Analog Atlas field kit - firmware ...`
  or a status line with `"time":false`, it should send `TIME <unix>` again.
- When it sees `# base station ready`, it is talking to the base station (section 8).

What the Analog Atlas app does: it sends `TIME` again on the banner or on `"time":false`,
at most once every 5 s, and never through the base station (status lines that carry
`"via":"espnow"`, a `# base station ready` line or a `{"base":...}` answer tell it that
the base station is on the port; the base station would only answer with a `#` line).

Ignore every line that is neither JSON (starts with `{`) nor a comment (starts with `#`),
except the CSV lines of a LOG DUMP. At reset the ESP32 boot ROM prints its own text
(e.g. `ets Jul 29 2019 12:21:46`, `rst:0x1 (POWERON_RESET),boot:0x13 ...`) and there can
be some garbage characters.

### Line types (by first character)

| First char | Type | Section |
|---|---|---|
| `{` with key `"t"` | data line, every 1 s | 2 |
| `{` with key `"status"` | status line, every 10 s and after commands | 3 |
| `{` with key `"info"` | answer to `INFO` | 4 |
| `{` with key `"base"` | base station info (answer to `INFO` on the base station) | 8 |
| `#` | comment for humans; `#LOG BEGIN` / `#LOG END` mark a dump | 5, 7 |
| anything else | CSV rows between `#LOG BEGIN` and `#LOG END`, otherwise ignore | 7 |

Parsers must **ignore unknown keys** (later firmware may add keys) and must not rely on
the order of keys.

---

## 2. Data line (every second)

```
{"t":12345,"unix":1791500000,"air":24.12,"rh":38.0,"p":91.234,"uv":5.2,"uv_mv":520,"ground":31.06,"surf":33.51,"amb":29.80,"lux_up":52000.0,"lux_down":15000.0}
```

| Key | Unit | Decimals | Sensor | Valid range (datasheet) | Notes |
|---|---|---|---|---|---|
| `t` | ms | 0 | ESP32 | 0 .. 4294967295 | Time since power-up (`millis()`). Always present. Wraps after 49.7 days. |
| `unix` | s (UTC) | 0 | ESP32 clock | 2024 .. 2099 | Unix time of this reading. **Only present when the kit knows the time** (TIME command or Wi-Fi NTP). |
| `air` | deg C | 2 | BME280 / BMP280 | -40 .. 85 | Air temperature (valid only inside a radiation shield in sunshine, see WIRING.md). |
| `rh` | % | 1 | BME280 only | > 0 .. 100 | Relative humidity. **Never sent by a BMP280** (it has no humidity sensor). A reading of exactly 0 % is treated as an error and left out. |
| `p` | kPa | 3 | BME280 / BMP280 | 30 .. 110 | **Absolute (station) pressure**, NOT sea-level pressure. Amman (700-1100 m) is about 88-95 kPa. |
| `uv` | UV index | 1 | GUVA-S12SD | 1.0 .. 12.5 | `uv = uv_mv / 100` (UV index = Vout / 0.1 V, module documentation; an approximation). |
| `uv_mv` | mV | 0 | GUVA-S12SD | 100 .. 1250 | Sensor output voltage (ESP32 ADC, 2.5 dB attenuation, mean of the middle 8 of 16 samples). |
| `uv_lt` | UV index | 1 | GUVA-S12SD | always `1.0` | **Limit key:** the UV index is **below 1.0**. The output was under 100 mV, where the ESP32 ADC cannot measure well (night, indoors, shade). Sent **instead of** `uv`/`uv_mv`. |
| `ground` | deg C | 2 | DS18B20 | -55 .. 125 | Soil temperature (12 bit, 0.0625 C steps). The value comes from the conversion started 1 s earlier, so it is missing in the first line after start-up. The error values -127 and 85 are never sent. |
| `surf` | deg C | 2 | MLX90614 object | -70 .. 380 | Infrared **surface** temperature of the ground (emissivity setting 1.0). |
| `amb` | deg C | 2 | MLX90614 ambient | -40 .. 125 | Temperature of the MLX90614 itself (not the air temperature). |
| `lux_up` | lux | 1 | BH1750 at 0x23 | 0 .. 121557 | Light from the sky (sensor facing up). |
| `lux_down` | lux | 1 | BH1750 at 0x5C | 0 .. 121557 | Light reflected by the ground (sensor facing down). |
| `sat_up` | flag | - | BH1750 at 0x23 | always `1` | **Limit key:** the UP sensor is at its ceiling (more than 121557 lux). Sent **instead of** `lux_up`. |
| `sat_down` | flag | - | BH1750 at 0x5C | always `1` | **Limit key:** the DOWN sensor is at its ceiling. Sent **instead of** `lux_down`. |

Rules:

- A key is **left out** when its sensor is missing, failed, or gave a value outside the
  valid range. The firmware never sends `null`, `NaN`, 0 or -127 as a placeholder.
- `uv`+`uv_mv` and `uv_lt` never appear together. `lux_up` and `sat_up` never appear
  together (same for `down`). If none of them is present, the sensor gave no valid data.
- Every data line is shorter than 240 bytes.
- When a sensor fails, a `#` line explains it (section 5) and the kit tries to find
  the sensor again every 10 s. The problem is reported once (a "not found" line at
  start-up, or a "stopped giving valid data" line when a working sensor fails), not at
  every retry; a line is printed when the sensor is found again.

### BH1750 range (lux_up / lux_down, sat_up / sat_down)

With the library default (measurement time register MTreg = 69) a BH1750 ends at
65535 counts / 1.2 = **54 612 lux**, but full sunlight can be about 100 000 lux, so
the UP sensor would clip outdoors and the albedo would be wrong. The firmware therefore
sets **MTreg = 31** (the smallest allowed value) in continuous high-resolution mode:

- range 0 .. 65535 / 1.2 x 69 / 31 = **121 557 lux**, one step = about 1.86 lux;
- if a sensor still reads its maximum count, the kit sends `"sat_up":1` or
  `"sat_down":1` instead of the lux value (and a `#` warning at most once a minute).

### Example lines

All sensors working, time known:
```
{"t":3605012,"unix":1791503600,"air":27.41,"rh":21.3,"p":91.087,"uv":7.9,"uv_mv":792,"ground":30.13,"surf":41.77,"amb":31.02,"lux_up":96341.6,"lux_down":24311.9}
```
BMP280 instead of BME280 (no `rh`), night (UV below range), time unknown:
```
{"t":120044,"air":14.08,"p":91.402,"uv_lt":1.0,"ground":15.88,"surf":9.13,"amb":14.75,"lux_up":0.0,"lux_down":0.0}
```
MLX90614 missing, UP light sensor saturated:
```
{"t":7200310,"unix":1791507200,"air":31.22,"rh":15.2,"p":90.881,"uv":10.4,"uv_mv":1042,"ground":33.50,"sat_up":1,"lux_down":29011.4}
```
(The numbers in these examples are only examples of the format.)

---

## 3. Status line

Sent every 10 s, at start-up, and right after `TIME`, `LOG START`, `LOG STOP`,
`LOG CLEAR`, `STATUS`, `INFO`.

```
{"status":{"fw":"1.0.1","bme":"BME280","log":true,"interval":60,"rows":123,"time":true,"free_kb":1200,"boot":12}}
```

| Key | Type | Meaning |
|---|---|---|
| `fw` | string | Firmware version |
| `bme` | string | `"BME280"`, `"BMP280"` or `"none"` (air sensor working right now) |
| `log` | bool | Logging to flash is on |
| `interval` | int, s | Logging interval |
| `rows` | int | Data rows in the log file (header not counted). Left out if the flash file system does not work. |
| `time` | bool | The kit knows the Unix time (`unix` keys are being sent) |
| `free_kb` | int, KB | Free space in the flash file system. Left out if it does not work. |
| `boot` | int | Boot counter (+1 at every power-up or reset), same as the `boot` column of the log. Left out if the flash file system does not work (also in the info line). |

---

## 4. Info line (answer to `INFO`)

`INFO` prints the status line, then:

```
{"info":{"fw":"1.0.1","boot":12,"reset":"poweron","mac":"24:6F:28:AA:BB:CC","bme":"BME280","bme_addr":"0x76","mlx":true,"bh_up":true,"bh_down":true,"ds18b20":1,"uv":true,"time_src":"usb","espnow":false,"fs_kb":1408}}
```

| Key | Meaning |
|---|---|
| `reset` | Reason of the last start: `poweron`, `pin`, `software`, `crash`, `watchdog`, `deepsleep`, `brownout` (supply too weak!), `other` |
| `mac` | Wi-Fi MAC address of the kit (also the ESP-NOW sender address) |
| `bme`, `bme_addr` | Air sensor type and I2C address (`bme_addr` only when one works) |
| `mlx`, `bh_up`, `bh_down` | Sensor works right now |
| `ds18b20` | Number of DS18B20 found (0 = not working; the first one is used) |
| `uv` | A UV sensor is configured (`UV_SENSOR_FITTED`). An analog sensor cannot be detected automatically. |
| `time_src` | `none`, `usb` (TIME command) or `ntp` (Wi-Fi) |
| `espnow` | Firmware built with `ESPNOW_SEND 1` |
| `fs_kb` | Size of the flash file system |

After the info line come one or two `#` lines with the same information in words.
The info line is never sent by ESP-NOW.

---

## 5. Comment lines (`#`)

Every line that starts with `#` is a message for humans: show it in a log panel, do
not parse it. The text may change between firmware versions. Typical messages:

```
# Analog Atlas field kit - firmware 1.0.1
# last reset: poweron
# BME280 not found at 0x76/0x77 - check SDA=21 SCL=22, VCC to 3V3, GND
# BMP280 found at 0x76 (chip id 0x58): air temperature + pressure. A BMP280 has NO humidity sensor, so "rh" is left out.
# DS18B20 stopped giving valid data - will try again every 10 s
# BH1750 UP is saturated (more than 121557 lux) - lux left out, "sat_up":1 sent instead
# WARNING: log memory is 90% full (140 KB free) - save it with LOG DUMP, then LOG CLEAR
# ERR unknown command 'FOO' - type HELP
```

Lines with a fixed meaning (safe to match):

| Line starts with | Meaning |
|---|---|
| `# Analog Atlas field kit - firmware` | the kit has just started (send `TIME` again) |
| `# base station ready` | the base station has just started |
| `#LOG BEGIN` | (no space after `#`) a log dump starts, CSV lines follow |
| `#LOG END` | the log dump is complete |
| `# ERR` | a command was not accepted |

---

## 6. Commands (app to kit)

One command per line, **upper or lower case**, at most 95 characters. Extra spaces are ignored.

| Command | Answer |
|---|---|
| `HELP` | `#` lines with the command list |
| `INFO` | status line + info line + `#` summary |
| `STATUS` | status line |
| `TIME <unix>` | Sets the clock. Unix time in **seconds** (UTC); decimals allowed, e.g. `TIME 1791500000.250`. Must be between 2024-01-01 and 2099. Answer: `# time set: unix 1791500000` + status line. A wrong value gives `# ERR TIME needs Unix time in SECONDS ...` (milliseconds are refused). The kit keeps `unix = offset + time since power-up`; the clock is lost at a reset or power cut. |
| `LOG START` | Start logging, one row every 60 s |
| `LOG START <s>` | Start logging every `s` seconds (1 .. 86400). If logging is already on, only the interval changes. Answer: `#` line + status line. The setting is saved, so **logging starts again by itself after a power cut**. |
| `LOG STOP` | Stop logging (rows are kept). `#` line + status line. |
| `LOG DUMP` | `# LOG DUMP: <n> rows`, then `#LOG BEGIN`, the CSV header, all rows, `#LOG END` (section 7). No data lines are sent during the dump. |
| `LOG CLEAR` | Deletes the log file. `#` line + status line. **Cannot be undone** - the app should ask the user first. |
| anything else | `# ERR unknown command '...' - type HELP` |

The app should send `TIME` and then `INFO` after connecting (section 1).

---

## 7. Log file and LOG DUMP (CSV)

The kit stores rows in `/log.csv` in its flash memory (LittleFS, about 1.4 MB in the
"Default 4MB with spiffs" partition scheme). Example dump:

```
# LOG DUMP: 3 rows
#LOG BEGIN
unix,boot,ms,air,rh,p,uv,ground,surf,lux_up,lux_down
,7,60512,22.41,31.0,91.255,<1.0,21.75,20.12,412.3,96.4
1791500123,7,120513,22.45,30.8,91.254,1.4,21.75,20.31,2210.9,511.2
1791500183,7,180512,22.60,,91.251,2.0,21.81,,>121557,30210.5
#LOG END
```
(Example of the format only.)

| Column | Unit | Meaning |
|---|---|---|
| `unix` | s | Unix time of the row; **empty when the kit did not know the time** |
| `boot` | - | Boot counter (+1 at every power-up/reset), stored in `/boot.txt` |
| `ms` | ms | Time since that boot (`t` of the data line) |
| `air`, `rh`, `p`, `uv`, `ground`, `surf`, `lux_up`, `lux_down` | as in section 2 | **Empty field = no valid value** |

Special text values (limits, not measurements):

- `uv` = `<1.0`: UV index below 1.0 (same as `"uv_lt":1.0`).
- `lux_up` / `lux_down` = `>121557`: that sensor was saturated (same as `"sat_up":1`).

Not in the log: `uv_mv` and `amb` (only in the live data lines).

More details:

- Each row is the reading of **that second** (a snapshot, not an average).
- Rows are written one by one and the file is closed after each row, so a power cut
  loses at most the row being written.
- The first row comes at the first reading after `LOG START` (or after power-up when
  logging resumes), then every `interval` seconds.
- The kit warns (`#`) when the memory is 90 % full and **stops logging cleanly** when
  less than 32 KB are free (`# LOG STOPPED: ...`, `"log":false` in the status line).
  After the first row it prints how many days the free memory lasts at that interval.
- During a dump no readings are taken. At 115200 baud about 11 KB are sent per second
  (a 24-hour log at 60 s, about 1440 rows of roughly 70 bytes, takes about 10 s).

### Rows without `unix` (time reconstruction)

After a power cut the kit does not know the time until it gets `TIME` (app) or NTP
(Wi-Fi). Rows logged in that time have an empty `unix`. The app can fill them in:

1. If **another row of the same `boot`** has a `unix` value:
   `unix_row = unix_ref + (ms_row - ms_ref) / 1000`
   (the ESP32 clock drifts only a few seconds per day).
2. Otherwise ask the user for the time when that boot started (for example "I plugged
   in the power bank at 08:14:30"): `unix_row = start + ms_row / 1000`.
3. Never invent a time: if neither is known, show the row with "time unknown".

What the Analog Atlas app does with a log (kit memory or CSV file):

- Rules 1-3 above, per boot. For a boot without any `unix` it shows a field "Boot N
  started at" (local time of the computer, to the second). Rows with "time unknown" are
  kept, but left out of the 24-hour windows.
- It cuts the timed rows into 24-hour windows, starting at the first timed row. A window
  is a full day when its `air` rows cover at least 20 h with no gap longer than 1 h; only
  full windows give a daily mean and a daily range (swing).
- "Save log as CSV" writes `unix,est_unix,boot,ms,air,rh,p,uv,ground,surf,lux_up,lux_down`:
  `unix` only when the kit clock gave the time, `est_unix` for a time the app rebuilt
  (rule 1 or 2), and the limit texts `<1.0` and `>121557` as they came. When such a file
  is read again, `est_unix` times stay marked as estimated.

---

## 8. ESP-NOW (optional radio link)

Field kit compiled with `#define ESPNOW_SEND 1`:

- Every **data line and status line** is also broadcast (to `FF:FF:FF:FF:FF:FF`) by
  ESP-NOW on **Wi-Fi channel 1**: exactly the same text, without line end, at most
  250 bytes per packet (lines are < 240 bytes). `#` lines and the info line are not sent.
- USB output does not change.
- Broadcasts have no acknowledgement and no retry: lines can be lost. Use `t` to see
  gaps (normally `t` grows by about 1000 per line).

Base station (`base_station.ino`, a second ESP32 on the computer's USB):

- Prints every received JSON line with `,"via":"espnow","rssi":<dBm>` inserted before
  the final `}`:
  ```
  {"t":12345,"air":24.12,"lux_down":15000.0,"via":"espnow","rssi":-61}
  {"status":{"fw":"1.0.1","bme":"BME280","log":false,"interval":60,"rows":0,"time":false,"free_kb":1390,"boot":3},"via":"espnow","rssi":-61}
  ```
  `rssi` = signal strength of that packet in dBm (closer to 0 = stronger). If the radio
  gave no signal strength, only `"via":"espnow"` is added.
- Packets that are not one printable JSON object `{...}` are ignored (counted).
- `# base station ready` at start, then a line with channel and MAC address, then a line
  that says which senders are forwarded.
- **Only your kit:** with `FIELD_KIT_MAC` set in `base_station.ino`, or after the `PAIR`
  command (the next packet from a field kit, a `{"t":...` or `{"status":...` line, sets
  the address; it is kept in flash until `UNPAIR`), only packets from that MAC address are
  forwarded. Packets from other senders are counted as `other`. Without either, every
  sender is forwarded.
- While nothing arrives: a heartbeat every 10 s, e.g.
  `# base station alive - nothing forwarded yet on channel 1, 0 packets from other senders (...)` or
  `# base station alive - no data for 20 s (forwarded 1234, ignored 0, other senders 0, lost 0)`.
- Commands: `INFO` (or `STATUS`) answers
  `{"base":{"fw":"1.0.1","channel":1,"mac":"24:6F:28:AA:BB:CC","kit":"24:6F:28:11:22:33","rx":1234,"ignored":0,"other":0,"lost":0,"last_rssi":-61}}`
  (`kit` = the forwarded field kit, or `"any"`; `last_rssi` only after a packet arrived)
  and `#` lines. `PAIR` and `UNPAIR` as above. `HELP` lists this.
  `TIME`, `LOG ...` are **not forwarded** to the kit (the base station answers with a
  `#` line); use the kit's own USB port for logging commands.
- Data through the base station contains `unix` only if the kit itself knows the time.
  The app may also time-stamp lines when they arrive.

---

## 9. Notes for using the values

- **Albedo** = `lux_down * k / lux_up`, where `k` is the pair calibration factor
  (UP/DOWN ratio measured with both sensors side by side facing up, see WIRING.md,
  ideal `k` = 1). Only meaningful in daylight with both values present (no `sat_*`
  key). The BH1750 measures visible light weighted like the human eye, so this is a
  "visible albedo". In the app, `k` is typed in the field kit panel ("Albedo calibration
  k", default 1 = not calibrated, kept in the browser). The app computes albedo only
  when `lux_up` is above 1000 lux and the sun is at least 20 degrees above the horizon
  (calculated from the kit location and the time; with a lower sun the angle errors of
  the sensors dominate), and it shows the median of the last minute. Otherwise it says
  why: a sensor saturated or missing, no daylight, or the sun too low.
- **Pressure** `p` is the absolute pressure at the kit. To compare with a weather
  report (QNH, sea level): `QNH = p / (1 - 2.25577e-5 * h)^5.25588`, `h` = elevation
  of the kit in metres.
- **surf** uses emissivity 1.0. Natural ground has an emissivity a little below 1, so
  `surf` can read slightly low; keep the setting the same for all measurements.
- **uv** is the module's approximation (UV index = Vout / 0.1 V), not a calibrated
  UV radiometer.
- **ground** depth is not known to the kit: the user should enter it (e.g. 5 cm).
