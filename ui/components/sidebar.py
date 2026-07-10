"""Shared sidebar project selector — import and call render_sidebar() at the top of each page."""

import os
import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")


def render_sidebar() -> str | None:
    """Render the project selector in the sidebar and return the active project_id.

    Sets st.session_state.project_id and calls st.rerun() if the selection changes.
    Returns the current project_id (may be None if no projects exist).
    """
    with st.sidebar:
        st.markdown("---")
        try:
            resp = httpx.get(f"{API_BASE}/projects", timeout=5)
            projects = resp.json() if resp.status_code == 200 else []
        except Exception:
            projects = []

        if not projects:
            st.caption("No projects found.")
            return st.session_state.get("project_id")

        options = {
            f"{p['name'][:30]}… ({p['id'][:8]})" if len(p["name"]) > 30
            else f"{p['name']} ({p['id'][:8]})": p["id"]
            for p in projects
        }
        current_id = st.session_state.get("project_id")
        current_label = next((k for k, v in options.items() if v == current_id), None)

        chosen = st.selectbox(
            "Active project",
            list(options.keys()),
            index=list(options.keys()).index(current_label) if current_label else 0,
            key="_global_project_select",
        )
        chosen_id = options[chosen]

        if not st.session_state.get("project_id"):
            # First visit — set and rerun so the page loads with project context
            st.session_state.project_id = chosen_id
            st.rerun()
        elif chosen_id != st.session_state.get("project_id"):
            # User explicitly switched projects
            st.session_state.project_id = chosen_id
            for k in list(st.session_state.keys()):
                if k.startswith("llm_pred_") or k in ("screening_doc_index",):
                    del st.session_state[k]
            st.rerun()

    return st.session_state.get("project_id")
