---
name: better-tesla project overview
description: Goal, pipeline, and component status for the Tesla CAN bus analyzer project
type: project
---

Project builds a live Tesla CAN bus analyzer and signal mapper.

Pipeline: Tesla CAN → NodeMCU ESP8266 + MCP2515 (8MHz crystal) → Serial/USB 115200 → Python bridge → MCP Server → Claude Code

Components:
- firmware/ — PlatformIO/Arduino firmware for ESP8266 + MCP2515. DONE (v1.0.0)
- bridge/ — Python serial bridge. TODO
- mcp_server/ — MCP server with ChromaDB RAG for DBC lookups. TODO
- data/ — ~100MB DBC files + decoded JSON, to be indexed with ChromaDB

**Why:** Real-time unknown signal discovery on Tesla CAN buses using AI-assisted annotation.

**How to apply:** Next steps are Python serial bridge (bridge.py) then MCP server + ChromaDB setup.
