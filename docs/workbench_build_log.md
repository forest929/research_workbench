# Scientific Research Workbench — Build Log

Running log of the effort to turn the existing claims→clusters→conversations→
fine-tune backend into a usable **scientific research workbench** with four
features:

1. **Conversation metadata generation** (GPU-central) — synthesize, per topic, a
   `CLAIM: … / evidence from source X / evidence from source Y` structure, shown
   in a side panel. Showcase path uses already-ingested publications; live path
   generates on the fly from a user's interest topic.
2. **Fine-tuning** — the generated metadata is the LoRA training data.
3. **Claim clustering visualization** — cluster claims so a researcher can click
   a claim and investigate the supporting evidence in the dataset.
4. **Research workbench** — the umbrella UI tying it together.

---

## 2026-07-04 — Investigation (pre-plan)

### What already exists (backend fully built, data fully materialized)

Reference project `100d1b89-e6bd-4628-a1d6-aefe89fcabe1` — *Women's Cancer Drug
Evidence*:
- 2,857 documents, 6,648 claims, 3,776 clusters, 3,776 synthesized conversations.
- LoRA fine-tune already ran: `ftjob-55db57ee011743cf8d73c6605a2477d5` (v2, 3,776
  examples). Adapter served via self-hosted vLLM (see `lora_finetuning_runbook.md`).

Backend pipeline modules (all present, working):
- `portfolio_architect/claims/extraction.py` — 1 LLM call/doc → structured claims
  + deterministic `quote_verified` substring check.
- `portfolio_architect/claims/clustering.py` — intervention blocking + numpy
  cosine union-find, threshold 0.82, singleton fallback.
- `portfolio_architect/claims/conversation.py` — 1 LLM call/cluster → (question,
  cited answer).
- `portfolio_architect/finetuning/nebius_ft.py` — Token Factory FT client.
- `db/claims.py`, `db/claim_clusters.py` — CRUD (get clusters, members with
  `source_id`/`doc_type` join).
- Scripts: `extract_claims.py`, `backfill_claim_embeddings.py`,
  `build_conversations.py`, `export_lora_dataset.py`, `finetune_lora.py`.

Embedding: `Qwen/Qwen3-Embedding-8B`, dim 4096 (per runbook). Generation +
judge via Token Factory. `llm.generate(messages, temperature, call_type, conn,
project_id)`.

### The gap (what this effort builds)

- **No API router** exposes claims / clusters / conversations. `api/main.py`
  wires: projects, documents, research, criteria, artifacts, discrepancy,
  screening, ingest, export — nothing for claims.
- **No frontend page** renders the workbench. `App.jsx` routes: Research,
  Documents, Screening, Steering, Discrepancy, Report. Sidebar `NAV` lists the
  same six.
- **No on-the-fly path**: a user cannot enter an interest topic and get a fresh
  claim/evidence conversation generated live.

### Frontend conventions observed
- React + Vite + react-router + @tanstack/react-query, Tailwind (navy/blue).
- `frontend/src/api/index.js` — thin `api.get/post` wrappers per endpoint.
- Pages under `frontend/src/pages/`, project-scoped routes `/projects/:id/...`.
- Sidebar `NAV` array drives navigation; add an entry to surface a new page.

### Plan status
Plan approved. Decisions: live depth = *retrieve from existing corpus*; synth
engine = *side-by-side base vs fine-tuned*; viz = *interactive graph/map*.

---

## 2026-07-04 — Backend built + verified

New/changed:
- `config.py` — added `finetuned_base_url`/`finetuned_model`/`finetuned_api_key`/
  `finetuned_timeout_s` + `finetuned_enabled` property. `.env` already had the
  correct `Qwen/Qwen3-Embedding-8B` / dim 4096, so live retrieval is in-space.
- `llm/client.py` — `_get_finetuned_client()` + `generate_finetuned()` (separate
  AsyncOpenAI at the self-hosted vLLM base_url; raises when unconfigured so
  callers fall back).
- `claims/retrieval.py` (new) — `retrieve_claims_for_topic()`: embed topic →
  numpy cosine over embedded claims (joined to documents for `source_id`) →
  top-k. Hard dimension check guards against a wrong embedding model.
- `claims/conversation.py` — `build_conversation_compare()`: synthesizes with
  base + fine-tuned; fine-tuned is best-effort (`finetuned_error` on failure).
- `api/routers/workbench.py` (new, registered in `main.py`):
  `GET /clusters` (+2D PCA coords, cached), `GET /clusters/stats`,
  `GET /clusters/{id}` (conversation + per-source evidence),
  `POST /workbench/generate` (live). `/clusters/stats` declared before the
  `/{cluster_id}` param route so the static path wins.

