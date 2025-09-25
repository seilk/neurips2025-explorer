"""FastAPI entry point for the NeurIPS 2025 papers explorer."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
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
def lookup_arxiv_url(title: str, author_initial: str, author_last: str) -> str | None:
    """Return the best arXiv link using Google results with author heuristics."""
    cleaned_title = title.strip()
    if not cleaned_title:
        return None

    author_initial_clean = author_initial.strip()
    author_last_clean = author_last.strip()
    expected_author = (
        f"{author_initial_clean[:1].lower()} {author_last_clean.lower()}"
        if author_initial_clean and author_last_clean
        else ""
    )

    query_parts = [cleaned_title]
    if author_initial_clean and author_last_clean:
        query_parts.append(f"intext: {author_initial_clean[:1]} {author_last_clean}")
    query = quote_plus(" ".join(query_parts))
    search_url = f"https://www.google.com/search?q={query}&hl=en"
    try:
        response = requests.get(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            },
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    first_result = soup.select_one("div.g")
    if first_result is None:
        return None

    anchor = first_result.find("a", href=True)
    if anchor is None:
        return None
    href = anchor["href"].strip()

    if href.startswith("/url?"):
        parsed = urlparse(href)
        target = parse_qs(parsed.query).get("q", [href])[0]
    else:
        target = href

    if "arxiv.org/abs" not in target:
        return None

    return target


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
def arxiv_lookup(
    title: str = Query(..., min_length=3, max_length=200),
    author_initial: str = Query("", max_length=10),
    author_last: str = Query("", max_length=120),
) -> dict[str, str]:
    """Resolve the most relevant arXiv link for a paper title."""
    resolved = lookup_arxiv_url(title, author_initial, author_last)
    fallback = f"https://www.google.com/search?q={quote_plus(title)}"
    if resolved and "arxiv.org/abs" in resolved:
        return {"url": resolved, "source": "arxiv"}
    return {"url": fallback, "source": "google"}
