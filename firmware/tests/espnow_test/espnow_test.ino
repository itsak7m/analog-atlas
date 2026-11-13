/*
  Analog Atlas - TEST 7: ESP-NOW radio link between TWO ESP32 boards (ping test)
  ----------------------------------------------------------------------------
  Board: "ESP32 Dev Module". Serial Monitor: 115200 baud. No libraries needed.

  Upload THIS SAME sketch to both boards (field kit board and base station board).
  Power both (USB or power bank) and watch the Serial Monitor of at least one.

  Every second each board broadcasts a PING on Wi-Fi channel 1 (like the field kit).
  A board that hears a PING answers with a PONG. The sender counts the answers and
  measures the round-trip time. Every 10 s it prints a summary.

  PASS when, at the distance you plan to use (e.g. 10 m, 30 m, through a wall):
  - at least 90 % of the pings are answered,
  - RSSI (signal strength, in dBm) is shown. Closer to 0 is stronger. As a rule of
    thumb, packets start to get lost when it gets weaker than about -80 dBm.
  Walk away with one board (on a power bank) to find your real range.
*/

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <esp_mac.h>
#include <esp_log.h>

const uint8_t CHANNEL = 1;
const uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
const uint32_t PING_EVERY_MS = 1000;
const uint32_t REPORT_EVERY_MS = 10000;

// The radio message. "packed" = no gaps between the fields.
struct __attribute__((packed)) TestMsg {
  char magic[4];      // "AAT1" = Analog Atlas Test, version 1
  uint8_t type;       // 1 = PING, 2 = PONG
  uint8_t target[6];  // PONG only: MAC address of the board that sent the PING
  uint32_t seq;       // ping number
  uint32_t sentUs;    // sender's micros() when the PING left
};

struct RxItem {
  TestMsg msg;
  uint8_t from[6];
  int8_t rssi;
};

QueueHandle_t rxQueue;  // a FreeRTOS queue is a ready-made, thread-safe ring buffer
uint8_t myMac[6];
uint32_t seq = 0, lastPingMs = 0, lastReportMs = 0;
uint32_t pingsSent = 0, pongsGot = 0, pingsHeard = 0;
long rssiSum = 0;
int rssiMin = 0, rssiCount = 0;
uint32_t rttSumUs = 0, rttMaxUs = 0;
uint32_t queueFull = 0;  // changed by the Wi-Fi task: only use it inside statLock
portMUX_TYPE statLock = portMUX_INITIALIZER_UNLOCKED;

// Runs in the Wi-Fi task: only copy the packet into the queue, never print here.
void onReceive(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != (int)sizeof(TestMsg) || info == nullptr) return;
  RxItem item;
  memcpy(&item.msg, data, sizeof(TestMsg));
  if (memcmp(item.msg.magic, "AAT1", 4) != 0) return;
  memcpy(item.from, info->src_addr, 6);
  item.rssi = info->rx_ctrl ? (int8_t)info->rx_ctrl->rssi : 0;
  if (xQueueSend(rxQueue, &item, 0) != pdTRUE) {  // never wait inside the callback
    portENTER_CRITICAL(&statLock);
    queueFull++;
    portEXIT_CRITICAL(&statLock);
  }
}

void send(uint8_t type, const uint8_t *target, uint32_t s, uint32_t sentUs) {
  TestMsg m = {};
  memcpy(m.magic, "AAT1", 4);
  m.type = type;
  if (target) memcpy(m.target, target, 6);
  m.seq = s;
  m.sentUs = sentUs;
  esp_now_send(BROADCAST, (const uint8_t *)&m, sizeof(m));
}

void setup() {
  Serial.begin(115200);
  esp_log_level_set("*", ESP_LOG_NONE);
  delay(500);
  Serial.println();
  Serial.println("=== Analog Atlas TEST 7: ESP-NOW ping test (run this on BOTH boards) ===");
  rxQueue = xQueueCreate(16, sizeof(RxItem));
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("FAIL: ESP-NOW did not start");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onReceive);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("FAIL: could not add the broadcast peer");
    while (true) delay(1000);
  }
  esp_read_mac(myMac, ESP_MAC_WIFI_STA);
  Serial.printf("This board: %02X:%02X:%02X:%02X:%02X:%02X, channel %u. Waiting for the other board...\n", myMac[0],
                myMac[1], myMac[2], myMac[3], myMac[4], myMac[5], CHANNEL);
  lastReportMs = millis();
}

void loop() {
  uint32_t now = millis();
  if (now - lastPingMs >= PING_EVERY_MS) {
    lastPingMs = now;
    seq++;
    send(1, nullptr, seq, (uint32_t)micros());
    pingsSent++;
  }

  RxItem it;
  while (xQueueReceive(rxQueue, &it, 0) == pdTRUE) {
    if (it.msg.type == 1) {  // PING from the other board: answer at once
      send(2, it.from, it.msg.seq, it.msg.sentUs);
      pingsHeard++;
    } else if (it.msg.type == 2 && memcmp(it.msg.target, myMac, 6) == 0) {  // PONG for us
      uint32_t rtt = (uint32_t)micros() - it.msg.sentUs;
      pongsGot++;
      rttSumUs += rtt;
      if (rtt > rttMaxUs) rttMaxUs = rtt;
      rssiSum += it.rssi;
      if (rssiCount == 0 || it.rssi < rssiMin) rssiMin = it.rssi;
      rssiCount++;
      Serial.printf("pong #%lu from %02X:%02X:%02X:%02X:%02X:%02X  rtt %.1f ms  rssi %d dBm\n",
                    (unsigned long)it.msg.seq, it.from[0], it.from[1], it.from[2], it.from[3], it.from[4],
                    it.from[5], rtt / 1000.0f, it.rssi);
    }
  }

  if (now - lastReportMs >= REPORT_EVERY_MS) {
    lastReportMs = now;
    Serial.println("---------------------------------------------------------------");
    if (pongsGot == 0) {
      Serial.printf("last 10 s: sent %lu pings, NO answer (heard %lu pings from others).\n", (unsigned long)pingsSent,
                    (unsigned long)pingsHeard);
      Serial.println("FAIL: is the other board powered and running this same sketch? Both use channel 1.");
    } else {
      uint32_t pct = pongsGot * 100 / (pingsSent ? pingsSent : 1);
      if (pct > 100) pct = 100;  // with more than 2 boards there can be more answers
      Serial.printf("last 10 s: sent %lu pings, got %lu answers (%lu %%), rssi avg %ld dBm (weakest %d), rtt avg %.1f ms (max %.1f)\n",
                    (unsigned long)pingsSent, (unsigned long)pongsGot, (unsigned long)pct, rssiSum / rssiCount, rssiMin,
                    rttSumUs / 1000.0f / pongsGot, rttMaxUs / 1000.0f);
      Serial.println(pct >= 90 ? "PASS: the link works at this distance" : "FAIL: too many lost packets at this distance");
    }
    portENTER_CRITICAL(&statLock);
    uint32_t lost = queueFull;
    queueFull = 0;
    portEXIT_CRITICAL(&statLock);
    if (lost) Serial.printf("(%lu packets lost because the queue was full)\n", (unsigned long)lost);
    Serial.println("---------------------------------------------------------------");
    pingsSent = pongsGot = pingsHeard = 0;
    rssiSum = 0;
    rssiCount = 0;
    rssiMin = 0;
    rttSumUs = rttMaxUs = 0;
  }
  delay(1);
}
