/*
  Analog Atlas - TEST 2: BME280 / BMP280 (air temperature, humidity, pressure)
  ---------------------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud.
  Libraries: "Adafruit BME280 Library" (+ "Adafruit Unified Sensor", "Adafruit BusIO").
  baro.h in this folder is the same driver as in field_kit/.

  What it does
  1. Reads the chip ID at 0x76 and 0x77: 0x60 = BME280, 0x58 = BMP280 (no humidity!).
  2. Every 2 s it reads the sensor with the field kit's driver (baro.h).
  3. For a BME280 it lets the Adafruit library calculate the SAME measurement and
     compares both ("driver check"). A BMP280 cannot be read by that library.
  4. If you set MY_ELEVATION_M below, it also prints the sea-level pressure (QNH),
     which you can compare with the airport weather report.

  PASS when
  - a chip ID 0x60 (BME280) or 0x58 (BMP280) is found,
  - "driver check PASS" is shown (BME280 only),
  - air temperature is within about 1 C of a good thermometer next to it
    (wait 10 minutes; keep both away from the ESP32, lamps, sun and your hands),
  - humidity rises fast when you breathe on the sensor and then slowly falls back,
  - QNH is within about 3 hPa of the airport report (your elevation must be
    right to about 10 m: 10 m of height = about 1 hPa).
*/

#include <Wire.h>
#include <math.h>
#include <Adafruit_BME280.h>
#include "baro.h"

// Your height above sea level where the sensor is, in WHOLE metres (from a map or
// GPS), e.g. 850. -1 = unknown (then no QNH is printed).
#define MY_ELEVATION_M -1

const int PIN_SDA = 21;
const int PIN_SCL = 22;

Baro baro;
Adafruit_BME280 ada;
bool ready = false;
bool adaOk = false;

// Looks for the sensor at 0x76 and 0x77 and sets it up.
bool findSensor() {
  bool someone = false;
  for (uint8_t a = 0x76; a <= 0x77; a++) {
    uint8_t id;
    if (!Baro::readChipId(Wire, a, id)) continue;
    someone = true;
    Serial.printf("0x%02X answers, chip ID = 0x%02X -> %s\n", a, id, Baro::chipName(id));
    if (id == 0x60) {
      // Adafruit library first (its begin() resets the chip), then our driver.
      adaOk = ada.begin(a, &Wire);
      if (adaOk) {
        ada.setSampling(Adafruit_BME280::MODE_FORCED, Adafruit_BME280::SAMPLING_X1, Adafruit_BME280::SAMPLING_X4,
                        Adafruit_BME280::SAMPLING_X1, Adafruit_BME280::FILTER_OFF);
      } else {
        Serial.println("  (the Adafruit library could not start - driver check skipped)");
      }
    } else if (id == 0x58 || id == 0x56 || id == 0x57) {
      Serial.println("  This is a BMP280: temperature + pressure only, NO humidity.");
      Serial.println("  (The Adafruit BME280 library cannot read it; the field kit's driver can.)");
      adaOk = false;
    } else {
      Serial.println("  Not a BME280/BMP280 - the field kit cannot use this chip.");
      continue;
    }
    if (baro.begin(Wire, a)) {
      Serial.printf("PASS: %s ready at 0x%02X\n", baro.name(), a);
      return true;
    }
    Serial.println("FAIL: the chip answers but could not be set up (loose wire?)");
  }
  if (!someone) {
    Serial.println("FAIL: nothing at 0x76/0x77. Check VCC/VIN -> 3V3, GND, SDA -> GPIO21, SCL -> GPIO22;");
    Serial.println("      on 6-pin boards also CSB -> 3V3 and SDO -> GND. Run tests/i2c_scanner.");
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 2: BME280 / BMP280 ===");
  Serial.println("Datasheet ranges: -40..85 C, 0..100 %, 300..1100 hPa (30..110 kPa).");
  Serial.println("Typical values: indoors about 15..35 C and 20..70 %; pressure in Amman (700..1100 m)");
  Serial.println("about 88..95 kPa, at sea level about 100..103 kPa.");
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  ready = findSensor();
}

void loop() {
  if (!ready) {
    delay(5000);
    Serial.println();
    ready = findSensor();
    return;
  }

  float t, pPa, h;
  bool hOk;
  if (!baro.read(t, pPa, h, hOk)) {
    Serial.println("FAIL: reading failed (I2C error) - check the wires. Searching again...");
    ready = false;
    return;
  }
  Serial.printf("%s 0x%02X | air %.2f C | ", baro.name(), baro.address(), t);
  if (hOk) Serial.printf("humidity %.1f %% | ", h);
  else Serial.print("humidity: none (BMP280) | ");
  Serial.printf("pressure %.3f kPa = %.2f hPa\n", pPa / 1000.0f, pPa / 100.0f);

  // Driver check: the Adafruit library reads the SAME measurement registers
  // (we do not start a new measurement), so both results must agree.
  if (adaOk && baro.kind() == Baro::BME280) {
    float t2 = ada.readTemperature();
    float p2 = ada.readPressure();
    float h2 = ada.readHumidity();
    float dT = fabsf(t - t2), dP = fabsf(pPa - p2), dH = hOk ? fabsf(h - h2) : 0.0f;
    bool pass = !isnan(t2) && !isnan(p2) && !isnan(h2) && dT <= 0.05f && dP <= 5.0f && dH <= 0.1f;
    Serial.printf("  Adafruit library: %.2f C, %.1f %%, %.3f kPa -> driver check %s (diff %.2f C, %.1f Pa, %.2f %%)\n",
                  t2, h2, p2 / 1000.0f, pass ? "PASS" : "FAIL", dT, dP, dH);
  }

  // Plausibility (datasheet limits)
  if (t < -40.0f || t > 85.0f) Serial.println("  FAIL: temperature outside the sensor range -40..85 C");
  if (pPa < 30000.0f || pPa > 110000.0f) Serial.println("  FAIL: pressure outside the sensor range 30..110 kPa");
  if (hOk && h <= 0.0f) Serial.println("  WARNING: humidity reads 0 % - damaged humidity sensor?");

#if MY_ELEVATION_M >= 0
  // Sea-level pressure (QNH) with the standard atmosphere: p0 = p / (1 - 2.25577e-5 * h)^5.25588
  float qnh = (pPa / 100.0f) / powf(1.0f - 2.25577e-5f * (float)MY_ELEVATION_M, 5.25588f);
  Serial.printf("  QNH for %d m: %.1f hPa - compare with the airport report (in a METAR it looks like Q1013)\n",
                (int)MY_ELEVATION_M, qnh);
#endif
  delay(2000);
}
