// baro.h - small driver for the Bosch BME280 and BMP280 air sensors (I2C)
// ---------------------------------------------------------------------------
// The same file is used in field_kit/ and in tests/bme280_test/.
// If you change one copy, copy it to the other folder too.
//
// Why our own driver and not the "Adafruit BME280 Library"?
//   * The Adafruit library only accepts a real BME280 (chip ID 0x60).
//     Many cheap boards sold as "BME280" really carry a BMP280 (chip ID 0x58,
//     no humidity) and would simply not work.
//   * The Adafruit library does not notice I2C errors, so a loose wire could
//     turn into a wrong number. This driver checks EVERY transfer and returns
//     false instead of a value when something goes wrong.
//   * It uses "forced mode": the sensor makes ONE measurement when we ask and
//     then sleeps. Less self-heating means a better air temperature.
// tests/bme280_test compares this driver with the Adafruit library on your
// real sensor, so you can check that both give the same numbers.
//
// The compensation formulas are the integer formulas from the Bosch datasheets
// (BMP280 and BME280, "compensation formula in 32/64 bit fixed point").
// Check: with the worked example of the BMP280 datasheet (adc_T = 519888,
// adc_P = 415148) this code gives 25.08 C and 100653.25 Pa.

#pragma once
#include <Arduino.h>
#include <Wire.h>

class Baro {
public:
  enum Kind : uint8_t { NONE = 0, BMP280 = 1, BME280 = 2 };

  // Reads the chip ID register (0xD0) of the device at 'addr'.
  // Returns false if nobody answered at this address.
  static bool readChipId(TwoWire &wire, uint8_t addr, uint8_t &id) {
    wire.beginTransmission(addr);
    wire.write((uint8_t)0xD0);
    if (wire.endTransmission(false) != 0) return false;
    if (wire.requestFrom(addr, (size_t)1) != 1) return false;
    id = (uint8_t)wire.read();
    return true;
  }

  // Name of a chip ID, for messages.
  static const char *chipName(uint8_t id) {
    switch (id) {
      case 0x60: return "BME280";
      case 0x56:
      case 0x57:
      case 0x58: return "BMP280";
      case 0x55: return "BMP180";
      case 0x61: return "BME680";
      default: return "unknown chip";
    }
  }

  // Finds out the chip type, resets it, reads its calibration values and sets it up.
  // Returns true when a BME280 or BMP280 is ready at 'addr'.
  bool begin(TwoWire &wire, uint8_t addr) {
    _wire = &wire;
    _addr = addr;
    _kind = NONE;
    _id = 0;
    if (!readChipId(wire, addr, _id)) return false;

    Kind k;
    if (_id == 0x60) k = BME280;
    else if (_id == 0x56 || _id == 0x57 || _id == 0x58) k = BMP280;
    else return false;  // some other chip answered at this address

    if (!writeReg(REG_RESET, 0xB6)) return false;  // soft reset
    delay(5);                                      // the chip needs 2 ms to start

    // Wait until the chip has copied its calibration data (status bit 0 = 0).
    uint8_t st = 0x01;
    uint32_t t0 = millis();
    while (true) {
      if (!readRegs(REG_STATUS, &st, 1)) return false;
      if ((st & 0x01) == 0) break;
      if (millis() - t0 > 50) return false;
      delay(2);
    }

    // Calibration ("trimming") values: registers 0x88..0xA1 (26 bytes, little endian).
    uint8_t c[26];
    if (!readRegs(0x88, c, sizeof(c))) return false;
    T1 = (uint16_t)(c[1] << 8 | c[0]);
    T2 = (int16_t)(c[3] << 8 | c[2]);
    T3 = (int16_t)(c[5] << 8 | c[4]);
    P1 = (uint16_t)(c[7] << 8 | c[6]);
    P2 = (int16_t)(c[9] << 8 | c[8]);
    P3 = (int16_t)(c[11] << 8 | c[10]);
    P4 = (int16_t)(c[13] << 8 | c[12]);
    P5 = (int16_t)(c[15] << 8 | c[14]);
    P6 = (int16_t)(c[17] << 8 | c[16]);
    P7 = (int16_t)(c[19] << 8 | c[18]);
    P8 = (int16_t)(c[21] << 8 | c[20]);
    P9 = (int16_t)(c[23] << 8 | c[22]);
    if (k == BME280) {
      H1 = c[25];  // register 0xA1
      uint8_t h[7];  // registers 0xE1..0xE7
      if (!readRegs(0xE1, h, sizeof(h))) return false;
      H2 = (int16_t)(h[1] << 8 | h[0]);
      H3 = h[2];
      H4 = (int16_t)(((int8_t)h[3]) * 16 | (h[4] & 0x0F));
      H5 = (int16_t)(((int8_t)h[5]) * 16 | (h[4] >> 4));
      H6 = (int8_t)h[6];
    }
    // A real chip never has these two values at 0: then the read went wrong.
    if (T1 == 0 || P1 == 0) return false;

    if (!writeReg(REG_CONFIG, 0x00)) return false;  // IIR filter off
    if (k == BME280 && !writeReg(REG_CTRL_HUM, OSRS_H)) return false;
    if (!writeReg(REG_CTRL_MEAS, CTRL_MEAS_SLEEP)) return false;
    _kind = k;
    return true;
  }

