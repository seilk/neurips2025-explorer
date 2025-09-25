"""Search helpers used by the API layer."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from . import database

LIST_SEPARATOR = " | "


def prepare_fts_query(query: str) -> str:
    """Convert a raw user query into an FTS5-friendly string.

    We split on whitespace, escape any unwanted characters, and append a
    trailing `*` so partial matches work as the user types.  Keeping the query
    simple prevents FTS syntax errors while remaining performant.
    """
    tokens = re.findall(r"\w+", query.lower())
    if not tokens:
        return ""
    return " AND ".join(f"{token}*" for token in tokens)


def fts_lookup(conn: sqlite3.Connection, query: str) -> List[int]:
    if not query:
        return []
    fts_query = prepare_fts_query(query)
    if not fts_query:
        return []
    rows = conn.execute(
        "SELECT rowid FROM papers_fts WHERE papers_fts MATCH ?;", (fts_query,)
    ).fetchall()
    return [row[0] for row in rows]


def normalise_filters(raw_filters: Dict[str, Any] | None) -> Dict[str, List[str]]:
    if not raw_filters:
        return {}
    normalised: Dict[str, List[str]] = {}
    for key, value in raw_filters.items():
        if value is None:
            continue
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, Sequence):
            candidates = [str(item) for item in value]
        else:
            candidates = [str(value)]
        normalised[key] = [candidate.strip() for candidate in candidates if candidate.strip()]
    return normalised


def record_matches_filters(record: Dict[str, Any], filters: Dict[str, List[str]]) -> bool:
    for field, values in filters.items():
        if not values:
            continue
        field_value = record.get(field)
        if field_value is None:
            # Try the helper column present in the SQLite index (e.g. authors_search)
            helper_value = record.get(f"{field}_search")
            if helper_value is not None:
                field_value = helper_value
        if field_value is None:
            return False

        if isinstance(field_value, bool):
            field_tokens = ["true" if field_value else "false"]
        elif isinstance(field_value, (int, float)):
            field_tokens = [str(field_value)]
        elif isinstance(field_value, str):
            field_tokens = [field_value]
        elif isinstance(field_value, dict):
            field_tokens = [str(field_value)]
        elif isinstance(field_value, Iterable):
            field_tokens = [str(item) for item in field_value]
        else:
            field_tokens = [str(field_value)]

        lowered_tokens = [token.lower() for token in field_tokens]
        if not any(value.lower() in token for token in lowered_tokens for value in values):
            return False
    return True


def sort_records(records: List[Dict[str, Any]], field: str, descending: bool = False) -> None:
    def sort_key(record: Dict[str, Any]) -> Any:
        value = record.get(field)
        if isinstance(value, list) and value:
            return str(value[0]).lower()
        if value is None:
            return ""
        return str(value).lower()

    records.sort(key=sort_key, reverse=descending)


def augment_record(record: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in list(record.items()):
        if value is None:
            continue
        if isinstance(value, list):
            joined = LIST_SEPARATOR.join(str(item) for item in value if item not in (None, ""))
            record[f"{key}_search"] = joined
        elif isinstance(value, dict):
            record[f"{key}_search"] = json.dumps(value)
    return record


class PaperStore:
    """In-memory view over the SQLite dataset with FTS acceleration."""

    def __init__(self) -> None:
        self.conn = database.open_connection()
        raw_records = database.fetch_all_records(self.conn)
        self.records = [augment_record(record) for record in raw_records]
        self.record_by_id = {record["id"]: record for record in self.records}
        self.all_ids = [record["id"] for record in self.records]
        self.columns = list(database.list_columns(self.conn))
        self.facets = self._build_facets()

    def _build_facets(self) -> Dict[str, List[str]]:
        """Collect distinct values for commonly-used filters."""
        facet_fields = {
            "decision": 50,
            "event_type": 50,
            "session": 100,
            "topic": 100,
            "keywords": 200,
            "authors": 200,
        }
        facets: Dict[str, set[str]] = {key: set() for key in facet_fields}
        for record in self.records:
            for field, limit in facet_fields.items():
                raw_value = record.get(field)
                if raw_value is None:
                    continue
                if isinstance(raw_value, list):
                    for item in raw_value:
                        if len(facets[field]) >= limit:
                            break
                        facets[field].add(str(item))
                else:
                    if len(facets[field]) < limit:
                        facets[field].add(str(raw_value))
        return {field: sorted(values) for field, values in facets.items()}

    def search(
        self,
        query: str | None,
        filters: Dict[str, Any] | None,
        page: int,
        page_size: int,
        sort_by: str | None,
        sort_order: str | None,
        seed: str | None = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        filters_norm = normalise_filters(filters)

        if query:
            id_candidates = fts_lookup(self.conn, query)
            if not id_candidates:
                return 0, []
        else:
            id_candidates = self.all_ids

        candidate_records = [self.record_by_id[i] for i in id_candidates]

        matched_records = [record for record in candidate_records if record_matches_filters(record, filters_norm)]

        if sort_by == "random":
            # Stable, seedable random ordering across pages using a deterministic hash
            import hashlib

            s = seed or "0"

            def rand_key(record: Dict[str, Any]) -> int:
                rid = str(record.get("id", ""))
                h = hashlib.sha256(f"{s}:{rid}".encode("utf-8")).digest()
                # Use first 8 bytes as big-endian integer
                return int.from_bytes(h[:8], "big", signed=False)

            matched_records.sort(key=rand_key)
        elif sort_by:
            descending = sort_order == "desc"
            sort_records(matched_records, sort_by, descending)
        else:
            sort_records(matched_records, "name")

        total = len(matched_records)
        start = max(page - 1, 0) * page_size
        end = start + page_size
        paginated = matched_records[start:end]
        return total, paginated

    def get(self, paper_id: int) -> Dict[str, Any] | None:
        return self.record_by_id.get(paper_id)

    def schema(self) -> Dict[str, Any]:
        field_types: Dict[str, str] = {}
        for record in self.records:
            for key, value in record.items():
                if value is None:
                    continue
                detected = detect_type(value)
                if key in field_types and field_types[key] != detected:
                    field_types[key] = "mixed"
                else:
                    field_types.setdefault(key, detected)
        return {
            "fields": [
                {"name": name, "type": field_type}
                for name, field_type in sorted(field_types.items())
            ],
            "facets": self.facets,
        }


def detect_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"
