/*
  Analog Atlas - TEST 1: I2C SCANNER
  ----------------------------------
  Finds every device on the I2C bus (SDA = GPIO21, SCL = GPIO22) and names the
  ones the field kit needs. Run this FIRST after wiring the I2C sensors.

  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud. No libraries needed.

  PASS = all of these addresses are found:
    0x23  BH1750 facing UP   (its ADDR pin to GND)
    0x5C  BH1750 facing DOWN (its ADDR pin to 3V3)
    0x5A  MLX90614 (GY-906)
    0x76 or 0x77  BME280 / BMP280
  The scan repeats every 5 seconds, so you can plug sensors in one by one
  (switch the power off while you change wires!).
*/

#include <Wire.h>

const int PIN_SDA = 21;
const int PIN_SCL = 22;

// Checks if a line has a pull-up resistor: we switch on the ESP32's weak internal
// pull-DOWN. A real pull-up resistor on a sensor board is stronger, so the line
// still reads HIGH. With no pull-up (or a short to GND) it reads LOW.
void checkPullup(int pin, const char *name) {
  pinMode(pin, INPUT_PULLDOWN);
  delay(5);
  int level = digitalRead(pin);
  pinMode(pin, INPUT);
  if (level == HIGH) {
    Serial.printf("  %s (GPIO%d): HIGH - pull-up resistor present (good)\n", name, pin);
  } else {
    Serial.printf("  %s (GPIO%d): LOW - NO pull-up found, or the wire touches GND.\n", name, pin);
    Serial.println("      Sensor boards normally have pull-ups: check 3V3/GND of the boards and this wire.");
  }
}

const char *nameOf(uint8_t a) {
  switch (a) {
    case 0x23: return "BH1750 light sensor UP (ADDR -> GND)";
    case 0x5C: return "BH1750 light sensor DOWN (ADDR -> 3V3)";
    case 0x5A: return "MLX90614 infrared thermometer (GY-906)";
    case 0x76: return "BME280/BMP280 (SDO -> GND)";
    case 0x77: return "BME280/BMP280 (SDO -> 3V3)";
    default: return "not part of the field kit";
  }
}

// Reads the chip ID register 0xD0 (BME280 = 0x60, BMP280 = 0x58).
bool readChipId(uint8_t addr, uint8_t &id) {
  Wire.beginTransmission(addr);
  Wire.write((uint8_t)0xD0);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (size_t)1) != 1) return false;
  id = (uint8_t)Wire.read();
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 1: I2C scanner (SDA = GPIO21, SCL = GPIO22) ===");
  Serial.println("Pull-up check (before the I2C bus starts):");
  checkPullup(PIN_SDA, "SDA");
  checkPullup(PIN_SCL, "SCL");
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
}

void loop() {
  Serial.println();
  Serial.println("Scanning addresses 0x01..0x7E ...");
  bool seen[128] = {false};
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      seen[a] = true;
      found++;
      Serial.printf("  found 0x%02X  %s\n", a, nameOf(a));
    }
  }
  if (found == 0) {
    Serial.println("  nothing found! Check: 3V3 and GND to every sensor, SDA to GPIO21, SCL to GPIO22,");
    Serial.println("  SDA and SCL not swapped, and that the sensor boards' pins are soldered.");
  }

  // BME280 or BMP280? (the chip ID tells)
  for (uint8_t a = 0x76; a <= 0x77; a++) {
    uint8_t id;
    if (seen[a] && readChipId(a, id)) {
      const char *type = (id == 0x60) ? "BME280 (temperature + humidity + pressure)"
                         : (id == 0x58 || id == 0x56 || id == 0x57) ? "BMP280 (temperature + pressure, NO humidity)"
                         : (id == 0x61) ? "BME680 (not supported by the field kit)"
                         : "unknown chip";
      Serial.printf("  0x%02X chip ID = 0x%02X -> %s\n", a, id, type);
    }
  }

  bool okUp = seen[0x23], okDown = seen[0x5C], okMlx = seen[0x5A], okBme = seen[0x76] || seen[0x77];
  Serial.printf("Result: BH1750 UP %s, BH1750 DOWN %s, MLX90614 %s, BME280 %s\n", okUp ? "ok" : "MISSING",
                okDown ? "ok" : "MISSING", okMlx ? "ok" : "MISSING", okBme ? "ok" : "MISSING");
  if (okUp && okDown && okMlx && okBme) {
    Serial.println("PASS - all I2C sensors of the field kit answer.");
  } else {
    Serial.println("FAIL - see the MISSING parts above. Hints:");
    if (!okUp || !okDown) {
      Serial.println("  BH1750: UP board ADDR pin -> GND (0x23), DOWN board ADDR pin -> 3V3 (0x5C).");
      Serial.println("  If both ADDR pins are the same, both boards have the same address and only one shows up.");
    }
    if (!okMlx) Serial.println("  MLX90614: VIN -> 3V3, GND, SDA, SCL. Use the 3 V 'BAA' version (see WIRING.md).");
    if (!okBme) Serial.println("  BME280: VCC/VIN -> 3V3, GND, SDA, SCL; on 6-pin boards CSB -> 3V3 and SDO -> GND.");
  }
  delay(5000);
}
