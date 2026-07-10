"""Page 3: View analysis results and re-run workstreams + judge."""

import os
import httpx
import streamlit as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ui.components.judge_scorecard import render_scorecard
from ui.components.criterion_card import render_criterion_card
from ui.components.sidebar import render_sidebar

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("3️⃣ Research — Analysis Results")

project_id = render_sidebar()
if not project_id:
    st.warning("No projects yet. Visit **Onboarding** to create one.")
    st.stop()

# ── Project state header ──────────────────────────────────────────────────────
try:
    r = httpx.get(f"{API_BASE}/projects/{project_id}", timeout=10)
    project = r.json()
    state = project.get("state", "unknown")
    iteration = project.get("iteration_count", 0)
    name = project.get("name", "")
    # State badge — colour-coded so truncation is never an issue
    STATE_COLOURS = {
        "awaiting_review": "🟡", "complete": "🟢", "running": "🔵",
        "death_spiral": "🔴", "onboarding": "⚪", "ingesting": "🔵",
    }
    badge = STATE_COLOURS.get(state, "⚪")
    st.markdown(
        f"{badge} **{state.replace('_', ' ').title()}** &nbsp;·&nbsp; "
        f"**{iteration}** iteration(s) &nbsp;·&nbsp; {name}"
    )

    if project.get("death_spiral_reason"):
        st.error(f"**Death Spiral:** {project['death_spiral_reason']}")
        resolution = st.text_area("Resolution guidance:")
        if st.button("Resolve & Unlock"):
            r2 = httpx.post(
                f"{API_BASE}/projects/{project_id}/resolve",
                json={"resolution_guidance": resolution},
                timeout=10,
            )
            st.success("Resolved. Re-run analysis to continue.")
            st.rerun()
except Exception as e:
    st.error(f"Could not fetch project: {e}")
    st.stop()

# ── Load results from DB on every page open ───────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _load_results(pid: str):
    try:
        r = httpx.get(f"{API_BASE}/projects/{pid}/results", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

db_results = _load_results(project_id)

# Merge: session-state run result takes precedence (most recent CLI or UI run)
run_result = st.session_state.get("last_run_result")

# ── Re-run button ─────────────────────────────────────────────────────────────
st.divider()
if st.button("▶️ Re-run Analysis (All Workstreams + Judge)", type="primary"):
    _load_results.clear()
    with st.spinner("Running parallel workstreams and LLM-as-Judge..."):
        try:
            r = httpx.post(f"{API_BASE}/projects/{project_id}/run", timeout=300)
            r.raise_for_status()
            run_result = r.json()
            st.session_state["last_run_result"] = run_result
            st.success(f"Run complete — state: `{run_result.get('state_after')}`")
            st.rerun()
        except Exception as e:
            st.error(f"Run failed: {e}")

# ── Display results ───────────────────────────────────────────────────────────
# Pick the richest available source: session-state run > DB results
criteria = []
synthesis = ""
verdict = None

if run_result:
    criteria = run_result.get("criteria", [])
    synthesis = run_result.get("synthesis", "")
    verdict = run_result.get("logical_verdict") or run_result.get("structural_verdict")
elif db_results:
    criteria = db_results.get("criteria", [])
    synthesis = db_results.get("synthesis", "")
    verdict = db_results.get("latest_verdict")

if not criteria and not synthesis:
    st.info("No analysis results yet. Click **Re-run Analysis** to generate them.")
    st.stop()

# ── Judge scorecard ───────────────────────────────────────────────────────────
if verdict:
    st.divider()
    st.subheader("LLM-as-Judge Scorecard")
    render_scorecard(verdict)

# ── Synthesis ─────────────────────────────────────────────────────────────────
if synthesis:
    st.divider()
    with st.expander("📄 Literature Synthesis", expanded=True):
        st.markdown(synthesis)

# ── Criteria ─────────────────────────────────────────────────────────────────
if criteria:
    inclusion = [c for c in criteria if c.get("criterion_type") == "inclusion" or c.get("type") == "inclusion"]
    exclusion = [c for c in criteria if c.get("criterion_type") == "exclusion" or c.get("type") == "exclusion"]

    st.divider()
    st.subheader(f"Extracted Criteria ({len(criteria)} total)")

    col_in, col_ex = st.columns(2)
    with col_in:
        st.markdown(f"**Inclusion ({len(inclusion)})**")
        for c in inclusion:
            render_criterion_card(c, project_id, API_BASE)
    with col_ex:
        st.markdown(f"**Exclusion ({len(exclusion)})**")
        for c in exclusion:
            render_criterion_card(c, project_id, API_BASE)

# ── Prototype clusters ────────────────────────────────────────────────────────
if run_result:
    prototypes = run_result.get("prototypes", [])
    if prototypes:
        st.divider()
        with st.expander(f"Prototype Samples — {len(prototypes)} clusters"):
            for p in prototypes:
                st.markdown(f"**Cluster {p.get('cluster_id', '?')}** · `{p.get('source_id')}`")
                st.text(p.get("content", "")[:300])
                st.divider()

# ── Approve ───────────────────────────────────────────────────────────────────
st.divider()
if state == "awaiting_review":
    if st.button("✅ Approve Criteria & Mark Complete"):
        try:
            r = httpx.post(f"{API_BASE}/projects/{project_id}/approve", timeout=10)
            r.raise_for_status()
            st.success("Project marked COMPLETE.")
            _load_results.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Approval failed: {e}")

# ── Next step callout ─────────────────────────────────────────────────────────
if criteria:
    st.divider()
    st.markdown(
        "**Next step:** review the extracted criteria above, then head to "
        "**7️⃣ Screening** to validate individual papers with LLM assistance. "
        "Each human decision feeds back into the decision memory used for future predictions."
    )
    if st.button("➡️ Go to Screening", type="primary"):
        st.switch_page("pages/07_screening.py")
