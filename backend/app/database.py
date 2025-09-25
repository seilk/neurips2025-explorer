"""Data access helpers for the NeurIPS papers explorer backend."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import get_database_path


def open_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a read-only SQLite connection to the papers database."""
    if db_path is None:
        db_path = get_database_path()
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_records(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieve every paper as a parsed dictionary."""
    rows = conn.execute("SELECT id, raw_json FROM papers ORDER BY id ASC;").fetchall()
    records: List[Dict[str, Any]] = []
    for row in rows:
        record = json.loads(row["raw_json"])
        record["id"] = row["id"]
        records.append(record)
    return records


def list_columns(conn: sqlite3.Connection) -> Iterable[str]:
    """Return the known column names from the `papers` table."""
    rows = conn.execute("PRAGMA table_info(papers);").fetchall()
    return [row[1] for row in rows]
