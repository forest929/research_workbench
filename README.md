# AI Research Workbench

A scientific research workbench for drug-therapy evidence, built on **Nebius AI
Cloud**. It ingests biomedical literature, extracts structured claims, clusters
them across papers, synthesizes cited answers, and visualizes the whole evidence
landscape as an interactive map. You can also add your own sources by DOI and see
where they land against the corpus.

The bundled demo corpus is **women's cancer drug evidence** (breast, ovarian,
cervical, endometrial): ~10k PubMed papers → ~27k claims → ~16k clusters, each
multi-source cluster carrying a cited, synthesized answer.

> Note: this repo grew out of an earlier "portfolio architect" screening tool
> (the `agents/`, `feedback/`, `screening` code). The **workbench is the current
> product** and the only surface in the React UI.

---

## 1. Prerequisites

| Tool | Version | Used for |
|------|---------|----------|
| Python | 3.12+ (tested on 3.13) | backend + data pipeline |
| Node.js | 18+ | frontend (Vite + React) |
| Nebius account | — | LLM (Token Factory) + embedding endpoint |

From **[Nebius AI Studio](https://studio.nebius.ai)** you need:
1. An **API key** (used for both the Token Factory LLM and the embedding endpoint).
2. A deployed **embedding endpoint** serving `Qwen/Qwen3-Embedding-8B` (dim 4096).

---

## 2. Backend setup

```bash
# from the repo root
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .                     # installs deps declared in pyproject.toml
```

### Configure environment

```bash
cp .env.example .env
```

Edit `.env` — the values that matter:

```bash
NEBIUS_KEY=sk-...                                   # your Nebius API key
GENERATION_MODEL=meta-llama/Llama-3.3-70B-Instruct  # Token Factory model
JUDGE_MODEL=nvidia/Llama-3_1-Nemotron-Ultra-253B-v1

# Embedding endpoint — MUST be Qwen3-Embedding-8B / 4096-dim to match the corpus.
# (.env.example still shows the older bge-m3 / 1024 defaults — override them.)
NEBIUS_EMBEDDING_URL=https://<your-endpoint>.api.nebius.ai/v1/
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=4096

DATABASE_PATH=portfolio_architect.db

# Optional — only for the fine-tuned side-by-side comparison (self-hosted vLLM).
# Leave blank; the workbench works fine without it.
FINETUNED_BASE_URL=
FINETUNED_MODEL=
```

> ⚠️ The embedding model/dimension **must** match what the corpus was built with
> (`Qwen/Qwen3-Embedding-8B`, 4096). A mismatch makes all similarity/clustering
> meaningless. Never commit `.env`.

---

## 3. Frontend setup

```bash
cd frontend
npm install
cd ..
```

The dev server proxies `/api` → `http://localhost:8000` (see
`frontend/vite.config.js`), so the backend must be running for the UI to work.

---

## 4. Get data into the database

The DB schema is created automatically on first backend start (migrations run in
the FastAPI lifespan). Two options for content:

### Option A — Use the bundled corpus (fastest)

The repo ships `portfolio_architect.db` already populated with the fully
processed women's-cancer corpus (project id
`100d1b89-e6bd-4628-a1d6-aefe89fcabe1`). **Skip to step 5.** You still need a
valid `NEBIUS_KEY` + embedding endpoint for live features (add-by-DOI).

### Option B — Rebuild the corpus from scratch

Run the pipeline in order. Grab the project ID from the first command's output
and reuse it. This makes many LLM + embedding calls — budget a few dollars and
~1–2 hours.

```bash
# 1. Ingest PubMed papers (past 3 years, most-recent-first; skip chunk-embedding)
python scripts/ingest_womens_cancer_drugs.py --pubmed-only --no-embed --max-records 12000
export PID=<project-id-printed-above>

# 2. Extract structured claims (~1 LLM call per paper)
python scripts/extract_claims.py --project-id $PID --concurrency 12

# 3. Embed the claims (Qwen3 endpoint)
python scripts/backfill_claim_embeddings.py --project-id $PID

# 4. Cluster claims (verified, PubMed-only; pure compute, no LLM)
python scripts/rebuild_clusters.py --project-id $PID

# 5. Precompute 2D map coordinates + save the PCA projection model
python scripts/compute_cluster_coords.py --project-id $PID

# 6. Synthesize a cited answer per multi-source cluster (~1 LLM call per cluster)
python scripts/build_conversations.py --project-id $PID --min-members 2

# 7. Backfill publication month/year from the PubMed cache
python scripts/backfill_pub_dates.py --project-id $PID
```

Re-run steps 4–6 any time you want to re-cluster or re-synthesize.

---

## 5. Run it

Two terminals (backend needs the venv active):

```bash
# Terminal 1 — backend
uvicorn api.main:app --reload --port 8000     # API docs at /docs

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**, select the *Women's Cancer Drug Evidence*
project, and you're on the workbench.

---

## 6. Using the workbench

- **Cluster map** — each bubble is a multi-source claim cluster; size ∝ number of
  claims, color = dominant verdict (supports / contradicts / partial /
  inconclusive). Drag to pan, scroll to zoom. Click a bubble for its synthesized
  answer and per-source verified evidence (exact quotes, statistical significance,
  effect size, and publication date).
- **Drug / disease filters** — highlight related bubbles, grey out the rest; the
  drug picker is searchable.
- **Single-paper claims tab** — search/filter the ~15k individual claims that
  didn't converge into a multi-source cluster.
- **Add a source by DOI** — paste a DOI; a background job resolves it (PubMed →
  Crossref), extracts + embeds claims, and attaches them to the nearest cluster or
  creates a new one — shown as a distinct violet-dashed bubble. If the source is
  already in the corpus, the map pulses and pans to where it lives.

---

## 7. Optional — fine-tuned model comparison

The side-by-side "base vs fine-tuned" answer view needs a self-hosted vLLM serving
the LoRA adapter. See `docs/lora_finetuning_runbook.md` for the full procedure
(train on Token Factory → self-host on a Nebius GPU VM). Once it's reachable via an
SSH tunnel, set `FINETUNED_BASE_URL` + `FINETUNED_MODEL` in `.env`. (This flow is
currently kept in the backend but not wired into the UI.)

---

## Troubleshooting

- **Map empty / "no clusters"** — the selected project hasn't been through the
  pipeline. Use Option A, or run Option B.
- **Slow first load of the map / dropdowns** — the first request warms an
  in-process cache (a few seconds over a large corpus); later loads are instant.
  **Restart the API after any pipeline run** so caches don't serve stale clusters.
- **Add-by-DOI fails to resolve** — needs outbound network to NCBI/Crossref.
  Unknown DOIs, or those without an abstract, fail with a clear message.
- **Similarity/clustering looks wrong** — almost always an embedding-model
  mismatch. Confirm `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B` and `EMBEDDING_DIM=4096`.
- **`no such column` on startup** — restart the backend; migrations run
  automatically in the FastAPI lifespan.

More detail on architecture and design decisions: `docs/SESSION_NOTES.md`,
`docs/workbench_build_log.md`, and `CLAUDE.md`.
