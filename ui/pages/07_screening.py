"""Page 7: Human screening with LLM prediction + decision memory feedback loop.

Layout:
  - Progress bar across the full corpus
  - Two-column review: paper content (left) | LLM prediction + decision (right)
  - Auto-predict on page load — no "Get Prediction" button required
  - Quick Include / Exclude buttons auto-advance to the next paper
  - Expandable reason-code form for detailed annotations
"""

import os
import sys
import httpx
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ui.components.sidebar import render_sidebar

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("7️⃣ Screening — Inclusion / Exclusion Review")

project_id = render_sidebar()
if not project_id:
    st.warning("No projects yet. Visit **Onboarding** to create one.")
    st.stop()

# ── Constants ─────────────────────────────────────────────────────────────────
REASON_CODES = [
    "REVIEW_ARTICLE", "SIMULATION_ONLY", "GREENHOUSE_ONLY",
    "WRONG_POPULATION", "WRONG_INTERVENTION", "WRONG_OUTCOME",
    "PROTOCOL_PAPER", "DUPLICATE", "LANGUAGE", "DATE", "NO_ABSTRACT", "OTHER",
]
REASON_LABELS = {
    "REVIEW_ARTICLE": "Review article",
    "SIMULATION_ONLY": "Simulation only",
    "GREENHOUSE_ONLY": "Greenhouse-only experiment",
    "WRONG_POPULATION": "Wrong population",
    "WRONG_INTERVENTION": "Wrong intervention",
    "WRONG_OUTCOME": "Wrong outcome",
    "PROTOCOL_PAPER": "Protocol / registration paper",
    "DUPLICATE": "Duplicate record",
    "LANGUAGE": "Non-English",
    "DATE": "Outside date range",
    "NO_ABSTRACT": "No abstract",
    "OTHER": "Other",
}


def _parse_doc(raw: str) -> dict:
    KNOWN_KEYS = {
        "Title", "Authors", "Journal", "Year", "DOI", "Abstract",
        "PMID", "Source", "Type", "Language", "Keywords",
    }
    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if ": " in line:
            candidate_key, _, val = line.partition(": ")
            candidate_key = candidate_key.strip()
            if candidate_key in KNOWN_KEYS or current_key is None:
                current_key = candidate_key
                fields[current_key] = val.strip()
                continue
        if current_key and line.strip():
            fields[current_key] = fields[current_key] + " " + line.strip()
    return fields


def _confidence_bar(conf: float, label: str) -> str:
    color = "#28a745" if label == "include" else "#dc3545"
    icon = "✅" if label == "include" else "❌"
    pct = int(conf * 100)
    return (
        f"<div style='margin:4px 0'>"
        f"<span style='font-size:1.3em; color:{color}'>{icon} <b>{label.upper()}</b></span> "
        f"<span style='color:#888'>({pct}% confidence)</span>"
        f"</div>"
        f"<div style='background:#eee; border-radius:4px; height:8px; margin:4px 0'>"
        f"<div style='background:{color}; width:{pct}%; height:8px; border-radius:4px'></div>"
        f"</div>"
    )


def _save_decision(
    project_id: str,
    doc_id: str,
    human_label: str,
    pred: dict,
    reason_code: str | None = None,
    human_reason: str | None = None,
    reviewer: str | None = None,
) -> bool:
    payload = {
        "human_label": human_label,
        "human_reason": human_reason or None,
        "reason_code": reason_code or None,
        "is_protocol_specific": True,
        "reviewer": reviewer or None,
        "llm_label": pred.get("label"),
        "llm_confidence": pred.get("confidence"),
        "llm_reasoning": pred.get("reasoning"),
    }
    try:
        dr = httpx.post(
            f"{API_BASE}/projects/{project_id}/screening/{doc_id}/decide",
            json=payload,
            timeout=30,
        )
        dr.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Failed to save decision: {e}")
        return False


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_review, tab_stats, tab_prefs = st.tabs(["📋 Review Queue", "📊 Stats", "🧠 Learned Preferences"])

