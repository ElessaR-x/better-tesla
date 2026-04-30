# better-tesla — Tesla CAN Bus Analyzer

## Pipeline
```
Tesla CAN → NodeMCU ESP8266 + MCP2515 (8MHz) → Serial/USB 115200
           → Python serial bridge (bridge.py)
           → MCP Server (mcp_server.py) + ChromaDB RAG
           → Claude Code (live analysis)
```

## Hardware
- NodeMCU ESP8266 (nodemcuv2)
- MCP2515 CAN controller — **ALWAYS use MCP_8MHZ crystal**
- SPI wiring: CS=D8(GPIO15), INT=D2(GPIO4), SCK=D5, MOSI=D7, MISO=D6

## CAN Bus Speeds
| Bus       | Speed   | Signals              |
|-----------|---------|----------------------|
| Chassis   | 500kbps | speed, steering, ABS |
| Body      | 125kbps | HVAC, lights, doors  |
| Vehicle   | 500kbps | drivetrain, battery  |

Default: 500kbps (Chassis bus)

## Serial Protocol (115200 baud)
Output: newline-delimited JSON frames
```json
{"ts":12345,"id":"0x123","ext":false,"dlc":8,"data":"01 02 03 04 05 06 07 08"}
```

Commands (send over serial, newline-terminated):
- `ping`            — health check
- `stats`           — frame counts
- `reset`           — clear stats
- `speed 125|250|500` — change CAN speed live
- `filter <hex_id>` — accept only one 11-bit ID
- `nofilter`        — accept all frames

## Project Structure
```
firmware/         PlatformIO project (ESP8266 + MCP2515)
  src/main.cpp    CAN sniffer firmware
  include/config.h  pin/speed config
  platformio.ini

bridge/           Python serial → MCP bridge (TODO)
  bridge.py

mcp_server/       MCP server + ChromaDB RAG (TODO)
  server.py
  rag.py

data/             DBC files + decoded JSON (~100MB, not in git)
```

## MCP Server Tools (to implement)
- `read_live_frames(n)` — last N CAN frames
- `search_dbc(id)`      — match ID against DBC database via ChromaDB
- `watch_changes(seconds)` — IDs that changed in last N seconds
- `annotate(id, signal_name, notes)` — save new signal mapping

## Key Rules
- MCP2515 crystal is **8MHz** — never change to 16MHz
- DBC data lives in `data/` — index with ChromaDB, never load all into RAM
- Serial output is always newline-delimited JSON (OUTPUT_FORMAT=1)
- Tesla Chassis bus: 500kbps, Body bus: 125kbps
