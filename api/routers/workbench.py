"""Scientific research workbench API.

Surfaces the already-materialized claim clusters + synthesized conversations
(the CLAIM / evidence-from-source-X metadata) and the live "generate from a
topic" path that retrieves over the existing corpus and synthesizes a fresh
answer with the base and fine-tuned models side by side.

No new tables — reads claims/claim_clusters. 2D coordinates for the cluster map
are computed here via numpy PCA over cluster centroids and cached in-process.
"""

import json
from uuid import UUID, uuid4

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from api.deps import get_conn, get_db_pool
from portfolio_architect.config import get_settings
from portfolio_architect.embedding import codec
from portfolio_architect.db.projects import get_project, update_disease_vocab
from portfolio_architect.vocab import parse_vocab
from portfolio_architect.db.claims import get_verdict_summary
from portfolio_architect.db.claim_clusters import (
    get_clusters_for_project,
    get_cluster_members,
    set_conversation,
)
from portfolio_architect.claims.clustering import normalize_intervention, NON_INTERVENTION_KEYS
from portfolio_architect.claims.conversation import (
    build_conversation, build_conversation_compare, _select_members, rank_members, verdict_stats, stats_line,
)
from portfolio_architect.db.saved_publications import save_publication, saved_source_ids
from portfolio_architect.db.documents import parse_source_metadata
from portfolio_architect.claims import doi_ingest
from portfolio_architect.judge import conversation_judge
from portfolio_architect import assistant as research_assistant

router = APIRouter(prefix="/projects/{project_id}", tags=["workbench"])

_settings = get_settings()

# Cache 2D projections per (project_id, multi_only) — clusters are static once
# built, so recomputing PCA on every map load is wasteful.
_PROJECTION_CACHE: dict[tuple[str, bool], dict[str, tuple[float, float]]] = {}
_DISEASE_TAG_CACHE: dict[tuple[str, bool], dict[str, list[str]]] = {}



def invalidate_caches(project_id: str) -> None:
    """Drop all in-process caches for a project. Called after add-by-DOI mutates
    clusters so the map / dropdowns / singles reflect the new data on next fetch."""
    for cache in (_PROJECTION_CACHE, _DISEASE_TAG_CACHE):
        for key in [k for k in cache if k[0] == project_id]:
            cache.pop(key, None)
    _VERIFIED_CLAIMS_CACHE.pop(project_id, None)
    _SINGLETON_CACHE.pop(project_id, None)

# Disease vocabulary is per-project (projects.disease_vocab_json) — see
# portfolio_architect/vocab.py. A curated term set matches the freeform
# population/outcome/claim text rather than exposing thousands of raw population
# strings. Empty vocab ⇒ disease tagging/filtering is simply off for that
# project, so a project on any topic never inherits another's disease terms.
def _vocab(project: dict) -> dict[str, dict]:
    return parse_vocab(project.get("disease_vocab_json"))

# Interventions that are too generic to be a useful drug filter.
_DRUG_STOPWORDS = {"unknown", "none", "null", "", "chemotherapy", "immunotherapy",
                   "radiotherapy", "surgery", "endocrine therapy", "placebo"}

# At/under this many total clusters a project is "small": a fresh or focused
# review where almost nothing has clustered across papers yet. In that regime we
# also surface single-claim clusters — on the map, in the drug filter, and for
# synthesis — so the workbench isn't empty before the corpus reaches critical
# mass. Bounded by cluster count so the large corpus (15k+ clusters) is never
# affected and singleton-synthesis cost stays capped.
SMALL_PROJECT_CLUSTER_CAP = 400


def _is_small_project(clusters: list[dict]) -> bool:
    return len(clusters) <= SMALL_PROJECT_CLUSTER_CAP


