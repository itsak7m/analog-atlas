/*
  Analog Atlas - TEST 5: DS18B20 waterproof probe (soil temperature) on GPIO4
  -------------------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud.
  Libraries: "OneWire" and "DallasTemperature".

  Wiring: red -> 3V3, black -> GND, yellow (data) -> GPIO4, and a 4.7 kOhm resistor
  between GPIO4 and 3V3. (Some probes use other colours - check the seller's info.)

  What it shows: the pull-up check, the 64-bit ROM address of every sensor on the
  wire (with checksum check), the number of sensors and the temperatures.

  PASS when
  - the data line is HIGH at rest (pull-up present) and a sensor answers,
  - exactly 1 sensor is found, its ROM starts with 28 (= DS18B20) and the CRC is ok,
  - the temperature is plausible (room: about 15..35 C), never -127 or 85,
  - holding the metal tip in your hand makes it rise within a minute,
  - ICE WATER test: a cup full of crushed ice + a little water, stir, wait 2 minutes:
    0.0 C +- 0.5 C (the datasheet accuracy between -10 and +85 C).
*/

#include <OneWire.h>
#include <DallasTemperature.h>

const int PIN_DATA = 4;

OneWire oneWire(PIN_DATA);
DallasTemperature sensors(&oneWire);

const char *familyName(uint8_t f) {
  switch (f) {
    case 0x28: return "DS18B20";
    case 0x10: return "DS18S20/DS1820";
    case 0x22: return "DS1822";
    case 0x3B: return "DS1825/MAX31850";
    default: return "not a temperature sensor";
  }
}

void scanBus() {
  Serial.println();
  Serial.println("Searching the 1-Wire bus on GPIO4 ...");
  // Pull-up check: switch on the ESP32's weak internal pull-DOWN. The 4.7 kOhm
  // pull-up is much stronger, so with the resistor the line still reads HIGH.
  pinMode(PIN_DATA, INPUT_PULLDOWN);
  delay(5);
  int level = digitalRead(PIN_DATA);
  pinMode(PIN_DATA, INPUT);
  if (level == HIGH) Serial.println("  data line at rest: HIGH - pull-up resistor present (good)");
  else Serial.println("  data line at rest: LOW - the 4.7 kOhm resistor to 3V3 is MISSING, or data touches GND");

  if (!oneWire.reset()) {
    Serial.println("FAIL: no sensor answered (no 'presence pulse'). Check 3V3, GND, data -> GPIO4 and the 4.7 kOhm.");
    return;
  }
  uint8_t rom[8];
  int count = 0, good = 0;
  oneWire.reset_search();
  while (oneWire.search(rom)) {
    count++;
    bool crcOk = (OneWire::crc8(rom, 7) == rom[7]);
    Serial.printf("  sensor %d: ROM %02X%02X%02X%02X%02X%02X%02X%02X  family 0x%02X = %s, CRC %s\n", count, rom[0],
                  rom[1], rom[2], rom[3], rom[4], rom[5], rom[6], rom[7], rom[0], familyName(rom[0]),
                  crcOk ? "ok" : "WRONG (bad contact?)");
    if (crcOk && rom[0] == 0x28) good++;
  }
  sensors.begin();
  Serial.printf("  sensors found: %d (DS18B20 with good CRC: %d), parasite power: %s\n", count, good,
                sensors.isParasitePowerMode() ? "YES - connect the red wire to 3V3" : "no (good)");
  if (count == 1 && good == 1) Serial.println("PASS: exactly one DS18B20 found");
  else if (count == 0) Serial.println("FAIL: a device answered the reset but the search found nothing - check the contacts");
  else if (count > 1) Serial.println("NOTE: more than one sensor - the field kit uses the first one");
  else Serial.println("FAIL: the device is not a DS18B20 or its ROM checksum is wrong");
  sensors.setResolution(12);  // 0.0625 C steps
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 5: DS18B20 on GPIO4 ===");
  Serial.println("Datasheet: -55..125 C, accuracy +-0.5 C from -10 to +85 C.");
  Serial.println("-127 means 'no answer' and 85 means 'power-up value' - both are errors, not temperatures.");
  scanBus();
}

void loop() {
  static uint32_t lastScan = 0;
  if (millis() - lastScan > 30000) {  // search the bus again every 30 s
    lastScan = millis();
    scanBus();
  }
  sensors.requestTemperatures();  // waits for the conversion (750 ms at 12 bit) - fine in a test
  int n = sensors.getDeviceCount();
  if (n == 0) {
    Serial.println("no sensor");
  }
  for (int i = 0; i < n; i++) {
    float t = sensors.getTempCByIndex(i);
    if (t == DEVICE_DISCONNECTED_C) Serial.printf("sensor %d: NO ANSWER (-127) - loose wire?\n", i + 1);
    else if (t == 85.0f) Serial.printf("sensor %d: 85.00 = power-up value, not a measurement (weak supply?)\n", i + 1);
    else if (t < -55.0f || t > 125.0f) Serial.printf("sensor %d: %.2f C is outside -55..125 C - error\n", i + 1, t);
    else Serial.printf("sensor %d: %.2f C\n", i + 1, t);
  }
  delay(1000);
}
