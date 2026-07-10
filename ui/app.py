"""AI Portfolio Architect — Streamlit application entry point."""

import os
import httpx
import streamlit as st

st.set_page_config(
    page_title="AI Portfolio Architect",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# ── Global project selector (sidebar) ────────────────────────────────────────
# Runs on every page render so project_id is always available in session_state.
with st.sidebar:
    st.markdown("---")
    try:
        resp = httpx.get(f"{API_BASE}/projects", timeout=5)
        projects = resp.json() if resp.status_code == 200 else []
    except Exception:
        projects = []

    if projects:
        options = {
            f"{p['name'][:32]}… ({p['id'][:8]})" if len(p['name']) > 32
            else f"{p['name']} ({p['id'][:8]})": p["id"]
            for p in projects
        }
        current_id = st.session_state.get("project_id")
        current_label = next((k for k, v in options.items() if v == current_id), None)
        chosen = st.selectbox(
            "Active project",
            list(options.keys()),
            index=list(options.keys()).index(current_label) if current_label else 0,
            key="_sidebar_project_select",
        )
        chosen_id = options[chosen]
        if chosen_id != st.session_state.get("project_id"):
            st.session_state.project_id = chosen_id
            # Clear page-local caches when project changes
            for k in list(st.session_state.keys()):
                if k.startswith("llm_pred_") or k in ("screening_doc_index",):
                    del st.session_state[k]
            st.rerun()
        elif not st.session_state.get("project_id"):
            st.session_state.project_id = chosen_id

# ── Home page content ─────────────────────────────────────────────────────────
st.title("🏗️ AI Portfolio Architect")
st.markdown(
    "Transform unstructured research text into **verified portfolio definitions** "
    "with inclusion/exclusion criteria, grounded in sources and evaluated by an LLM judge."
)

project_id = st.session_state.get("project_id")
if project_id:
    try:
        r = httpx.get(f"{API_BASE}/projects/{project_id}", timeout=5)
        if r.status_code == 200:
            p = r.json()
            st.success(
                f"**Active project:** {p['name']}  ·  state: `{p['state']}`  "
                f"·  {p['iteration_count']} iteration(s)"
            )
    except Exception:
        pass

st.info(
    "Use the sidebar to navigate between stages:\n\n"
    "1. **Onboarding** — Create a project and define the research scope\n"
    "2. **Documents** — Upload source documents\n"
    "3. **Research** — Run parallel workstreams + LLM-as-Judge\n"
    "4. **Steering** — Edit / delete criteria, set Gold Values\n"
    "5. **Discrepancy** — Analyze competing scope definitions\n"
    "6. **Report** — View and download the verified criteria report\n"
    "7. **Screening** — Human validation loop with LLM assistance and decision memory"
)