Verification (project `100d1b89`, curl):
- `stats` → 152 multi-member clusters, 3776 conversations, verdict totals
  (supports 4470 / inconclusive 1816 / partially 189 / contradicts 173).
- `clusters?multi_only=true` → 152 items, each with spread x/y PCA coords.
- `clusters/{id}` → question + synthesized answer + 11 members with
  source_id/verdict/evidence_quote.
- `POST generate {"topic":"trastuzumab deruxtecan in HER2-low breast cancer"}` →
  intervention block "trastuzumab deruxtecan", 12 members, real base answer;
  fine-tuned degrades cleanly to `finetuned_error` (endpoint not configured).
- **Grounding spot-check (runbook §5):** all 11 citations in the generated base
  answer are real corpus records **and** all appear in the retrieved members —
  i.e. grounded synthesis, no fabrication (as expected when generating *with*
  retrieved context).

## 2026-07-04 — Frontend built + verified

New/changed:
- `api/index.js` — `fetchClusters`, `fetchClusterStats`, `fetchClusterDetail`,
  `generateConversation`.
- `components/ClusterMap.jsx` — SVG scatter, viewBox pan/zoom, nodes sized by
  member_count, colored by dominant verdict, hover label, click → select. No new
  charting dependency.
- `components/ConversationPanel.jsx` — feature-1 layout: research question +
  synthesized answer + Evidence list (`CLAIM:` / verdict badge / quote /
  `SourceLink` / quote-verified flag). Exports `EvidenceItem` for reuse.
- `components/ComparisonView.jsx` — base vs fine-tuned answer cards +
  retrieved evidence; fine-tuned card shows an "offline" note when disabled.
- `pages/WorkbenchPage.jsx` — header stats + topic-generate bar; map (left) +
  tabbed right panel (Cluster detail / Generated).
- Wired `App.jsx` route `/projects/:id/workbench` + Sidebar NAV "Workbench".

Verification:
- `npm run build` → clean (1646 modules).
- Dev server serves the SPA (`<title>AI Portfolio Architect</title>`) and proxies
  `/api` → backend (stats returns 152 clusters through the proxy).

### How to run the demo
```
uvicorn api.main:app --reload --port 8000      # backend
cd frontend && npm run dev                     # http://localhost:5173
```
Open the *Women's Cancer Drug Evidence* project → **Workbench**. To enable the
fine-tuned column, bring up the self-hosted vLLM adapter (runbook §4), open an
SSH tunnel, and set `FINETUNED_BASE_URL` / `FINETUNED_MODEL` in `.env`.

---

## 2026-07-04 — Phase 2: workbench-only refocus + stronger dataset

New user direction: (1) keep **only** the workbench in the frontend; (2) exclude
NCT trials from the workbench (keep rows in DB — non-destructive); (3) strengthen
the corpus from PubMed; (4) replace free-text generate with **drug × disease
dropdowns**; (5) cluster details must be concise — verdict, **source URL**, and
the **exact verified quote**, all verified. Decisions: exclude trials (not
delete), stay in women's-cancer-drugs domain, PubMed window = **past 3 years**.

Code changes:
- `db/claim_clusters.get_claims_with_embeddings` + `claims/clustering.py`
  (`cluster_project_claims`, `add_singleton_clusters`) — new `verified_only` /
  `exclude_trials` flags (join documents on doc_type). New
  `scripts/rebuild_clusters.py` makes clustering reproducible (verified,
  PubMed-only by default).
- `api/routers/workbench.py` — `GET /workbench/options` (drugs + curated disease
  list with live counts, from verified paper claims); `POST /workbench/generate`
  now takes `{drug, disease}` and synthesizes from verified, non-trial claims
  only; cluster detail filters members to `quote_verified=1` & non-trial.
- Frontend: `App.jsx`/`Sidebar` reduced to workbench only (bundle 315→250 kB);
  WorkbenchPage free-text → two dropdowns (`fetchWorkbenchOptions`);
  ComparisonView header shows drug/disease.
- `scripts/ingest_womens_cancer_drugs.py` — 3-year recency window
  (`PUBMED_START`, dynamic); `--append` to add NEW records to the existing
  project; `pubmed_search` paginates + `sort=pub_date`; **fixes**: (a) append
  loop no longer re-inserts chunks for existing docs (was duplicating chunks —
  cleaned 439 dupes), (b) esearch fetched fresh + resilient (NCBI `retstart`
  caps at 9,999 — pagination past 10k needs WebEnv; graceful stop).
  `build_conversations.py` — `--min-members` to bound synthesis cost.

Key insight: the workbench claims pipeline does **not** use chunk embeddings
(extraction reads raw_content; clustering uses per-claim embeddings). So ingest
runs with `--no-embed` — big cost/time saving.

