# AI Research Workbench

A scientific research workbench for drug-therapy evidence, built on **Nebius AI
Cloud**. You ask a research question, and it searches the literature, extracts
structured claims, clusters them across papers, synthesizes **cited answers**,
grades each answer with an **LLM judge**, and lays the whole evidence landscape
out as an interactive map. A built-in **research assistant** answers follow-up
questions ("compare A vs B", "what contradicts the majority view", "where are the
gaps?") over your corpus — each reply retrieved, cited, and self-checked by the
judge.

The bundled demo corpus is **women's cancer drug evidence** (breast, ovarian,
cervical, endometrial): ~10k PubMed papers → ~27k claims → ~440 multi-source
clusters, each carrying a cited, synthesized answer.

> This repo grew out of an earlier "portfolio architect" screening tool; the
> **workbench is the current product** and the only UI. The legacy screening
> pipeline (`agents/`, `feedback/`, `ranking/`) is dormant — still in the tree,
> but no longer wired to a route or the UI.

## What it does

- **Search-first start.** Type a question on the landing page → it creates a
  review, searches **PubMed** (last 5 years, ~30 most-relevant papers by default),
  and builds the evidence base. The pipeline (extract → embed → cluster → lay out
  the map) runs hidden behind a single "Building…" state; you can cancel it.
  Answers are synthesized **lazily** — when you open a cluster — so the map
  appears fast. (Files / Excel / PDFs / DOI lists have their own import page.)
- **3-pane console.** Papers (left) · evidence map + answer (center) · reading
  list (right). Panes resize and toggle.
  - **Papers** — every paper with full citation (journal · year · title ·
    authors · PMID · DOI), searchable, infinite-scroll; click a title to
    spotlight it on the map.
  - **Map** — each bubble is a multi-source claim cluster; size ∝ claims,
    color = dominant verdict. Drug × disease filters (cross-filtered — pick a
    disease and the drug list narrows to that disease). Click a bubble for its
    synthesized answer + per-source verified evidence.
  - **Reading list** — bookmarks with notes, add-by-DOI, "save all" for a
    filter, and **"New review from these"** to spin your curated selection into
    the next round of research.
- **Cited answers** — synthesized per cluster with deterministic numbered
  citations `[1] [2]` and a linked evidence list. Clicking a citation jumps to
  that source's evidence card **and** reveals the paper in the Papers / Reading
  panels.
- **Research assistant** ("Ask the evidence") — free-form questions answered by
  retrieve → synthesize a cited answer → self-check with the judge. Every Q&A is
  saved to history for later review.
- **LLM-as-judge** — scores each answer (faithfulness / citation accuracy /
  relevance / completeness, 1–5) with a separate judge model; cached per answer.
- **Per-project disease vocabulary** — seeded from your question on creation,
  editable — so any topic works, not just the women's-cancer demo.

---

## Architecture

```
Browser ─▶ React + Vite SPA (frontend/)          search-first landing + 3-pane console
                │  calls the backend (VITE_API_URL, or the dev proxy /api → :8000)
                ▼
        FastAPI backend (api/)  ─▶ Nebius Token Factory  (generation + judge LLM)
                │               ─▶ Nebius AI Endpoint     (Qwen3-Embedding-8B)
                ▼
        SQLite via aiosqlite  — embeddings packed as float32 blobs
```

- **Backend** — 4 routers: `projects` (lifecycle, delete), `ingest` (search /
  files / DOI + progress + **cancel**), `workbench` (clusters, cluster detail
  with lazy synthesis, options, add-by-DOI, disease vocab, **judge**,
  **assistant** + history, save-filtered, papers), `reading_list` (bookmarks +
  **spin-off**). The DB layer (`db/pool.py`) is `aiosqlite` behind an
  asyncpg-shaped proxy; the same call sites also run on Postgres + pgvector by
  setting `DATABASE_URL` (see `is_postgres()` branches), but **SQLite is the
  shipping default**.
- **Embeddings** are packed `float32` bytes (`embedding/codec.py`); the decoder
  also reads legacy JSON. Run `scripts/migrate_embeddings_to_blob.py --vacuum` to
  convert + shrink an old database (a legacy JSON DB is ~4× larger and slow).
- **LLMs** on Nebius Token Factory. Generation and the judge use distinct
  models/prompts and separate clients (`llm/client.py`), keeping the judge
  independent of the thing it grades.

