/*
  Analog Atlas - TEST 3: MLX90614 infrared thermometer (GY-906) - ground SURFACE temperature
  -----------------------------------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud.
  Library: "Adafruit MLX90614 Library" (+ "Adafruit BusIO").

  The MLX90614 measures two things:
    ambient = the temperature of the sensor's own metal can ("amb" in the field kit)
    object  = the temperature of the surface it looks at ("surf" in the field kit)
  It "sees" a wide cone (90 degrees for the standard BAA version): at 30 cm height the
  measured spot on the ground is about 60 cm wide.

  This test reads both values with the Adafruit library AND with the field kit's
  own method, which also checks the PEC checksum byte the sensor sends.

  PASS when
  - the sensor is found at 0x5A and "PEC ok" is shown,
  - ambient is close to room temperature (sensor range -40..125 C),
  - object follows what you point it at (sensor range -70..380 C):
      palm of your hand at 2..5 cm       -> about 30..36 C
      glass of ice water, from above     -> about 0..5 C
      clear sky (outdoors)               -> far below the air temperature
  - same-surface check: put the DS18B20 probe into a bowl of water (stir!) and point
    the MLX90614 at the water surface from about 5 cm: both agree within about 2 C.
*/

#include <Wire.h>
#include <Adafruit_MLX90614.h>

const int PIN_SDA = 21;
const int PIN_SCL = 22;
const uint8_t ADDR_MLX = 0x5A;

Adafruit_MLX90614 mlx;
bool ready = false;

// CRC-8 (polynomial 0x07) = the PEC byte of SMBus
uint8_t crc8(const uint8_t *data, size_t len) {
  uint8_t crc = 0;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}

// The field kit's method: read register reg (0x06 ambient, 0x07 object) and check the PEC.
// Returns 0 = ok, 1 = no answer, 2 = PEC (checksum) wrong, 3 = sensor error flag
int readWithPec(uint8_t reg, float &tempC) {
  Wire.beginTransmission(ADDR_MLX);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 1;
  if (Wire.requestFrom(ADDR_MLX, (size_t)3) != 3) return 1;
  uint8_t lo = (uint8_t)Wire.read(), hi = (uint8_t)Wire.read(), pec = (uint8_t)Wire.read();
  const uint8_t frame[5] = {(uint8_t)(ADDR_MLX << 1), reg, (uint8_t)((ADDR_MLX << 1) | 1), lo, hi};
  if (crc8(frame, sizeof(frame)) != pec) return 2;
  uint16_t raw = (uint16_t)lo | ((uint16_t)hi << 8);
  if (raw & 0x8000) return 3;
  tempC = raw * 0.02f - 273.15f;
  return 0;
}

bool start() {
  if (!mlx.begin(ADDR_MLX, &Wire)) {
    Serial.println("FAIL: no MLX90614 at 0x5A. Check VIN -> 3V3, GND, SDA -> GPIO21, SCL -> GPIO22.");
    Serial.println("      Is it the 3 V 'BAA' version? A 5 V 'AAA' version needs 5 V (see WIRING.md).");
    return false;
  }
  Serial.println("PASS: MLX90614 found at 0x5A");
  double e = mlx.readEmissivity();
  if (isnan(e)) {
    Serial.println("  emissivity: could not be read");
  } else {
    Serial.printf("  emissivity setting: %.3f (factory value 1.000)%s\n", e,
                  fabs(e - 1.0) > 0.01 ? "  <- changed by someone! The field kit assumes 1.000" : "");
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 3: MLX90614 (GY-906) ===");
  Wire.begin(PIN_SDA, PIN_SCL, 100000);  // the MLX90614 allows at most 100 kHz
  ready = start();
}

void loop() {
  if (!ready) {
    delay(5000);
    ready = start();
    return;
  }
  double amb = mlx.readAmbientTempC();  // NAN = no answer
  double obj = mlx.readObjectTempC();
  float amb2 = 0, obj2 = 0;
  int ra = readWithPec(0x06, amb2);
  int ro = readWithPec(0x07, obj2);

  if (isnan(amb) || isnan(obj)) Serial.print("library: no answer | ");
  else Serial.printf("library: ambient %.2f C, object %.2f C | ", amb, obj);
  const char *why[] = {"ok", "no answer", "PEC WRONG (disturbed transfer)", "sensor error flag"};
  if (ra == 0 && ro == 0) Serial.printf("field kit method: ambient %.2f C, object %.2f C, PEC ok\n", amb2, obj2);
  else Serial.printf("field kit method: ambient %s, object %s\n", why[ra], why[ro]);

  if (ra == 0 && (amb2 < -40.0f || amb2 > 125.0f)) Serial.println("  FAIL: ambient outside -40..125 C");
  if (ro == 0 && (obj2 < -70.0f || obj2 > 380.0f)) Serial.println("  FAIL: object outside -70..380 C");
  if (ra == 2 || ro == 2) Serial.println("  WARNING: checksum errors - shorten/twist the I2C wires, check GND");
  delay(1000);
}
