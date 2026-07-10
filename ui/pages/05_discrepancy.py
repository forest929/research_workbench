"""Page 5: Cross-team discrepancy analyzer."""

import os
import sys
import httpx
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ui.components.sidebar import render_sidebar

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

FRICTION_ICONS = {
    "wording": "📝",
    "evidence_interpretation": "🔬",
    "scope_boundary": "🔲",
    "contradictory": "⚡",
}

st.title("5️⃣ Discrepancy Analyzer")
st.markdown(
    "Paste two competing scope definitions. The system performs a **semantic diff** "
    "to identify logical friction — where wording, evidence interpretation, or "
    "scope boundaries conflict."
)

project_id = render_sidebar()
if not project_id:
    st.warning("No projects yet. Visit **Onboarding** to create one.")
    st.stop()

col1, col2 = st.columns(2)
with col1:
    label_a = st.text_input("Team A label", value="Team A")
    definition_a = st.text_area("Team A's Scope Definition", height=250)
with col2:
    label_b = st.text_input("Team B label", value="Team B")
    definition_b = st.text_area("Team B's Scope Definition", height=250)

if st.button("🔍 Analyze Discrepancy", type="primary"):
    if not definition_a or not definition_b:
        st.error("Both definitions are required.")
    else:
        with st.spinner("Analyzing semantic friction..."):
            try:
                r = httpx.post(
                    f"{API_BASE}/projects/{project_id}/discrepancy",
                    json={
                        "definition_a": definition_a,
                        "definition_b": definition_b,
                        "label_a": label_a,
                        "label_b": label_b,
                    },
                    timeout=120,
                )
                r.raise_for_status()
                result = r.json()
                st.session_state["discrepancy_result"] = result
            except Exception as e:
                st.error(f"Analysis failed: {e}")

result = st.session_state.get("discrepancy_result")
if result:
    st.divider()
    overlap = result.get("semantic_overlap", 0)
    st.metric("Semantic Overlap", f"{overlap:.0%}", help="Cosine similarity of scope embeddings")

    friction_points = result.get("friction_points", [])
    st.subheader(f"Friction Points ({len(friction_points)})")
    for fp in friction_points:
        icon = FRICTION_ICONS.get(fp.get("friction_type", ""), "⚠️")
        with st.expander(f"{icon} {fp.get('summary', 'Friction point')}"):
            col1, col2 = st.columns(2)
            col1.markdown(f"**{label_a}:** {fp.get('position_a', '')}")
            col2.markdown(f"**{label_b}:** {fp.get('position_b', '')}")
            st.caption(f"Type: `{fp.get('friction_type', 'unknown')}`")

    if result.get("recommendation"):
        st.subheader("Recommendation")
        st.info(result["recommendation"])