  // Makes one measurement. Returns false (and no numbers) on any error.
  // tempC in degrees C, pressPa in pascal (Pa), humPct in % (only if humOk is true).
  bool read(float &tempC, float &pressPa, float &humPct, bool &humOk) {
    humOk = false;
    if (_kind == NONE) return false;
    // Start ONE measurement ("forced mode"). ctrl_hum must be written before ctrl_meas.
    if (_kind == BME280 && !writeReg(REG_CTRL_HUM, OSRS_H)) return false;
    if (!writeReg(REG_CTRL_MEAS, CTRL_MEAS_FORCED)) return false;
    delay(20);  // with our settings a measurement takes about 16 ms
    uint8_t st = 0;
    uint32_t t0 = millis();
    while (true) {
      if (!readRegs(REG_STATUS, &st, 1)) return false;
      if ((st & 0x08) == 0) break;          // status bit 3 = "measuring"
      if (millis() - t0 > 100) return false;  // much too long: something is wrong
      delay(2);
    }

    // Raw data: pressure (3 bytes), temperature (3 bytes), humidity (2 bytes, BME280 only)
    uint8_t d[8];
    size_t n = (_kind == BME280) ? 8 : 6;
    if (!readRegs(REG_DATA, d, n)) return false;
    int32_t adcP = ((int32_t)d[0] << 12) | ((int32_t)d[1] << 4) | (d[2] >> 4);
    int32_t adcT = ((int32_t)d[3] << 12) | ((int32_t)d[4] << 4) | (d[5] >> 4);
    // 0x80000 means "no measurement" (the value after a reset): never use it.
    if (adcT == 0x80000 || adcP == 0x80000) return false;

    // --- temperature (datasheet integer formula), result in 0.01 C ---
    int32_t var1 = ((((adcT >> 3) - ((int32_t)T1 << 1))) * ((int32_t)T2)) >> 11;
    int32_t var2 = (((((adcT >> 4) - ((int32_t)T1)) * ((adcT >> 4) - ((int32_t)T1))) >> 12) *
                    ((int32_t)T3)) >> 14;
    int32_t tFine = var1 + var2;
    tempC = (float)((tFine * 5 + 128) >> 8) / 100.0f;

    // --- pressure (datasheet 64-bit formula), result in Pa * 256 ---
    int64_t a = (int64_t)tFine - 128000;
    int64_t b = a * a * (int64_t)P6;
    b = b + ((a * (int64_t)P5) << 17);
    b = b + (((int64_t)P4) << 35);
    a = ((a * a * (int64_t)P3) >> 8) + ((a * (int64_t)P2) << 12);
    a = ((((int64_t)1) << 47) + a) * ((int64_t)P1) >> 33;
    if (a == 0) return false;  // would divide by zero
    int64_t p = 1048576 - adcP;
    p = (((p << 31) - b) * 3125) / a;
    a = (((int64_t)P9) * (p >> 13) * (p >> 13)) >> 25;
    b = (((int64_t)P8) * p) >> 19;
    p = ((p + a + b) >> 8) + (((int64_t)P7) << 4);
    pressPa = (float)p / 256.0f;

    // --- humidity (BME280 only, datasheet integer formula), result in %RH * 1024 ---
    if (_kind == BME280) {
      int32_t adcH = ((int32_t)d[6] << 8) | d[7];
      if (adcH != 0x8000) {  // 0x8000 = "no measurement"
        int32_t v = tFine - ((int32_t)76800);
        v = (((((adcH << 14) - (((int32_t)H4) << 20) - (((int32_t)H5) * v)) + ((int32_t)16384)) >> 15) *
             (((((((v * ((int32_t)H6)) >> 10) * (((v * ((int32_t)H3)) >> 11) + ((int32_t)32768))) >> 10) +
                 ((int32_t)2097152)) * ((int32_t)H2) + 8192) >> 14));
        v = v - (((((v >> 15) * (v >> 15)) >> 7) * ((int32_t)H1)) >> 4);
        v = (v < 0) ? 0 : v;
        v = (v > 419430400) ? 419430400 : v;
        humPct = (float)(v >> 12) / 1024.0f;
        humOk = true;
      }
    }
    return true;
  }

