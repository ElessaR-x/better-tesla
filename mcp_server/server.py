"""
better-tesla MCP Server

Tools:
  read_live_frames(n)              — last N CAN frames from SQLite
  search_dbc(query)                — semantic + exact search in ChromaDB
  watch_changes(seconds)           — IDs active in last N seconds
  annotate(id, signal_name, notes) — save signal annotation

Run:
    python server.py
    # or via MCP CLI:
    mcp run server.py
"""

import sqlite3
import time
from pathlib import Path

import chromadb
from mcp.server.fastmcp import FastMCP

DB_PATH    = Path(__file__).parent.parent / "can.db"
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION = "can_signals"

mcp = FastMCP("better-tesla")

# ---------------------------------------------------------------------------
# Shared resources (lazy init — opened on first tool call)
# ---------------------------------------------------------------------------

_chroma_col = None
_db_conn    = None


def _col():
    global _chroma_col
    if _chroma_col is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _chroma_col = client.get_collection(COLLECTION)
    return _chroma_col


def _db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        if not DB_PATH.exists():
            raise RuntimeError(
                f"Database not found: {DB_PATH}\n"
                "Start bridge.py first to collect frames."
            )
        _db_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn


# ---------------------------------------------------------------------------
# Tool: read_live_frames
# ---------------------------------------------------------------------------

@mcp.tool()
def read_live_frames(n: int = 50) -> list[dict]:
    """
    Return the last N CAN frames recorded by the serial bridge.

    Each frame: { rowid, ts_dev, ts_host, can_id, is_ext, dlc, data }
      - ts_dev:  milliseconds since device boot
      - ts_host: Unix timestamp (host clock)
      - can_id:  hex string, e.g. "0x118"
      - data:    space-separated hex bytes, e.g. "01 A2 FF 00 00 00 00 00"
    """
    n = max(1, min(n, 1000))
    cur = _db().execute(
        "SELECT rowid, ts_dev, ts_host, can_id, is_ext, dlc, data "
        "FROM frames ORDER BY rowid DESC LIMIT ?",
        (n,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()  # chronological order
    return rows


# ---------------------------------------------------------------------------
# Tool: search_dbc
# ---------------------------------------------------------------------------

@mcp.tool()
def search_dbc(query: str, n_results: int = 8) -> list[dict]:
    """
    Search the DBC knowledge base for a CAN ID or signal keyword.

    `query` can be:
      - A hex CAN ID:  "0x118" or "118" or "264"
      - A decimal ID:  "264"
      - A signal name or keyword: "torque", "speed", "door", "brake"

    Returns up to n_results matches with full signal metadata.
    Each result: { frame_name, signal_name, bus_name, address_hex, unit,
                   enum_labels, start_bit, length, scale, offset, source, score }
    """
    col = _col()
    results = []

    # --- Exact address match (hex or decimal) ---
    stripped = query.strip().lower().lstrip("0x")
    exact_results: list[dict] = []

    # Try to interpret as a number
    try:
        addr_int = int(stripped, 16) if all(c in "0123456789abcdef" for c in stripped) else int(stripped)
        addr_hex = f"0x{addr_int:03X}"
        where = {"address_hex": {"$eq": addr_hex}}
        exact = col.get(where=where, include=["metadatas"])
        if exact["ids"]:
            for meta in exact["metadatas"]:
                exact_results.append({**meta, "score": 1.0, "match": "exact_id"})
    except (ValueError, Exception):
        pass

    if exact_results:
        return exact_results[:n_results]

    # --- Semantic / keyword search ---
    res = col.query(
        query_texts=[query],
        n_results=min(n_results, col.count()),
        include=["metadatas", "distances"],
    )
    for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
        results.append({
            **meta,
            "score": round(1.0 - dist, 4),
            "match": "semantic",
        })

    return results


# ---------------------------------------------------------------------------
# Tool: watch_changes
# ---------------------------------------------------------------------------

@mcp.tool()
def watch_changes(seconds: float = 5.0) -> list[dict]:
    """
    Return CAN IDs that were active in the last `seconds` seconds,
    with frame count and first/last seen timestamps.

    Useful for spotting which IDs react when you press a button or
    move a control on the car.

    Returns list of: { can_id, frame_count, first_seen, last_seen, dlc }
    """
    seconds = max(0.1, min(seconds, 300.0))
    since = time.time() - seconds
    cur = _db().execute(
        """
        SELECT can_id,
               COUNT(*)       AS frame_count,
               MIN(ts_host)   AS first_seen,
               MAX(ts_host)   AS last_seen,
               MAX(dlc)       AS dlc
        FROM   frames
        WHERE  ts_host >= ?
        GROUP  BY can_id
        ORDER  BY frame_count DESC
        """,
        (since,),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Tool: annotate
# ---------------------------------------------------------------------------

@mcp.tool()
def annotate(can_id: str, signal_name: str, notes: str = "") -> dict:
    """
    Save a human-readable annotation for a CAN signal.

    can_id:      hex string like "0x118" or "118"
    signal_name: short name you assign, e.g. "vehicle_speed_kmh"
    notes:       any extra context, units, observed values, etc.

    Annotations are stored in the SQLite database and persist across sessions.
    Existing annotations for the same can_id are overwritten.
    """
    # Normalise CAN ID to uppercase 0x... format
    stripped = can_id.strip().lstrip("0x").lstrip("0X")
    try:
        addr_int = int(stripped, 16)
        normalised_id = f"0x{addr_int:03X}"
    except ValueError:
        return {"ok": False, "error": f"Invalid CAN ID: {can_id!r}"}

    db = _db()
    db.execute(
        """
        INSERT INTO annotations (can_id, signal_name, notes, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(can_id) DO UPDATE SET
            signal_name = excluded.signal_name,
            notes       = excluded.notes,
            updated_at  = excluded.updated_at
        """,
        (normalised_id, signal_name, notes, time.time()),
    )
    db.commit()
    return {
        "ok":         True,
        "can_id":     normalised_id,
        "signal_name": signal_name,
        "notes":      notes,
    }


# ---------------------------------------------------------------------------
# Tool: send_command
# ---------------------------------------------------------------------------

@mcp.tool()
def send_command(cmd: str) -> dict:
    """
    Send a raw command to the NodeMCU firmware via the serial bridge.
    
    Examples:
      - 'hazard on'  (enables auto-hazard)
      - 'hazard off'
      - 'mute on'
      - 'send 3C2 0800000000000000'  (inject a raw frame)
      - 'stats'
    """
    db = _db()
    db.execute("INSERT INTO commands (cmd) VALUES (?)", (cmd,))
    db.commit()
    return {
        "ok": True,
        "cmd": cmd,
        "note": "Command queued. The bridge will send it to the serial port shortly."
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
