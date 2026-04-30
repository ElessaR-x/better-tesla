#include <Arduino.h>
#include <SPI.h>
#include <mcp2515.h>
#include "config.h"

MCP2515 mcp2515(CAN_CS_PIN);

struct FrameEntry {
    uint32_t id;
    uint8_t  dlc;
    uint8_t  data[8];
    uint32_t ts_ms;
    bool     ext;
};

FrameEntry frameBuf[FRAME_BUF_SIZE];
volatile uint8_t bufHead = 0;
volatile uint8_t bufTail = 0;
volatile uint8_t bufCount = 0;

// --- stats ---
uint32_t totalFrames = 0;
uint32_t errorCount  = 0;

// --- command parser ---
String cmdBuf = "";

// --- reverse mute state ---
bool     muteModeEnabled = false;   // user toggle: mute on/off
bool     inReverse       = false;
uint32_t lastMuteInject  = 0;
uint8_t  muteCounter     = 0;       // rolling counter for 0x221

// --- hazard (dörtlü) auto-on in reverse ---
bool     hazardModeEnabled = true;  // user toggle: hazard-on-reverse
bool     hazardsAreOn      = false; // tracks actual hazard state from 0x3F5
uint8_t  last3C2m0[8]      = {0x00, 0x55, 0x55, 0x55, 0x00, 0x00, 0x69, 0x85}; // fallback base

// 0x221 VCFRONT_LVPowerState (mux 0) — observed frame structure:
//   bytes 0-5 constant: 60 54 44 05 54 51
//   byte 6: bits 0-1 = 01 (constant), bits 2-3 = uiAudioLVState, bits 4-7 = counter (odd only)
//   byte 7: checksum = XOR(bytes 0-6) ^ (counter&4 ? 0x37 : 0xB7)
// uiAudioLVState values: 0=LV_OFF, 1=LV_ON, 2=LV_GOING_DOWN, 3=LV_FAULT
static const uint8_t MUTE_FRAME_BASE[6] = {0x60, 0x54, 0x44, 0x05, 0x54, 0x51};

uint8_t computeChecksum221(const uint8_t* d, uint8_t counter) {
    uint8_t xorVal = 0;
    for (int i = 0; i < 7; i++) xorVal ^= d[i];
    // base constant flips bit 7 when counter bit 2 is set
    uint8_t base = (counter & 0x04) ? 0x37 : 0xB7;
    return xorVal ^ base;
}

void injectMuteFrame() {
    can_frame f;
    f.can_id  = 0x221;
    f.can_dlc = 8;
    memcpy(f.data, MUTE_FRAME_BASE, 6);
    // byte 6: counter in high nibble (odd), LV_FAULT(3) in bits 2-3, bits 0-1 = 01
    uint8_t ctr = (muteCounter * 2 + 1) & 0x0F; // odd counters: 1,3,5,7,9,11,13,15
    f.data[6] = (ctr << 4) | 0x0D;              // 0x0D = bits[0-1]=01, bits[2-3]=11(LV_FAULT)
    f.data[7] = computeChecksum221(f.data, ctr);
    muteCounter = (muteCounter + 1) & 0x07;
    mcp2515.sendMessage(&f);
}

// ---------------------------------------------------------------------------
// 0x3C2 VCLEFT_switchStatus — physical hazard button spoofing
// ---------------------------------------------------------------------------
void toggleHazardButton() {
    can_frame f;
    f.can_id  = 0x3C2;
    f.can_dlc = 8;
    memcpy(f.data, last3C2m0, 8);
    // Set bit 3 in byte 0 to simulate VCLEFT_hazardButtonPressed = 1
    f.data[0] |= 0x08; 
    mcp2515.sendMessage(&f);
}

void checkGearFrame(const can_frame& f) {
    // Track VCFRONT_lighting (0x3F5) to know if hazards are actually on
    if ((f.can_id & CAN_EFF_MASK) == 0x3F5 && f.can_dlc >= 1) {
        uint8_t req = (f.data[0] >> 4) & 0x0F;
        hazardsAreOn = (req != 0);
        return;
    }

    // Cache the latest 0x3C2 m0 frame for safe injection
    if ((f.can_id & CAN_EFF_MASK) == 0x3C2 && f.can_dlc == 8) {
        // Mux index is bits 0-1 of byte 0. If 0, it's m0.
        if ((f.data[0] & 0x03) == 0) {
            memcpy(last3C2m0, f.data, 8);
        }
        return;
    }

    if ((f.can_id & CAN_EFF_MASK) != 0x118) return;
    if (f.can_dlc < 4) return;
    // DI_gear: bit 21, length 3, little-endian
    uint32_t raw = (uint32_t)f.data[0]
                 | ((uint32_t)f.data[1] << 8)
                 | ((uint32_t)f.data[2] << 16)
                 | ((uint32_t)f.data[3] << 24);
    uint8_t gear = (raw >> 21) & 0x07;
    bool wasReverse = inReverse;
    inReverse = (gear == 2); // DI_GEAR_R = 2
    if (inReverse != wasReverse) {
        Serial.print(F("{\"event\":\"gear\",\"reverse\":"));
        Serial.print(inReverse ? F("true") : F("false"));
        Serial.println(F("}"));
        // Toggle hazard button if it doesn't match our desired state
        if (hazardModeEnabled) {
            if (inReverse && !hazardsAreOn) toggleHazardButton();
            else if (!inReverse && hazardsAreOn) toggleHazardButton();
        }
    }
}

