"""FastAPI entry point for the NeurIPS 2025 papers explorer."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import PaperResponse, SearchRequest, SearchResponse
from .search import PaperStore

app = FastAPI(title="NeurIPS 2025 Papers API", version="1.0.0")

# Enable CORS for the web frontend. Adjust the origins list when you know the
# exact deployment domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.on_event("startup")
def startup() -> None:
    app.state.store = PaperStore()


def get_store() -> PaperStore:
    store = getattr(app.state, "store", None)
    if store is None:
        raise RuntimeError("PaperStore is not initialised")
    return store


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    """Simple landing route so Render and users get a 200 response."""
    return {
        "status": "ok",
        "message": "NeurIPS 2025 Papers API. See /docs for interactive documentation or /health for status.",
    }


@lru_cache(maxsize=256)
def lookup_arxiv_url(title: str) -> str | None:
    """Return the best arXiv link for a paper title, or None if unavailable."""
    cleaned = title.strip()
    if not cleaned:
        return None
    query = quote_plus(f'"{cleaned}"')
    url = f"http://export.arxiv.org/api/query?search_query=ti:{query}&start=0&max_results=1"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "neurips2025-explorer/1.0 (+https://github.com/seilk/neurips2025-explorer)"},
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None

    id_text = entry.findtext("atom:id", default="", namespaces=ns).strip()
    if "arxiv.org/abs" in id_text:
        return id_text

    for link in entry.findall("atom:link", ns):
        href = link.attrib.get("href", "").strip()
        if "arxiv.org/abs" in href:
            return href

    return None


@app.get("/papers/schema")
def schema(store: PaperStore = Depends(get_store)) -> dict[str, object]:
    return store.schema()


@app.post("/papers/search", response_model=SearchResponse)
def search_papers(payload: SearchRequest, store: PaperStore = Depends(get_store)) -> SearchResponse:
    total, results = store.search(
        query=payload.query,
        filters=payload.filters,
        page=payload.page,
        page_size=payload.page_size,
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
    )
    return SearchResponse(total=total, page=payload.page, page_size=payload.page_size, results=results)


@app.get("/papers/{paper_id}", response_model=PaperResponse)
def get_paper(paper_id: int, store: PaperStore = Depends(get_store)) -> PaperResponse:
    paper = store.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PaperResponse(paper=paper)


@app.get("/arxiv")
def arxiv_lookup(title: str = Query(..., min_length=3, max_length=200)) -> dict[str, str]:
    """Resolve the most relevant arXiv link for a paper title."""
    resolved = lookup_arxiv_url(title)
    fallback = f"https://www.google.com/search?q={quote_plus(title)}"
    if resolved and "arxiv.org/abs" in resolved:
        return {"url": resolved, "source": "arxiv"}
    return {"url": fallback, "source": "google"}
