/*
  ============================================================================
  Analog Atlas - FIELD KIT firmware                                    v1.0.1
  NASA Space Apps Challenge 2026 - Amman
  ============================================================================
  Board : ESP32 DevKit V1 (ESP32-WROOM-32)
          Arduino IDE: Tools > Board > esp32 > "ESP32 Dev Module"
  Core  : "esp32 by Espressif" 3.3.x (Boards Manager)
  Libs  : OneWire, DallasTemperature, BH1750 (by Christopher Laws) - Library Manager
          The BME280/BMP280 (baro.h) and the MLX90614 (mlxReadTemp below) are read
          with small built-in functions that check every I2C transfer.

  WHAT IT DOES
  - Every second it reads all sensors and prints ONE line of JSON on USB (115200 baud):
      {"t":12345,"unix":1791500000,"air":24.12,"rh":38.0,"p":91.234,"uv":5.2,"uv_mv":520,
       "ground":31.06,"surf":33.51,"amb":29.80,"lux_up":52000.0,"lux_down":15000.0}
    When a sensor is missing or gives a bad value, its key is LEFT OUT.
    This program never prints made-up numbers (no 0 or -127 as a "placeholder").
    Two kinds of "limit" keys tell what we know when a value is out of range:
      "uv_lt":1.0              UV index is below 1.0 (too little UV for the ESP32 ADC)
      "sat_up":1, "sat_down":1 that BH1750 is at its ceiling (too bright to measure)
  - Lines that start with '#' are messages for people (errors and hints).
    A missing sensor is reported once; the kit looks for it again every 10 s
    without repeating the message, and prints a line when it is found.
  - Every 10 seconds it prints a status line: {"status":{...}}
  - It can save one row every N seconds into its own flash memory (file /log.csv),
    also when no computer is connected (power bank). Logging starts again by
    itself after a power cut.
  - Commands: type HELP in the Serial Monitor (115200 baud, line ending "Newline").

  For the app: firmware/PROTOCOL.md      Wiring and sensor tests: firmware/WIRING.md
*/

// ============================ SETTINGS YOU MAY CHANGE ============================

// Optional Wi-Fi, ONLY used to get the correct time from the internet (NTP) at
// power-up. Leave "" to skip. A phone hotspot works. Do not share this file
// after you typed your password into it.
#define WIFI_SSID ""
#define WIFI_PASS ""

// Optional: 1 = also send every JSON line by ESP-NOW radio to the base station
// (firmware/base_station). The USB output does not change.
#ifndef ESPNOW_SEND
#define ESPNOW_SEND 0
#endif

// 1 = a GUVA-S12SD UV sensor is connected to GPIO34. Set 0 if it is not:
// an unconnected analog pin gives random numbers, and we must not print them.
#ifndef UV_SENSOR_FITTED
#define UV_SENSOR_FITTED 1
#endif

// ================================== LIBRARIES ===================================
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <BH1750.h>
#include <stdarg.h>
#include <time.h>
#include <sys/time.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <esp_sntp.h>
#include "baro.h"
#if ESPNOW_SEND
#include <esp_now.h>
#include <esp_wifi.h>
#endif

// ===================================== PINS =====================================
const int PIN_SDA = 21;      // I2C data  (BME280, MLX90614, 2x BH1750)
const int PIN_SCL = 22;      // I2C clock
const int PIN_ONEWIRE = 4;   // DS18B20 data wire, with a 4.7 kOhm resistor to 3V3
const int PIN_UV = 34;       // GUVA-S12SD analog output (ADC1, input-only pin)
const int PIN_LED = 2;       // blue LED on the board: blinks at every reading

// ================================ I2C ADDRESSES =================================
const uint8_t ADDR_BH_UP = 0x23;    // BH1750 facing UP   (its ADDR pin to GND)
const uint8_t ADDR_BH_DOWN = 0x5C;  // BH1750 facing DOWN (its ADDR pin to 3V3)
const uint8_t ADDR_MLX = 0x5A;      // MLX90614 (GY-906 board)
const uint8_t BARO_ADDRS[2] = {0x76, 0x77};  // BME280/BMP280: 0x76 (SDO to GND) or 0x77 (SDO to 3V3)

// ================================= FIXED VALUES =================================
const char FW_VERSION[] = "1.0.1";
const uint32_t READ_PERIOD_MS = 1000;     // one reading per second
const uint32_t STATUS_PERIOD_MS = 10000;  // status line every 10 s
const uint32_t RETRY_PERIOD_MS = 10000;   // try missing sensors again every 10 s
const uint32_t WIFI_TIMEOUT_MS = 15000;   // Wi-Fi + NTP time: give up after 15 s
const uint8_t ESPNOW_CHANNEL = 1;         // the base station listens on Wi-Fi channel 1
const uint8_t FAILS_BEFORE_LOST = 3;      // 3 bad readings in a row = sensor lost
const uint32_t WARN_EVERY_MS = 60000;     // repeat the same warning at most once a minute

// BH1750 "measurement time" register (MTreg). The library default 69 ends at
// 65535 counts / 1.2 = 54 612 lux, but full sun can be about 100 000 lux.
// 31 is the smallest allowed value: the range grows to 65535 / 1.2 * 69 / 31
// = 121 557 lux and one step is about 1.9 lux. If a sensor is still at its
// ceiling we send "sat_up":1 / "sat_down":1 instead of a lux value.
const uint8_t BH_MTREG = 31;
const float BH_MAX_COUNT = 65535.0f;
const float BH_MAX_LUX = BH_MAX_COUNT / 1.2f * 69.0f / BH_MTREG;  // 121557.3 lux

// UV sensor (GUVA-S12SD): UV index = output voltage / 0.1 V (module documentation).
// We use the ESP32 ADC with 2.5 dB attenuation: it measures about 100 mV .. 1250 mV
// (UV index 1.0 .. 12.5). Below 100 mV we only know "UV index < 1.0".
const int UV_SAMPLES = 16;
const int UV_MIN_MV = 100;          // lowest voltage the ADC measures well at 2.5 dB
const int UV_MAX_MV = 1250;         // highest voltage the ADC measures at 2.5 dB
const int UV_MAX_SPREAD_MV = 100;   // middle samples spread more than this = loose wire
const int UV_RAW_FULL_SCALE = 4095;

// Log file (LittleFS in the "spiffs" flash partition, about 1.4 MB)
const char LOG_PATH[] = "/log.csv";
const char BOOT_PATH[] = "/boot.txt";
const char CFG_PATH[] = "/cfg.txt";
const char CSV_HEADER[] = "unix,boot,ms,air,rh,p,uv,ground,surf,lux_up,lux_down";
const uint32_t LOG_DEFAULT_S = 60, LOG_MIN_S = 1, LOG_MAX_S = 86400;
const size_t LOG_STOP_FREE_BYTES = 32 * 1024;  // stop logging when less than 32 KB are free
const uint32_t FS_CHECK_EVERY_MS = 10000;

