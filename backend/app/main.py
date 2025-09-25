"""FastAPI entry point for the NeurIPS 2025 papers explorer."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
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
