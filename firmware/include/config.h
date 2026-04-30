#pragma once

// MCP2515 SPI pins (NodeMCU ESP8266)
// D8 = GPIO15 = SS/CS
// D7 = GPIO13 = MOSI
// D6 = GPIO12 = MISO
// D5 = GPIO14 = SCK
// D2 = GPIO4  = INT (optional interrupt pin)
#define CAN_CS_PIN 15 // D8
#define CAN_INT_PIN 4 // D2

// Second MCP2515 (Optional)
// Set ENABLE_SECOND_MCP2515 to true to enable reading from a second CAN bus.
// It shares SPI pins (MOSI, MISO, SCK) but uses a different CS pin.
#define ENABLE_SECOND_MCP2515 true
#define CAN2_CS_PIN 0 // D3

// MCP2515 oscillator: ALWAYS 8MHz crystal
#define CAN_CRYSTAL MCP_8MHZ

// Tesla CAN bus speeds
// Chassis bus: 500kbps  (most signals: speed, steering, brakes)
// Body bus:    125kbps  (HVAC, lights, doors)
// Vehicle bus: 500kbps
#define CAN_DEFAULT_SPEED CAN_500KBPS

// Serial output
#define SERIAL_BAUD 115200

// Frame buffer size (ring buffer)
#define FRAME_BUF_SIZE 64

// Output format: 0=CSV, 1=JSON
#define OUTPUT_FORMAT 1