// A time before 2024-01-01 or after 2099 must be a mistake.
const int64_t MIN_VALID_UNIX = 1704067200LL;
const int64_t MAX_VALID_UNIX = 4102444800LL;

// Datasheet limits. A value outside these limits is an error, not a measurement.
const float AIR_MIN_C = -40.0f, AIR_MAX_C = 85.0f;       // BME280/BMP280
const float P_MIN_KPA = 30.0f, P_MAX_KPA = 110.0f;        // 300..1100 hPa
const float DS_MIN_C = -55.0f, DS_MAX_C = 125.0f;         // DS18B20
const float DS_POWER_ON_C = 85.0f;                         // DS18B20 value before any conversion
const float MLX_OBJ_MIN_C = -70.0f, MLX_OBJ_MAX_C = 380.0f;  // MLX90614 object (surface)
const float MLX_AMB_MIN_C = -40.0f, MLX_AMB_MAX_C = 125.0f;  // MLX90614 ambient (its own body)

// ==================================== TYPES =====================================
// One reading of all sensors. has... = false means "no valid value" (key left out).
struct Reading {
  int64_t upMs;      // time since power-up in ms (64 bit, never overflows)
  uint32_t ms;       // the same as millis() - this is the "t" key
  bool hasAir, hasRh, hasP, hasUv, hasUvBelow, hasGround, hasSurf, hasAmb, hasLuxUp, hasLuxDown;
  bool satUp, satDown;  // BH1750 at its ceiling: too bright to measure
  float air, rh, pKPa, uv, ground, surf, amb, luxUp, luxDown;
  int uvMv;
};

// One BH1750 light sensor.
struct LightSensor {
  BH1750 dev;
  uint8_t addr;
  const char *name;      // "UP" or "DOWN"
  const char *addrPin;   // wiring hint for the ADDR pin
  bool ok;
  uint8_t fails;
  uint32_t readyMs;      // first measurement is ready after this time
  uint32_t lastWarnMs;
};

// =================================== OBJECTS ====================================
Baro baro;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature ds18b20(&oneWire);
DeviceAddress dsAddr;
LightSensor lightUp = {BH1750(ADDR_BH_UP), ADDR_BH_UP, "UP", "ADDR pin to GND", false, 0, 0, 0};
LightSensor lightDown = {BH1750(ADDR_BH_DOWN), ADDR_BH_DOWN, "DOWN", "ADDR pin to 3V3", false, 0, 0, 0};

// ================================ GLOBAL STATE ==================================
bool baroOk = false;
uint8_t baroFails = 0;
uint32_t rhWarnMs = 0;
bool mlxOk = false;
uint8_t mlxFails = 0;
bool dsOk = false;
uint8_t dsFails = 0, dsCount = 0;
bool dsPending = false;    // a temperature conversion is running
uint32_t dsRequestMs = 0;
uint32_t uvWarnMs = 0;
bool retryQuiet = false;   // true while retryLostSensors() runs: "not found" lines are not repeated

bool timeKnown = false;
int64_t timeOffsetMs = 0;  // unix time in ms = timeOffsetMs + uptime in ms
const char *timeSource = "none";

bool fsOk = false;
uint32_t bootCount = 0;
bool logOn = false;
uint32_t logIntervalS = LOG_DEFAULT_S;
uint32_t logRows = 0;
int64_t nextLogUpMs = 0;
bool logSizeNotePending = false;
bool fsWarnedAlmostFull = false;
size_t fsFreeCached = 0;
uint32_t fsCheckedMs = 0;
bool fsCheckedOnce = false;

uint32_t nextReadMs = 0, lastStatusMs = 0, lastRetryMs = 0, ledOffMs = 0;
bool ledOn = false;
char cmdBuf[96];
size_t cmdLen = 0;
bool cmdOverflow = false;

