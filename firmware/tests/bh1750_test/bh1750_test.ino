/*
  Analog Atlas - TEST 4: two BH1750 light sensors (GY-302) - UP (0x23) and DOWN (0x5C)
  ------------------------------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud.
  Library: "BH1750" by Christopher Laws.

  The UP sensor measures the light coming from the sky, the DOWN sensor the light
  reflected by the ground. The app calculates albedo = lux_down * k / lux_up, where k is
  the pair calibration factor measured below (1 = not calibrated).

  Range: like the field kit we set the "measurement time" register MTreg to 31
  (the minimum). The range is then 0..121 557 lux (one step about 1.9 lux) instead
  of 0..54 612 lux, so full sun fits. If a sensor is still at its ceiling, this test
  prints SATURATED (the field kit then sends "sat_up":1 or "sat_down":1).

  PASS when
  - both sensors are found (UP: ADDR pin to GND -> 0x23, DOWN: ADDR pin to 3V3 -> 0x5C),
  - covering a sensor with your finger brings it close to 0 lux (a few lux at most),
  - a desk lamp or a window gives hundreds to thousands of lux, daylight outdoors
    gives thousands, full sun up to about 100 000 lux,
  - PAIR CALIBRATION (important for albedo): put both sensors side by side, BOTH
    facing up, under the same light (outdoors, open sky, not in a shadow). The ratio
    UP/DOWN shown below should be between about 0.8 and 1.25 (the datasheet allows
    +-20 % between single sensors). Write the ratio down and type it into the app:
    field kit panel, "Albedo calibration k". The app multiplies lux_down by it
    before calculating albedo.
*/

#include <Wire.h>
#include <BH1750.h>

const int PIN_SDA = 21;
const int PIN_SCL = 22;
const uint8_t MTREG = 31;
const float MAX_LUX = 65535.0f / 1.2f * 69.0f / MTREG;  // 121557 lux

BH1750 up(0x23), down(0x5C);
bool upOk = false, downOk = false;

bool present(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

bool startSensor(BH1750 &s, uint8_t addr, const char *name, const char *hint) {
  // check the address first: the library prints its own error lines otherwise
  if (!present(addr)) {
    Serial.printf("FAIL: BH1750 %s not found at 0x%02X - %s\n", name, addr, hint);
    return false;
  }
  if (!s.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, addr, &Wire) || !s.setMTreg(MTREG)) {
    Serial.printf("FAIL: BH1750 %s at 0x%02X answers but could not be set up\n", name, addr);
    return false;
  }
  Serial.printf("PASS: BH1750 %s found at 0x%02X (range up to %.0f lux)\n", name, addr, MAX_LUX);
  return true;
}

// Reads one sensor. Returns false on error. sat = true if at the ceiling.
bool readSensor(BH1750 &s, float &lux, bool &sat) {
  lux = s.readLightLevel();
  if (lux < 0.0f) return false;
  sat = (lux * 1.2f * MTREG / 69.0f) >= 65534.5f;
  return true;
}

void printOne(const char *name, bool ok, bool readOk, float lux, bool sat) {
  if (!ok) Serial.printf("%s: missing | ", name);
  else if (!readOk) Serial.printf("%s: READ ERROR | ", name);
  else if (sat) Serial.printf("%s: SATURATED (> %.0f lux) | ", name, MAX_LUX);
  else Serial.printf("%s: %9.1f lux | ", name, lux);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 4: BH1750 UP + DOWN ===");
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  upOk = startSensor(up, 0x23, "UP", "its ADDR pin must go to GND");
  downOk = startSensor(down, 0x5C, "DOWN", "its ADDR pin must go to 3V3");
  delay(200);  // first measurement
}

void loop() {
  static uint32_t lastRetry = 0;
  if ((!upOk || !downOk) && millis() - lastRetry > 5000) {
    lastRetry = millis();
    if (!upOk) upOk = startSensor(up, 0x23, "UP", "its ADDR pin must go to GND");
    if (!downOk) downOk = startSensor(down, 0x5C, "DOWN", "its ADDR pin must go to 3V3");
  }
  float lu = 0, ld = 0;
  bool su = false, sd = false;
  bool ru = upOk && readSensor(up, lu, su);
  bool rd = downOk && readSensor(down, ld, sd);
  printOne("UP", upOk, ru, lu, su);
  printOne("DOWN", downOk, rd, ld, sd);
  if (ru && rd && !su && !sd && lu > 20.0f && ld > 20.0f) {
    Serial.printf("ratio UP/DOWN %.3f (albedo if mounted up/down: %.3f)\n", lu / ld, ld / lu);
  } else {
    Serial.println("ratio: needs both sensors above 20 lux and not saturated");
  }
  delay(1000);
}
