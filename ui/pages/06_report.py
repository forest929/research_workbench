"""Page 6: View and download the verified criteria report."""

import os
import sys
import httpx
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ui.components.sidebar import render_sidebar

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("6️⃣ Report — Verified Criteria Artifact")

project_id = render_sidebar()
if not project_id:
    st.warning("No projects yet. Visit **Onboarding** to create one.")
    st.stop()

if st.button("🔄 Refresh Report"):
    st.rerun()

try:
    r = httpx.get(f"{API_BASE}/projects/{project_id}/report", timeout=30)
    if r.status_code == 200:
        report_md = r.text
        st.download_button(
            label="⬇️ Download Markdown Report",
            data=report_md,
            file_name=f"portfolio_report_{project_id[:8]}.md",
            mime="text/markdown",
        )
        st.divider()
        st.markdown(report_md)
    else:
        st.error(f"Could not fetch report: HTTP {r.status_code}")
except Exception as e:
    st.error(f"Report fetch failed: {e}")
    st.info("Make sure the API server is running and the project has been analyzed.")