```
api/routers/            projects · ingest · workbench · reading_list
portfolio_architect/
  db/                   pool (asyncpg-shim, SQLite + optional Postgres), migrations, per-table CRUD
  embedding/            Nebius embed client + float32 storage codec
  claims/               extraction, clustering, conversation synthesis, retrieval, add-by-DOI
  judge/                conversation_judge (LLM-as-judge over answers)
  assistant.py          research-assistant agent (retrieve → synthesize → judge)
  ingestion/            fetchers (PubMed / Scholar / arXiv), chunker
  llm/                  Token Factory client + prompts
  secrets.py            optional config loading from Nebius MysteryBox
  vocab.py              per-project disease vocabulary (+ starter-vocab inference)
frontend/src/pages/     Landing · NewProject · Workbench (3-pane console) · Ingest
frontend/src/components/ PapersPanel · ReadingListPanel · ClusterMap · ConversationPanel · CitedAnswer · …
scripts/                corpus build + maintenance utilities
```

### Nebius service mapping

| Stage                              | Nebius service                              |
|------------------------------------|---------------------------------------------|
| Claim / text embedding             | AI Endpoints (GPU, `Qwen3-Embedding-8B`)    |
| Answer generation + LLM judge      | Token Factory (serverless LLM)              |
| Corpus store                       | SQLite (kept in Object Storage)             |
| Backend + frontend hosting         | AI Endpoints (serverless containers)        |
| Config / secrets                   | MysteryBox                                  |
| Image registry                     | Container Registry                          |

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
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env
```

Edit `.env` — the values that matter:

```bash
NEBIUS_KEY=sk-...                                   # your Nebius API key
GENERATION_MODEL=meta-llama/Llama-3.3-70B-Instruct  # Token Factory model
JUDGE_MODEL=nvidia/Llama-3_1-Nemotron-Ultra-253B-v1
MAX_TOKENS_JUDGE=6144                               # judge is a reasoning model; needs room for <think> + JSON

NEBIUS_EMBEDDING_URL=https://<your-endpoint>.api.nebius.ai/v1/
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=4096

DATABASE_PATH=portfolio_architect.db
NCBI_API_KEY=                                       # optional — raises the PubMed rate limit
```

> ⚠️ The embedding model/dimension **must** match what the corpus was built with
> (`Qwen/Qwen3-Embedding-8B`, 4096). A mismatch makes clustering meaningless.
> Never commit `.env`.

---

## 3. Frontend setup

```bash
cd frontend && npm install && cd ..
```

The dev server proxies `/api` → `http://localhost:8000` (see
`frontend/vite.config.js`), so the backend must be running for the UI to work.
When the frontend is hosted separately from the backend, build it with
`VITE_API_URL=<backend-url>` and it calls that URL directly (no proxy).

---

## 4. Get data into the database

The schema is created automatically on first backend start (migrations run in
the FastAPI lifespan). Two options:

### Option A — Use the corpus DB (fastest)

`portfolio_architect.db` is the fully processed women's-cancer corpus. It's kept
in Nebius Object Storage (too large to commit); pull it to the repo root:

```bash
aws s3 cp s3://research-workbench-bucket/updated_15July/portfolio_architect.db \
  ./portfolio_architect.db --endpoint-url https://storage.eu-north1.nebius.cloud
```

You still need a valid `NEBIUS_KEY` + embedding endpoint for live features
(search, add-by-DOI, the assistant). Then **skip to step 5**.

### Option B — Just search from the app

Start the app (step 5), type a question on the landing page, and it searches
PubMed and builds the evidence base for you. For a large CLI rebuild, the
`scripts/` pipeline does the same steps in bulk.

---

## 5. Run it

```bash
# Terminal 1 — backend (venv active)
uvicorn api.main:app --reload --port 8000     # API docs at /docs

# Terminal 2 — frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**. Type a question to start a new review, or pick
the *Women's Cancer Drug Evidence* project to open the workbench.

---

## 6. Using the workbench

- **Landing** — a search box (start a new review) and your existing reviews
  (open, delete; created / last-edited shown).
- **Building** — after a search, the map shows "Building your evidence base…"
  while the pipeline runs. Cancel any time.
- **Map** — drag to pan, scroll to zoom. Filter by drug / disease (cross-filtered
  so the two agree). Click a bubble → its cited answer, verdict mix, and verified
  per-source evidence. **Run LLM judge** scores the answer (out of 20).
- **Ask the evidence** — the bar above the map asks the research assistant a
  free-form question; the cited, judged answer opens in the answer panel, and
  **History** revisits past questions.
- **Papers / Reading list** — the side panels; toggle or drag to resize. Save
  papers, add by DOI, and **New review from these** to start the next round from
  your selection.

---

## 7. Deploying on Nebius

The app ships as two container images — **backend** (FastAPI) and **frontend**
(nginx-served SPA) — in the Nebius **Container Registry**, and runs as two
**AI Endpoints** (serverless containers, each with a public URL). The corpus DB
is **not** baked into the image: the backend downloads it from **Object Storage**
on startup. Runtime config lives in a **MysteryBox** secret and is injected as
environment variables.

Build artifacts in the repo: `Dockerfile`, `docker-entrypoint.sh` (S3 download →
uvicorn), `.dockerignore`, `frontend/Dockerfile`, `frontend/nginx.conf`,
`docker-compose.yml` (single-VM alternative).

### Build + push the images

```bash
nebius iam get-access-token | docker login --username iam --password-stdin cr.eu-north1.nebius.cloud
REG=cr.eu-north1.nebius.cloud/<registry-path>          # registry ID with the "registry-" prefix stripped

