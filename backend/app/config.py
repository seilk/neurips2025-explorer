"""Application configuration values.

The defaults here are designed for local development.  They can be overridden
with environment variables when deploying to Render or another hosting service.
"""
from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "papers.db"


def get_database_path() -> Path:
    """Return the SQLite database location, falling back to the packaged copy."""
    override = os.getenv("PAPERS_DB_PATH")
    if override:
        return Path(override)
    return DEFAULT_DB_PATH


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
