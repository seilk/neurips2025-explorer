# NeurIPS 2025 Papers Explorer

Fast, mobile-friendly search UI for NeurIPS 2025 accepted papers with full‑text search, rich filters, LaTeX, and instant highlighting.

- Backend: FastAPI + in‑memory SQLite FTS5 (very fast queries)
- Frontend: Next.js (App Router), KaTeX for LaTeX, animated UI
- Deploy: Render (API) + Vercel or Render (Web)

## Quick Start (Local)

Build index → run API → run Web.

```
pip install -r backend/requirements.txt
python backend/scripts/build_index.py \
  --input neurips_2025_accepted_papers.json \
  --output backend/data/papers.db

export PAPERS_DB_PATH=backend/data/papers.db
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

In another shell:

```
cd frontend
export NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm ci
npm run dev
```

Open http://localhost:3000

## Key Features

- FTS across all fields; facets for Decision/Topic
- Titles/Abstracts render LaTeX (remark‑math + rehype‑katex)
- Keyword highlighting (orange, across fields)
- “Go to arXiv” prefers arXiv Export API; robust Google fallback
- Global Shuffle and A–Z
  - Shuffle uses server‑side ordering with a seed for stable pagination

## API

- GET `/health` – health check
- GET `/` – API info
- GET `/papers/schema` – field types + facet values
- POST `/papers/search` – body: `{ query?, filters?, page, page_size, sort_by?, sort_order?, seed? }`
  - `sort_by: "random"` with `seed: string` → stable global shuffle
- GET `/arxiv?title=...&author_initial=...&author_last=...` → `{ url, source }`

## Deploy (Render: API)

This repo includes `render.yaml`.

- Build: `pip install -r backend/requirements.txt` then build index
- Start Command (answer to “Start Command?”):
  - `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`

After deploy, note the service URL, e.g. `https://<service>.onrender.com`.

## Deploy (Web)

Vercel (recommended free tier):

- Env Var: `NEXT_PUBLIC_API_BASE_URL=https://<your-render-api>.onrender.com`
- Build: `npm ci && npm run build`
- Start: `next start -p $PORT`

Render (Web Service):

- Same build/start as above; set `NEXT_PUBLIC_API_BASE_URL` accordingly

Tip: The API returns JSON at `/`, so you must deploy the frontend separately for the site UI.

## Notes

- CORS is `*` for convenience; restrict to your frontend origin in production.
- The index builder deduplicates exact‑title duplicates before writing the DB.