void pushFrame(const can_frame& f) {
    if (bufCount >= FRAME_BUF_SIZE) {
        bufTail = (bufTail + 1) % FRAME_BUF_SIZE;
        bufCount--;
    }
    FrameEntry& e = frameBuf[bufHead];
    e.id    = f.can_id & CAN_EFF_MASK;
    e.dlc   = f.can_dlc;
    e.ext   = (f.can_id & CAN_EFF_FLAG) != 0;
    e.ts_ms = millis();
    memcpy(e.data, f.data, f.can_dlc);
    bufHead = (bufHead + 1) % FRAME_BUF_SIZE;
    bufCount++;
    totalFrames++;
}

void printFrameJSON(const FrameEntry& e) {
    Serial.print(F("{\"ts\":"));
    Serial.print(e.ts_ms);
    Serial.print(F(",\"id\":\"0x"));
    if (e.ext) {
        char buf[9];
        snprintf(buf, sizeof(buf), "%08X", e.id);
        Serial.print(buf);
    } else {
        char buf[4];
        snprintf(buf, sizeof(buf), "%03X", e.id);
        Serial.print(buf);
    }
    Serial.print(F("\",\"ext\":"));
    Serial.print(e.ext ? F("true") : F("false"));
    Serial.print(F(",\"dlc\":"));
    Serial.print(e.dlc);
    Serial.print(F(",\"data\":\""));
    for (uint8_t i = 0; i < e.dlc; i++) {
        char h[3];
        snprintf(h, sizeof(h), "%02X", e.data[i]);
        Serial.print(h);
        if (i < e.dlc - 1) Serial.print(' ');
    }
    Serial.println(F("\"}"));
}

void printFrameCSV(const FrameEntry& e) {
    Serial.print(e.ts_ms);
    Serial.print(',');
    if (e.ext) {
        Serial.print(e.id, HEX);
    } else {
        char buf[4];
        snprintf(buf, sizeof(buf), "%03X", e.id);
        Serial.print(buf);
    }
    Serial.print(',');
    Serial.print(e.dlc);
    Serial.print(',');
    for (uint8_t i = 0; i < e.dlc; i++) {
        char h[3];
        snprintf(h, sizeof(h), "%02X", e.data[i]);
        Serial.print(h);
        if (i < e.dlc - 1) Serial.print(' ');
    }
    Serial.println();
}

void printFrame(const FrameEntry& e) {
#if OUTPUT_FORMAT == 1
    printFrameJSON(e);
#else
    printFrameCSV(e);
#endif
}

void flushBuffer() {
    while (bufCount > 0) {
        printFrame(frameBuf[bufTail]);
        bufTail = (bufTail + 1) % FRAME_BUF_SIZE;
        bufCount--;
    }
}

