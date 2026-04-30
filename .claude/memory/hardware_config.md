---
name: Hardware configuration constraints
description: NodeMCU + MCP2515 wiring and Tesla CAN bus speed settings
type: project
---

MCP2515 crystal is ALWAYS 8MHz → always use MCP_8MHZ constant in firmware and config. Never use 16MHz.

SPI wiring (NodeMCU ESP8266):
- CS:   D8 / GPIO15
- INT:  D2 / GPIO4
- SCK:  D5 / GPIO14
- MOSI: D7 / GPIO13
- MISO: D6 / GPIO12

Tesla CAN bus speeds:
- Chassis bus: 500kbps (speed, steering, brakes, ABS)
- Body bus:    125kbps (HVAC, lights, doors)
- Vehicle bus: 500kbps (drivetrain, battery)
Default test: Chassis bus at 500kbps.

**Why:** 8MHz crystal mismatch causes all CAN reads to fail silently. Body bus needs separate speed setting.
**How to apply:** Any firmware or bridge code must default to MCP_8MHZ + CAN_500KBPS.
