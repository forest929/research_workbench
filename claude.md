# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI-powered systematic review platform ("AI Portfolio Architect") — built on Nebius AI Cloud for a hackathon. Users import literature, run LLM analysis to extract inclusion/exclusion criteria, screen papers with LLM assistance + active learning, and iteratively refine the review through a human feedback loop.

## Running the project

See **README.md** for full setup, environment, and the corpus-build pipeline.
Quick start:

```bash
# Backend (DB migrations auto-run on startup via the FastAPI lifespan)
uvicorn api.main:app --reload --port 8000

# Frontend (the React SPA is the only UI)
cd frontend && npm run dev   # http://localhost:5173
```

Create a project and import documents from the app (search / file upload / DOI
list), or rebuild the corpus with the `scripts/` pipeline (see README.md →
"Rebuild the corpus"). The legacy Streamlit UI has been removed.

## Architecture

```
api/                       FastAPI backend
  main.py                  Lifespan: pool init + migrations
  deps.py                  get_conn() dependency (SQLite via _ConnProxy shim)
  routers/
    projects.py / ingest.py / workbench.py / reading_list.py

portfolio_architect/
  agents/
    coordinator.py         trigger_research_run() state machine
    runner.py              asyncio.gather() over 3 workstreams
    workstreams/           parameter_extraction, literature_synthesis, cluster_selection
    checks/                structural_check (pure Python), logical_check (LLM judge)
  db/
    migrations.py          ALTER_STATEMENTS list + run_migrations()
    pool.py                aiosqlite pool (get_pool / close_pool)
    *.py                   per-table CRUD modules
  embedding/client.py      Nebius Endpoints (BAAI/bge-m3, dim=1024)
  feedback/
    decision_memory.py     store_decision(), retrieve_similar_examples() (cosine k-NN)
    disagreement.py        record_disagreement() when LLM ≠ human
    preference_learning.py update_preferences(), build_guidance_text() (threshold=3)
  ingestion/chunker.py     chunk_text() — shared by API router + ingest script
  llm/
    client.py              generate() → Nebius Token Factory
    prompt_builder.py      build_messages() for screening (criteria + few-shot + guidance)
  ranking/active_learning.py  rank_pending_documents() — pure-numpy cosine k-NN uncertainty

frontend/                  React + Vite SPA — the only UI
  src/pages/               Projects, Ingest (progress), Workbench, ReadingList

scripts/
  ingest_global_warming.py  Data ingest ONLY — no LLM calls (analysis decoupled)
```

## Critical implementation details

### SQLite / asyncpg shim
The DB layer uses **aiosqlite** with a `_ConnProxy` in `db/pool.py` that mimics the asyncpg interface. All SQL uses **`?` placeholders** (not `$1`). `fetchrow` returns a dict-like object; use `r["column"]` not `r.column`.

SQLite has no `ADD COLUMN IF NOT EXISTS` — migrations wrap each `ALTER TABLE` in `try/except` in `db/migrations.py`.

### Feedback / decision memory loop
- Human corrections stored via `feedback/decision_memory.store_decision()`
- On each new paper, `retrieve_similar_examples()` does cosine similarity over all stored decisions and returns the top-k as few-shot examples injected into the screening prompt
- After ≥3 decisions with the same reason code, `preference_learning.py` surfaces a pattern and injects guidance text into future prompts
- LLM prediction is auto-triggered when a paper loads in the screening UI (no button required)

### Ingestion / LLM separation
- `scripts/ingest_global_warming.py` — data only (fetch → chunk → embed → persist)
- LLM analysis is always triggered separately via the API (`POST /projects/{id}/run`)
- Chunking is in `portfolio_architect/ingestion/chunker.py`, imported by both the router and the script

### LLM calls
All generation goes through `portfolio_architect/llm/client.generate()` → Nebius Token Factory. The LLM judge (`checks/logical_check.py`) is a separate call with a distinct prompt and returns strict JSON parsed defensively.

## Environment variables

```bash
NEBIUS_API_KEY=...
NEBIUS_ENDPOINT_URL=...       # embedding endpoint
NEBIUS_LLM_MODEL=...          # Token Factory model for generation
NEBIUS_JUDGE_MODEL=...        # ideally different model for the judge
DATABASE_URL=sqlite:///...    # or Nebius managed PG
NCBI_API_KEY=...              # optional; increases PubMed rate limit
API_BASE_URL=http://localhost:8000   # backend URL
```

See `.env.example` for the full list. Never commit `.env`.
