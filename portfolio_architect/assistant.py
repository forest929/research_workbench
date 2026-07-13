"""Research-assistant agent over a project's built corpus.

Turns the static evidence map into a conversational partner: it answers a
free-form question the templated cluster questions can't ("compare A vs B",
"what contradicts the majority view", "where are the gaps") by orchestrating the
same building blocks the rest of the app uses —

  retrieve (cosine over claim embeddings)  →  synthesize a cited answer  →
  self-check with the independent judge.

Reuses claim retrieval as its retrieval tool and the LLM-as-judge to grade its
own answer, so an assistant reply carries the same provenance guarantees as a
cluster answer. Returns a cluster-detail-shaped payload so the frontend renders
it with the existing conversation panel.
"""

from collections import Counter

from portfolio_architect.claims.retrieval import retrieve_claims_for_topic
from portfolio_architect.claims.conversation import (
    claims_to_xml, verdict_stats, stats_line, _select_members, rank_members,
)
from portfolio_architect.llm import client as llm
from portfolio_architect.judge import conversation_judge

ASSISTANT_SYSTEM = """You are a research assistant answering a specific question using ONLY the \
retrieved atomic claims below — each extracted from a real paper, with a verdict and a verbatim \
quote. You are given the full-coverage evidence totals and a focused set of the most relevant claims.

Answer the exact question asked — including comparisons ("A vs B"), contradictions ("what challenges \
X"), and coverage gaps. Rules:
- Open with one sentence grounding the answer in the totals (e.g. "Across the 24 retrieved claims, \
most support ..."). Do not cite a source for that sentence.
- Every statement about a specific finding is immediately followed by its citation [source_id].
- State disagreement explicitly; do not smooth it over. When two agents/arms are compared, say which \
the evidence favours and on what outcome.
- If the retrieved evidence does not actually answer the question, say so plainly — name it as a gap \
rather than inventing an answer.
- Mention effect sizes and statistical significance when provided.
- This is an evidence summary, not clinical advice. Plain prose, 3-6 sentences, no headings."""

ASSISTANT_USER = """<question>
{question}
</question>

<evidence_totals>
{evidence_totals}
</evidence_totals>

<claims>
{claims_xml}
</claims>

Answer the question directly, citing every specific claim you use by its source_id."""


def _member(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "claim_text": m.get("claim_text"),
        "verdict": m.get("verdict"),
        "evidence_quote": m.get("evidence_quote"),
        "quote_verified": m.get("quote_verified"),
        "source_id": m.get("source_id"),
        "doc_type": m.get("doc_type"),
        "pub_date": m.get("pub_date"),
        "population": m.get("population"),
        "intervention": m.get("intervention"),
        "outcome": m.get("outcome"),
        "effect_size": m.get("effect_size"),
        "statistical_significance": m.get("statistical_significance"),
        "evidence_strength": m.get("evidence_strength"),
    }


async def answer_question(conn, project_id, question: str, judge: bool = True) -> dict:
    """Retrieve → synthesize → self-check for one free-form question. Returns a
    cluster-detail-shaped dict so the UI renders it with the conversation panel."""
    claims = await retrieve_claims_for_topic(conn, project_id, question, top_k=40)
    verified = [c for c in claims if c.get("quote_verified") and c.get("doc_type") != "trial"]
    if not verified:
        return {
            "question": question, "answer": "", "judge": None, "members": [],
            "verdict_mix": {}, "member_count": 0, "shown_count": 0,
            "distinct_document_count": 0, "no_evidence": True, "is_assistant": True,
        }

    ranked = rank_members(verified)              # annotates evidence_strength, dissent-first
    selected = _select_members(ranked)           # the focused set the answer quotes
    totals = stats_line(verdict_stats(verified))

    messages = [
        {"role": "system", "content": ASSISTANT_SYSTEM},
        {"role": "user", "content": ASSISTANT_USER.format(
            question=question, evidence_totals=totals, claims_xml=claims_to_xml(selected))},
    ]
    try:
        answer = (await llm.generate(
            messages, temperature=0.2, call_type="assistant", conn=conn, project_id=project_id)).strip()
    except Exception as e:
        answer = ""

    verdict = None
    if judge and answer:
        verdict = await conversation_judge.judge_conversation(
            question, selected, answer, evidence_totals=totals, conn=conn, project_id=project_id)

    return {
        "question": question,
        "answer": answer,
        "judge": verdict,
        "members": [_member(m) for m in selected],
        "verdict_mix": dict(Counter(m.get("verdict") for m in verified)),
        "member_count": len(verified),
        "shown_count": len(selected),
        "distinct_document_count": len({m.get("source_id") for m in verified if m.get("source_id")}),
        "is_assistant": True,
    }
