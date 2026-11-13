/*
  ============================================================================
  Analog Atlas - BASE STATION firmware                                 v1.0.1
  NASA Space Apps Challenge 2026 - Amman
  ============================================================================
  Board : a second ESP32 DevKit V1, connected to the computer by USB
          Arduino IDE: Tools > Board > esp32 > "ESP32 Dev Module"
  Libs  : none (only the ESP32 core)

  WHAT IT DOES
  The field kit (field_kit.ino with #define ESPNOW_SEND 1) broadcasts every JSON
  line by ESP-NOW radio on Wi-Fi channel 1. This board listens on channel 1 and
  prints every line it receives on USB (115200 baud), with two keys added at the
  end:  ,"via":"espnow","rssi":<dBm>    (rssi = signal strength, e.g. -61)

    received:  {"t":12345,"air":24.12,"lux_down":15000.0}
    printed :  {"t":12345,"air":24.12,"lux_down":15000.0,"via":"espnow","rssi":-61}

  Lines starting with '#' are messages for people. The app reads this board
  exactly like the field kit itself (see firmware/PROTOCOL.md).

  ONLY YOUR KIT: at an event many ESP32 boards may send on channel 1. Tell the base
  station which kit is yours, then packets from other senders are not forwarded:
  - type PAIR in the Serial Monitor while your field kit is on: the next packet from a
    field kit sets its address, and the base station remembers it (UNPAIR forgets it), or
  - type the kit's MAC address (the "mac" in its INFO line) into FIELD_KIT_MAC below.
  Without either, every sender is forwarded (and a '#' line says so at start-up).

  How the radio data reaches USB: the ESP-NOW "receive callback" runs in the
  Wi-Fi task, not in loop(). It must be short and must not print. So it only
  copies each packet into a ring buffer; loop() takes packets out and prints them.
*/

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_log.h>
#include <esp_mac.h>
#include <Preferences.h>

// Optional: the MAC address of YOUR field kit, e.g. "24:6F:28:AA:BB:CC" (the "mac" in
// the kit's INFO line). Leave "" to use the PAIR command instead.
#define FIELD_KIT_MAC ""

const char FW_VERSION[] = "1.0.1";
const uint8_t ESPNOW_CHANNEL = 1;     // must be the same channel as the field kit
const int PIN_LED = 2;                // blue LED: blinks for every packet
const uint32_t HEARTBEAT_MS = 10000;  // '#' line every 10 s while nothing arrives
const int RING_SLOTS = 16;            // room for 16 packets waiting to be printed

// One received packet
struct Packet {
  uint16_t len;
  int8_t rssi;
  bool hasRssi;
  uint8_t mac[6];
  char data[ESP_NOW_MAX_DATA_LEN + 1];  // +1 for the end-of-text 0
};

// Ring buffer: the callback writes at ringHead, loop() reads at ringTail.
// A spinlock (portMUX) protects it because the two run on different CPU cores:
// ringHead, ringTail and lostRingFull are only used between
// portENTER_CRITICAL and portEXIT_CRITICAL.
Packet ring[RING_SLOTS];
uint16_t ringHead = 0;
uint16_t ringTail = 0;
uint32_t lostRingFull = 0;  // packets lost because the ring was full
portMUX_TYPE ringLock = portMUX_INITIALIZER_UNLOCKED;

uint32_t forwarded = 0;   // packets printed
uint32_t ignored = 0;     // packets that were not one JSON object
uint32_t otherSender = 0; // packets from another device than the paired field kit
uint8_t kitMac[6] = {0};  // the paired field kit
bool kitMacSet = false;
bool kitMacFixed = false; // set by FIELD_KIT_MAC (PAIR / UNPAIR are then refused)
bool pairing = false;     // PAIR: the next field kit packet sets kitMac
Preferences prefs;        // keeps the paired address in flash (survives a restart)
uint32_t lastPacketMs = 0, lastHeartbeatMs = 0, ledOffMs = 0;
bool ledOn = false;
int lastRssi = 0;
bool haveRssi = false;
char cmdBuf[64];
size_t cmdLen = 0;

// Called by the Wi-Fi task for every ESP-NOW packet. Keep it short, never print here.
void onEspNowReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (data == nullptr || len <= 0 || len > ESP_NOW_MAX_DATA_LEN) return;
  portENTER_CRITICAL(&ringLock);
  uint16_t next = (uint16_t)((ringHead + 1) % RING_SLOTS);
  if (next == ringTail) {
    lostRingFull++;  // loop() is too slow: this packet is lost
  } else {
    Packet &p = ring[ringHead];
    memcpy(p.data, data, (size_t)len);
    p.data[len] = 0;
    p.len = (uint16_t)len;
    p.hasRssi = (info != nullptr && info->rx_ctrl != nullptr);
    p.rssi = p.hasRssi ? (int8_t)info->rx_ctrl->rssi : 0;
    if (info != nullptr && info->src_addr != nullptr) memcpy(p.mac, info->src_addr, 6);
    else memset(p.mac, 0, 6);
    ringHead = next;
  }
  portEXIT_CRITICAL(&ringLock);
}

