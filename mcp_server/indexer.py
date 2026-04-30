"""
One-time indexer: DBC files + decoded JSON → ChromaDB

Run once before starting the MCP server:
    python indexer.py

Re-run any time data files change.
"""

import json
import sys
from pathlib import Path

import cantools
import chromadb

DATA_DIR   = Path(__file__).parent.parent / "data"
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION = "can_signals"

DBC_FILES = [
    ("vehicle", DATA_DIR / "vehicle.dbc"),
    ("party",   DATA_DIR / "party.dbc"),
]
JSON_FILE = DATA_DIR / "can_frames_decoded_all_values_mcu3.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc_text(frame_name: str, signal_name: str, bus: str,
                   unit: str, enum_labels: list[str]) -> str:
    """Build a rich text blob for semantic embedding."""
    parts = [frame_name, signal_name, bus]
    if unit:
        parts.append(f"unit:{unit}")
    if enum_labels:
        parts.append("values: " + " ".join(enum_labels[:40]))
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# DBC parsing
# ---------------------------------------------------------------------------

def load_dbc_documents(source: str, path: Path) -> list[dict]:
    """Parse one DBC file → list of ChromaDB-ready document dicts."""
    db = cantools.database.load_file(str(path))
    docs = []
    for msg in db.messages:
        addr_hex = f"0x{msg.frame_id:03X}"
        for sig in msg.signals:
            unit = sig.unit or ""
            enum_labels = [str(v) for v in sig.choices.values()] if sig.choices else []
            doc_id = f"{source}_{addr_hex}_{sig.name}"
            docs.append({
                "id":        doc_id,
                "text":      _make_doc_text(msg.name, sig.name, source, unit, enum_labels),
                "metadata": {
                    "source":       source,
                    "address_hex":  addr_hex,
                    "address_dec":  msg.frame_id,
                    "frame_name":   msg.name,
                    "signal_name":  sig.name,
                    "bus_name":     source.upper(),
                    "unit":         unit,
                    "enum_labels":  ", ".join(str(v) for v in enum_labels[:60]),
                    "start_bit":    sig.start,
                    "length":       sig.length,
                    "scale":        sig.scale,
                    "offset":       sig.offset,
                },
            })
    return docs


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def load_json_documents() -> list[dict]:
    """Parse can_frames_decoded_all_values_mcu3.json → ChromaDB documents."""
    with open(JSON_FILE) as f:
        data = json.load(f)

    docs = []
    for frame in data["frames"]:
        addr_hex  = frame["address_hex"]
        frame_name = frame["frame_name"]
        bus_name   = frame["bus_name"]

        for sig in frame["signals"]:
            sig_name = sig["signal_name"]
            enum_labels = [pv["label"] for pv in sig.get("possible_values", [])]

            doc_id = f"mcu3_{addr_hex}_{sig_name}"
            docs.append({
                "id":    doc_id,
                "text":  _make_doc_text(frame_name, sig_name, bus_name, "", enum_labels),
                "metadata": {
                    "source":       "mcu3_json",
                    "address_hex":  addr_hex,
                    "address_dec":  frame["address_dec"],
                    "frame_name":   frame_name,
                    "signal_name":  sig_name,
                    "bus_name":     bus_name,
                    "unit":         "",
                    "enum_labels":  ", ".join(enum_labels[:60]),
                    "start_bit":    -1,
                    "length":       -1,
                    "scale":        1.0,
                    "offset":       0.0,
                },
            })
    return docs


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def build_index() -> None:
    print(f"ChromaDB path: {CHROMA_DIR}")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Drop and recreate for a clean index
    try:
        client.delete_collection(COLLECTION)
        print("Dropped existing collection.")
    except Exception:
        pass

    col = client.create_collection(
        COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    all_docs: list[dict] = []

    # DBC files
    for source, path in DBC_FILES:
        if not path.exists():
            print(f"  SKIP (not found): {path}")
            continue
        docs = load_dbc_documents(source, path)
        print(f"  {source}.dbc → {len(docs)} signals")
        all_docs.extend(docs)

    # JSON
    if JSON_FILE.exists():
        docs = load_json_documents()
        print(f"  mcu3 JSON → {len(docs)} signals")
        all_docs.extend(docs)

    # Deduplicate by id (JSON wins over DBC for same address+signal)
    seen: dict[str, dict] = {}
    for d in all_docs:
        seen[d["id"]] = d
    unique = list(seen.values())
    print(f"Total unique documents: {len(unique)}")

    # Batch upsert — re-fetch collection each time to avoid stale reference
    batch = 500
    for i in range(0, len(unique), batch):
        chunk = unique[i : i + batch]
        col = client.get_collection(COLLECTION)
        col.add(
            ids=[d["id"] for d in chunk],
            documents=[d["text"] for d in chunk],
            metadatas=[d["metadata"] for d in chunk],
        )
        print(f"  Indexed {min(i + batch, len(unique))} / {len(unique)} ...")

    print("Done.")


if __name__ == "__main__":
    build_index()
