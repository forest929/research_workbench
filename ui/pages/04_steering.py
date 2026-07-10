"""Page 4: Human-in-the-Loop steering — label prototypes, set Gold Values."""

import os
import sys
import httpx
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ui.components.sidebar import render_sidebar

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("4️⃣ Steering — Human-in-the-Loop")

project_id = render_sidebar()
if not project_id:
    st.warning("No projects yet. Visit **Onboarding** to create one.")
    st.stop()

st.markdown(
    "Label prototype samples to create **Gold Values** — hard constraints that agents "
    "cannot override in subsequent analysis runs."
)

# Show existing criteria to allow direct Gold Value marking
st.subheader("Mark Existing Criteria as Gold Values")
try:
    r = httpx.get(f"{API_BASE}/projects/{project_id}/criteria", timeout=10)
    criteria = r.json() if r.status_code == 200 else []
except Exception:
    criteria = []

if criteria:
    for c in criteria:
        is_gold = c.get("is_gold", False)
        gold_label = " 🔒" if is_gold else ""
        ctype = c["criterion_type"].upper()
        with st.expander(f"[{ctype}]{gold_label} {c['statement'][:70]}"):
            st.markdown(f"**Rationale:** {c.get('rationale', '')}")
            st.markdown(f"**Sources:** {', '.join(c.get('source_ids', []))}")

            # ── Edit statement ────────────────────────────────────────────
            new_stmt = st.text_area(
                "Statement (edit to change):",
                value=c["statement"],
                key=f"stmt_{c['id']}",
                height=80,
            )
            save_col, gold_col, del_col = st.columns([2, 2, 1])

            with save_col:
                if st.button("💾 Save statement", key=f"save_{c['id']}"):
                    if new_stmt.strip() and new_stmt.strip() != c["statement"]:
                        try:
                            httpx.patch(
                                f"{API_BASE}/projects/{project_id}/criteria/{c['id']}",
                                json={"statement": new_stmt.strip()},
                                timeout=10,
                            )
                            st.success("Statement updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
                    else:
                        st.info("No change detected.")

            with gold_col:
                if not is_gold:
                    note = st.text_input("Gold note:", key=f"note_{c['id']}", label_visibility="collapsed",
                                         placeholder="Analyst note (optional)")
                    if st.button("🔒 Set as Gold Value", key=f"gold_{c['id']}"):
                        try:
                            httpx.patch(
                                f"{API_BASE}/projects/{project_id}/criteria/{c['id']}",
                                json={"is_gold": True, "gold_note": note or None},
                                timeout=10,
                            )
                            st.success("Gold Value set.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")
                else:
                    st.success(f"🔒 Gold  {c.get('gold_note', '') or ''}")

            with del_col:
                if st.button("🗑️ Delete", key=f"del_{c['id']}", type="secondary"):
                    try:
                        httpx.delete(
                            f"{API_BASE}/projects/{project_id}/criteria/{c['id']}",
                            timeout=10,
                        )
                        st.success("Criterion deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")
else:
    st.info("No criteria extracted yet. Run the analysis first (Page 3).")

st.divider()
st.subheader("Label a New Text Sample")
with st.form("label_sample"):
    text_sample = st.text_area("Paste a text sample to label:", height=150)
    label = st.radio("Label", ["inclusion", "exclusion", "ambiguous"])
    note = st.text_input("Analyst note (optional)")
    is_hard = st.checkbox("Hard constraint (agents cannot override)", value=True)
    cluster_id = st.text_input("Cluster ID (optional)")
    submitted = st.form_submit_button("Submit Label")

if submitted:
    if not text_sample:
        st.error("Text sample is required.")
    else:
        try:
            r = httpx.post(
                f"{API_BASE}/projects/{project_id}/gold-labels",
                json={
                    "text_sample": text_sample,
                    "label": label,
                    "note": note or None,
                    "is_hard_constraint": is_hard,
                    "cluster_id": cluster_id or None,
                },
                timeout=10,
            )
            r.raise_for_status()
            st.success("Gold label saved.")
        except Exception as e:
            st.error(f"Failed to save label: {e}")

st.divider()
st.subheader("Existing Gold Labels")
try:
    r = httpx.get(f"{API_BASE}/projects/{project_id}/gold-labels", timeout=10)
    labels = r.json() if r.status_code == 200 else []
    for gl in labels:
        hard_tag = " 🔒" if gl.get("is_hard_constraint") else ""
        st.markdown(
            f"**[{gl['label'].upper()}]{hard_tag}** — "
            f"{gl['text_sample'][:100]} "
            f"{'— *' + gl['note'] + '*' if gl.get('note') else ''}"
        )
except Exception:
    st.info("No gold labels yet.")