# Backend (build for amd64 — Nebius nodes are x86; --network=host avoids build DNS flakiness)
docker build --network=host --platform linux/amd64 -t $REG/amr-backend:latest .
docker push $REG/amr-backend:latest

# Frontend — bake the backend URL into the SPA at build time
docker build --network=host --platform linux/amd64 \
  --build-arg VITE_API_URL=<backend-endpoint-url> -t $REG/amr-frontend:latest ./frontend
docker push $REG/amr-frontend:latest
```

### Config + secrets

- Store runtime config in a **MysteryBox** secret (`NEBIUS_KEY`, embedding +
  model settings, the S3 credentials, and `DB_S3_URI` / `DATABASE_PATH`). The
  backend also reads a secret directly when `NEBIUS_SECRET_ID` is set
  (`portfolio_architect/secrets.py`) — otherwise it uses `.env` / env vars.
- The backend needs an **S3 access key** (service account with bucket read) to
  download the DB. Provide `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION=eu-north1`, `S3_ENDPOINT_URL=https://storage.eu-north1.nebius.cloud`,
  and `DB_S3_URI=s3://research-workbench-bucket/.../portfolio_architect.db`.

### Create the endpoints

The backend is **CPU-only** (it just calls out to Token Factory + the embedding
endpoint) — use a `cpu-e2` platform, not a GPU, to avoid burning budget.

```bash
# Backend — inject each config key with a --env KEY=VALUE (repeat per key)
nebius ai endpoint create \
  --name amr-backend --parent-id <project-id> \
  --image $REG/amr-backend:latest \
  --platform cpu-e2 --preset 4vcpu-16gb --disk-size 64Gi \
  --subnet-id <subnet-id> --container-port 8000/http --public --auth none \
  --registry-username iam --registry-password "$(nebius iam get-access-token)" \
  --env NEBIUS_KEY=... --env DB_S3_URI=... --env AWS_ACCESS_KEY_ID=...   # …all keys

# Frontend — no env needed (backend URL is baked in at build)
nebius ai endpoint create \
  --name amr-frontend --parent-id <project-id> \
  --image $REG/amr-frontend:latest \
  --platform cpu-e2 --preset 2vcpu-8gb --disk-size 64Gi \
  --subnet-id <subnet-id> --container-port 80/http --public --auth none \
  --registry-username iam --registry-password "$(nebius iam get-access-token)"
```

Each endpoint returns a public tunnel URL. Open the frontend URL — it calls the
backend directly (CORS is open on the backend). The backend takes ~1–3 min on
first start to download the ~930 MB DB, so keep **≥ 1 instance warm** (avoid
scale-to-zero) and allow a generous startup grace on the `/health` check.

> **Cost:** endpoints bill while running. Stop them when idle:
> `nebius ai endpoint stop <endpoint-id>` (and `... delete <id>` to tear down).

### Single-VM alternative

`docker-compose.yml` runs backend + frontend on one host (nginx proxies
`/api` → `backend:8000`, one origin, no CORS). `docker compose pull && up -d`
after populating `.env`.

---

## Troubleshooting

- **Map empty / "no clusters"** — the project hasn't been analyzed. Use Option A,
  or start a search. Restart the API after a bulk pipeline run so caches don't
  serve stale clusters.
- **Assistant / retrieval feels slow on the demo corpus** — brute-force cosine
  over ~27k claims takes ~25s; it's sub-second on a normal-sized project.
- **Judge returns "not valid JSON"** — the judge is a reasoning model; ensure
  `MAX_TOKENS_JUDGE=6144` so its `<think>` trace + JSON fit.
- **Similarity / clustering looks wrong** — almost always an embedding-model
  mismatch. Confirm `EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B`, `EMBEDDING_DIM=4096`.
- **Add-by-DOI / search fails** — needs outbound network to NCBI / Crossref.
- **Container can't find the DB** — the entrypoint needs the S3 credentials +
  `DB_S3_URI` in its env (from the MysteryBox secret) to download it on startup.
- **Shrink a legacy database** — `python scripts/migrate_embeddings_to_blob.py --vacuum`.