// Number of packets lost because the ring buffer was full (read under the lock).
uint32_t lostCount() {
  portENTER_CRITICAL(&ringLock);
  uint32_t n = lostRingFull;
  portEXIT_CRITICAL(&ringLock);
  return n;
}

// Takes the oldest packet out of the ring buffer. Returns false if it is empty.
bool takePacket(Packet &out) {
  bool got = false;
  portENTER_CRITICAL(&ringLock);
  if (ringTail != ringHead) {
    out = ring[ringTail];
    ringTail = (uint16_t)((ringTail + 1) % RING_SLOTS);
    got = true;
  }
  portEXIT_CRITICAL(&ringLock);
  return got;
}

void macToText(const uint8_t *mac, char *out, size_t size) {
  snprintf(out, size, "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

// "24:6F:28:AA:BB:CC" -> 6 bytes. Returns false if the text is not a MAC address.
bool textToMac(const char *text, uint8_t *mac) {
  unsigned v[6];
  char extra = 0;
  if (sscanf(text, "%2x:%2x:%2x:%2x:%2x:%2x%c", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &extra) != 6) return false;
  for (int i = 0; i < 6; i++) mac[i] = (uint8_t)v[i];
  return true;
}

// Removes line endings at the end and checks that the packet is ONE printable JSON object { ... }.
bool cleanPacket(Packet &p) {
  size_t len = p.len;
  // remove line endings or spaces at the end (the field kit sends none, but be safe)
  while (len > 0 && (p.data[len - 1] == '\n' || p.data[len - 1] == '\r' || p.data[len - 1] == ' ')) len--;
  p.data[len] = 0;
  p.len = (uint16_t)len;
  bool ok = (len >= 2 && p.data[0] == '{' && p.data[len - 1] == '}');
  for (size_t i = 0; ok && i < len; i++) {
    uint8_t c = (uint8_t)p.data[i];
    if (c < 0x20 || c > 0x7E) ok = false;
  }
  return ok;
}

// PAIR: the next field kit packet (a data line {"t":... or a status line) sets the kit address.
void learnKit(const Packet &p) {
  if (strncmp(p.data, "{\"t\":", 5) != 0 && strncmp(p.data, "{\"status\":", 10) != 0) return;
  memcpy(kitMac, p.mac, 6);
  kitMacSet = true;
  pairing = false;
  prefs.putBytes("kitmac", kitMac, 6);
  char mac[18];
  macToText(kitMac, mac, sizeof(mac));
  Serial.printf("# base station: paired with the field kit %s - only its packets are forwarded now (UNPAIR to undo)\n", mac);
}

// Prints one packet as a JSON line with "via" and "rssi" added before the final '}'.
void forwardPacket(Packet &p) {
  if (!cleanPacket(p)) {
    ignored++;
    return;
  }
  if (pairing) learnKit(p);
  if (kitMacSet && memcmp(p.mac, kitMac, 6) != 0) {
    otherSender++;  // another device on channel 1: not our kit
    return;
  }
  size_t len = p.len;
  const char *sep = (len == 2) ? "" : ",";  // "{}" has no keys: no comma needed
  Serial.write((const uint8_t *)p.data, len - 1);  // everything except the final '}'
  if (p.hasRssi) Serial.printf("%s\"via\":\"espnow\",\"rssi\":%d}", sep, (int)p.rssi);
  else Serial.printf("%s\"via\":\"espnow\"}", sep);  // no signal strength known: leave it out
  Serial.println();

  forwarded++;
  lastPacketMs = millis();
  if (p.hasRssi) {
    lastRssi = p.rssi;
    haveRssi = true;
  }
  digitalWrite(PIN_LED, HIGH);
  ledOn = true;
  ledOffMs = millis() + 30;
}

void macText(char *out, size_t size) {
  uint8_t mac[6] = {0};
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  macToText(mac, out, size);
}

// Which senders are forwarded, in words (start-up, INFO, UNPAIR).
void printKitFilter() {
  if (kitMacSet) {
    char mac[18];
    macToText(kitMac, mac, sizeof(mac));
    Serial.printf("# base station: forwarding only the field kit %s (%s)\n", mac, kitMacFixed ? "FIELD_KIT_MAC" : "paired");
  } else {
    Serial.println("# base station: forwarding EVERY sender - type PAIR while your field kit is on, so a stray device cannot add data");
  }
}

void printInfo() {
  char mac[18];
  macText(mac, sizeof(mac));
  uint32_t lost = lostCount();
  char kit[18] = "any";
  if (kitMacSet) macToText(kitMac, kit, sizeof(kit));
  Serial.printf("{\"base\":{\"fw\":\"%s\",\"channel\":%u,\"mac\":\"%s\",\"kit\":\"%s\",\"rx\":%lu,\"ignored\":%lu,\"other\":%lu,\"lost\":%lu",
                FW_VERSION, ESPNOW_CHANNEL, mac, kit, (unsigned long)forwarded, (unsigned long)ignored,
                (unsigned long)otherSender, (unsigned long)lost);
  if (haveRssi) Serial.printf(",\"last_rssi\":%d", lastRssi);
  Serial.println("}}");
  Serial.printf("# base station: %lu lines forwarded, %lu ignored (not JSON), %lu from other senders, %lu lost (buffer full)\n",
                (unsigned long)forwarded, (unsigned long)ignored, (unsigned long)otherSender, (unsigned long)lost);
  printKitFilter();
}

// The base station only forwards data. It answers HELP, INFO, PAIR and UNPAIR; other
// commands (TIME, LOG ...) are meant for the field kit and need the kit's own USB cable.
void runCommand(char *line) {
  while (*line == ' ') line++;
  size_t len = strlen(line);
  while (len > 0 && line[len - 1] == ' ') line[--len] = 0;
  if (len == 0) return;
  for (char *c = line; *c; c++) *c = (char)toupper((unsigned char)*c);
  if (!strcmp(line, "INFO") || !strcmp(line, "STATUS")) {
    printInfo();
  } else if (!strcmp(line, "HELP") || !strcmp(line, "?")) {
    Serial.println("# base station commands: HELP, INFO, PAIR (forward only the next field kit heard), UNPAIR");
    Serial.println("# TIME and LOG commands only work on the field kit's own USB port");
  } else if ((!strcmp(line, "PAIR") || !strcmp(line, "UNPAIR")) && kitMacFixed) {
    Serial.println("# base station: the kit address is set by FIELD_KIT_MAC in the sketch - change it there");
  } else if (!strcmp(line, "PAIR")) {
    pairing = true;
    Serial.println("# base station: PAIR - waiting for the next packet from a field kit (switch it on, ESPNOW_SEND 1)");
  } else if (!strcmp(line, "UNPAIR")) {
    pairing = false;
    kitMacSet = false;
    prefs.remove("kitmac");
    printKitFilter();
  } else if (!strncmp(line, "TIME", 4)) {
    Serial.println("# base station: TIME is not needed here (the app knows when each line arrives)");
  } else {
    Serial.printf("# base station: '%s' is a field kit command - connect the kit by USB for it\n", line);
  }
}

void handleSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      cmdBuf[cmdLen] = 0;
      runCommand(cmdBuf);
      cmdLen = 0;
    } else if (cmdLen < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  esp_log_level_set("*", ESP_LOG_NONE);  // keep the USB output clean (only JSON and '#' lines)
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  delay(100);
  Serial.println();

  WiFi.mode(WIFI_STA);    // ESP-NOW needs the Wi-Fi radio in "station" mode
  WiFi.disconnect();      // no router: we choose the channel ourselves
  esp_wifi_set_ps(WIFI_PS_NONE);  // no power saving: the radio always listens
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK || esp_now_register_recv_cb(onEspNowReceive) != ESP_OK) {
    Serial.println("# ERROR: ESP-NOW could not start - restarting in 5 s");
    delay(5000);
    ESP.restart();
  }

  // Which field kit to forward: FIELD_KIT_MAC, else the address saved by PAIR, else every sender.
  prefs.begin("atlas-base", false);
  bool badMac = false;
  if (strlen(FIELD_KIT_MAC) > 0) {
    kitMacSet = kitMacFixed = textToMac(FIELD_KIT_MAC, kitMac);
    badMac = !kitMacSet;
  } else if (prefs.getBytesLength("kitmac") == 6) {
    kitMacSet = (prefs.getBytes("kitmac", kitMac, 6) == 6);
  }

  char mac[18];
  macText(mac, sizeof(mac));
  Serial.println("# base station ready");
  Serial.printf("# Analog Atlas base station - firmware %s - listening for ESP-NOW on Wi-Fi channel %u (this board: %s)\n",
                FW_VERSION, ESPNOW_CHANNEL, mac);
  if (badMac) Serial.println("# ERROR: FIELD_KIT_MAC is not a MAC address like 24:6F:28:AA:BB:CC - forwarding every sender");
  printKitFilter();
  lastHeartbeatMs = millis();
}

void loop() {
  Packet p;
  int printed = 0;
  // Print what is waiting, but not more than 8 lines per loop so commands stay responsive
  while (printed < 8 && takePacket(p)) {
    forwardPacket(p);
    printed++;
  }

  handleSerial();

  uint32_t now = millis();
  if (now - lastPacketMs >= HEARTBEAT_MS && now - lastHeartbeatMs >= HEARTBEAT_MS) {
    lastHeartbeatMs = now;
    if (forwarded == 0) {
      Serial.printf("# base station alive - nothing forwarded yet on channel %u, %lu packets from other senders (is the field kit on, with ESPNOW_SEND 1?)\n",
                    ESPNOW_CHANNEL, (unsigned long)otherSender);
    } else {
      Serial.printf("# base station alive - no data for %lu s (forwarded %lu, ignored %lu, other senders %lu, lost %lu)\n",
                    (unsigned long)((now - lastPacketMs) / 1000), (unsigned long)forwarded, (unsigned long)ignored,
                    (unsigned long)otherSender, (unsigned long)lostCount());
    }
  }
  if (ledOn && (int32_t)(now - ledOffMs) >= 0) {
    digitalWrite(PIN_LED, LOW);
    ledOn = false;
  }
  delay(1);
}