void handleCommand(const String& cmd) {
    if (cmd == "stats") {
        Serial.print(F("{\"cmd\":\"stats\",\"total\":"));
        Serial.print(totalFrames);
        Serial.print(F(",\"errors\":"));
        Serial.print(errorCount);
        Serial.print(F(",\"buf\":"));
        Serial.print(bufCount);
        Serial.print(F(",\"mute\":"));
        Serial.print(muteModeEnabled ? F("true") : F("false"));
        Serial.print(F(",\"hazard\":"));
        Serial.print(hazardModeEnabled ? F("true") : F("false"));
        Serial.print(F(",\"reverse\":"));
        Serial.print(inReverse ? F("true") : F("false"));
        Serial.println(F("}"));
    } else if (cmd == "reset") {
        totalFrames = 0;
        errorCount  = 0;
        Serial.println(F("{\"cmd\":\"reset\",\"ok\":true}"));
    } else if (cmd == "ping") {
        Serial.println(F("{\"cmd\":\"ping\",\"ok\":true}"));
    } else if (cmd == "mute on") {
        muteModeEnabled = true;
        Serial.println(F("{\"cmd\":\"mute\",\"enabled\":true}"));
    } else if (cmd == "mute off") {
        muteModeEnabled = false;
        Serial.println(F("{\"cmd\":\"mute\",\"enabled\":false}"));
    } else if (cmd == "hazard on") {
        hazardModeEnabled = true;
        Serial.println(F("{\"cmd\":\"hazard\",\"enabled\":true}"));
    } else if (cmd == "hazard off") {
        hazardModeEnabled = false;
        if (hazardsAreOn) toggleHazardButton();
        Serial.println(F("{\"cmd\":\"hazard\",\"enabled\":false}"));
    } else if (cmd.startsWith("send ")) {
        // send <hex_id> <hex_data_no_spaces>  e.g. send 221 605444055451FC00
        String rest = cmd.substring(5);
        int sp = rest.indexOf(' ');
        if (sp < 0) {
            Serial.println(F("{\"cmd\":\"send\",\"ok\":false,\"err\":\"format: send <id> <data>\"}"));
            return;
        }
        uint32_t sid = strtoul(rest.substring(0, sp).c_str(), nullptr, 16);
        String hexData = rest.substring(sp + 1);
        hexData.trim();
        can_frame f;
        f.can_id  = sid;
        f.can_dlc = hexData.length() / 2;
        if (f.can_dlc > 8) f.can_dlc = 8;
        for (uint8_t i = 0; i < f.can_dlc; i++) {
            char h[3] = {hexData[i*2], hexData[i*2+1], 0};
            f.data[i] = strtoul(h, nullptr, 16);
        }
        MCP2515::ERROR err = mcp2515.sendMessage(&f);
        Serial.print(F("{\"cmd\":\"send\",\"id\":\"0x"));
        Serial.print(sid, HEX);
        Serial.print(F("\",\"ok\":"));
        Serial.println(err == MCP2515::ERROR_OK ? F("true}") : F("false}"));
    } else if (cmd.startsWith("speed ")) {
        int kbps = cmd.substring(6).toInt();
        CAN_SPEED newSpeed;
        bool valid = true;
        switch (kbps) {
            case 125: newSpeed = CAN_125KBPS; break;
            case 250: newSpeed = CAN_250KBPS; break;
            case 500: newSpeed = CAN_500KBPS; break;
            default:  valid = false; break;
        }
        if (valid) {
            mcp2515.reset();
            mcp2515.setBitrate(newSpeed, CAN_CRYSTAL);
            mcp2515.setNormalMode();
            Serial.print(F("{\"cmd\":\"speed\",\"kbps\":"));
            Serial.print(kbps);
            Serial.println(F(",\"ok\":true}"));
        } else {
            Serial.println(F("{\"cmd\":\"speed\",\"ok\":false,\"err\":\"use 125/250/500\"}"));
        }
    } else if (cmd.startsWith("filter ")) {
        uint32_t filterId = strtoul(cmd.substring(7).c_str(), nullptr, 16);
        mcp2515.setConfigMode();
        mcp2515.setFilterMask(MCP2515::MASK0, false, 0x7FF);
        mcp2515.setFilter(MCP2515::RXF0, false, filterId);
        mcp2515.setNormalMode();
        Serial.print(F("{\"cmd\":\"filter\",\"id\":\"0x"));
        Serial.print(filterId, HEX);
        Serial.println(F("\",\"ok\":true}"));
    } else if (cmd == "nofilter") {
        mcp2515.setConfigMode();
        mcp2515.setFilterMask(MCP2515::MASK0, false, 0);
        mcp2515.setFilterMask(MCP2515::MASK1, false, 0);
        mcp2515.setNormalMode();
        Serial.println(F("{\"cmd\":\"nofilter\",\"ok\":true}"));
    } else {
        Serial.println(F("{\"cmd\":\"unknown\",\"ok\":false}"));
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(200);
    Serial.println(F("{\"boot\":\"better-tesla-sniffer\",\"v\":\"1.1.0\"}"));

    mcp2515.reset();
    MCP2515::ERROR err = mcp2515.setBitrate(CAN_DEFAULT_SPEED, CAN_CRYSTAL);
    if (err != MCP2515::ERROR_OK) {
        Serial.print(F("{\"fatal\":\"mcp2515_bitrate\",\"code\":"));
        Serial.print((int)err);
        Serial.println(F("}"));
        while (1) { delay(1000); }
    }
    mcp2515.setNormalMode();
    Serial.println(F("{\"mcp2515\":\"ready\",\"speed\":\"500kbps\",\"crystal\":\"8MHz\"}"));
}

void loop() {
    if (mcp2515.checkReceive()) {
        can_frame frame;
        MCP2515::ERROR err = mcp2515.readMessage(&frame);
        if (err == MCP2515::ERROR_OK) {
            checkGearFrame(frame);
            pushFrame(frame);
        } else {
            errorCount++;
        }
    }

    // Inject mute frame every 100ms while in reverse and mute enabled
    if (muteModeEnabled && inReverse) {
        uint32_t now = millis();
        if (now - lastMuteInject >= 100) {
            lastMuteInject = now;
            injectMuteFrame();
        }
    }

    // Periodic injection is no longer needed since physical button toggle latches in GTW.

    if (bufCount > 0) {
        flushBuffer();
    }

    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            cmdBuf.trim();
            if (cmdBuf.length() > 0) {
                handleCommand(cmdBuf);
                cmdBuf = "";
            }
        } else {
            cmdBuf += c;
        }
    }

    yield();
}
