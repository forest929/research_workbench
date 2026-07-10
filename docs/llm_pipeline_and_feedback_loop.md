# LLM Pipeline & Human Feedback Loop

## Overview

There are two separate LLM pipelines: **Research Analysis** (triggered once per run) and **Screening** (triggered per document). Human validation feeds back into the second one in real time.

---

## Pipeline 1 — Research Analysis

**Triggered by:** `POST /projects/{id}/run`

```
coordinator.trigger_research_run()
│
├─ runner.run_all()   ← 3 workstreams run in parallel (asyncio.gather)
│   ├─ parameter_extraction.run()
│   │     hybrid_search(scope_statement) → retrieved chunks
│   │     llm.generate(CRITERION_EXTRACTION prompt) → criteria list JSON
│   │
│   ├─ literature_synthesis.run()
│   │     hybrid_search(scope_statement) → retrieved chunks
│   │     llm.generate(SYNTHESIS prompt, temp=0.2) → cited narrative text
│   │
│   └─ cluster_selection.run()
│         hybrid_search → picks 1 representative chunk per cluster
│
├─ structural_check()   ← pure Python, no LLM
│     validates criteria schema, count, required fields
│
└─ logical_check()   ← LLM judge (Nemotron model)
      sees: scope_statement + retrieved chunks + criteria
      returns: JSON with 4 dimension scores (faithfulness, integrity,
               citation accuracy, uncertainty) + overall + verdict
```

**Key design:** generation and judging use *different models* via separate client instances. The judge sees the source chunks it is assessing against — not just the output — so it can genuinely check faithfulness.

**State machine:** `onboarding → analyzing → awaiting_review | death_spiral | failed`

---

## Pipeline 2 — Screening

**Triggered by:** `POST /projects/{id}/screening/{doc_id}/llm-predict`

This is where human feedback actively shapes future LLM behaviour.

```
llm_predict(document_id)
│
├─ get doc_embedding (mean of chunk embeddings, cached on doc)
│
├─ retrieve_similar_examples(doc_embedding, top_k=5)
│     cosine k-NN over all human-validated decisions in `decisions` table
│     returns: the 5 most similar previously-decided papers + their human labels
│
├─ build_guidance_text()
│     reads `preference_observations` table
│     returns e.g. "Reviewers have consistently excluded review articles (4 times)"
│     (only surfaces patterns that have hit threshold = 3)
│
├─ build_messages(abstract, criteria, similar_examples, guidance)
│     assembles one prompt block:
│       [system: screening rules]
│       [inclusion/exclusion criteria]
│       [guidance block ← from preference_learning]
│       [few-shot examples ← from decision_memory, most similar first]
│       [document to screen]
│
└─ llm.generate() → {label, confidence, reasoning, reason_code}
```

---

## How Human Decisions Feed Back

When a human submits a decision (`POST /decide`), three things happen atomically in one API call:

```
record_decision(human_label, reason_code, llm_label, llm_confidence)
│
├─ store_decision()         ← MEMORY BANK
│     stores doc embedding + human label + reason in `decisions` table
│     immediately becomes a candidate few-shot example for future papers
│
├─ record_disagreement()    ← AUDIT TRAIL
│     if llm_label ≠ human_label → inserts into `disagreements` table
│     powers the discrepancy dashboard (agreement rate, which reason codes misfire)
│
└─ update_preferences()     ← PATTERN EXTRACTION
      increments count for (reason_code, label) pair in `preference_observations`
      once count ≥ 3: "reviewers exclude REVIEW_ARTICLE consistently"
      this guidance text gets injected into ALL future screening prompts
```

The loop closes the next time `llm-predict` runs on a new document — it finds the new decision in the memory bank, ranks it by cosine similarity, and potentially includes it as a few-shot example. There is no retraining or fine-tuning: **the accumulated human decisions are the model's "memory", carried entirely through the prompt.**

---

## End-to-End Feedback Diagram

```
HUMAN DECISION
     │
     ▼
┌────────────────────────────────────────────────┐
│  POST /decide                                  │
│  store_decision() → decisions table            │
│  record_disagreement() → disagreements table   │
│  update_preferences() → preference_obs table   │
└────────────────┬───────────────────────────────┘
                 │  (immediate, same request)
                 ▼
         Next paper loads
                 │
                 ▼
┌────────────────────────────────────────────────┐
│  POST /llm-predict                             │
│  cosine k-NN → top-5 similar past decisions    │
│  build_guidance_text() → pattern text          │
│  build_messages() → full prompt                │
│  generate() → {label, confidence, reasoning}  │
└────────────────────────────────────────────────┘
```

---

## Key Files

| File | Role |
|------|------|
| `portfolio_architect/agents/coordinator.py` | Orchestrates the research run state machine |
| `portfolio_architect/agents/runner.py` | Runs the 3 workstreams concurrently |
| `portfolio_architect/agents/workstreams/parameter_extraction.py` | Extracts inclusion/exclusion criteria via LLM |
| `portfolio_architect/agents/workstreams/literature_synthesis.py` | Synthesises a cited narrative via LLM |
| `portfolio_architect/judge/logical_check.py` | LLM-as-judge scoring (4 dimensions) |
| `portfolio_architect/judge/structural_check.py` | Pure-Python schema validation, no LLM |
| `portfolio_architect/llm/prompt_builder.py` | Assembles the dynamic screening prompt |
| `portfolio_architect/feedback/decision_memory.py` | Stores decisions; cosine k-NN retrieval |
| `portfolio_architect/feedback/preference_learning.py` | Detects patterns; injects guidance text |
| `portfolio_architect/feedback/disagreement.py` | Tracks LLM vs human disagreements |
| `portfolio_architect/ranking/active_learning.py` | Ranks pending docs by uncertainty |
| `api/routers/screening.py` | Screening endpoints: predict, decide, stats |

---

## Known Limitations & Improvement Opportunities

- **Cold start:** `retrieve_similar_examples` returns nothing until at least 1 decision is stored. The first paper gets no few-shot examples and relies only on criteria. Queue ordering falls back to FIFO (`uncertainty=0.0` for all).

- **k-NN scales linearly:** similarity search is a pure-Python cosine loop over all stored decisions on every prediction. Fine for dozens of decisions, slow for thousands. Embeddings live as JSON strings in SQLite, not in a vector index.

- **Preference threshold is hardcoded** at `3` in `preference_learning.py:_THRESHOLD`. A pattern must appear 3 times before it injects guidance — the 3rd decision immediately affects all subsequent prompts.

- **Two independent signals, no reconciliation:** the queue returns both `al_label` (k-NN vote from human decisions) and the LLM's prediction. These can disagree; the discrepancy dashboard only tracks LLM vs human, not AL vs LLM.

- **Judge has no feedback loop:** its scores are logged and displayed but never used to automatically trigger re-runs or adjust prompts. The `death_spiral` verdict is the only automated consequence of a bad judge score.
