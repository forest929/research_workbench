# Deploying to Nebius (backend) + a hosted frontend

Splits the app into a **Nebius-hosted backend container** and a **separately
hosted frontend**. The build artifacts referenced below already live in the repo.

## Files this uses

| File | Purpose |
|------|---------|
| `Dockerfile` | Backend image (FastAPI + uvicorn). No DB inside — `DATABASE_PATH=/data/...` points at a mounted volume. |
| `.dockerignore` | Keeps the SQLite DB, `.env`, and `*.pem` **out** of the backend image. |
| `frontend/Dockerfile` | Multi-stage: build the SPA → serve with nginx. |
| `frontend/nginx.conf` | Serves the SPA and reverse-proxies `/api` → backend (stripping the `/api` prefix, mirroring the Vite dev proxy). |
| `frontend/.dockerignore` | Excludes `node_modules` / `dist`. |

## The one real decision: the database

The DB (`portfolio_architect.db`) is **~930 MB SQLite** (after the embedding
migration + VACUUM). SQLite is single-writer and file-based, which fights
Kubernetes. Two paths:

- **Demo (fast):** keep SQLite. Run **one** backend replica, put the DB file on a
  **persistent volume (PVC)** mounted at `/data`, and copy the file onto it once.
  Simple; no horizontal scaling. **Never bake the DB into the image.**
- **Real / scalable:** move to **Managed PostgreSQL + pgvector**. The DB layer
  (`portfolio_architect/db/pool.py`) is already an asyncpg-shim with
  Postgres-shaped SQL, so the port is: swap `aiosqlite` → `asyncpg`, store
  embeddings as `vector`/`bytea`, migrate the data.

Start with the PVC path for a hackathon demo.

## Two gotchas

1. **The `/api` prefix.** The frontend calls `/api/...`; the Vite dev proxy
   **strips `/api`** (the backend serves routes at root). Production must do the
   same — `frontend/nginx.conf` does it with `proxy_pass http://backend:8000/;`
   (trailing slash strips the prefix), so the SPA needs no code change. If you
   host the frontend as static files instead, build with `VITE_API_URL=<backend
   URL>` (the client already reads it) and fix the one hardcoded `/api` upload
   fetch in `frontend/src/api/index.js`.
2. **CORS** is already `allow_origins=["*"]` (`api/main.py`) — tighten to your
   frontend's domain for production.

The backend needs **no GPU** — it only calls out to the Nebius embedding Endpoint
and Token Factory, which stay as separate managed services.

## Steps

### 1–2. Build + push the images to Nebius Container Registry

```bash
# Backend (context = repo root)
docker build -t cr.eu-north1.nebius.cloud/<registry>/amr-backend:latest .
docker push  cr.eu-north1.nebius.cloud/<registry>/amr-backend:latest

# Frontend (context = frontend/)
docker build -t cr.eu-north1.nebius.cloud/<registry>/amr-frontend:latest ./frontend
docker push  cr.eu-north1.nebius.cloud/<registry>/amr-frontend:latest
```

### 3. Run on Nebius Managed Kubernetes

You need: a `Secret` (env below), a `PVC` for the DB (demo path), a backend
`Deployment` (**replicas: 1** for SQLite) + `Service`, a frontend `Deployment` +
`Service`, and an `Ingress`/LoadBalancer for the public URL. Point the frontend
container's `nginx.conf` `backend` host at the backend `Service` name. Use
`/health` for liveness/readiness probes.

> Simpler alternative for a demo: one Nebius VM running `docker compose` (backend
> + frontend + a mounted DB volume) is far less overhead than k8s if you don't
> need scaling.

Getting the DB onto the PVC (demo path): `kubectl cp portfolio_architect.db
<backend-pod>:/data/portfolio_architect.db` (or an init job).

### 4. Host the frontend

Two options:
1. **nginx container in the same cluster** (what `frontend/Dockerfile` does) —
   same origin, no CORS, recommended.
2. **Static files on Nebius Object Storage** (S3-compatible static hosting) —
   cheapest; build with `VITE_API_URL=<backend public URL>` and fix the one
   hardcoded `/api` upload fetch.

## Environment variables (backend Secret/ConfigMap)

```
NEBIUS_KEY=sk-...
GENERATION_MODEL=meta-llama/Llama-3.3-70B-Instruct
JUDGE_MODEL=nvidia/Llama-3_1-Nemotron-Ultra-253B-v1
NEBIUS_EMBEDDING_URL=https://<endpoint>.api.nebius.ai/v1/
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=4096
MAX_TOKENS_JUDGE=3072
DATABASE_PATH=/data/portfolio_architect.db     # the mounted PVC path
NCBI_API_KEY=...                               # optional; raises PubMed rate limit
```

## Still to do when you pick the DB path

Generate the full `k8s/` manifest set (Secret, PVC-or-Postgres wiring, both
Deployments, Services, Ingress) matched to the SQLite-PVC vs Postgres choice.