#if ESPNOW_SEND
const uint8_t BROADCAST_MAC[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
bool espnowOk = false;
uint32_t espnowErrors = 0;
#endif

// "printf" for the '#' lines. The attribute lets the compiler check the formats.
void note(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void noteFail(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void addf(char *buf, size_t size, size_t &len, const char *fmt, ...) __attribute__((format(printf, 4, 5)));

// =================================== HELPERS ====================================

// Prints a message line for people: "# ..."
void vnote(const char *fmt, va_list ap) {
  char buf[220];
  vsnprintf(buf, sizeof(buf), fmt, ap);
  Serial.print("# ");
  Serial.println(buf);
}

void note(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vnote(fmt, ap);
  va_end(ap);
}

// Like note(), for "sensor not found" lines: printed at start-up, but not again at every
// retry (every 10 s), so a kit without one sensor does not push the useful messages out.
void noteFail(const char *fmt, ...) {
  if (retryQuiet) return;
  va_list ap;
  va_start(ap, fmt);
  vnote(fmt, ap);
  va_end(ap);
}

// Adds formatted text to buf (like printf) and never writes past the end.
void addf(char *buf, size_t size, size_t &len, const char *fmt, ...) {
  if (len + 1 >= size) return;
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf + len, size - len, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  len += (size_t)n;
  if (len >= size) len = size - 1;  // text was cut (the buffers are big enough, this is a safety net)
}

// Time since power-up in milliseconds (64 bit: no overflow after 49 days like millis()).
int64_t uptimeMs() {
  return esp_timer_get_time() / 1000;
}

// Unix time (seconds) of a moment given as uptime in ms. Only valid when timeKnown.
unsigned long unixAt(int64_t upMs) {
  return (unsigned long)((timeOffsetMs + upMs) / 1000);
}

// true if a device answers at this I2C address
bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

// Short text for the reason of the last reset (shown at start-up and in INFO).
const char *resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "pin";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "crash";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    default: return "other";
  }
}

void macText(char *out, size_t size) {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  snprintf(out, size, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

// ================================ FILE SYSTEM ===================================

bool readSmallFile(const char *path, char *buf, size_t size) {
  buf[0] = 0;
  if (!LittleFS.exists(path)) return false;
  File f = LittleFS.open(path, FILE_READ);
  if (!f) return false;
  size_t n = f.read((uint8_t *)buf, size - 1);
  buf[n] = 0;
  f.close();
  return true;
}

bool writeSmallFile(const char *path, const char *text) {
  File f = LittleFS.open(path, FILE_WRITE);
  if (!f) return false;
  size_t len = strlen(text);
  bool ok = (f.write((const uint8_t *)text, len) == len);
  f.close();
  return ok;
}

// Logging settings survive a power cut in /cfg.txt ("log=1" and "interval=60").
void saveConfig() {
  if (!fsOk) return;
  char buf[48];
  snprintf(buf, sizeof(buf), "log=%d\ninterval=%lu\n", logOn ? 1 : 0, (unsigned long)logIntervalS);
  if (!writeSmallFile(CFG_PATH, buf)) note("WARNING: could not save %s", CFG_PATH);
}

void loadConfig() {
  char buf[64];
  if (!readSmallFile(CFG_PATH, buf, sizeof(buf))) return;  // no file: logging off, 60 s
  const char *p = strstr(buf, "log=");
  if (p) logOn = (p[4] == '1');
  p = strstr(buf, "interval=");
  if (p) {
    unsigned long v = strtoul(p + 9, nullptr, 10);
    if (v >= LOG_MIN_S && v <= LOG_MAX_S) logIntervalS = (uint32_t)v;
  }
}

// Counts the data rows of /log.csv (all lines minus the header line).
uint32_t countLogRows() {
  if (!LittleFS.exists(LOG_PATH)) return 0;
  File f = LittleFS.open(LOG_PATH, FILE_READ);
  if (!f) return 0;
  uint8_t buf[512];
  uint32_t lines = 0;
  size_t n;
  while ((n = f.read(buf, sizeof(buf))) > 0) {
    for (size_t i = 0; i < n; i++) {
      if (buf[i] == '\n') lines++;
    }
  }
  f.close();
  return lines > 0 ? lines - 1 : 0;
}

size_t fsFreeBytes() {
  size_t total = LittleFS.totalBytes();
  size_t used = LittleFS.usedBytes();
  return used < total ? total - used : 0;
}

void startFilesystem() {
  // true = format the flash area the first time it is used (or if it is broken)
  fsOk = LittleFS.begin(true);
  if (!fsOk) {
    note("ERROR: flash file system (LittleFS) does not work - logging is OFF.");
    note("Check Tools > Partition Scheme = \"Default 4MB with spiffs\" and upload again.");
    return;
  }
  char buf[24];
  bootCount = 1;
  if (readSmallFile(BOOT_PATH, buf, sizeof(buf))) bootCount = (uint32_t)strtoul(buf, nullptr, 10) + 1;
  snprintf(buf, sizeof(buf), "%lu\n", (unsigned long)bootCount);
  if (!writeSmallFile(BOOT_PATH, buf)) note("WARNING: could not save the boot counter");
  loadConfig();
  logRows = countLogRows();
  fsFreeCached = fsFreeBytes();
  fsCheckedMs = millis();
  fsCheckedOnce = true;
  note("flash memory: %u KB free of %u KB, %s has %lu rows", (unsigned)(fsFreeCached / 1024),
       (unsigned)(LittleFS.totalBytes() / 1024), LOG_PATH, (unsigned long)logRows);
}

// ================================ SENSOR SET-UP =================================

bool initBaro() {
  baroOk = false;
  baroFails = 0;
  bool someone = false;
  for (uint8_t addr : BARO_ADDRS) {
    uint8_t id = 0;
    if (!Baro::readChipId(Wire, addr, id)) continue;  // nobody at this address
    someone = true;
    if (baro.begin(Wire, addr)) {
      baroOk = true;
      if (baro.kind() == Baro::BMP280) {
        note("BMP280 found at 0x%02X (chip id 0x%02X): air temperature + pressure. A BMP280 has NO humidity sensor, so \"rh\" is left out.",
             addr, id);
      } else {
        note("BME280 found at 0x%02X (chip id 0x%02X): air temperature, humidity, pressure", addr, id);
      }
      return true;
    }
    noteFail("0x%02X answers with chip id 0x%02X (%s) - not a working BME280/BMP280", addr, id, Baro::chipName(id));
  }
  if (!someone) noteFail("BME280 not found at 0x76/0x77 - check SDA=%d SCL=%d, VCC to 3V3, GND", PIN_SDA, PIN_SCL);
  return false;
}

// CRC-8 (polynomial 0x07) = the "PEC" check byte that the MLX90614 sends.
uint8_t crc8(const uint8_t *data, size_t len) {
  uint8_t crc = 0;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}

// Reads one temperature register of the MLX90614: 0x06 = ambient (its own body),
// 0x07 = object (the surface it looks at). The PEC byte is checked, so a
// disturbed transfer can never become a wrong temperature.
bool mlxReadTemp(uint8_t reg, float &tempC) {
  Wire.beginTransmission(ADDR_MLX);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;  // repeated start
  if (Wire.requestFrom(ADDR_MLX, (size_t)3) != 3) return false;
  uint8_t lo = (uint8_t)Wire.read();
  uint8_t hi = (uint8_t)Wire.read();
  uint8_t pec = (uint8_t)Wire.read();
  const uint8_t frame[5] = {(uint8_t)(ADDR_MLX << 1), reg, (uint8_t)((ADDR_MLX << 1) | 1), lo, hi};
  if (crc8(frame, sizeof(frame)) != pec) return false;
  uint16_t raw = (uint16_t)lo | ((uint16_t)hi << 8);
  if (raw & 0x8000) return false;  // bit 15 = error flag of the sensor
  tempC = raw * 0.02f - 273.15f;   // 1 step = 0.02 K
  return true;
}

bool initMlx() {
  mlxOk = false;
  mlxFails = 0;
  if (!i2cPresent(ADDR_MLX)) {
    noteFail("MLX90614 not found at 0x5A - check SDA=%d SCL=%d, VIN to 3V3 (3 V 'BAA' version), GND", PIN_SDA, PIN_SCL);
    return false;
  }
  float ta;
  if (!mlxReadTemp(0x06, ta) || ta < MLX_AMB_MIN_C || ta > MLX_AMB_MAX_C) {
    noteFail("MLX90614 answers at 0x5A but its data fails the check (PEC) - check the wires and the supply (see WIRING.md: 3 V 'BAA' version)");
    return false;
  }
  mlxOk = true;
  note("MLX90614 found at 0x5A: surface (\"surf\") and sensor body (\"amb\") temperature");
  return true;
}

bool initLight(LightSensor &s) {
  s.ok = false;
  s.fails = 0;
  // Check first: the BH1750 library prints its own non-'#' error lines otherwise.
  if (!i2cPresent(s.addr)) {
    noteFail("BH1750 %s not found at 0x%02X - check SDA=%d SCL=%d and %s", s.name, s.addr, PIN_SDA, PIN_SCL, s.addrPin);
    return false;
  }
  if (!s.dev.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, s.addr, &Wire) || !s.dev.setMTreg(BH_MTREG)) {
    noteFail("BH1750 %s at 0x%02X answers but could not be set up", s.name, s.addr);
    return false;
  }
  s.ok = true;
  s.readyMs = millis() + 200;  // one measurement takes up to ~80 ms at this setting
  note("BH1750 %s found at 0x%02X (light from %s)", s.name, s.addr, s.addr == ADDR_BH_UP ? "the sky" : "the ground");
  return true;
}

bool initDs18b20() {
  dsOk = false;
  dsFails = 0;
  dsPending = false;
  ds18b20.begin();
  dsCount = ds18b20.getDS18Count();
  if (dsCount == 0 || !ds18b20.getAddress(dsAddr, 0)) {
    noteFail("DS18B20 not found on GPIO%d - check the 4.7 kOhm resistor from DATA to 3V3 and the 3 wires", PIN_ONEWIRE);
    return false;
  }
  ds18b20.setResolution(dsAddr, 12);    // 12 bit = 0.0625 C steps, 750 ms per conversion
  ds18b20.setWaitForConversion(false);  // do not wait: we collect the result 1 s later
  dsOk = true;
  note("DS18B20 found on GPIO%d: ROM %02X%02X%02X%02X%02X%02X%02X%02X%s", PIN_ONEWIRE, dsAddr[0], dsAddr[1], dsAddr[2],
       dsAddr[3], dsAddr[4], dsAddr[5], dsAddr[6], dsAddr[7],
       dsCount > 1 ? " (more than one sensor on the wire - using the first)" : "");
  if (ds18b20.isParasitePowerMode()) note("DS18B20 runs in 2-wire 'parasite' mode - better connect its red wire to 3V3");
  return true;
}

// Called every 10 s: try again every sensor that is not working. The "not found" lines are
// not repeated here (retryQuiet); a line is printed when a sensor is found again.
void retryLostSensors() {
  if (!baroOk && !mlxOk && !lightUp.ok && !lightDown.ok) {
    Wire.end();  // nothing on I2C works: restart the I2C bus as well
    Wire.begin(PIN_SDA, PIN_SCL, 100000);
  }
  retryQuiet = true;
  if (!baroOk) initBaro();
  if (!mlxOk) initMlx();
  if (!lightUp.ok) initLight(lightUp);
  if (!lightDown.ok) initLight(lightDown);
  if (!dsOk) initDs18b20();
  retryQuiet = false;
}

// ================================ SENSOR READING ================================

// Counts a failed reading. After FAILS_BEFORE_LOST failures in a row the sensor
// is marked as lost; retryLostSensors() then tries to find it again every 10 s.
bool countFail(uint8_t &fails, const char *name) {
  if (++fails < FAILS_BEFORE_LOST) return false;
  note("%s stopped giving valid data - will try again every 10 s", name);
  return true;
}

void readBaro(Reading &r) {
  if (!baroOk) return;
  float t, pPa, h;
  bool hOk;
  if (!baro.read(t, pPa, h, hOk)) {
    if (countFail(baroFails, baro.name())) {
      baroOk = false;
      baro.forget();
    }
    return;
  }
  float pKPa = pPa / 1000.0f;
  bool tOk = (t >= AIR_MIN_C && t <= AIR_MAX_C);
  bool pOk = (pKPa >= P_MIN_KPA && pKPa <= P_MAX_KPA);
  if (tOk) {
    r.hasAir = true;
    r.air = t;
  }
  if (pOk) {
    r.hasP = true;
    r.pKPa = pKPa;
  }
  if (hOk) {
    // The formula clamps to 0..100 %. Exactly 0 % means "below the formula's range",
    // which happens with a damaged humidity element, so we do not report it.
    if (h > 0.0f && h <= 100.0f) {
      r.hasRh = true;
      r.rh = h;
    } else if (warnDue(rhWarnMs)) {
      note("humidity reads 0 %% (lower limit of the sensor) - value left out");
    }
  }
  if (tOk || pOk) {
    baroFails = 0;
  } else if (countFail(baroFails, baro.name())) {
    baroOk = false;
    baro.forget();
  }
}

void readMlx(Reading &r) {
  if (!mlxOk) return;
  float to, ta;
  bool okO = mlxReadTemp(0x07, to) && to >= MLX_OBJ_MIN_C && to <= MLX_OBJ_MAX_C;
  bool okA = mlxReadTemp(0x06, ta) && ta >= MLX_AMB_MIN_C && ta <= MLX_AMB_MAX_C;
  if (okO) {
    r.hasSurf = true;
    r.surf = to;
  }
  if (okA) {
    r.hasAmb = true;
    r.amb = ta;
  }
  if (okO || okA) {
    mlxFails = 0;
  } else if (countFail(mlxFails, "MLX90614")) {
    mlxOk = false;
  }
}

// Sends MTreg and the measurement mode again. A BH1750 that lost power for a moment
// would fall back to its default MTreg 69 and stop measuring; the library would then
// convert its counts with the wrong factor. Sending this every second prevents that.
// (Written with Wire directly: no delay, and no non-'#' error lines from the library.)
bool bhRefresh(uint8_t addr) {
  const uint8_t cmds[3] = {
    (uint8_t)(0x40 | (BH_MTREG >> 5)),    // MTreg high bits: 01000_xxx
    (uint8_t)(0x60 | (BH_MTREG & 0x1F)),  // MTreg low bits:  011_xxxxx
    (uint8_t)BH1750::CONTINUOUS_HIGH_RES_MODE,
  };
  for (uint8_t c : cmds) {
    Wire.beginTransmission(addr);
    Wire.write(c);
    if (Wire.endTransmission() != 0) return false;
  }
  return true;
}

void readLight(LightSensor &s, bool &has, float &lux, bool &sat) {
  has = false;
  sat = false;
  if (!s.ok) return;
  if ((int32_t)(millis() - s.readyMs) < 0) return;  // first measurement not finished yet
  char name[16];
  snprintf(name, sizeof(name), "BH1750 %s", s.name);
  float v = s.dev.readLightLevel();  // -1 = I2C error
  if (v < 0.0f) {
    if (countFail(s.fails, name)) s.ok = false;
    return;
  }
  s.fails = 0;
  // Refresh the settings for the NEXT reading (about 1 s from now: plenty of time).
  if (!bhRefresh(s.addr) && countFail(s.fails, name)) s.ok = false;
  // Back to the raw sensor count: 65535 means "too bright to measure" (saturated).
  float count = v * 1.2f * BH_MTREG / 69.0f;
  if (count >= BH_MAX_COUNT - 0.5f) {
    sat = true;  // at the ceiling: the real light level is unknown (higher)
    if (warnDue(s.lastWarnMs)) {
      note("BH1750 %s is saturated (more than %.0f lux) - lux left out, \"sat_%s\":1 sent instead", s.name,
           BH_MAX_LUX, s.addr == ADDR_BH_UP ? "up" : "down");
    }
    return;
  }
  has = true;
  lux = v;
}

// DS18B20 without waiting: we start a conversion now and pick up its result
// in the next cycle (1 s later, the conversion needs at most 750 ms).
void readDs18b20(Reading &r) {
  if (!dsOk) return;
  uint32_t now = millis();
  if (dsPending && now - dsRequestMs >= DallasTemperature::millisToWaitForConversion(12)) {
    dsPending = false;
    float t = ds18b20.getTempC(dsAddr);
    // -127 = no answer / bad checksum, 85 = power-up value (no real conversion)
    if (t != DEVICE_DISCONNECTED_C && t != DS_POWER_ON_C && t >= DS_MIN_C && t <= DS_MAX_C) {
      r.hasGround = true;
      r.ground = t;
      dsFails = 0;
    } else if (countFail(dsFails, "DS18B20")) {
      dsOk = false;
      return;
    }
  }
  if (!dsPending) {
    if (ds18b20.requestTemperaturesByAddress(dsAddr)) {
      dsPending = true;
      dsRequestMs = now;
    } else if (countFail(dsFails, "DS18B20")) {
      dsOk = false;
    }
  }
}

// true at most once per WARN_EVERY_MS for the same warning (lastMs remembers the time)
bool warnDue(uint32_t &lastMs) {
  if (lastMs != 0 && millis() - lastMs < WARN_EVERY_MS) return false;
  lastMs = millis();
  if (lastMs == 0) lastMs = 1;  // 0 means "never warned"
  return true;
}

// Sorts a small array (insertion sort).
void sortInts(int *v, int n) {
  for (int i = 1; i < n; i++) {
    int x = v[i], j = i - 1;
    while (j >= 0 && v[j] > x) {
      v[j + 1] = v[j];
      j--;
    }
    v[j + 1] = x;
  }
}

void readUv(Reading &r) {
#if UV_SENSOR_FITTED
  int mv[UV_SAMPLES], raw[UV_SAMPLES];
  for (int i = 0; i < UV_SAMPLES; i++) {
    raw[i] = analogRead(PIN_UV);              // 0..4095
    mv[i] = (int)analogReadMilliVolts(PIN_UV);  // calibrated millivolts
  }
  sortInts(mv, UV_SAMPLES);
  sortInts(raw, UV_SAMPLES);
  // Average of the middle 8 of 16 samples: single spikes of the ESP32 ADC do not count.
  long sum = 0;
  for (int i = UV_SAMPLES / 4; i < UV_SAMPLES * 3 / 4; i++) sum += mv[i];
  int avgMv = (int)((sum + UV_SAMPLES / 4) / (UV_SAMPLES / 2));
  int spread = mv[UV_SAMPLES * 3 / 4 - 1] - mv[UV_SAMPLES / 4];
  int medianRaw = raw[UV_SAMPLES / 2];

  if (spread > UV_MAX_SPREAD_MV) {
    if (warnDue(uvWarnMs)) {
      note("UV reading unstable (middle samples spread %d mV, limit %d mV) - check the GUVA-S12SD OUT wire on GPIO%d",
           spread, UV_MAX_SPREAD_MV, PIN_UV);
    }
    return;
  }
  if (medianRaw >= UV_RAW_FULL_SCALE) {
    if (warnDue(uvWarnMs)) {
      note("UV sensor output is above the ADC range (about %d mV = UV index %.1f) - value left out; check wiring",
           UV_MAX_MV, UV_MAX_MV / 100.0f);
    }
    return;
  }
  if (medianRaw > 100 && avgMv == 0) {
    if (warnDue(uvWarnMs)) note("ESP32 ADC calibration missing (raw %d but 0 mV) - UV left out", medianRaw);
    return;
  }
  if (avgMv < UV_MIN_MV) {
    r.hasUvBelow = true;  // we only know: UV index < 1.0
    return;
  }
  r.hasUv = true;
  r.uvMv = avgMv;
  r.uv = avgMv / 100.0f;  // UV index = Vout / 0.1 V
#else
  (void)r;
#endif
}

// ===================================== OUTPUT ===================================

// Builds the one-line JSON object for a reading (keys of missing values are left out).
void buildJson(const Reading &r, char *out, size_t size) {
  size_t n = 0;
  out[0] = 0;
  addf(out, size, n, "{\"t\":%lu", (unsigned long)r.ms);
  if (timeKnown) addf(out, size, n, ",\"unix\":%lu", unixAt(r.upMs));
  if (r.hasAir) addf(out, size, n, ",\"air\":%.2f", r.air);
  if (r.hasRh) addf(out, size, n, ",\"rh\":%.1f", r.rh);
  if (r.hasP) addf(out, size, n, ",\"p\":%.3f", r.pKPa);
  if (r.hasUv) addf(out, size, n, ",\"uv\":%.1f,\"uv_mv\":%d", r.uv, r.uvMv);
  if (r.hasUvBelow) addf(out, size, n, ",\"uv_lt\":%.1f", UV_MIN_MV / 100.0f);
  if (r.hasGround) addf(out, size, n, ",\"ground\":%.2f", r.ground);
  if (r.hasSurf) addf(out, size, n, ",\"surf\":%.2f", r.surf);
  if (r.hasAmb) addf(out, size, n, ",\"amb\":%.2f", r.amb);
  if (r.hasLuxUp) addf(out, size, n, ",\"lux_up\":%.1f", r.luxUp);
  if (r.satUp) addf(out, size, n, ",\"sat_up\":1");
  if (r.hasLuxDown) addf(out, size, n, ",\"lux_down\":%.1f", r.luxDown);
  if (r.satDown) addf(out, size, n, ",\"sat_down\":1");
  addf(out, size, n, "}");
}

#if ESPNOW_SEND
void espnowSend(const char *line) {
  if (!espnowOk) return;
  size_t len = strlen(line);
  if (len == 0 || len > ESP_NOW_MAX_DATA_LEN) return;
  if (esp_now_send(BROADCAST_MAC, (const uint8_t *)line, len) != ESP_OK) espnowErrors++;
}
#endif

// Prints a JSON line on USB (and sends it by ESP-NOW when that is switched on).
void emitJson(const char *line) {
  Serial.println(line);
#if ESPNOW_SEND
  espnowSend(line);
#endif
}

void printStatus() {
  char line[240];
  size_t n = 0;
  addf(line, sizeof(line), n, "{\"status\":{\"fw\":\"%s\",\"bme\":\"%s\",\"log\":%s,\"interval\":%lu", FW_VERSION,
       baroOk ? baro.name() : "none", logOn ? "true" : "false", (unsigned long)logIntervalS);
  if (fsOk) {
    if (millis() - fsCheckedMs >= FS_CHECK_EVERY_MS || !fsCheckedOnce) {
      fsFreeCached = fsFreeBytes();
      fsCheckedMs = millis();
      fsCheckedOnce = true;
    }
    addf(line, sizeof(line), n, ",\"rows\":%lu", (unsigned long)logRows);
  }
  addf(line, sizeof(line), n, ",\"time\":%s", timeKnown ? "true" : "false");
  if (fsOk) {  // without the file system the boot counter is unknown: leave it out
    addf(line, sizeof(line), n, ",\"free_kb\":%u,\"boot\":%lu", (unsigned)(fsFreeCached / 1024), (unsigned long)bootCount);
  }
  addf(line, sizeof(line), n, "}}");
  emitJson(line);
}

void printInfo() {
  printStatus();
  char mac[18];
  macText(mac, sizeof(mac));
  char line[240];
  size_t n = 0;
  addf(line, sizeof(line), n, "{\"info\":{\"fw\":\"%s\"", FW_VERSION);
  if (fsOk) addf(line, sizeof(line), n, ",\"boot\":%lu", (unsigned long)bootCount);
  addf(line, sizeof(line), n, ",\"reset\":\"%s\",\"mac\":\"%s\"", resetReason(), mac);
  addf(line, sizeof(line), n, ",\"bme\":\"%s\"", baroOk ? baro.name() : "none");
  if (baroOk) addf(line, sizeof(line), n, ",\"bme_addr\":\"0x%02X\"", baro.address());
  addf(line, sizeof(line), n, ",\"mlx\":%s,\"bh_up\":%s,\"bh_down\":%s,\"ds18b20\":%u", mlxOk ? "true" : "false",
       lightUp.ok ? "true" : "false", lightDown.ok ? "true" : "false", dsOk ? (unsigned)dsCount : 0u);
  addf(line, sizeof(line), n, ",\"uv\":%s,\"time_src\":\"%s\",\"espnow\":%s", UV_SENSOR_FITTED ? "true" : "false",
       timeSource, ESPNOW_SEND ? "true" : "false");
  if (fsOk) addf(line, sizeof(line), n, ",\"fs_kb\":%u", (unsigned)(LittleFS.totalBytes() / 1024));
  addf(line, sizeof(line), n, "}}");
  Serial.println(line);  // INFO is an answer to a USB command: not sent by ESP-NOW
  note("sensors: %s %s, MLX90614 %s, BH1750 UP %s, BH1750 DOWN %s, DS18B20 %s, UV %s", baroOk ? baro.name() : "BME280",
       baroOk ? "ok" : "MISSING", mlxOk ? "ok" : "MISSING", lightUp.ok ? "ok" : "MISSING",
       lightDown.ok ? "ok" : "MISSING", dsOk ? "ok" : "MISSING", UV_SENSOR_FITTED ? "fitted (GPIO34)" : "not fitted");
#if ESPNOW_SEND
  note("ESP-NOW: %s on channel %u, send errors %lu", espnowOk ? "on" : "FAILED", ESPNOW_CHANNEL, (unsigned long)espnowErrors);
#endif
}

void printHelp() {
  note("Commands (end with Enter / newline, upper or lower case):");
  note("  HELP             this list");
  note("  INFO             status line + sensor list");
  note("  STATUS           status line only");
  note("  TIME <unix>      set the clock in Unix seconds, e.g. TIME 1791500000 (the app does this)");
  note("  LOG START [s]    save a row every s seconds (default 60, %lu..%lu); goes on after a power cut",
       (unsigned long)LOG_MIN_S, (unsigned long)LOG_MAX_S);
  note("  LOG STOP         stop saving rows (the saved rows stay)");
  note("  LOG DUMP         print all rows as CSV between #LOG BEGIN and #LOG END");
  note("  LOG CLEAR        delete all saved rows");
}

// ==================================== LOGGING ===================================

void stopLogging(const char *why) {
  logOn = false;
  saveConfig();
  note("LOG STOPPED: %s. The rows are kept: save them with LOG DUMP, then LOG CLEAR.", why);
  printStatus();
}

// Appends one CSV row to /log.csv. Empty field = no valid value.
void logRow(const Reading &r) {
  if (!fsOk) {
    stopLogging("the flash file system does not work");
    return;
  }
  if (!fsCheckedOnce || millis() - fsCheckedMs >= FS_CHECK_EVERY_MS) {  // checking takes some time
    fsFreeCached = fsFreeBytes();
    fsCheckedMs = millis();
    fsCheckedOnce = true;
  }
  if (fsFreeCached < LOG_STOP_FREE_BYTES) {
    stopLogging("the flash memory is full");
    return;
  }
  if (!fsWarnedAlmostFull && fsFreeCached < LittleFS.totalBytes() / 10) {
    fsWarnedAlmostFull = true;
    note("WARNING: log memory is 90%% full (%u KB free) - save it with LOG DUMP, then LOG CLEAR", (unsigned)(fsFreeCached / 1024));
  }

  char row[200];
  size_t n = 0;
  row[0] = 0;
  if (timeKnown) addf(row, sizeof(row), n, "%lu", unixAt(r.upMs));
  addf(row, sizeof(row), n, ",%lu,%lu,", (unsigned long)bootCount, (unsigned long)r.ms);
  if (r.hasAir) addf(row, sizeof(row), n, "%.2f", r.air);
  addf(row, sizeof(row), n, ",");
  if (r.hasRh) addf(row, sizeof(row), n, "%.1f", r.rh);
  addf(row, sizeof(row), n, ",");
  if (r.hasP) addf(row, sizeof(row), n, "%.3f", r.pKPa);
  addf(row, sizeof(row), n, ",");
  if (r.hasUv) addf(row, sizeof(row), n, "%.1f", r.uv);
  else if (r.hasUvBelow) addf(row, sizeof(row), n, "<%.1f", UV_MIN_MV / 100.0f);
  addf(row, sizeof(row), n, ",");
  if (r.hasGround) addf(row, sizeof(row), n, "%.2f", r.ground);
  addf(row, sizeof(row), n, ",");
  if (r.hasSurf) addf(row, sizeof(row), n, "%.2f", r.surf);
  addf(row, sizeof(row), n, ",");
  if (r.hasLuxUp) addf(row, sizeof(row), n, "%.1f", r.luxUp);
  else if (r.satUp) addf(row, sizeof(row), n, ">%.0f", BH_MAX_LUX);  // saturated: "more than"
  addf(row, sizeof(row), n, ",");
  if (r.hasLuxDown) addf(row, sizeof(row), n, "%.1f", r.luxDown);
  else if (r.satDown) addf(row, sizeof(row), n, ">%.0f", BH_MAX_LUX);
  addf(row, sizeof(row), n, "\n");

  File f = LittleFS.open(LOG_PATH, FILE_APPEND);
  if (!f) {
    stopLogging("cannot open the log file");
    return;
  }
  bool ok = true;
  if (f.size() == 0) {  // new file: write the header line first
    size_t hl = strlen(CSV_HEADER);
    ok = (f.write((const uint8_t *)CSV_HEADER, hl) == hl) && (f.write((const uint8_t *)"\n", 1) == 1);
  }
  ok = ok && (f.write((const uint8_t *)row, n) == n);
  f.close();  // closing saves the data: a power cut later cannot lose this row
  if (!ok) {
    stopLogging("write error (flash full?)");
    return;
  }
  logRows++;
  fsFreeCached = (fsFreeCached > n) ? fsFreeCached - n : 0;  // estimate until the next real check
  if (logSizeNotePending) {
    logSizeNotePending = false;
    double bytesPerDay = (double)n * (86400.0 / logIntervalS);
    note("first row saved (%u bytes). With %u KB free this is enough for about %.1f days at one row every %lu s",
         (unsigned)n, (unsigned)(fsFreeCached / 1024), (double)fsFreeCached / bytesPerDay, (unsigned long)logIntervalS);
  }
}

void dumpLog() {
  if (!fsOk) {
    note("ERR no flash file system - nothing to dump");
    return;
  }
  note("LOG DUMP: %lu rows", (unsigned long)logRows);
  Serial.println("#LOG BEGIN");
  File f;
  if (LittleFS.exists(LOG_PATH)) f = LittleFS.open(LOG_PATH, FILE_READ);
  if (!f || f.size() == 0) {
    Serial.println(CSV_HEADER);  // empty log: only the header
  } else {
    uint8_t buf[256];
    size_t n;
    uint8_t last = '\n';
    while ((n = f.read(buf, sizeof(buf))) > 0) {
      Serial.write(buf, n);
      last = buf[n - 1];
    }
    if (last != '\n') Serial.println();
  }
  if (f) f.close();
  Serial.println("#LOG END");
}

void clearLog() {
  if (!fsOk) {
    note("ERR no flash file system");
    return;
  }
  if (LittleFS.exists(LOG_PATH) && !LittleFS.remove(LOG_PATH)) {
    note("ERR could not delete %s", LOG_PATH);
    return;
  }
  logRows = 0;
  fsWarnedAlmostFull = false;
  fsCheckedOnce = false;
  note("log cleared%s", logOn ? " - logging goes on into a new file" : "");
  printStatus();
}

// ==================================== COMMANDS ==================================

// Sets the clock. Unix seconds, decimals allowed (e.g. 1791500000.250).
void setTimeFromCommand(const char *arg) {
  char *end = nullptr;
  double v = strtod(arg, &end);
  while (end && *end == ' ') end++;
  // written so that "NAN" or "INF" also fail (every comparison with NaN is false)
  bool ok = (end != arg) && (end && *end == 0) && (v >= (double)MIN_VALID_UNIX) && (v < (double)MAX_VALID_UNIX);
  if (!ok) {
    note("ERR TIME needs Unix time in SECONDS (10 digits), e.g. TIME 1791500000");
    return;
  }
  timeOffsetMs = (int64_t)(v * 1000.0 + 0.5) - uptimeMs();
  timeKnown = true;
  timeSource = "usb";
  note("time set: unix %lu", unixAt(uptimeMs()));
  printStatus();
}

void startLogging(const char *arg) {
  unsigned long s = LOG_DEFAULT_S;
  if (*arg) {
    char *end = nullptr;
    s = strtoul(arg, &end, 10);
    while (end && *end == ' ') end++;
    if (end == arg || (end && *end != 0) || s < LOG_MIN_S || s > LOG_MAX_S) {
      note("ERR use LOG START <seconds> with %lu..%lu, e.g. LOG START 60", (unsigned long)LOG_MIN_S, (unsigned long)LOG_MAX_S);
      return;
    }
  }
  if (!fsOk) {
    note("ERR cannot log: the flash file system does not work");
    return;
  }
  bool wasOn = logOn;
  logIntervalS = (uint32_t)s;
  logOn = true;
  nextLogUpMs = 0;  // first row at the next reading
  logSizeNotePending = true;
  fsCheckedOnce = false;
  saveConfig();
  note("logging %s: one row every %lu s into %s (it goes on after a power cut)", wasOn ? "changed" : "ON",
       (unsigned long)s, LOG_PATH);
  if (!timeKnown) note("time unknown: the 'unix' column stays empty until TIME is sent (see PROTOCOL.md)");
  printStatus();
}

void runCommand(char *line) {
  // trim spaces at both ends and make it upper case
  while (*line == ' ' || *line == '\t') line++;
  size_t len = strlen(line);
  while (len > 0 && (line[len - 1] == ' ' || line[len - 1] == '\t')) line[--len] = 0;
  if (len == 0) return;
  for (char *c = line; *c; c++) *c = (char)toupper((unsigned char)*c);
  // collapse runs of spaces: "LOG   START  60" -> "LOG START 60"
  char *w = line;
  for (char *c = line; *c; c++) {
    if (*c == '\t') *c = ' ';
    if (*c == ' ' && w > line && w[-1] == ' ') continue;
    *w++ = *c;
  }
  *w = 0;

  if (!strcmp(line, "HELP") || !strcmp(line, "?")) {
    printHelp();
  } else if (!strcmp(line, "INFO")) {
    printInfo();
  } else if (!strcmp(line, "STATUS")) {
    printStatus();
  } else if (!strncmp(line, "TIME ", 5)) {
    setTimeFromCommand(line + 5);
  } else if (!strcmp(line, "TIME")) {
    note("ERR TIME needs a value, e.g. TIME 1791500000");
  } else if (!strcmp(line, "LOG START") || !strncmp(line, "LOG START ", 10)) {
    startLogging(line[9] ? line + 10 : "");
  } else if (!strcmp(line, "LOG STOP")) {
    logOn = false;
    saveConfig();
    note("logging OFF (%lu rows kept)", (unsigned long)logRows);
    printStatus();
  } else if (!strcmp(line, "LOG DUMP")) {
    dumpLog();
  } else if (!strcmp(line, "LOG CLEAR")) {
    clearLog();
  } else {
    note("ERR unknown command '%s' - type HELP", line);
  }
}

// Collects characters from USB until a newline (or carriage return) arrives.
void handleSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdOverflow) {
        note("ERR command too long");
      } else {
        cmdBuf[cmdLen] = 0;
        runCommand(cmdBuf);
      }
      cmdLen = 0;
      cmdOverflow = false;
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    } else {
      cmdOverflow = true;
    }
  }
}

