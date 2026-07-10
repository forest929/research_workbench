"""Page 2: Upload and ingest source documents."""

import os
import json
import urllib.request
import urllib.parse
import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.title("2️⃣ Documents — Ingest Source Material")

project_id = st.session_state.get("project_id")
if not project_id:
    st.warning("No active project. Go to **Onboarding** first.")
    st.stop()

st.info(f"Active project: `{project_id}`")

tab_paste, tab_api = st.tabs(["📋 Paste Text", "🌐 Import from OpenData API"])

# ── Tab 1: manual paste ──────────────────────────────────────────────────────
with tab_paste:
    with st.form("ingest_doc"):
        st.subheader("Add a Document")
        source_id = st.text_input(
            "Source ID (DOI, URL, or free-text label)",
            placeholder="e.g., 10.1234/example or Smith_2023_ESG_Report",
        )
        doc_type = st.selectbox("Document Type", ["paper", "scope_definition", "trial", "other"])
        content = st.text_area(
            "Document Content", height=300, placeholder="Paste the full text here."
        )
        submitted = st.form_submit_button("Ingest Document")

    if submitted:
        if not source_id or not content:
            st.error("Source ID and content are required.")
        else:
            try:
                r = httpx.post(
                    f"{API_BASE}/projects/{project_id}/documents",
                    json={"source_id": source_id, "doc_type": doc_type, "content": content},
                    timeout=30,
                )
                r.raise_for_status()
                doc = r.json()
                st.success(
                    f"Document ingested! ID: `{doc['id']}`. Embedding triggered in background."
                )
                st.json(doc)
            except Exception as e:
                st.error(f"Ingestion failed: {e}")

# ── Tab 2: OpenDataSoft API import ───────────────────────────────────────────
with tab_api:
    st.subheader("Import from OpenDataSoft API")
    st.markdown(
        "Paste the dataset page URL (e.g. from **nihr.opendatasoft.com**) and the tool "
        "will fetch all records, format them as documents, and ingest them in bulk."
    )

    dataset_url = st.text_input(
        "Dataset page URL",
        placeholder="https://nihr.opendatasoft.com/explore/assets/womens-health-curated-portfolio/view/",
        value="https://nihr.opendatasoft.com/explore/assets/womens-health-curated-portfolio/view/",
    )
    doc_type_api = st.selectbox(
        "Document type for imported records",
        ["scope_definition", "paper", "trial", "other"],
        key="api_doc_type",
    )
    max_records = st.number_input(
        "Max records to import (0 = all)", min_value=0, value=0, step=50
    )

    if st.button("Preview dataset (fetch first 3 records)"):
        api_url = _ods_api_url(dataset_url)
        if not api_url:
            st.error("Could not parse dataset URL. Make sure it is an OpenDataSoft explore URL.")
        else:
            with st.spinner("Fetching preview..."):
                try:
                    records, total = _fetch_page(api_url, limit=3, offset=0)
                    st.success(f"Dataset has **{total} total records**. Preview of first 3:")
                    for rec in records:
                        with st.expander(
                            rec.get("project_title") or rec.get("title") or str(list(rec.values())[0])[:60]
                        ):
                            st.json(rec)
                except Exception as e:
                    st.error(f"Fetch failed: {e}")

    st.divider()

    if st.button("⬇️ Import all records into project", type="primary"):
        api_url = _ods_api_url(dataset_url)
        if not api_url:
            st.error("Could not parse dataset URL.")
        else:
            progress = st.progress(0, text="Fetching records...")
            status = st.empty()

            # Fetch all records
            all_records = []
            offset = 0
            limit = 100
            try:
                while True:
                    batch, total = _fetch_page(api_url, limit=limit, offset=offset)
                    all_records.extend(batch)
                    cap = int(max_records) if max_records else total
                    done = min(len(all_records), cap)
                    progress.progress(min(done / cap, 0.4), text=f"Fetched {done}/{cap} records...")
                    if len(batch) < limit or len(all_records) >= cap:
                        break
                    offset += limit
                if max_records:
                    all_records = all_records[: int(max_records)]
            except Exception as e:
                st.error(f"Fetch failed: {e}")
                st.stop()

            total_fetched = len(all_records)
            status.info(f"Fetched {total_fetched} records. Ingesting via API...")

            # Ingest each record as a document
            success = 0
            fail = 0
            for i, rec in enumerate(all_records):
                source_id = str(
                    rec.get("project_id") or rec.get("id") or f"record_{i}"
                )
                text = _record_to_text(rec)
                try:
                    r = httpx.post(
                        f"{API_BASE}/projects/{project_id}/documents",
                        json={
                            "source_id": source_id,
                            "doc_type": doc_type_api,
                            "content": text,
                        },
                        timeout=30,
                    )
                    r.raise_for_status()
                    success += 1
                except Exception:
                    fail += 1

                pct = 0.4 + 0.6 * (i + 1) / total_fetched
                progress.progress(pct, text=f"Ingested {i+1}/{total_fetched}...")

            progress.progress(1.0, text="Done!")
            if fail:
                st.warning(f"Ingested {success} records. {fail} failed — check the API logs.")
            else:
                st.success(
                    f"✅ {success} records ingested and embedding triggered in background. "
                    "Go to **Research** to run analysis once embedding completes."
                )
            st.rerun()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ods_api_url(page_url: str) -> str | None:
    """
    Convert an OpenDataSoft explore page URL to the v2.1 records API URL.
    e.g. https://host/explore/assets/dataset-slug/view/
      →  https://host/api/explore/v2.1/catalog/datasets/dataset-slug/records
    """
    try:
        page_url = page_url.strip().rstrip("/")
        # Extract slug: last path segment before /view or the slug after /assets/
        parts = page_url.split("/")
        if "assets" in parts:
            slug = parts[parts.index("assets") + 1]
        elif "dataset" in parts:
            slug = parts[parts.index("dataset") + 1]
        else:
            # fall back: second-to-last segment
            slug = parts[-2] if parts[-1] in ("view", "export", "map", "analyze") else parts[-1]
        host = "/".join(parts[:3])  # https://host
        return f"{host}/api/explore/v2.1/catalog/datasets/{slug}/records"
    except Exception:
        return None


