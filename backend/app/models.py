"""Pydantic models shared across the API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from .config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class SearchRequest(BaseModel):
    """Incoming payload for the search endpoint."""

    query: Optional[str] = Field(None, description="Full text query to run against all fields")
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dictionary of field -> value(s) used for filtering."
    )
    page: int = Field(1, ge=1, description="1-based page index")
    page_size: int = Field(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Number of results per page",
    )
    sort_by: Optional[str] = Field(
        None,
        description="Field name to sort by (defaults to title)",
    )
    sort_order: Optional[str] = Field(
        "asc",
        description="Sort direction: 'asc' or 'desc'",
    )

    @validator("query")
    def trim_query(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return value.strip() or None

    @validator("sort_order")
    def validate_sort_order(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        candidate = value.lower()
        if candidate not in {"asc", "desc"}:
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return candidate


class SearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[Dict[str, Any]]


class PaperResponse(BaseModel):
    paper: Dict[str, Any]