// ==================================== WIRELESS ==================================

// Optional: get the time from the internet once at power-up, then switch Wi-Fi off.
void syncTimeOverWifi() {
  if (strlen(WIFI_SSID) == 0) return;
  note("Wi-Fi: connecting to \"%s\" to get the time (max %lu s)...", WIFI_SSID, (unsigned long)(WIFI_TIMEOUT_MS / 1000));
  uint32_t start = millis();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) delay(100);
  if (WiFi.status() != WL_CONNECTED) {
    note("Wi-Fi: no connection within %lu s - time stays unknown until the app sends TIME",
         (unsigned long)(WIFI_TIMEOUT_MS / 1000));
  } else {
    note("Wi-Fi: connected, asking pool.ntp.org for the time...");
    configTime(0, 0, "pool.ntp.org");  // UTC, no daylight saving
    bool ok = false;
    while (millis() - start < WIFI_TIMEOUT_MS) {
      struct timeval tv;
      gettimeofday(&tv, nullptr);
      if ((int64_t)tv.tv_sec >= MIN_VALID_UNIX) {
        timeOffsetMs = (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000 - uptimeMs();
        timeKnown = true;
        timeSource = "ntp";
        ok = true;
        break;
      }
      delay(100);
    }
    if (ok) note("time from NTP: unix %lu", unixAt(uptimeMs()));
    else note("NTP: no answer within %lu s - time stays unknown until the app sends TIME", (unsigned long)(WIFI_TIMEOUT_MS / 1000));
    esp_sntp_stop();
  }
  WiFi.disconnect(true);  // leave the network and switch the Wi-Fi radio off (saves power)
  WiFi.mode(WIFI_OFF);
}