def _fetch_page(api_url: str, limit: int, offset: int) -> tuple[list[dict], int]:
    params = urllib.parse.urlencode({"limit": limit, "offset": offset})
    url = f"{api_url}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Portfolio-Architect/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("results", []), data.get("total_count", 0)


def _record_to_text(rec: dict) -> str:
    """Flatten a record dict into readable text for ingestion."""
    preferred = [
        "project_title", "scientific_title", "project_id", "programme", "category",
        "topic", "sub_topic", "funder", "contracted_organisation", "award_holder_name",
        "start_date", "end_date", "award_amount", "project_status",
        "plain_english_abstract", "scientific_abstract",
        "research_summary", "research_type", "disease_condition_topic",
        "age_groups_addressed", "primary_research_focus",
    ]
    parts = []
    seen = set()
    for key in preferred:
        val = rec.get(key)
        if val and str(val).strip():
            parts.append(f"{key.replace('_', ' ').title()}: {val}")
            seen.add(key)
    for key, val in rec.items():
        if key not in seen and val and str(val).strip():
            parts.append(f"{key.replace('_', ' ').title()}: {val}")
    return "\n".join(parts)


# ── Document list ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("Ingested Documents")
try:
    r = httpx.get(f"{API_BASE}/projects/{project_id}/documents", timeout=10)
    if r.status_code == 200:
        docs = r.json()
        if docs:
            embedded = sum(1 for d in docs if d["embedded"])
            st.caption(f"{len(docs)} documents — {embedded} embedded, {len(docs)-embedded} pending")
            for doc in docs:
                status = "✅" if doc["embedded"] else "⏳"
                st.markdown(
                    f"{status} **{doc['source_id']}** `{doc['doc_type']}` — "
                    f"{doc['chunk_count']} chunks"
                )
        else:
            st.info("No documents ingested yet.")
except Exception as e:
    st.error(f"Could not fetch documents: {e}")