  Kind kind() const { return _kind; }
  uint8_t address() const { return _addr; }
  uint8_t chipId() const { return _id; }
  const char *name() const { return _kind == BME280 ? "BME280" : (_kind == BMP280 ? "BMP280" : "none"); }
  void forget() { _kind = NONE; }  // after errors: begin() must be called again

private:
  // Registers (same addresses on BME280 and BMP280)
  static constexpr uint8_t REG_RESET = 0xE0, REG_CTRL_HUM = 0xF2, REG_STATUS = 0xF3,
                           REG_CTRL_MEAS = 0xF4, REG_CONFIG = 0xF5, REG_DATA = 0xF7;
  // Oversampling codes: 1 = x1, 2 = x2, 3 = x4, 4 = x8, 5 = x16.
  // Temperature x1, pressure x4 (less noise), humidity x1.
  static constexpr uint8_t OSRS_T = 1, OSRS_P = 3, OSRS_H = 1;
  static constexpr uint8_t CTRL_MEAS_SLEEP = (OSRS_T << 5) | (OSRS_P << 2) | 0x00;   // mode 00 = sleep
  static constexpr uint8_t CTRL_MEAS_FORCED = (OSRS_T << 5) | (OSRS_P << 2) | 0x01;  // mode 01 = forced

  TwoWire *_wire = nullptr;
  uint8_t _addr = 0, _id = 0;
  Kind _kind = NONE;
  uint16_t T1 = 0, P1 = 0;
  int16_t T2 = 0, T3 = 0, P2 = 0, P3 = 0, P4 = 0, P5 = 0, P6 = 0, P7 = 0, P8 = 0, P9 = 0;
  uint8_t H1 = 0, H3 = 0;
  int16_t H2 = 0, H4 = 0, H5 = 0;
  int8_t H6 = 0;

  bool readRegs(uint8_t reg, uint8_t *buf, size_t len) {
    _wire->beginTransmission(_addr);
    _wire->write(reg);
    if (_wire->endTransmission(false) != 0) return false;  // false = repeated start
    if (_wire->requestFrom(_addr, len) != len) return false;
    for (size_t i = 0; i < len; i++) buf[i] = (uint8_t)_wire->read();
    return true;
  }

  bool writeReg(uint8_t reg, uint8_t value) {
    _wire->beginTransmission(_addr);
    _wire->write(reg);
    _wire->write(value);
    return _wire->endTransmission() == 0;
  }
};