#if ESPNOW_SEND
// ESP-NOW: the ESP32 radio sends short packets without a router.
void startEspNow() {
  WiFi.mode(WIFI_STA);  // ESP-NOW needs the Wi-Fi radio in "station" mode
  WiFi.setAutoReconnect(false);
  WiFi.disconnect();    // not connected to a router, so we can choose the channel
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    note("ESP-NOW: could not start - data only on USB");
    return;
  }
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST_MAC, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    note("ESP-NOW: could not add the broadcast address - data only on USB");
    return;
  }
  espnowOk = true;
  char mac[18];
  macText(mac, sizeof(mac));
  note("ESP-NOW: on - every JSON line is also broadcast on Wi-Fi channel %u (this kit: %s)", ESPNOW_CHANNEL, mac);
}
#endif

// ================================== MAIN PARTS ==================================

void takeReading() {
  Reading r = {};
  r.upMs = uptimeMs();
  r.ms = (uint32_t)r.upMs;  // same value as millis()
  digitalWrite(PIN_LED, HIGH);
  ledOn = true;
  ledOffMs = millis() + 50;

  readBaro(r);
  readMlx(r);
  readLight(lightUp, r.hasLuxUp, r.luxUp, r.satUp);
  readLight(lightDown, r.hasLuxDown, r.luxDown, r.satDown);
  readDs18b20(r);
  readUv(r);

  char line[256];
  buildJson(r, line, sizeof(line));
  emitJson(line);

  // Logging: one row every logIntervalS seconds (500 ms tolerance for timing jitter)
  if (logOn && r.upMs + 500 >= nextLogUpMs) {
    int64_t step = (int64_t)logIntervalS * 1000;
    nextLogUpMs = (nextLogUpMs == 0) ? r.upMs + step : nextLogUpMs + step;
    if (nextLogUpMs <= r.upMs) nextLogUpMs = r.upMs + step;  // we were late (e.g. after LOG DUMP)
    logRow(r);
  }
}

