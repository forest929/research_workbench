"""Page 1: Create project and define research scope."""

import os
import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("1️⃣ Onboarding — Define Research Scope")

if "project_id" not in st.session_state:
    st.session_state.project_id = None

# Auto-select if exactly one project exists and none is active
if not st.session_state.project_id:
    try:
        r = httpx.get(f"{API_BASE}/projects", timeout=10)
        if r.status_code == 200:
            projects = r.json()
            if len(projects) == 1:
                st.session_state.project_id = projects[0]["id"]
                st.info(f"Auto-selected the only project: **{projects[0]['name']}**  \n`{projects[0]['id']}`")
    except Exception:
        pass

with st.form("create_project"):
    st.subheader("Create a New Project")
    name = st.text_input("Project Name", placeholder="e.g., ESG Portfolio 2025")
    description = st.text_area("Description (optional)", height=80)
    scope_statement = st.text_area(
        "Scope Statement",
        height=200,
        placeholder=(
            "Describe the research scope in detail. Include:\n"
            "- What types of documents/entities are IN scope\n"
            "- What types are EXPLICITLY out of scope\n"
            "- Edge cases or grey areas\n"
            "- Any conflicting definitions from different teams"
        ),
    )
    submitted = st.form_submit_button("Create Project")

if submitted:
    if not name or not scope_statement:
        st.error("Project name and scope statement are required.")
    else:
        try:
            r = httpx.post(
                f"{API_BASE}/projects",
                json={"name": name, "description": description, "scope_statement": scope_statement},
                timeout=15,
            )
            r.raise_for_status()
            project = r.json()
            st.session_state.project_id = project["id"]
            st.success(f"Project created! ID: `{project['id']}`")
            st.json(project)
        except Exception as e:
            st.error(f"Failed to create project: {e}")

st.divider()
st.subheader("Or Select Existing Project")
try:
    r = httpx.get(f"{API_BASE}/projects", timeout=10)
    if r.status_code == 200:
        projects = r.json()
        if projects:
            options = {f"{p['name']} ({p['id'][:8]})": p["id"] for p in projects}
            current_label = next(
                (k for k, v in options.items() if v == st.session_state.project_id), None
            )
            selected = st.selectbox(
                "Existing projects",
                list(options.keys()),
                index=list(options.keys()).index(current_label) if current_label else 0,
            )
            if st.button("Select"):
                st.session_state.project_id = options[selected]
                st.success(f"Selected project: `{options[selected]}`")
except Exception:
    st.info("Start the API server to see existing projects.")

if st.session_state.project_id:
    st.info(f"**Active project:** `{st.session_state.project_id}`")
