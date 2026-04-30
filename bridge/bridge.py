"""
Serial bridge: NodeMCU firmware → SQLite

Reads newline-delimited JSON frames from ESP8266 serial port,
writes them to a SQLite database that the MCP server queries.

Usage:
    python bridge.py                    # auto-detect port
    python bridge.py --port /dev/ttyUSB0
    python bridge.py --port /dev/ttyUSB0 --db ../can.db
    python bridge.py --list-ports
"""

import argparse
import json
import logging
import signal
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import serial
import serial.tools.list_ports

DB_PATH = Path(__file__).parent.parent / "can.db"
BAUD = 115200
RECONNECT_DELAY = 2.0   # seconds between reconnect attempts
FRAME_TABLE_MAX = 100_000  # prune oldest rows above this threshold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS frames (
            rowid    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_dev   INTEGER NOT NULL,
            ts_host  REAL    NOT NULL,
            can_id   TEXT    NOT NULL,
            is_ext   INTEGER NOT NULL DEFAULT 0,
            dlc      INTEGER NOT NULL,
            data     TEXT    NOT NULL,
            bus      INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_frames_can_id  ON frames(can_id);
        CREATE INDEX IF NOT EXISTS idx_frames_ts_host ON frames(ts_host);

        CREATE TABLE IF NOT EXISTS annotations (
            can_id      TEXT PRIMARY KEY,
            signal_name TEXT NOT NULL,
            notes       TEXT NOT NULL DEFAULT '',
            updated_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bridge_log (
            rowid    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_host  REAL NOT NULL,
            level    TEXT NOT NULL,
            msg      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS commands (
            rowid    INTEGER PRIMARY KEY AUTOINCREMENT,
            cmd      TEXT NOT NULL,
            status   TEXT NOT NULL DEFAULT 'pending'
        );
    """)
    conn.commit()
    return conn


@contextmanager
def db_cursor(conn: sqlite3.Connection):
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def insert_frame(conn: sqlite3.Connection, frame: dict) -> None:
    with db_cursor(conn) as cur:
        cur.execute(
            "INSERT INTO frames (ts_dev, ts_host, can_id, is_ext, dlc, data, bus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                frame["ts"],
                time.time(),
                frame["id"].upper(),
                1 if frame.get("ext") else 0,
                frame["dlc"],
                frame["data"],
                frame.get("bus", 0),
            ),
        )


def prune_frames(conn: sqlite3.Connection) -> None:
    """Keep only the most recent FRAME_TABLE_MAX rows."""
    with db_cursor(conn) as cur:
        cur.execute(
            "DELETE FROM frames WHERE rowid NOT IN "
            "(SELECT rowid FROM frames ORDER BY rowid DESC LIMIT ?)",
            (FRAME_TABLE_MAX,),
        )
        deleted = cur.rowcount
    if deleted > 0:
        log.debug("Pruned %d old frames", deleted)


def log_to_db(conn: sqlite3.Connection, level: str, msg: str) -> None:
    try:
        with db_cursor(conn) as cur:
            cur.execute(
                "INSERT INTO bridge_log (ts_host, level, msg) VALUES (?, ?, ?)",
                (time.time(), level, msg),
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Serial port helpers
# ---------------------------------------------------------------------------

def find_nodemcu_port() -> str | None:
    """Return first likely NodeMCU/CH340/CP210x port."""
    keywords = ["CH340", "CP210", "USB Serial", "usbserial", "ttyUSB", "ttyACM", "wchusbserial"]
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "") + (port.manufacturer or "") + (port.hwid or "")
        if any(k.lower() in desc.lower() for k in keywords):
            return port.device
    # fallback: first available
    ports = serial.tools.list_ports.comports()
    return ports[0].device if ports else None


def list_ports() -> None:
    print("Available serial ports:")
    for p in serial.tools.list_ports.comports():
        print(f"  {p.device:20s}  {p.description}")


# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------

def parse_line(line: str) -> dict | None:
    """Parse a JSON line from firmware. Returns frame dict or None."""
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Distinguish frame messages from status/command responses
    if "id" in obj and "dlc" in obj and "data" in obj:
        return obj
    return None


# ---------------------------------------------------------------------------
# Main bridge loop
# ---------------------------------------------------------------------------

def run_bridge(port: str, db_path: Path, stop_event: Event) -> None:
    conn = init_db(db_path)
    log.info("Database: %s", db_path)
    log_to_db(conn, "INFO", f"Bridge started on {port}")

    frame_count = 0
    prune_every = 5000  # prune DB every N frames

    while not stop_event.is_set():
        try:
            log.info("Connecting to %s @ %d baud ...", port, BAUD)
            ser = serial.Serial(port, BAUD, timeout=1.0)
            log.info("Connected.")
            log_to_db(conn, "INFO", f"Serial connected: {port}")

            while not stop_event.is_set():
                # Process pending commands
                try:
                    with db_cursor(conn) as cur:
                        cur.execute("SELECT rowid, cmd FROM commands WHERE status='pending' ORDER BY rowid ASC")
                        pending_cmds = cur.fetchall()
                        for rowid, cmd in pending_cmds:
                            cmd_bytes = (cmd.strip() + "\n").encode("ascii")
                            ser.write(cmd_bytes)
                            log.info("Sent cmd: %s", cmd.strip())
                            cur.execute("UPDATE commands SET status='done' WHERE rowid=?", (rowid,))
                except Exception as e:
                    log.warning("Error processing commands: %s", e)

                raw = ser.readline()
                if not raw:
                    continue

                try:
                    line = raw.decode("ascii", errors="replace")
                except Exception:
                    continue

                frame = parse_line(line)
                if frame is None:
                    # Print non-frame messages (boot, stats, commands)
                    stripped = line.strip()
                    if stripped:
                        log.info("FW >> %s", stripped)
                    continue

                insert_frame(conn, frame)
                frame_count += 1

                if frame_count % 100 == 0:
                    log.info("Frames: %d  (latest id=%s)", frame_count, frame["id"])

                if frame_count % prune_every == 0:
                    prune_frames(conn)

        except serial.SerialException as e:
            log.warning("Serial error: %s — retrying in %.1fs", e, RECONNECT_DELAY)
            log_to_db(conn, "WARN", str(e))
            time.sleep(RECONNECT_DELAY)
        except KeyboardInterrupt:
            break

    log.info("Bridge stopped. Total frames written: %d", frame_count)
    log_to_db(conn, "INFO", f"Bridge stopped. frames={frame_count}")
    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="better-tesla serial bridge")
    parser.add_argument("--port", help="Serial port (auto-detect if omitted)")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--list-ports", action="store_true", help="List ports and exit")
    parser.add_argument("--baud", type=int, default=BAUD, help="Baud rate")
    args = parser.parse_args()

    if args.list_ports:
        list_ports()
        return

    port = args.port or find_nodemcu_port()
    if not port:
        log.error("No serial port found. Use --port or --list-ports.")
        sys.exit(1)

    stop_event = Event()

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    run_bridge(port, Path(args.db), stop_event)


if __name__ == "__main__":
    main()