# ══════════════════════════════════════════════════════════════════════════════
# Tab 1 — Review Queue
# ══════════════════════════════════════════════════════════════════════════════
with tab_review:
    refresh_col, hint_col = st.columns([1, 4])
    with refresh_col:
        if st.button("🔄 Refresh Queue"):
            st.cache_data.clear()
            st.rerun()
    with hint_col:
        st.caption(
            "After screening several papers, trigger a new analysis run on "
            "**Page 3 — Research** to refine criteria with this new evidence."
        )

    # Load queue
    queue_data: dict = {}
    try:
        r = httpx.get(
            f"{API_BASE}/projects/{project_id}/screening/queue",
            params={"limit": 30},
            timeout=60,
        )
        r.raise_for_status()
        queue_data = r.json()
    except Exception as e:
        st.error(f"Could not load queue: {e}")

    queue: list[dict] = queue_data.get("queue", [])
    validated: int = queue_data.get("validated_count", 0)

    # Fetch real corpus total from stats so progress bar is accurate
    # (queue is capped at 30; total_documents reflects the full corpus)
    real_total: int = validated + len(queue)  # fallback
    try:
        sr = httpx.get(f"{API_BASE}/projects/{project_id}/screening/stats", timeout=10)
        if sr.status_code == 200:
            real_total = sr.json().get("total_documents", real_total)
    except Exception:
        pass

    # ── Progress bar ──────────────────────────────────────────────────────────
    if real_total > 0:
        progress = min(validated / real_total, 1.0)
        st.progress(
            progress,
            text=f"Screened **{validated}** of **{real_total}** documents ({progress:.0%})",
        )
    else:
        col_a, col_b = st.columns(2)
        col_a.metric("Validated decisions", validated)
        col_b.metric("Pending documents", len(queue))

    if not queue_data:
        st.info("Could not reach the API — check that the backend is running.")
    elif not queue:
        st.success("All documents screened — nothing left in the queue.")

    if not queue:
        st.stop()

    st.divider()

    # ── Navigation ────────────────────────────────────────────────────────────
    if "screening_doc_index" not in st.session_state:
        st.session_state["screening_doc_index"] = 0

    idx = min(st.session_state["screening_doc_index"], len(queue) - 1)
    current_doc = queue[idx]
    doc_id = current_doc["id"]
    pred_key = f"llm_pred_{doc_id}"

    nav_col1, nav_col2, nav_col3 = st.columns([1, 5, 1])
    with nav_col1:
        if st.button("⬅️ Prev", disabled=idx == 0):
            st.session_state["screening_doc_index"] = idx - 1
            st.rerun()
    with nav_col3:
        if st.button("Next ➡️", disabled=idx >= len(queue) - 1):
            st.session_state["screening_doc_index"] = idx + 1
            st.rerun()
    nav_col2.caption(
        f"Paper **{idx + 1}** of **{len(queue)}** — ranked by uncertainty (most uncertain first)"
    )

    st.divider()

    # ── Auto-predict if not cached ─────────────────────────────────────────────
    if pred_key not in st.session_state:
        with st.spinner("Getting LLM prediction with few-shot examples from decision memory…"):
            try:
                pr = httpx.post(
                    f"{API_BASE}/projects/{project_id}/screening/{doc_id}/llm-predict",
                    timeout=60,
                )
                pr.raise_for_status()
                st.session_state[pred_key] = pr.json()
            except Exception as e:
                st.session_state[pred_key] = {
                    "label": "unknown",
                    "confidence": 0.5,
                    "reasoning": f"Prediction unavailable: {e}",
                    "parse_error": True,
                }

    pred = st.session_state[pred_key]

    # ── Parse document content ────────────────────────────────────────────────
    raw_content = current_doc.get("content", "")
    parsed = _parse_doc(raw_content)
    source_id = current_doc.get("source_id", "—")

    title = parsed.get("Title", source_id)
    abstract = parsed.get("Abstract", "")
    authors = parsed.get("Authors", "")
    journal = parsed.get("Journal", "")
    year = parsed.get("Year", "")
    doi = parsed.get("DOI", "")

    # ── Two-column layout ─────────────────────────────────────────────────────
    left_col, right_col = st.columns([3, 2])

    # ── LEFT: Paper content ───────────────────────────────────────────────────
    with left_col:
        st.subheader(title[:120] + ("…" if len(title) > 120 else ""))
        meta_parts = [p for p in [
            authors[:80] + ("…" if len(authors) > 80 else ""),
            journal,
            year,
        ] if p]
        if meta_parts:
            st.caption(" · ".join(meta_parts))
        if doi:
            st.caption(f"DOI: `{doi}`")

        al_label = current_doc.get("al_label", "unknown")
        al_conf = current_doc.get("al_confidence", 0.5)
        if al_label != "unknown":
            al_icon = "✅" if al_label == "include" else "❌"
            st.caption(
                f"Active Learning pre-rank: {al_icon} {al_label.upper()} ({al_conf:.0%})"
            )

        st.markdown("---")
        if abstract:
            st.markdown(abstract)
        else:
            st.info("No abstract available in this record.")

    # ── RIGHT: Prediction + decision ──────────────────────────────────────────
    with right_col:
        pred_label = pred.get("label", "unknown")
        pred_conf = pred.get("confidence", 0.5)
        pred_reasoning = pred.get("reasoning", "")
        pred_parse_error = pred.get("parse_error", False)

        st.markdown("**🤖 LLM Assessment**")
        if pred_label != "unknown":
            st.markdown(_confidence_bar(pred_conf, pred_label), unsafe_allow_html=True)
        else:
            st.warning("Prediction unavailable")

        if pred_parse_error:
            st.caption("⚠️ LLM output could not be parsed reliably.")

        if pred_reasoning:
            with st.expander("Reasoning", expanded=True):
                st.markdown(pred_reasoning)

        if pred.get("guidance_applied"):
            st.caption("✓ Project-specific reviewer preferences applied.")

        examples = pred.get("similar_examples", [])
        if examples:
            with st.expander(f"📚 {len(examples)} similar validated examples"):
                for ex in examples:
                    lbl = ex.get("human_label", "?").upper()
                    icon = "✅" if lbl == "INCLUDE" else "❌"
                    reason = ex.get("human_reason") or REASON_LABELS.get(
                        ex.get("reason_code", ""), ""
                    )
                    sim = ex.get("similarity", 0)
                    st.markdown(
                        f"{icon} **{lbl}** — sim {sim:.3f}  ·  {ex.get('source_id', '')[:30]}"
                    )
                    if reason:
                        st.caption(f"Reason: {reason}")
                    preview = ex.get("preview", "")
                    if preview:
                        st.text(preview[:180])
                    st.divider()

        if st.button("🔄 Re-predict", key=f"repred_{doc_id}"):
            del st.session_state[pred_key]
            st.rerun()

        st.markdown("---")
        st.markdown("**✍️ Your Decision**")

        # Quick-decision buttons — one click to include or exclude and auto-advance
        q_col1, q_col2 = st.columns(2)
        include_clicked = q_col1.button(
            "✅ Include", key=f"inc_{doc_id}", type="primary", use_container_width=True
        )
        exclude_clicked = q_col2.button(
            "❌ Exclude", key=f"exc_{doc_id}", type="secondary", use_container_width=True
        )

        # Optional annotation expander
        with st.expander("+ Add reason code / note"):
            reason_options = ["(none)"] + REASON_CODES
            default_rc = pred.get("reason_code") or "(none)"
            rc_index = (
                reason_options.index(default_rc)
                if default_rc in reason_options
                else 0
            )
            reason_code_raw = st.selectbox(
                "Reason code",
                reason_options,
                index=rc_index,
                format_func=lambda x: REASON_LABELS.get(x, x),
                key=f"rc_{doc_id}",
            )
            detail_reason = st.text_area(
                "Free-text note",
                placeholder="e.g. Greenhouse experiment only, no field validation.",
                key=f"reason_{doc_id}",
                height=80,
            )
            reviewer = st.text_input("Reviewer ID (optional)", key=f"rev_{doc_id}")

        # Handle quick-decision clicks — read optional fields from session state
        if include_clicked or exclude_clicked:
            decision = "include" if include_clicked else "exclude"
            rc_val = st.session_state.get(f"rc_{doc_id}", "(none)")
            reason_code = None if rc_val == "(none)" else rc_val
            dr_text = st.session_state.get(f"reason_{doc_id}") or None
            rv = st.session_state.get(f"rev_{doc_id}") or None

            saved = _save_decision(
                project_id, doc_id, decision, pred,
                reason_code=reason_code,
                human_reason=dr_text,
                reviewer=rv,
            )
            if saved:
                st.session_state.pop(pred_key, None)
                # Auto-advance: queue will shrink by 1, stay at same index
                next_idx = min(idx, max(0, len(queue) - 2))
                st.session_state["screening_doc_index"] = next_idx
                st.cache_data.clear()
                icon = "✅" if decision == "include" else "❌"
                st.toast(f"{icon} {decision.upper()} saved", icon=icon)
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# Tab 2 — Stats
# ══════════════════════════════════════════════════════════════════════════════
with tab_stats:
    try:
        sr = httpx.get(f"{API_BASE}/projects/{project_id}/screening/stats", timeout=15)
        sr.raise_for_status()
        stats = sr.json()
    except Exception as e:
        st.error(f"Could not load stats: {e}")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total documents", stats.get("total_documents", 0))
    c2.metric("Pending", stats.get("pending_documents", 0))
    c3.metric("Validated", stats.get("total_decisions", 0))
    agreement = stats.get("agreement_rate")
    c4.metric("LLM–Human agreement", f"{agreement:.1%}" if agreement is not None else "N/A")

    disagree_count = stats.get("disagreements", 0)
    st.divider()
    st.subheader(f"Disagreements: {disagree_count}")

    if stats.get("by_direction"):
        st.markdown("**By direction (LLM → Human):**")
        for row in stats["by_direction"]:
            llm_icon = "✅" if row["llm_label"] == "include" else "❌"
            hum_icon = "✅" if row["human_label"] == "include" else "❌"
            st.markdown(f"- LLM {llm_icon} → Human {hum_icon}: **{row['cnt']}** times")

    if stats.get("by_reason_code"):
        st.divider()
        st.markdown("**Most common reason codes in disagreements:**")
        for row in stats["by_reason_code"]:
            label = REASON_LABELS.get(row["reason_code"], row["reason_code"])
            st.markdown(f"- {label}: **{row['cnt']}**")

    total_decisions = stats.get("total_decisions", 0)
    if total_decisions >= 5:
        st.divider()
        st.info(
            f"You have **{total_decisions}** validated decisions. "
            "Consider re-running analysis on **Page 3 — Research** to refine criteria."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Tab 3 — Learned Preferences
# ══════════════════════════════════════════════════════════════════════════════
with tab_prefs:
    try:
        pr = httpx.get(
            f"{API_BASE}/projects/{project_id}/screening/preferences", timeout=15
        )
        pr.raise_for_status()
        pref_data = pr.json()
    except Exception as e:
        st.error(f"Could not load preferences: {e}")
        st.stop()

    guidance = pref_data.get("guidance_text", "")
    prefs = pref_data.get("preferences", [])

    if guidance:
        st.subheader("Auto-generated prompt guidance")
        st.info(guidance)
        st.caption("This text is automatically appended to LLM screening prompts.")
    else:
        st.info(
            "No strong preferences detected yet. After a few consistent decisions "
            "(same reason code ≥3 times), patterns will appear here and be injected into future prompts."
        )

    if prefs:
        st.divider()
        st.subheader("Detected patterns")
        for p in prefs:
            label_icon = "✅" if p["label"] == "include" else "❌"
            rc = REASON_LABELS.get(p["reason_code"], p["reason_code"])
            st.markdown(f"{label_icon} **{rc}** — observed **{p['count']}** times")
            st.caption(p["observation"])
