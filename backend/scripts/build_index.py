"""Build a high-performance SQLite/FTS index from the NeurIPS 2025 accepted papers JSON.

Usage:
    python backend/scripts/build_index.py \
        --input ../../neurips_2025_accepted_papers.json \
        --output backend/data/papers.db

The script loads the JSON payload produced by OpenReview, normalises each paper
into a flat dictionary, and stores it into a SQLite database with an
FTS5-powered full text search virtual table.  Additional derivations (e.g.
search blobs for list fields) are included so that the API layer can perform
fast filtering without duplicating preprocessing logic.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List

LOGGER = logging.getLogger(__name__)


TEXT_LIST_SEPARATOR = " | "


def read_json(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict) or "results" not in payload:
        raise ValueError("Unexpected JSON structure: expected top-level 'results' list")
    results = payload["results"]
    if not isinstance(results, list):
        raise ValueError("'results' must be a list")
    LOGGER.info("Loaded %d paper entries", len(results))
    return results


def normalise_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested structures so SQLite can index them easily.

    - Lists are stored both as JSON (for inspection) and pipe-separated text (for FTS/filtering).
    - Dicts are stored as JSON strings.
    - Scalars are kept as-is.
    """
    row: Dict[str, Any] = {}
    text_fragments: List[str] = []

    for key, value in record.items():
        if key == "id":
            row[key] = int(value) if value is not None else None
            continue

        if value is None:
            row[key] = None
            continue

        if isinstance(value, list):
            # Keep the original JSON plus a friendly text version for search/filtering.
            row[key] = json.dumps(value, ensure_ascii=False)
            joined = TEXT_LIST_SEPARATOR.join(str(item) for item in value if item not in (None, ""))
            search_key = f"{key}_search"
            if joined:
                row[search_key] = joined
                text_fragments.append(joined)
            else:
                row[search_key] = ""
        elif isinstance(value, dict):
            row[key] = json.dumps(value, ensure_ascii=False)
            text_fragments.append(json.dumps(value, ensure_ascii=False))
        else:
            row[key] = value
            text_fragments.append(str(value))

    # FTS column with all searchable text bundled together.
    row["search_blob"] = "\n".join(fragment for fragment in text_fragments if fragment)
    # Keep pristine JSON around so the API can reconstruct exact structures easily.
    row["raw_json"] = json.dumps(record, ensure_ascii=False)
    return row


def prepare_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in records:
        row = normalise_record(record)
        if "id" not in row or row["id"] is None:
            raise ValueError("Each record must include a numeric 'id'")
        rows.append(row)
    return rows


def create_database(path: Path, rows: List[Dict[str, Any]]) -> None:
    if path.exists():
        LOGGER.info("Removing existing database at %s", path)
        path.unlink()

    columns = sorted({key for row in rows for key in row.keys() if key != "id"})
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")

        column_defs = ["id INTEGER PRIMARY KEY"] + [f'"{col}" TEXT' for col in columns]
        conn.execute(f"CREATE TABLE papers ({', '.join(column_defs)});")

        placeholders = ", ".join([":" + col for col in ["id", *columns]])
        insert_sql = f"INSERT INTO papers ({', '.join(['id', *columns])}) VALUES ({placeholders});"

        with conn:
            conn.executemany(insert_sql, [{col: row.get(col) for col in ['id', *columns]} for row in rows])

        conn.execute(
            """
            CREATE VIRTUAL TABLE papers_fts USING fts5(
                search_blob,
                content='papers',
                content_rowid='id',
                tokenize='unicode61'
            );
            """
        )
        conn.execute(
            "INSERT INTO papers_fts (rowid, search_blob) SELECT id, search_blob FROM papers;"
        )

        # Helpful covering indexes for common filters.
        for col in ("decision", "event_type", "session", "topic", "visible"):
            if col in columns:
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_papers_{col} ON papers('{col}');".replace("'", ""))

        conn.commit()
        LOGGER.info("Database built with %d rows and %d columns", len(rows), len(columns) + 1)
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Path to the source JSON file")
    parser.add_argument("--output", type=Path, required=True, help="Destination SQLite database path")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    records = read_json(args.input)
    rows = prepare_rows(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    create_database(args.output, rows)


if __name__ == "__main__":
    main()