void setup() {
  Serial.begin(115200);
  // Keep the USB output clean: only our JSON and '#' lines (no ESP-IDF log lines).
  // For debugging you can change ESP_LOG_NONE to ESP_LOG_ERROR.
  esp_log_level_set("*", ESP_LOG_NONE);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  delay(100);
  Serial.println();
  note("Analog Atlas field kit - firmware %s", FW_VERSION);
  note("last reset: %s", resetReason());
  if (esp_reset_reason() == ESP_RST_BROWNOUT) {
    note("WARNING: the last reset was a BROWNOUT - the power supply or USB cable is too weak");
  }

  startFilesystem();
  if (fsOk) note("this is boot number %lu (column 'boot' in the log)", (unsigned long)bootCount);

  Wire.begin(PIN_SDA, PIN_SCL, 100000);  // 100 kHz: the MLX90614 allows at most 100 kHz
  // Set the attenuation for ALL analog pins (not analogSetPinAttenuation): then
  // analogReadMilliVolts() uses the matching calibration.
  analogSetAttenuation(ADC_2_5db);
  analogReadResolution(12);

  initBaro();
  initMlx();
  initLight(lightUp);
  initLight(lightDown);
  initDs18b20();
#if UV_SENSOR_FITTED
  note("UV sensor (GUVA-S12SD) expected on GPIO%d - it cannot be detected automatically, check with tests/guva_s12sd_test",
       PIN_UV);
#else
  note("UV sensor not fitted (UV_SENSOR_FITTED 0): no \"uv\" values");
#endif

  syncTimeOverWifi();
#if ESPNOW_SEND
  startEspNow();
#endif
  if (!timeKnown) note("time unknown - send TIME <unix seconds> (the app does this when it connects)");
  if (logOn) {
    nextLogUpMs = 0;
    logSizeNotePending = true;
    note("logging resumed after power-up: one row every %lu s (send LOG STOP to stop)", (unsigned long)logIntervalS);
  }
  printStatus();
  note("type HELP for the list of commands");

  nextReadMs = millis();
  lastStatusMs = millis();
  lastRetryMs = millis();
}

void loop() {
  handleSerial();

  uint32_t now = millis();
  if ((int32_t)(now - nextReadMs) >= 0) {
    nextReadMs += READ_PERIOD_MS;
    if ((int32_t)(now - nextReadMs) >= 0) nextReadMs = now + READ_PERIOD_MS;  // we were late: start again
    takeReading();
  }
  if (millis() - lastStatusMs >= STATUS_PERIOD_MS) {
    lastStatusMs = millis();
    printStatus();
  }
  if (millis() - lastRetryMs >= RETRY_PERIOD_MS) {
    lastRetryMs = millis();
    retryLostSensors();
  }
  if (ledOn && (int32_t)(millis() - ledOffMs) >= 0) {
    digitalWrite(PIN_LED, LOW);
    ledOn = false;
  }
  delay(1);  // give other tasks a little time
}