def _matches_disease(claim: dict, keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = " ".join(
        str(claim.get(f) or "") for f in ("population", "claim_text", "outcome", "intervention")
    ).lower()
    return any(k in hay for k in keywords)


_VERIFIED_CLAIMS_CACHE: dict[str, list[dict]] = {}


async def _verified_paper_claims(conn, project_id: UUID) -> list[dict]:
    """All quote-verified, non-trial claims for the project, joined to their
    source document. The workbench's data contract: every claim shown has a
    real source and a verbatim, verified quote. Cached in-process — the corpus
    is static between rebuilds and this backs both the dropdowns and the live
    generate path (~21k rows)."""
    key = str(project_id)
    cached = _VERIFIED_CLAIMS_CACHE.get(key)
    if cached is not None:
        return cached
    rows = await conn.fetch(
        """
        SELECT c.id, c.claim_text, c.population, c.intervention, c.comparator,
               c.outcome, c.verdict, c.evidence_quote, c.effect_size,
               c.statistical_significance, c.confidence, d.source_id, d.doc_type
        FROM claims c JOIN documents d ON c.document_id = d.id
        WHERE c.project_id = ? AND c.quote_verified = 1 AND d.doc_type != 'trial'
        """,
        str(project_id),
    )
    _VERIFIED_CLAIMS_CACHE[key] = rows
    return rows


def _dominant_verdict(verdict_mix_json: str | None) -> str:
    try:
        mix = json.loads(verdict_mix_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return "inconclusive"
    if not mix:
        return "inconclusive"
    return max(mix.items(), key=lambda kv: kv[1])[0]


async def _load_cluster_centroids(
    conn, project_id: UUID, cluster_ids: list[str]
) -> dict[str, np.ndarray]:
    """Map cluster_id -> one representative 4096-dim embedding, used only to lay
    the map out in 2D via PCA. Two deliberate choices for speed: (1) take ONE
    embedding per cluster (GROUP BY) rather than averaging every member —
    loading all members' vectors made this >100s on a cold cache, while a single
    representative gives a near-identical 2D position; (2) restrict to the wanted
    cluster_ids via an indexed IN clause (chunked for SQLite's ~999-param limit)
    so we read ~484 embedding blobs, not one per singleton (16k+)."""
    out: dict[str, np.ndarray] = {}
    CHUNK = 500
    for i in range(0, len(cluster_ids), CHUNK):
        batch = cluster_ids[i : i + CHUNK]
        placeholders = ",".join("?" * len(batch))
        rows = await conn.fetch(
            f"SELECT cluster_id, claim_embedding FROM claims "
            f"WHERE cluster_id IN ({placeholders}) AND claim_embedding IS NOT NULL "
            f"GROUP BY cluster_id",
            *batch,
        )
        for r in rows:
            out[r["cluster_id"]] = codec.decode(r["claim_embedding"])
    return out


async def _cluster_disease_tags(conn, cluster_ids: list[str], vocab: dict[str, dict]) -> dict[str, list[str]]:
    """Map cluster_id -> the diseases (from the project's `vocab`) ANY of its
    members touch (keyword match on member population/claim_text/outcome).
    Tagging from members, not just the cluster's single templated question, so a
    drug cluster spanning several cancers is highlightable under each. Reads only
    small columns stored before the embedding blob, index-backed via
    idx_claims_cluster → fast. Empty vocab short-circuits (no DB scan)."""
    if not vocab or not cluster_ids:
        return {cid: [] for cid in cluster_ids}
    tags: dict[str, set[str]] = {cid: set() for cid in cluster_ids}
    CHUNK = 500
    for i in range(0, len(cluster_ids), CHUNK):
        batch = cluster_ids[i : i + CHUNK]
        placeholders = ",".join("?" * len(batch))
        rows = await conn.fetch(
            f"SELECT cluster_id, population, claim_text, outcome FROM claims "
            f"WHERE cluster_id IN ({placeholders})",
            *batch,
        )
        for r in rows:
            hay = f"{r['population'] or ''} {r['claim_text'] or ''} {r['outcome'] or ''}".lower()
            for k, meta in vocab.items():
                if any(w in hay for w in meta["keywords"]):
                    tags[r["cluster_id"]].add(k)
    return {cid: sorted(s) for cid, s in tags.items()}


def _project_2d(centroids: dict[str, np.ndarray]) -> dict[str, tuple[float, float]]:
    """PCA to 2D over cluster centroids. Degenerate cases (0/1/2 clusters) get
    trivial layouts so the map still renders."""
    ids = list(centroids.keys())
    if not ids:
        return {}
    if len(ids) == 1:
        return {ids[0]: (0.0, 0.0)}

    matrix = np.stack([centroids[i] for i in ids])
    centered = matrix - matrix.mean(axis=0)
    # economy SVD: principal axes are rows of Vt; project onto the top two.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    comps = vt[:2] if vt.shape[0] >= 2 else np.vstack([vt, np.zeros_like(vt[:1])])
    coords = centered @ comps.T  # (n, 2)
    return {ids[i]: (float(coords[i, 0]), float(coords[i, 1])) for i in range(len(ids))}


async def _require_project(conn, project_id: UUID) -> dict:
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


@router.get("/clusters")
async def list_clusters(
    project_id: UUID,
    multi_only: bool = True,
    conn=Depends(get_conn),
):
    """Claim clusters for the map. `multi_only` keeps only cross-paper clusters
    (member_count > 1) — the cases where sources agree/disagree, the interesting
    ones. Each item carries 2D map coordinates (x, y)."""
    project = await _require_project(conn, project_id)
    vocab = _vocab(project)
    clusters = await get_clusters_for_project(conn, project_id)
    # Small/fresh projects: show every cluster (incl. single-claim ones) so the
    # map isn't empty before papers start clustering across each other.
    if multi_only and not _is_small_project(clusters):
        # Keep multi-source clusters AND any user-added/-touched cluster, so a
        # source added by DOI always shows on the map even as a 1-claim bubble.
        clusters = [
            c for c in clusters
            if (c["member_count"] or 0) > 1
            or c["origin"] == "user" or (c["user_claim_count"] or 0) > 0
        ]

    cluster_ids = [c["id"] for c in clusters]
    cache_key = (str(project_id), multi_only)
    # Disease tags for filtering; cached (first call over ~16k clusters ~seconds).
    disease_tags = _DISEASE_TAG_CACHE.get(cache_key)
    if disease_tags is None or set(disease_tags) != set(cluster_ids):
        disease_tags = await _cluster_disease_tags(conn, cluster_ids, vocab)
        _DISEASE_TAG_CACHE[cache_key] = disease_tags

    out = []
    for c in clusters:
        # Coordinates are precomputed (scripts/compute_cluster_coords.py) so we
        # never load embeddings here — essential for the ~16k all-claims view.
        x = c["coord_x"] if c["coord_x"] is not None else 0.0
        y = c["coord_y"] if c["coord_y"] is not None else 0.0
        out.append({
            "id": c["id"],
            "intervention_key": c["intervention_key"],
            "member_count": c["member_count"],
            "distinct_document_count": c["distinct_document_count"],
            "verdict_mix": json.loads(c["verdict_mix_json"] or "{}"),
            "dominant_verdict": _dominant_verdict(c["verdict_mix_json"]),
            "question": c["question"],
            "diseases": disease_tags.get(c["id"], []),
            "citations_valid": c["citations_valid"],
            "has_answer": c["answer"] is not None,
            # A cluster reads as "user" if the user created it or added a claim to it.
            "origin": "user" if (c["origin"] == "user" or (c["user_claim_count"] or 0) > 0) else "corpus",
            "user_claim_count": c["user_claim_count"] or 0,
            "x": x,
            "y": y,
        })
    return {"clusters": out, "count": len(out), "multi_only": multi_only}


@router.get("/clusters/stats")
async def cluster_stats(project_id: UUID, conn=Depends(get_conn)):
    """Verdict totals + cluster counts for the workbench header."""
    await _require_project(conn, project_id)
    verdicts = await get_verdict_summary(conn, project_id)
    all_clusters = await get_clusters_for_project(conn, project_id)
    multi = [c for c in all_clusters if (c["member_count"] or 0) > 1]
    with_answer = [c for c in all_clusters if c["answer"] is not None]
    return {
        "verdicts": verdicts,
        "total_clusters": len(all_clusters),
        "multi_member_clusters": len(multi),
        "clusters_with_answer": len(with_answer),
        "finetuned_enabled": _settings.finetuned_enabled,
    }


@router.get("/clusters/{cluster_id}")
async def cluster_detail(
    project_id: UUID, cluster_id: str, full: bool = False, conn=Depends(get_conn)
):
    """One cluster's synthesized conversation + its per-source evidence — the
    feature-1 side-panel payload (CLAIM / evidence from source X / source Y).
    By default returns the strongest/dissenting claims (concise); `full=true`
    returns every verified claim in the cluster."""
    await _require_project(conn, project_id)
    cluster = await conn.fetchrow(
        "SELECT * FROM claim_clusters WHERE id = ? AND project_id = ?",
        cluster_id, str(project_id),
    )
    if not cluster:
        raise HTTPException(404, f"Cluster {cluster_id} not found")

    # Show only verified, non-trial evidence — every quote here is verbatim from
    # a real PubMed source.
    verified = [
        m for m in await get_cluster_members(conn, cluster_id)
        if m["quote_verified"] and m["doc_type"] != "trial"
    ]
    # Lazy synthesis: the create-project pipeline no longer synthesizes every
    # cluster upfront (so the map appears right after clustering). Build the cited
    # answer on first open and cache it. Uses ALL verified members so the opening
    # statistics stay full-coverage.
    answer, question, citations_valid = cluster["answer"], cluster["question"], cluster["citations_valid"]
    if not answer and verified:
        question, answer = await build_conversation(conn, project_id, cluster, verified)
        if answer:
            citations_valid = 1 if any((m.get("source_id") or "") in answer for m in verified) else 0
            await set_conversation(conn, cluster_id, question, answer, bool(citations_valid))

    # Concise by default (strongest / dissenting claims, same set the synthesized
    # answer drew on); full=true returns everything for the "load all" action.
    # Both paths are ranked by the calibrated evidence_strength score.
    members = rank_members(verified) if full else _select_members(verified)
    return {
        "id": cluster["id"],
        "intervention_key": cluster["intervention_key"],
        "question": question,
        "answer": answer,
        "judge": json.loads(cluster["judge_json"]) if cluster["judge_json"] else None,
        "citations_valid": citations_valid,
        "verdict_mix": json.loads(cluster["verdict_mix_json"] or "{}"),
        "member_count": len(verified),
        "shown_count": len(members),
        "distinct_document_count": len({m["source_id"] for m in verified}),
        "members": [
            {
                "id": m["id"],
                "claim_text": m["claim_text"],
                "verdict": m["verdict"],
                "evidence_quote": m["evidence_quote"],
                "quote_verified": m["quote_verified"],
                "source_id": m["source_id"],
                "doc_type": m["doc_type"],
                "pub_date": m["pub_date"],
                "population": m["population"],
                "intervention": m["intervention"],
                "outcome": m["outcome"],
                "effect_size": m["effect_size"],
                "statistical_significance": m["statistical_significance"],
                "evidence_strength": m.get("evidence_strength"),
            }
            for m in members
        ],
    }


@router.post("/clusters/{cluster_id}/judge")
async def judge_cluster(project_id: UUID, cluster_id: str, conn=Depends(get_conn)):
    """LLM-as-judge for a cluster's synthesized answer — scores faithfulness /
    citation accuracy / relevance / completeness (1-5) against the cluster's
    verified sources. Cached on first run: one judge call per answer, reused
    thereafter (keeps the demo deterministic and the cost bounded)."""
    await _require_project(conn, project_id)
    cluster = await conn.fetchrow(
        "SELECT * FROM claim_clusters WHERE id = ? AND project_id = ?",
        cluster_id, str(project_id),
    )
    if not cluster:
        raise HTTPException(404, f"Cluster {cluster_id} not found")
    if not cluster["answer"]:
        raise HTTPException(400, "This cluster has no synthesized answer to judge.")
    if cluster["judge_json"]:
        return {"judge": json.loads(cluster["judge_json"]), "cached": True}

    # Judge against the SAME sources the answer was synthesized from — the
    # top-ranked selection, not every verified member. Grading the answer
    # against sources the generator never saw structurally penalises large
    # clusters for "omitting" claims that were never in its context.
    verified = [
        m for m in await get_cluster_members(conn, cluster_id)
        if m["quote_verified"] and m["doc_type"] != "trial"
    ]
    members = _select_members(verified)
    # Full-coverage totals so the judge treats the answer's opening statistics
    # sentence as authoritative rather than an uncited claim.
    totals = stats_line(verdict_stats(verified))
    verdict = await conversation_judge.judge_conversation(
        cluster["question"], members, cluster["answer"], evidence_totals=totals,
        conn=conn, project_id=project_id,
    )
    await conn.execute(
        "UPDATE claim_clusters SET judge_json = ? WHERE id = ?", json.dumps(verdict), cluster_id,
    )
    return {"judge": verdict, "cached": False}


@router.post("/clusters/{cluster_id}/save-sources")
async def save_cluster_sources(project_id: UUID, cluster_id: str, conn=Depends(get_conn)):
    """Bookmark every distinct source under this cluster (research question) into
    the project's reading list."""
    await _require_project(conn, project_id)
    rows = await conn.fetch(
        """SELECT DISTINCT d.source_id FROM claims c JOIN documents d ON c.document_id = d.id
           WHERE c.cluster_id = ? AND d.source_id IS NOT NULL""",
        cluster_id,
    )
    for r in rows:
        await save_publication(conn, project_id, r["source_id"], added_from="cluster")
    return {"saved": len(rows)}


@router.get("/workbench/options")
async def workbench_options(project_id: UUID, conn=Depends(get_conn)):
    """Filter dropdown values for the **cluster map** — derived from multi-source
    clusters (the bubbles), so every option highlights at least one. Single-paper
    drugs (mastectomy etc.) live in the Single-paper claims tab instead."""
    project = await _require_project(conn, project_id)
    vocab = _vocab(project)
    clusters = await get_clusters_for_project(conn, project_id)
    multi = [c for c in clusters if (c["member_count"] or 0) > 1]
    # On a small/fresh project the map shows single-claim clusters too, so the
    # drug filter is built from ALL clusters (otherwise it's empty until papers
    # cluster). On the large corpus it stays multi-source-only, as before.
    drug_source = clusters if _is_small_project(clusters) else multi

    drug_counts: dict[str, int] = {}
    for c in drug_source:
        key = c["intervention_key"]
        if key in _DRUG_STOPWORDS or key in NON_INTERVENTION_KEYS:
            continue
        drug_counts[key] = drug_counts.get(key, 0) + (c["member_count"] or 0)
    drugs = sorted(
        ({"key": k, "count": n} for k, n in drug_counts.items()),
        key=lambda d: -d["count"],
    )

    # Diseases: how many map clusters are tagged with each (same member-based
    # tags the map highlights on), so the disease filter also always lights up.
    tags = await _cluster_disease_tags(conn, [c["id"] for c in drug_source], vocab)
    disease_counts: dict[str, int] = {k: 0 for k in vocab}
    for ds in tags.values():
        for d in ds:
            disease_counts[d] += 1
    diseases = [
        {"key": k, "label": vocab[k]["label"], "count": disease_counts[k]}
        for k in vocab if disease_counts[k]
    ]
    diseases.sort(key=lambda d: -d["count"])

    # `vocab` is returned raw so the workbench's disease-vocab editor can load
    # the current term set (label + keywords), which the counted list above drops.
    return {"drugs": drugs, "diseases": diseases, "vocab": vocab}


class AssistantBody(BaseModel):
    question: str


@router.post("/workbench/assistant")
async def workbench_assistant(project_id: UUID, body: AssistantBody, conn=Depends(get_conn)):
    """Research-assistant agent: answer a free-form question over the project's
    corpus (retrieve → synthesize a cited answer → self-check with the judge).
    Saves the Q&A to history, and returns a conversation-shaped payload the UI
    renders in the answer panel."""
    await _require_project(conn, project_id)
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(400, "Ask a question about the evidence.")
    result = await research_assistant.answer_question(conn, project_id, q)
    if result.get("answer"):
        aid = str(uuid4())
        await conn.execute(
            "INSERT INTO assistant_answers (id, project_id, question, answer, payload_json) VALUES (?, ?, ?, ?, ?)",
            aid, str(project_id), q, result["answer"], json.dumps(result),
        )
        result["id"] = aid
    return result


@router.get("/workbench/assistant/history")
async def assistant_history(project_id: UUID, conn=Depends(get_conn)):
    """Past assistant questions + their saved cited/judged answers, newest first."""
    await _require_project(conn, project_id)
    rows = await conn.fetch(
        "SELECT id, question, payload_json, created_at FROM assistant_answers "
        "WHERE project_id = ? ORDER BY created_at DESC LIMIT 50",
        str(project_id),
    )
    return {"items": [
        {"id": r["id"], "question": r["question"], "created_at": r["created_at"],
         **json.loads(r["payload_json"])}
        for r in rows
    ]}


@router.delete("/workbench/assistant/history/{answer_id}", status_code=204)
async def delete_assistant_answer(project_id: UUID, answer_id: str, conn=Depends(get_conn)):
    await _require_project(conn, project_id)
    await conn.execute(
        "DELETE FROM assistant_answers WHERE id = ? AND project_id = ?", answer_id, str(project_id))


@router.get("/workbench/papers")
async def list_papers(
    project_id: UUID, q: str = "", source_id: str = "", limit: int = 50, offset: int = 0, conn=Depends(get_conn),
):
    """Full browsable list of the project's papers with parsed citation metadata
    (title / authors / journal / year / DOI), claim count, and whether each is
    already in the reading list. Paginated; `q` filters on the raw text (title/
    abstract). Pass `source_id` to fetch one specific paper (e.g. to reveal a
    cited source)."""
    await _require_project(conn, project_id)
    limit = max(1, min(limit, 200))
    where = "WHERE d.project_id = ? AND d.doc_type = 'paper'"
    params: list = [str(project_id)]
    if source_id.strip():
        where += " AND d.source_id = ?"
        params.append(source_id.strip())
    elif q.strip():
        # Match a partial term against the title/DOI (both in the raw_content
        # header) and the source_id, which is the PMID (e.g. "pmid:12345").
        where += " AND (d.raw_content LIKE ? OR d.source_id LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like])

    # Year is not a reliable column (pub_date is often NULL for freshly ingested
    # projects), but every record's raw_content carries a "Year: YYYY" header
    # line. Sort on that extracted year (newest first), so ordering holds even
    # before pub_date is backfilled; NULL/unparseable years sink to the bottom.
    year_expr = (
        "CASE WHEN instr(d.raw_content, 'Year: ') > 0 "
        "THEN CAST(substr(d.raw_content, instr(d.raw_content, 'Year: ') + 6, 4) AS INTEGER) "
        "ELSE NULL END"
    )
    total = (await conn.fetchrow(
        f"SELECT COUNT(*) AS n FROM documents d {where}", *params))["n"]
    rows = await conn.fetch(
        f"""SELECT d.id, d.source_id, d.raw_content, d.pub_date, d.doc_type,
                   (SELECT COUNT(*) FROM claims c WHERE c.document_id = d.id) AS claim_count,
                   (SELECT GROUP_CONCAT(DISTINCT c.cluster_id) FROM claims c
                      WHERE c.document_id = d.id AND c.cluster_id IS NOT NULL) AS cluster_ids
            FROM documents d {where}
            ORDER BY {year_expr} DESC, d.pub_date DESC, d.source_id
            LIMIT ? OFFSET ?""",
        *params, limit, offset,
    )
    saved = set(await saved_source_ids(conn, project_id))
    papers = []
    for r in rows:
        md = parse_source_metadata(r["raw_content"])
        papers.append({
            "source_id": r["source_id"],
            "title": md["title"] or None,
            "authors": md["authors"] or None,
            "journal": md["journal"] or None,
            "year": md["year"] or r["pub_date"] or None,
            "doi": md["doi"] or None,
            "claim_count": r["claim_count"],
            # Clusters this paper's claims belong to — lets the UI jump to and
            # spotlight the paper on the cluster map.
            "cluster_ids": r["cluster_ids"].split(",") if r["cluster_ids"] else [],
            "saved": r["source_id"] in saved,
        })
    return {"total": total, "count": len(papers), "offset": offset, "limit": limit, "papers": papers}


class SaveFilteredBody(BaseModel):
    drug: str | None = None
    disease: str | None = None


@router.post("/workbench/save-filtered")
async def save_filtered_papers(project_id: UUID, body: SaveFilteredBody, conn=Depends(get_conn)):
    """Save every paper matching the current drug/disease filter to the reading
    list at once — the "save all these papers" action next to the workbench
    dropdowns. Matches on the same verified-claim logic the map filter uses."""
    project = await _require_project(conn, project_id)
    drug = (body.drug or "").strip().lower()
    disease_meta = _vocab(project).get(body.disease) if body.disease else None
    keywords = disease_meta["keywords"] if disease_meta else []
    if not drug and not keywords:
        raise HTTPException(400, "Select a drug or a disease to save its papers.")

    claims = await _verified_paper_claims(conn, project_id)
    # The drug filter shows canonical names (from the LLM alias map), so match
    # each claim's canonical key — not its raw normalized string — against it.
    from portfolio_architect.claims.clustering import block_key
    from portfolio_architect.claims.drug_normalizer import load_aliases
    canonical = await load_aliases(
        conn, [normalize_intervention(c["intervention"]) for c in claims]
    )
    source_ids = {
        c["source_id"] for c in claims
        if (not drug or block_key(c["intervention"], canonical) == drug)
        and _matches_disease(c, keywords)
        and c.get("source_id")
    }
    already = set(await saved_source_ids(conn, project_id))
    to_save = source_ids - already
    for sid in to_save:
        await save_publication(conn, project_id, sid, added_from="filter")
    return {"matched": len(source_ids), "saved": len(to_save), "already_saved": len(source_ids & already)}


class DiseaseVocabBody(BaseModel):
    vocab: dict[str, dict]


@router.put("/workbench/disease-vocab")
async def set_disease_vocab(project_id: UUID, body: DiseaseVocabBody, conn=Depends(get_conn)):
    """Replace the project's disease vocabulary (drives cluster tagging + the
    disease filter). Input is normalized and entries without keywords are
    dropped. Invalidates the workbench caches so tags/options recompute against
    the new terms on the next fetch."""
    await _require_project(conn, project_id)
    clean = parse_vocab(json.dumps(body.vocab))
    await update_disease_vocab(conn, project_id, json.dumps(clean))
    invalidate_caches(str(project_id))
    return {"ok": True, "vocab": clean}


_SINGLETON_CACHE: dict[str, list[dict]] = {}


async def _singleton_claims(conn, project_id: UUID) -> list[dict]:
    """All verified single-paper claims (member_count=1 clusters), each annotated
    with evidence_strength and sorted strongest-first. Cached in-process. Backs
    the Single-paper claims tab — the individual claims that didn't converge with
    others into a multi-source cluster."""
    key = str(project_id)
    cached = _SINGLETON_CACHE.get(key)
    if cached is not None:
        return cached
    rows = await conn.fetch(
        """
        SELECT c.id, c.claim_text, c.population, c.intervention, c.outcome,
               c.verdict, c.evidence_quote, c.quote_verified, c.effect_size,
               c.statistical_significance, c.confidence,
               d.source_id, d.doc_type, d.pub_date, cc.intervention_key
        FROM claims c
        JOIN claim_clusters cc ON c.cluster_id = cc.id
        JOIN documents d ON c.document_id = d.id
        WHERE cc.project_id = ? AND cc.member_count = 1
              AND c.quote_verified = 1 AND d.doc_type != 'trial'
        """,
        str(project_id),
    )
    rows = [dict(r) for r in rows]
    rank_members(rows)  # annotates evidence_strength
    rows.sort(key=lambda m: m["evidence_strength"], reverse=True)
    _SINGLETON_CACHE[key] = rows
    return rows


@router.get("/workbench/single-claims")
async def single_claims(
    project_id: UUID,
    q: str | None = None,
    disease: str | None = None,
    verdict: str | None = None,
    limit: int = 30,
    offset: int = 0,
    conn=Depends(get_conn),
):
    """Paginated, filterable list of single-paper claims (strongest first)."""
    project = await _require_project(conn, project_id)
    rows = await _singleton_claims(conn, project_id)

    disease_meta = _vocab(project).get(disease) if disease else None
    keywords = disease_meta["keywords"] if disease_meta else []
    ql = (q or "").strip().lower()

    def keep(m: dict) -> bool:
        if verdict and m["verdict"] != verdict:
            return False
        if keywords and not _matches_disease(m, keywords):
            return False
        if ql:
            hay = f"{m.get('claim_text') or ''} {m.get('intervention') or ''}".lower()
            if ql not in hay:
                return False
        return True

    filtered = [m for m in rows if keep(m)]
    page = filtered[offset:offset + limit]
    return {
        "total": len(filtered),
        "offset": offset,
        "limit": limit,
        "claims": [
            {
                "id": m["id"],
                "claim_text": m["claim_text"],
                "verdict": m["verdict"],
                "evidence_quote": m["evidence_quote"],
                "quote_verified": m["quote_verified"],
                "source_id": m["source_id"],
                "pub_date": m["pub_date"],
                "doc_type": m["doc_type"],
                "intervention": m["intervention"],
                "effect_size": m["effect_size"],
                "statistical_significance": m["statistical_significance"],
                "evidence_strength": m.get("evidence_strength"),
            }
            for m in page
        ],
    }


class AddSourceRequest(BaseModel):
    doi: str


def _user_source_row(r: dict) -> dict:
    try:
        cluster_ids = json.loads(r["cluster_ids"] or "[]")
    except (json.JSONDecodeError, TypeError):
        cluster_ids = []
    return {
        "id": r["id"], "doi": r["doi"], "source_id": r["source_id"],
        "status": r["status"], "message": r["message"], "title": r["title"],
        "claims_added": r["claims_added"], "cluster_ids": cluster_ids,
        "created_at": r["created_at"],
    }


@router.post("/workbench/add-source")
async def add_source(
    project_id: UUID,
    body: AddSourceRequest,
    background: BackgroundTasks,
    pool=Depends(get_db_pool),
    conn=Depends(get_conn),
):
    """Submit a DOI. Runs the resolve→extract→embed→cluster pipeline in the
    background (see claims/doi_ingest.py); poll GET /workbench/user-sources."""
    await _require_project(conn, project_id)
    doi = (body.doi or "").strip()
    if not doi:
        raise HTTPException(400, "doi is required")
    sid = str(uuid4())
    await conn.execute(
        "INSERT INTO user_sources (id, project_id, doi, status, message) VALUES (?, ?, ?, 'pending', 'Queued…')",
        sid, str(project_id), doi,
    )
    background.add_task(doi_ingest.process_source, pool, project_id, sid, doi)
    return {"id": sid, "status": "pending"}


@router.get("/workbench/user-sources")
async def user_sources(project_id: UUID, conn=Depends(get_conn)):
    """Recent add-by-DOI jobs + their status (for polling)."""
    await _require_project(conn, project_id)
    rows = await conn.fetch(
        "SELECT * FROM user_sources WHERE project_id = ? ORDER BY created_at DESC LIMIT 20",
        str(project_id),
    )
    return {"sources": [_user_source_row(r) for r in rows]}


class GenerateRequest(BaseModel):
    drug: str
    disease: str | None = None


@router.post("/workbench/generate")
async def generate_conversation(
    project_id: UUID,
    body: GenerateRequest,
    conn=Depends(get_conn),
):
    """Generate a cited answer for a chosen drug (× optional disease), grounded
    only in verified, non-trial claims already in the corpus, synthesized with
    the base and fine-tuned models side by side."""
    project = await _require_project(conn, project_id)
    drug = (body.drug or "").strip().lower()
    if not drug:
        raise HTTPException(400, "drug is required")

    disease_meta = _vocab(project).get(body.disease) if body.disease else None
    keywords = disease_meta["keywords"] if disease_meta else []

    claims = await _verified_paper_claims(conn, project_id)
    members = [
        c for c in claims
        if normalize_intervention(c["intervention"]) == drug and _matches_disease(c, keywords)
    ]
    if not members:
        label = disease_meta["label"] if disease_meta else "any disease"
        raise HTTPException(404, f"No verified paper evidence for '{body.drug}' in {label}.")

    # Pass ALL matched members so the synthesized answer's statistics stay
    # full-coverage; build_conversation_compare picks the dissent-expanded detail
    # subset internally (verdict_stats over all, _select_members for the prompt).
    members.sort(key=lambda c: (c.get("confidence") or 0), reverse=True)

    result = await build_conversation_compare(conn, project_id, drug, members)

    return {
        "drug": drug,
        "disease": disease_meta["label"] if disease_meta else None,
        "match_count": len(members),  # full-coverage count (drives the statistics)
        "finetuned_enabled": _settings.finetuned_enabled,
        **result,
        "members": [
            {
                "claim_text": m["claim_text"],
                "verdict": m["verdict"],
                "evidence_quote": m.get("evidence_quote"),
                "source_id": m["source_id"],
                "doc_type": m["doc_type"],
            }
            for m in _select_members(members)  # the dissent-expanded detail subset actually quoted
        ],
    }
