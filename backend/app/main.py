"""FastAPI entry point for the NeurIPS 2025 papers explorer."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qs, quote_plus, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import PaperResponse, SearchRequest, SearchResponse
from .search import PaperStore

app = FastAPI(title="NeurIPS 2025 Papers API", version="1.0.0")

NOISE_KEYWORDS = (
    "webcache.googleusercontent.com",
    "translate.google",
    "/search?",
    "tbm=",
    "imgres",
    "policies.google",
    "support.google",
)


def _resolve_google_href(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith("/url?") or href.startswith("https://www.google.com/url?") or href.startswith("http://www.google.com/url?"):
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        for key in ("q", "url"):
            values = qs.get(key)
            if values:
                return values[0]
        return ""
    return href


def _looks_like_noise(url: str) -> bool:
    lowered = url.lower()
    return any(token in lowered for token in NOISE_KEYWORDS)


def _is_arxiv_abs(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() == "arxiv.org" and parsed.path.startswith("/abs/")


def _is_arxiv_pdf(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() == "arxiv.org" and parsed.path.startswith("/pdf/")


def _arxiv_abs_url_from_pdf(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "arxiv.org":
        return None
    path = parsed.path
    if not path.startswith("/pdf/"):
        return None
    identifier = path[len("/pdf/") :]
    if identifier.endswith(".pdf"):
        identifier = identifier[:-4]
    identifier = identifier.strip("/")
    if not identifier:
        return None
    new_path = f"/abs/{identifier}"
    cleaned = parsed._replace(path=new_path, query="", fragment="")
    return cleaned.geturl()


def _normalize_title(text: str) -> str:
    # Simple normalization: lowercase, collapse spaces, strip punctuation-like chars
    keep = []
    for ch in text.lower():
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
        else:
            keep.append(" ")
    return " ".join("".join(keep).split())


def _lookup_arxiv_via_export_api(title: str, author_last: str) -> str | None:
    """Query arXiv export API using title phrase and optional author filter.

    Returns an /abs/ URL or None.
    """
    cleaned_title = title.strip()
    if not cleaned_title:
        return None
    # Build query: exact title phrase + optional author last name
    q = f'ti:"{cleaned_title}"'
    if author_last.strip():
        q += f" AND au:{author_last.strip()}"
    url = f"http://export.arxiv.org/api/query?search_query={quote_plus(q)}&start=0&max_results=5"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "neurips2025-explorer/1.0 (+https://github.com/seilk/neurips2025-explorer)"},
            timeout=5,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    desired = _normalize_title(cleaned_title)
    best: str | None = None
    for entry in root.findall("atom:entry", ns):
        entry_title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        norm_entry = _normalize_title(entry_title)
        # Prefer exact normalized match
        if norm_entry == desired:
            # get id or alternate link
            id_text = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
            if id_text and _is_arxiv_abs(id_text):
                return id_text
            for link in entry.findall("atom:link", ns):
                href = link.attrib.get("href", "").strip()
                if _is_arxiv_abs(href):
                    return href
                if _is_arxiv_pdf(href):
                    converted = _arxiv_abs_url_from_pdf(href)
                    if converted:
                        return converted
        # Keep the first sensible candidate as a fallback
        if best is None:
            id_text = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
            if _is_arxiv_abs(id_text):
                best = id_text
            else:
                for link in entry.findall("atom:link", ns):
                    href = link.attrib.get("href", "").strip()
                    if _is_arxiv_abs(href):
                        best = href
                        break
                    if _is_arxiv_pdf(href):
                        conv = _arxiv_abs_url_from_pdf(href)
                        if conv:
                            best = conv
                            break
    return best

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
    """Return the best arXiv link using arXiv API first, then Google SERP fallback."""
    cleaned_title = title.strip()
    if not cleaned_title:
        return None

    # 1) Try arXiv export API (most reliable and bot-safe)
    api_hit = _lookup_arxiv_via_export_api(cleaned_title, author_last)
    if api_hit:
        return api_hit

    # 2) Fallback to Google SERP parsing
    author_last_clean = author_last.strip()
    query_parts = [cleaned_title]
    if author_last_clean:
        query_parts.append(f"intext: {author_last_clean}")
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
    pdf_candidate: str | None = None

    for anchor in soup.find_all("a", href=True):
        target = _resolve_google_href(anchor["href"])
        if not target:
            continue
        if _looks_like_noise(target):
            continue
        parsed = urlparse(target)
        if not parsed.scheme or not parsed.netloc:
            continue

        if _is_arxiv_abs(target):
            return target
        if _is_arxiv_pdf(target) and pdf_candidate is None:
            converted = _arxiv_abs_url_from_pdf(target)
            if converted:
                pdf_candidate = converted

    return pdf_candidate


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


def _test_arxiv_helpers() -> None:
    """Lightweight assertions for helper utilities."""
    # 1) /abs/ link should be preserved
    assert _resolve_google_href("/url?q=https://arxiv.org/abs/2201.00001") == "https://arxiv.org/abs/2201.00001"
    # 2) /pdf/ with .pdf suffix converts to /abs/
    pdf_url = _resolve_google_href("/url?q=https://arxiv.org/pdf/2201.00001.pdf")
    assert _arxiv_abs_url_from_pdf(pdf_url) == "https://arxiv.org/abs/2201.00001"
    # 3) /pdf/ without .pdf suffix converts to /abs/
    assert _arxiv_abs_url_from_pdf("https://arxiv.org/pdf/2201.00001") == "https://arxiv.org/abs/2201.00001"
    # 4) Nested redirects via other domains are ignored by arXiv detectors
    redirected = _resolve_google_href("/url?q=https://example.com/redirect?url=https://arxiv.org/abs/2201.00001")
    assert not _is_arxiv_abs(redirected)
    assert not _is_arxiv_pdf(redirected)
    # 5) Known noise URLs are filtered
    assert _looks_like_noise("https://translate.google.com/.../")
    # 6) Google cache URLs are noise
    assert _looks_like_noise("https://webcache.googleusercontent.com/...")
    # 7) Helper returns None when no PDF identifier
    assert _arxiv_abs_url_from_pdf("https://arxiv.org/pdf/") is None


if __name__ == "__main__":
    _test_arxiv_helpers()
