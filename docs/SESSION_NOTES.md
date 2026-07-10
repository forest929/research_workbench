# Session Notes — Research Workbench (resume here)

Last updated: 2026-07-04. Read `docs/workbench_build_log.md` for the full history;
this file is just **what's in-flight and what to do next**.

Project / demo: `100d1b89-e6bd-4628-a1d6-aefe89fcabe1` (Women's Cancer Drug Evidence).
Run: `uvicorn api.main:app --port 8000` + `cd frontend && npm run dev` (http://localhost:5173).
Open: `/projects/100d1b89-e6bd-4628-a1d6-aefe89fcabe1/workbench`.

Current corpus: 10,076 papers, 26,892 claims (21,413 verified), **15,822 clusters**
(444 multi-source + 15,378 singletons). Trials (806) excluded from workbench.

---

## ✅ DONE — "show all verified claims as small bubbles"

Completed 2026-07-04: migration ran, `compute_cluster_coords.py` populated
coord_x/coord_y for all 15,822 clusters, `list_clusters` reads them (all-clusters
payload 5.2 MB, ~1.7s), WorkbenchPage fetches `multi_only=false`, ClusterMap renders
16k nodes (444 big + 15,378 dots) with memoized base layer. Dropdown now derives
from all clusters → 10,220 drugs, so `SearchableSelect` caps rendered rows at 60
("+N more — type to search"). Mastectomy etc. now appear with their singleton dots.
Left as-is: verify browser render smoothness at 16k (engineered for it; user to
eyeball). `_load_cluster_centroids`/`_project_2d` in workbench.py are dead code.

## (prior in-progress notes, now resolved)

Goal: map should show **all** clusters incl. singletons as tiny dots, not just the
444 multi-source ones. Backend can't run PCA over ~16k embeddings per request, so
coordinates are **precomputed and stored**.

**Done:**
- `db/migrations.py` — added `coord_x`, `coord_y` columns to `claim_clusters`.
- `scripts/compute_cluster_coords.py` — new; PCA (covariance/eigh) over one
  representative embedding per cluster → stores coord_x/coord_y. **Not run yet.**
- `api/routers/workbench.py`:
  - `list_clusters` now reads stored `coord_x/coord_y` (no runtime PCA).
  - `workbench_options` now derives drugs from **all** clusters (incl. singletons)
    so mastectomy etc. reappear and highlight their dots.
  - NOTE: `_load_cluster_centroids` / `_project_2d` are now **dead code** (left in).
- `frontend/src/components/ClusterMap.jsx` — rewritten for ~16k nodes: singleton
  radius 2.6, relaxation only on multi-source bubbles, **memoized base layer**
  (no re-render on hover/pan/zoom), `vectorEffect="non-scaling-stroke"`. Also added
  a placeholder for user-added clusters: `origin === 'user'` → violet dashed stroke.

**TODO to finish (in order):**
1. Restart API so the migration adds coord_x/coord_y (backend is running OLD code).
2. `python scripts/compute_cluster_coords.py --project-id 100d1b89-e6bd-4628-a1d6-aefe89fcabe1`
   (~1–2 min, pure compute). Verify all 15,822 clusters get coords.
3. `frontend/src/pages/WorkbenchPage.jsx` — change `fetchClusters(projectId, true)`
   → `fetchClusters(projectId, false)` so singletons load.
4. `npm run build` (catch JSX errors) then verify in browser: map renders ~16k
   bubbles, hover/pan/zoom stay smooth, filters still dim/highlight, cluster detail
   still opens on click. Watch first-paint + filter-change latency (memo should keep
   hover/zoom cheap; filter change re-renders 16k ≈ acceptable).
5. If first `/clusters?multi_only=false` is slow: it's the `_cluster_disease_tags`
   pass over ~16k clusters (cached after first call). Fine, but note it.

---

## ✅ DONE — month/year + singleton redesign (2026-07-04)

- **Month/year**: added `documents.pub_date` (migration) + `scripts/backfill_pub_dates.py`
  (parses PubMed XML cache → "YYYY-MM"/"YYYY"; 10,076/10,076 papers, 85% w/ month).
  Surfaced in `get_cluster_members` → cluster detail → `EvidenceItem` shows a
  calendar chip ("Jul 2026") next to the source link.
- **Singleton redesign**: reverted the map to **multi-source clusters only** (444
  bubbles, clean; dropdown back to 393). Singletons moved to a new
  **"Single-paper claims" tab** — `SinglesList.jsx` + `GET /workbench/single-claims`
  (paginated, filter by search/disease/verdict, ranked by evidence_strength,
  cached `_SINGLETON_CACHE`, 15,378 claims). Mastectomy etc. now live there
  (searchable) instead of cluttering the map. WorkbenchPage has a Map/Singles tab
  bar. `SearchableSelect` still caps rendered rows at 60.
- Note: all-claims map infra (coords for 16k, ClusterMap 16k perf) is retained and
  unused-on-map; coords also speed the multi map. `origin==='user'` bubble style
  hook still present in ClusterMap for the future DOI feature.

## (superseded) earlier notes on the two requests

### A. Show publication month/year next to the source link in each claim card
- **Data gap:** there is **no structured pub-date column**. PubMed dates live only
  inside `documents.raw_content` as a `Year: ...` line (see `record_to_text` /
  `_parse_pubmed_article` in `scripts/ingest_womens_cancer_drugs.py`). Month is
  parsed but not persisted either.
- Options: (a) add `documents.pub_date` (or year/month) columns + backfill from the
  PubMed XML cache in `data/raw_cache/pubmed`, then include it in
  `get_cluster_members` and the cluster-detail payload; or (b) cheap-but-hacky:
  regex the `Year:` line out of `raw_content` at query time.
- Recommend (a): add columns, backfill in a small script, surface `pub_date` in
  `cluster_detail` members, render next to `SourceLink` in `EvidenceItem`
  (`frontend/src/components/ConversationPanel.jsx`).

## ✅ DONE — locate-existing-source on map (2026-07-04)

When a submitted DOI is already in the corpus, `doi_ingest` now returns
status='existing' + the source's `cluster_ids` (instead of failing). Frontend
`AddSourceBar` shows a "Locate on map" button (+ auto-locates on completion);
`ClusterMap` spotlights those clusters with a pulsing amber ring and pans/zooms
to fit (`locatedIds` prop + `useEffect` fit). Also works for 'done' sources.
Verified against real DB state (pmid:35665782 → trastuzumab-deruxtecan cluster,
on map at coord 0.47,-0.31). NOTE: could not run a *live* DOI end-to-end because
the machine lost outbound network mid-session (DNS fails even unsandboxed) — the
resolve step needs it; retry when network is back.

## ✅ DONE — add-by-DOI pipeline (2026-07-04)

Paste a DOI → background pipeline → distinct violet-dashed "user" bubble on the map.
- Schema: `claim_clusters.origin` ('corpus'/'user') + `user_claim_count`; new
  `user_sources` job table (migrations). PCA projection model persisted to
  `data/projection_models/<pid>.npz` (via `compute_cluster_coords.py` +
  `claims/projection.py`) so new clusters land on the same axes.
- `claims/doi_ingest.py::process_source` (FastAPI BackgroundTask): resolve DOI
  (PubMed `[DOI]` → efetch; Crossref fallback) → insert doc + pub_date → extract
  claims (`extraction.run_one`) → `embed_batch` → assign each claim to the nearest
  same-intervention cluster (cosine ≥ 0.82) or create a new `origin='user'`
  cluster (coord via `projection.project_point`). Updates `user_sources.status`
  at each stage; calls `workbench.invalidate_caches` on done.
- API: `POST /workbench/add-source {doi}` (kicks background task) +
  `GET /workbench/user-sources` (poll). `list_clusters` keeps user clusters on the
  multi-only map and marks `origin='user'` when created-by/touched-by user.
- Frontend: `AddSourceBar.jsx` (input + live status polling, refreshes map on
  done) in the map view; ClusterMap styles `origin==='user'` violet-dashed + legend.
- **Verified**: DOI `10.1056/NEJMoa2203690` (DESTINY-Breast04) → 2 claims joined
  the trastuzumab-deruxtecan cluster (now a user bubble); bogus DOI → clean
  "failed" status. New-cluster path coded + `project_point` unit-verified (not yet
  exercised via a real novel-drug DOI — dense corpus makes most oncology DOIs join).

### (original design note) B. Add sources by DOI
User wants: paste a DOI → background (embed → extract claims → assign to closest
existing cluster by cosine, or create a new cluster if none within threshold) →
show that cluster with a **different bubble style** so you can see what the user is
interested in.
- Frontend hook already exists: ClusterMap styles `origin === 'user'` clusters with
  a violet dashed stroke. Need to (1) add an "Add source by DOI" input, (2) POST it,
  (3) poll/refresh, (4) have the clusters payload include `origin` per cluster.
- Backend to build:
  - Resolve DOI → metadata + abstract. Crossref (`api.crossref.org/works/{doi}`) for
    metadata; abstract often needs PubMed (map DOI→PMID via NCBI) since Crossref
    abstracts are spotty. Reuse ingest patterns.
  - Insert document (doc_type 'paper', source_id `doi:...` or `pmid:...`), chunk,
    embed claims: reuse `claims/extraction.run_one` + `embed_text`.
  - Assign to cluster: embed the claim(s), cosine vs existing cluster centroids
    (threshold ~0.82 like clustering); attach to best or create a new 1-member
    cluster. Recompute that cluster's `coord_x/coord_y` (or place near its neighbor).
  - Mark provenance: add `claim_clusters.origin TEXT DEFAULT 'corpus'` (migration);
    set `'user'` for user-added; return it in `list_clusters`.
  - Run in background (FastAPI BackgroundTasks or a simple job row + poll endpoint).
- Scope: this is the biggest remaining item — treat as its own mini-project.

---

## Key facts / gotchas (don't relearn these)
- **SQLite perf:** `claims.claim_embedding` is a 4096-float JSON blob inline on every
  row. NEVER `SELECT *` on claims in hot paths. `idx_claims_cluster` exists; select
  only columns *before* the blob to avoid overflow-page reads. Detail was 114s →
  0.24s after this. `PRAGMA busy_timeout=30000` set in `db/pool.py`.
- **Ranking:** `claims/conversation.py::evidence_strength()` — calibrated score
  (significant p-value +3, verified quote +2, effect size +1.5, CI +1, confidence
  ×0.5). `_select_members`/`rank_members` sort dissent-first then by it. LLM
  `confidence` is nearly useless (91% at 0.8–0.9). All 444 answers re-synthesized
  with it. `?full=true` on cluster detail loads all claims.
- **Clustering:** `NON_INTERVENTION_KEYS = {none,null,unknown,""}` excluded (was
  making giant meaningless "none"/"null" bubbles from observational studies).
  Embedding model MUST be `Qwen/Qwen3-Embedding-8B` dim 4096 (in `.env`).
- **Caches** in `workbench.py` (`_PROJECTION_CACHE` now unused, `_DISEASE_TAG_CACHE`,
  `_VERIFIED_CLAIMS_CACHE`) are per-process — **restart the API after data changes**
  (re-cluster / coord recompute) or the map serves stale cluster ids.
- **Fine-tuned/generate flow is removed from the UI** (dropdowns are map filters
  now). Backend `/workbench/generate` + `ComparisonView.jsx` remain but unused.
- Frontend: lean deps (React, react-router, react-query, tailwind, lucide only).
  No charting/combobox libs — `ClusterMap` and `SearchableSelect` are hand-rolled.
- Nothing is committed to git (all on `master`, working tree dirty). Pipeline
  scripts: ingest → extract_claims → backfill_claim_embeddings → rebuild_clusters →
  compute_cluster_coords → build_conversations.
