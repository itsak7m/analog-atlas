/*
  Analog Atlas - TEST 6: GUVA-S12SD UV sensor (analog) on GPIO34
  -------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud. No libraries needed.

  Wiring: + (VCC) -> 3V3, - (GND) -> GND, OUT (SIG) -> GPIO34.
  UV index = output voltage / 0.1 V (from the module documentation; an
  approximation, not a calibrated instrument).

  The ESP32 ADC is set like in the field kit: 2.5 dB attenuation, which measures
  about 100..1250 mV well (UV index 1.0..12.5). Below 100 mV we can only say
  "UV index < 1". The field kit then sends "uv_lt":1.0 instead of a number.

  An analog sensor cannot be "detected": an unconnected GPIO34 floats and shows
  random numbers. That is why this test also prints how much 16 quick samples
  scatter: a working sensor gives steady readings.

  PASS when
  - indoors, away from windows: below 100 mV (UV index < 1),
  - outdoors in sunshine: clearly above 100 mV (hundreds of mV on a sunny day),
  - covering the sensor with your hand outdoors makes it drop to below 100 mV,
  - the "spread" stays small (below about 100 mV) and the value is steady.
  Note: window glass and most plastics block much of the UV - test outdoors.
*/

const int PIN_UV = 34;
const int SAMPLES = 16;
const int MIN_MV = 100;   // lowest voltage the ADC measures well at 2.5 dB
const int MAX_MV = 1250;  // highest

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

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 6: GUVA-S12SD UV sensor on GPIO34 ===");
  // Set the attenuation for all analog pins (not per pin): then analogReadMilliVolts()
  // uses the matching calibration.
  analogSetAttenuation(ADC_2_5db);
  analogReadResolution(12);
}

void loop() {
  int mv[SAMPLES], raw[SAMPLES];
  for (int i = 0; i < SAMPLES; i++) {
    raw[i] = analogRead(PIN_UV);
    mv[i] = (int)analogReadMilliVolts(PIN_UV);
  }
  sortInts(mv, SAMPLES);
  sortInts(raw, SAMPLES);
  long sum = 0;
  for (int i = SAMPLES / 4; i < SAMPLES * 3 / 4; i++) sum += mv[i];  // middle 8 samples
  int avg = (int)((sum + SAMPLES / 4) / (SAMPLES / 2));
  int spread = mv[SAMPLES * 3 / 4 - 1] - mv[SAMPLES / 4];
  int rawMedian = raw[SAMPLES / 2];

  Serial.printf("raw %4d | %4d mV | spread %3d mV | ", rawMedian, avg, spread);
  if (spread > 100) {
    Serial.println("UNSTABLE - loose OUT wire or nothing connected to GPIO34?");
  } else if (rawMedian >= 4095) {
    Serial.printf("ABOVE RANGE (> about %d mV) - check wiring (VCC must be 3V3)\n", MAX_MV);
  } else if (avg < MIN_MV) {
    Serial.println("UV index < 1.0 (below the measuring range: normal indoors / at night)");
  } else {
    Serial.printf("UV index %.1f\n", avg / 100.0f);
  }
  delay(1000);
}