Data build (in progress): ingest ~9,999 most-recent (3-yr) PubMed papers
(`--append --pubmed-only --no-embed`) → extract_claims → backfill_claim_embeddings
→ rebuild_clusters (verified, PubMed-only) → build_conversations `--min-members 2`.
Est. cost ~$8–12 (mostly ~10k extraction calls). NCT trials remain in DB but are
excluded everywhere in the workbench.

### Data build — COMPLETE (2026-07-04)

Ran the full pipeline against the enlarged corpus. Results:

| Metric | Before | After |
|---|---|---|
| Papers | 2,051 | **10,076** |
| Trials (in DB, excluded from workbench) | 806 | 806 |
| Claims | 6,648 | **26,892** |
| Verified claims | 4,475 | **21,413** |
| Multi-source clusters | 152 | **484** |
| Cluster conversations | 152 | **484** (0 failed, 0 bad citations) |

Build cost (this session's delta): **8,509 LLM calls, ~12.8M tokens** (~$8–12).
Steps: append-ingest 7,966 new papers (`--append --pubmed-only --no-embed`,
~9,999 most-recent 3-yr) → extract_claims (20,244 new claims, 18 transient
timeouts) → backfill_claim_embeddings (all 26,892 embedded) → rebuild_clusters
(verified, PubMed-only → 484 multi + 16,278 singletons) → build_conversations
`--min-members 2`.

Gotchas hit + fixed this run:
- **esearch `retstart` caps at ~9,999** — pagination past 10k needs the WebEnv/
  history API; page 2 returns a malformed body. `pubmed_search` now fetches
  fresh (not cached — a corrupt cached page had crashed the whole search) and
  stops gracefully. Practical ceiling: 9,999 most-recent papers/query.
- **`--append` was re-inserting chunks** for existing docs (ON CONFLICT keeps the
  doc but the loop still re-chunked) → duplicate chunks. Fixed: skip chunk insert
  when the doc already has chunks. Cleaned 439 pre-existing dupes.
- **SQLite `busy_timeout=0`** → added `PRAGMA busy_timeout=30000` in `db/pool.py`
  so concurrent pipeline scripts + API serialize instead of "database is locked".
  Let embedding backfill run alongside the extraction tail with zero lock errors.
- **Token Factory throttling on synthesis**: huge generic clusters
  ("chemotherapy" 174 members) made enormous prompts → ~6 calls/min. Added
  `MAX_SYNTH_MEMBERS=12` (`_select_members`, dissent-first then confidence) in
  `claims/conversation.py` for the batch path (live path already capped). Rate
  jumped to **45 calls/min**; also applied to the cluster-detail panel
  (`shown_count` vs true `member_count`) so the UI stays concise.

Final verification (all pass):
- `/workbench/options` → 80 drugs (data-derived, e.g. neoadjuvant chemo 585,
  trastuzumab deruxtecan 291) + 4 diseases with live counts.
- `/clusters?multi_only=true` → 484 nodes with PCA coords.
- Cluster detail → capped, every shown member `quote_verified=1`, non-trial,
  with source_id + verbatim quote.
- `POST /workbench/generate {"drug":"olaparib","disease":"ovarian"}` → 12 matches;
  **7/7 citations are real corpus records, 12/12 quotes verbatim in source**.
- Frontend builds clean (250 kB, workbench-only); vite proxy serves new data.

---

## 2026-07-04 — Phase 3: map UX + performance

User asks: (1) map bubbles overlap/hide each other, hard to hover; (2) selecting
a drug/disease should highlight relevant bubbles + grey the rest, with drug ×
disease working simultaneously; (3) speed up cluster detail.

Performance (the big one):
- **Root cause**: no index on `claims(cluster_id)`, and `claim_embedding` (a
  4096-float JSON blob) is stored inline on every row — so any query
  filtering/grouping by cluster_id full-scanned ~1 GB of pages. Cluster detail
  for a 527-member cluster took **1 min 54 s**; the map's cold PCA load >100 s.
- **Fixes**: added `idx_claims_cluster` (migrations); `get_cluster_members`
  selects only columns stored *before* the blob (drops created_at/cluster_id,
  orders by id) so SQLite never chases overflow pages; the map projection now
  loads **one representative embedding per cluster** via an indexed, chunked
  `IN … GROUP BY` (not every member, not one-per-singleton).
- **Result**: cluster detail **0.24 s** (~470× faster); map cold load **~4 s**,
  cached after. Also added `PRAGMA busy_timeout` earlier this session.

Map interactivity (`components/ClusterMap.jsx` rewrite):
- Radius capped (compressed sqrt) — a 527-member bubble was ~80px and smothered
  neighbours; now max 32px.
- **Collision relaxation** pass nudges overlapping bubbles apart while keeping
  the PCA structure, so none are fully hidden.
- Draw order large→small (small on top, stays clickable); the hovered node is
  re-drawn on top with a `intervention · count` label so hover is never occluded.

Drug × disease highlighting:
- Backend tags each cluster with `diseases` computed from **all its members'**
  population/claim_text/outcome (not just the templated question) — so a drug
  cluster spanning several cancers is highlightable under each, matching what the
  live generate path returns. Cached (`_DISEASE_TAG_CACHE`).
- `ClusterMap` greys non-matching clusters (opacity 0.14, slate) and emphasises
  matches (blue ring) via a `matches(n)` predicate that ANDs drug + disease, so
  the two filters work **simultaneously**. Verified: drug-only, disease-only, and
  combined all light up sensible bubble sets (e.g. pembrolizumab × cervical → 1,
  cervical → 48).

Also fixed a separate perf bug in `/workbench/options` + `/generate`: they did
`SELECT c.*` (pulling every claim's embedding); trimmed to needed columns +
added `_VERIFIED_CLAIMS_CACHE`. Options warm load 0.44 s.

---

## 2026-07-04 — Phase 4: bubble polish, load-all, remove live generate

User asks: (1) nicer bubble UI; (2) an option to load *all* claims in the cluster
detail; (3) remove the "generate evidence" flow — it's all already in the DB.

- **Removed live generate**: WorkbenchPage no longer imports/uses
  `ComparisonView` or `generateConversation`. The mode tabs and "Generate
  evidence" button are gone. The drug × disease dropdowns are now **map filters**
  (highlight matching clusters, "N clusters highlighted" + Clear) rather than a
  generation trigger. The right panel is always the (precomputed) cluster detail.
  Backend `/workbench/generate` + `ComparisonView.jsx` remain but are unused —
  kept in case the fine-tuned side-by-side demo is wanted later.
- **Load all claims**: `/clusters/{id}` takes `?full=true` → returns every
  verified member instead of the concise dissent-first set. `fetchClusterDetail`
  gained a `full` arg; `ConversationPanel` shows "Load all N claims" / "Show top
  claims only" with a spinner, and the header reads "showing X of N verified
  claims". Fast (0.025s for 97 members) thanks to idx_claims_cluster.
- **Bubble UI** (`ClusterMap.jsx`): glossy radial-gradient spheres per verdict
  (light focal highlight → saturated edge), a soft `feGaussianBlur` glow on the
  hovered/selected node only (keeps pan/zoom smooth), fill-opacity transition,
  and **persistent labels** for the 8 biggest clusters plus the filtered matches
  (when ≤14) so the map is readable without hovering.

---

## 2026-07-04 — Phase 5: calibrated ranking, none/null fix, re-synthesis

- **Calibrated evidence ranking** (`claims/conversation.py`): the LLM's
  self-reported `confidence` is nearly useless (91% of claims at 0.8–0.9), so
  `_select_members`/`rank_members` now sort by `evidence_strength()` — a score
  from *checkable* attributes: reported significant p-value (+3), verified quote
  (+2), quantified effect size (+1.5, +1 for a CI), confidence only ×0.5 as a
  tiebreaker. Dissent-first preserved. Score exposed per claim; the detail cards
  show significance/effect-size chips (green when p<0.05). `?full=true` also
  ranked. Verified on the 527-member cluster: top claims are P=0.0004, p=0.042,
  p=0.024 … → "Not reported" last.
- **"none"/"null" bubbles explained + fixed**: not a code bug — observational /
  biomarker papers with no drug got `intervention="None (…)" / "Null (…)"`, which
  `normalize_intervention` collapsed to "none"/"null", merging hundreds of
  unrelated claims into two mega-bubbles (one had 397 members). Added
  `NON_INTERVENTION_KEYS = {none, null, unknown, ""}` to clustering; those blocks
  and singletons are now skipped (drug→evidence map only). Re-clustered → 444
  clean multi-source clusters (was 484), 0 none/null.
- **Re-synthesized all 444** cluster answers with the new ranking
  (`build_conversations --min-members 2`): 0 failed, 0 invalid citations. Answers
  and the displayed top-evidence are now drawn from the same calibrated set.
- **Bubble style reverted** to flat semi-transparent (per preference): radius
  reflects claim count (generous sqrt scale), overlaps allowed, light relaxation
  (`minDist=|rA−rB|+9`) mathematically prevents full occlusion so every bubble
  stays hoverable; small-on-top draw order + hovered-on-top re-render.

### Status (phase 1): all four features live
1. Conversation metadata (CLAIM/evidence side panel) — showcase + live topic path. ✅
2. Fine-tuning — surfaced via side-by-side base-vs-fine-tuned comparison. ✅
3. Claim clustering visualization — interactive map, click node → evidence. ✅
4. Research workbench — umbrella page tying it together. ✅
