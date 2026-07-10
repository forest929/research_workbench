"""Screening router: LLM prediction + human decision recording with feedback loop."""

import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_conn
from portfolio_architect.db.criteria import get_criteria
from portfolio_architect.db.projects import get_project
from portfolio_architect.embedding.client import embed_text
from portfolio_architect.feedback.decision_memory import (
    get_doc_embedding,
    retrieve_similar_examples,
    store_decision,
    get_validated_count,
)
from portfolio_architect.feedback.disagreement import record_disagreement, get_disagreement_stats
from portfolio_architect.feedback.preference_learning import (
    update_preferences,
    get_preferences,
    build_guidance_text,
)
from portfolio_architect.llm.client import generate
from portfolio_architect.llm.prompt_builder import build_messages, parse_prediction, REASON_CODES
from portfolio_architect.ranking.active_learning import rank_pending_documents, predict_document

router = APIRouter(prefix="/projects/{project_id}/screening", tags=["screening"])


# ── Request/response models ───────────────────────────────────────────────────

class DecisionBody(BaseModel):
    human_label: str               # "include" or "exclude"
    human_reason: str | None = None
    reason_code: str | None = None
    is_protocol_specific: bool = True
    reviewer: str | None = None
    llm_label: str | None = None
    llm_confidence: float | None = None
    llm_reasoning: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/queue")
async def get_screening_queue(
    project_id: UUID,
    limit: int = 20,
    conn=Depends(get_conn),
):
    """Return pending documents ranked by Active Learning uncertainty."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    # Ensure doc_embeddings are populated for pending docs that have chunks embedded
    await _ensure_doc_embeddings(conn, project_id)

    queue = await rank_pending_documents(conn, project_id, limit=limit)
    validated = await get_validated_count(conn, project_id)
    return {
        "queue": queue,
        "validated_count": validated,
        "total_pending": len(queue),
    }


@router.post("/{document_id}/llm-predict")
async def llm_predict(
    project_id: UUID,
    document_id: UUID,
    conn=Depends(get_conn),
):
    """Run LLM screening prediction using dynamic few-shot prompt from decision memory."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    doc_rows = await conn.fetch(
        "SELECT id, raw_content, doc_embedding FROM documents WHERE id = ? AND project_id = ?",
        str(document_id), str(project_id),
    )
    if not doc_rows:
        raise HTTPException(404, f"Document {document_id} not found")
    doc = doc_rows[0]

    # Get or compute document embedding
    doc_emb = json.loads(doc["doc_embedding"]) if doc.get("doc_embedding") else None
    if doc_emb is None:
        doc_emb = await get_doc_embedding(conn, document_id)
        if doc_emb:
            await conn.execute(
                "UPDATE documents SET doc_embedding = ? WHERE id = ?",
                json.dumps(doc_emb), str(document_id),
            )

    # Gather context for the prompt
    criteria = await get_criteria(conn, project_id)
    similar_examples = []
    if doc_emb:
        similar_examples = await retrieve_similar_examples(conn, project_id, doc_emb, top_k=5)
    guidance = await build_guidance_text(conn, project_id)

    messages = build_messages(
        abstract=doc["raw_content"],
        criteria=criteria,
        similar_examples=similar_examples,
        project_guidance=guidance,
    )

    raw = await generate(messages, temperature=0.0, call_type="screening", conn=conn, project_id=project_id)
    prediction = parse_prediction(raw)
    prediction["similar_examples"] = similar_examples
    prediction["guidance_applied"] = bool(guidance)

    # AL prediction for comparison
    if doc_emb:
        al = await predict_document(conn, project_id, doc_emb)
        prediction["al_prediction"] = al

    return prediction


@router.post("/{document_id}/decide")
async def record_decision(
    project_id: UUID,
    document_id: UUID,
    body: DecisionBody,
    conn=Depends(get_conn),
):
    """Record a human screening decision, update decision memory, detect disagreements."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    if body.human_label not in ("include", "exclude"):
        raise HTTPException(422, "human_label must be 'include' or 'exclude'")
    if body.reason_code and body.reason_code not in REASON_CODES:
        raise HTTPException(422, f"reason_code must be one of: {REASON_CODES}")

    decision = await store_decision(
        conn,
        project_id=project_id,
        document_id=document_id,
        human_label=body.human_label,
        human_reason=body.human_reason,
        reason_code=body.reason_code,
        is_protocol_specific=body.is_protocol_specific,
        reviewer=body.reviewer,
        llm_label=body.llm_label,
        llm_confidence=body.llm_confidence,
        llm_reasoning=body.llm_reasoning,
    )

    # Track disagreements
    if body.llm_label:
        await record_disagreement(
            conn,
            project_id=project_id,
            document_id=document_id,
            llm_label=body.llm_label,
            human_label=body.human_label,
            reason_code=body.reason_code,
            llm_confidence=body.llm_confidence,
        )

    # Update preference observations
    await update_preferences(conn, project_id, body.reason_code, body.human_label)

    return {"decision": decision, "status": "recorded"}


@router.get("/stats")
async def screening_stats(project_id: UUID, conn=Depends(get_conn)):
    """Return disagreement statistics and overall screening progress."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")

    stats = await get_disagreement_stats(conn, project_id)

    total_docs = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ?", str(project_id)
    )
    pending = await conn.fetch(
        "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ? AND screening_status = 'pending'",
        str(project_id),
    )
    stats["total_documents"] = total_docs[0]["cnt"] if total_docs else 0
    stats["pending_documents"] = pending[0]["cnt"] if pending else 0
    return stats


@router.get("/preferences")
async def screening_preferences(project_id: UUID, conn=Depends(get_conn)):
    """Return auto-detected reviewer preferences for this project."""
    project = await get_project(conn, project_id)
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    prefs = await get_preferences(conn, project_id)
    guidance = await build_guidance_text(conn, project_id)
    return {"preferences": prefs, "guidance_text": guidance}


@router.get("/similar/{document_id}")
async def get_similar_examples(
    project_id: UUID,
    document_id: UUID,
    top_k: int = 5,
    conn=Depends(get_conn),
):
    """Return validated decisions most similar to a given document."""
    doc_rows = await conn.fetch(
        "SELECT doc_embedding FROM documents WHERE id = ? AND project_id = ?",
        str(document_id), str(project_id),
    )
    if not doc_rows:
        raise HTTPException(404, "Document not found")

    doc_emb = json.loads(doc_rows[0]["doc_embedding"]) if doc_rows[0].get("doc_embedding") else None
    if doc_emb is None:
        doc_emb = await get_doc_embedding(conn, document_id)
    if doc_emb is None:
        return {"similar_examples": [], "reason": "document not embedded yet"}

    examples = await retrieve_similar_examples(conn, project_id, doc_emb, top_k=top_k)
    return {"similar_examples": examples}


# ── Internal helper ───────────────────────────────────────────────────────────

async def _ensure_doc_embeddings(conn, project_id: UUID) -> None:
    """Populate doc_embedding for documents that have chunks but no cached embedding yet."""
    rows = await conn.fetch(
        """SELECT d.id FROM documents d
           WHERE d.project_id = ? AND d.doc_embedding IS NULL AND d.embedded = 1""",
        str(project_id),
    )
    for r in rows:
        emb = await get_doc_embedding(conn, UUID(r["id"]))
        if emb:
            await conn.execute(
                "UPDATE documents SET doc_embedding = ? WHERE id = ?",
                json.dumps(emb), r["id"],
            )
