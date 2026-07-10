"""Reusable Streamlit component: 4-dimension judge scorecard with verdict badge."""

import streamlit as st


VERDICT_STYLES = {
    "pass": ("✅ PASS", "green"),
    "fail": ("❌ FAIL", "red"),
    "death_spiral": ("⚠️ DEATH SPIRAL", "orange"),
}

DIM_LABELS = {
    "faithfulness_score": "Faithfulness / Groundedness",
    "problem_integrity_score": "Problem-Statement Integrity",
    "citation_accuracy_score": "Citation Accuracy",
    "uncertainty_score": "Transparency of Uncertainty",
}
DIM_RATIONALE_KEYS = {
    "faithfulness_score": "faithfulness_rationale",
    "problem_integrity_score": "problem_integrity_rationale",
    "citation_accuracy_score": "citation_accuracy_rationale",
    "uncertainty_score": "uncertainty_rationale",
}


def render_scorecard(verdict: dict) -> None:
    verdict_text, color = VERDICT_STYLES.get(
        verdict.get("verdict", "fail"),
        ("❓ UNKNOWN", "gray"),
    )

    st.markdown(f"### Judge Verdict: :{color}[{verdict_text}]")
    overall = verdict.get("overall_score")
    if overall is not None:
        st.metric("Overall Score", f"{overall}/5")

    col1, col2 = st.columns(2)
    dims = list(DIM_LABELS.keys())
    for i, score_key in enumerate(dims):
        col = col1 if i < 2 else col2
        with col:
            score = verdict.get(score_key)
            label = DIM_LABELS[score_key]
            rationale_key = DIM_RATIONALE_KEYS[score_key]
            rationale = verdict.get(rationale_key, "")
            if score is not None:
                delta_color = "normal" if score >= 3 else "inverse"
                st.metric(label, f"{score}/5", delta_color=delta_color)
                if rationale:
                    st.caption(rationale)

    death_reason = verdict.get("death_spiral_reason")
    if death_reason:
        st.error(f"**Death Spiral Reason:** {death_reason}")
