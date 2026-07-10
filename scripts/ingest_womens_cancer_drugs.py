#!/usr/bin/env python3
"""
Ingest drug-therapy evidence for core women's cancers — breast, ovarian,
cervical, and endometrial/uterine cancer — into the AI Portfolio Architect
platform.

This is Phase 1 of a LoRA training-data pipeline: it builds the raw corpus
only. Claim extraction and "conversation" assembly for fine-tuning are a
separate, later step.

This script handles data ingestion and embedding ONLY.
LLM analysis (criteria extraction, judge) is triggered separately via:
  - UI: Page 3 Research → Re-run Analysis
  - API: POST /projects/{id}/run

Sources:
  - PubMed          (NCBI E-utilities, free, no key required for <3 req/s)
  - ClinicalTrials.gov (API v2, free, no auth) — trial registrations carry
    structured intervention/comparator/outcome data, useful for the later
    claim-extraction phase.

Raw API responses are cached to disk under data/raw_cache/ so re-runs do not
re-hit the network.

Usage:
    python scripts/ingest_womens_cancer_drugs.py [--max-records N]

Options:
    --max-records N      Cap total records ingested (default: 3000)
    --pubmed-only        Only fetch from PubMed
    --ctgov-only         Only fetch from ClinicalTrials.gov
    --no-embed           Skip embedding (useful for offline testing / cost safety)
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations
from portfolio_architect.db.projects import insert_project
from portfolio_architect.db.documents import (
    insert_document,
    insert_chunks,
    update_chunk_embedding,
)
from portfolio_architect.embedding.client import embed_batch
from portfolio_architect.ingestion.chunker import chunk_text as _chunk_text  # shared utility

# ── Config ───────────────────────────────────────────────────────────────────
BATCH_SIZE = 64          # embedding batch size
CHUNK_SIZE = 900         # chars per chunk (passed to shared chunker)
CHUNK_OVERLAP = 100      # overlap between chunks
NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")  # optional; increases rate limit

# Rate limiting
PUBMED_DELAY = 0.35 if not NCBI_API_KEY else 0.12   # seconds between NCBI calls
CTGOV_DELAY = 0.3                                     # polite delay between CT.gov pages

# Raw response cache — avoids re-hitting the network on re-runs
CACHE_DIR = Path(__file__).parent.parent / "data" / "raw_cache"
PUBMED_CACHE_DIR = CACHE_DIR / "pubmed"
CTGOV_CACHE_DIR = CACHE_DIR / "ctgov"

# Core women's cancers, drug/regimen-treatment focused (chemo, hormone/
# endocrine therapy, targeted therapy, immunotherapy). Primary window: last
# ~7 years. A second, no-date-filter pass over landmark drug/trial terms
# below pulls in foundational papers regardless of age.
CANCER_TERMS = (
    '"breast cancer"[Title/Abstract] OR "breast neoplasms"[Title/Abstract] OR '
    '"ovarian cancer"[Title/Abstract] OR "ovarian neoplasms"[Title/Abstract] OR '
    '"cervical cancer"[Title/Abstract] OR "cervical neoplasms"[Title/Abstract] OR '
    '"endometrial cancer"[Title/Abstract] OR "endometrial neoplasms"[Title/Abstract] OR '
    '"uterine cancer"[Title/Abstract]'
)
DRUG_TERMS = (
    '"chemotherapy"[Title/Abstract] OR "hormone therapy"[Title/Abstract] OR '
    '"endocrine therapy"[Title/Abstract] OR "targeted therapy"[Title/Abstract] OR '
    '"immunotherapy"[Title/Abstract] OR "immune checkpoint inhibitor"[Title/Abstract] OR '
    '"PARP inhibitor"[Title/Abstract] OR "CDK4/6 inhibitor"[Title/Abstract] OR '
    '"antibody-drug conjugate"[Title/Abstract] OR "HER2-targeted"[Title/Abstract] OR '
    '"tamoxifen"[Title/Abstract] OR "trastuzumab"[Title/Abstract] OR '
    '"pembrolizumab"[Title/Abstract] OR "olaparib"[Title/Abstract] OR '
    '"bevacizumab"[Title/Abstract] OR "aromatase inhibitor"[Title/Abstract]'
)
# Recency window: the past 3 years (computed from the current year), so the
# corpus reflects current drug-therapy evidence rather than a fixed ceiling.
PUBMED_START = f"{time.gmtime().tm_year - 3}/01/01"
PUBMED_QUERY = (
    f'({CANCER_TERMS}) AND ({DRUG_TERMS}) AND '
    f'("{PUBMED_START}"[Date - Publication] : "3000"[Date - Publication])'
)

# Landmark / practice-changing drug-trial search terms — no date filter, so
# foundational evidence isn't excluded purely for being older than 7 years.
LANDMARK_SEARCHES = [
    "tamoxifen adjuvant breast cancer randomized trial",
    "trastuzumab HER2 breast cancer pivotal trial",
    "olaparib PARP inhibitor ovarian cancer maintenance",
    "bevacizumab cervical cancer randomized trial",
    "pembrolizumab endometrial cancer trial",
    "CDK4/6 inhibitor palbociclib ribociclib abemaciclib metastatic breast cancer",
    "trastuzumab deruxtecan HER2 low breast cancer",
    "aromatase inhibitor letrozole anastrozole breast cancer trial",
]
LANDMARK_MAX_PER_SEARCH = 40

# ClinicalTrials.gov conditions — interventional drug/regimen studies only
CTGOV_CONDITIONS = [
    "breast cancer",
    "ovarian cancer",
    "cervical cancer",
    "endometrial cancer",
]

PROJECT_NAME = "Women's Cancer Drug Evidence — Breast, Ovarian, Cervical, Endometrial"
PROJECT_DESCRIPTION = (
    "A literature + trial-registry corpus of drug-therapy evidence for core women's "
    "cancers (breast, ovarian, cervical, endometrial/uterine), covering chemotherapy, "
    "hormone/endocrine therapy, targeted therapy (HER2-targeted agents, PARP inhibitors, "
    "CDK4/6 inhibitors, antibody-drug conjugates), and immunotherapy (immune checkpoint "
    "inhibitors). Built as raw source material for a later claim-extraction / LoRA "
    "fine-tuning data pipeline — this ingest step covers data collection only."
)
PROJECT_SCOPE = (
    "What is the drug/regimen evidence for treating breast, ovarian, cervical, and "
    "endometrial cancer? For each drug or combination, what is the evidence of efficacy "
    "against which population, compared to which comparator, on which outcome — and "
    "where is that evidence strong, contested, or absent?"
)

# ── Utilities ────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3) -> bytes:
    """Fetch URL with retries and exponential backoff."""
    headers = {"User-Agent": "AI-Portfolio-Architect/1.0 (research; contact kexinwang929@gmail.com)"}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = 2 ** attempt * 5
                print(f"  HTTP {e.code} — retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Failed after {retries} retries: {url}")


def _cached_get(url: str, cache_dir: Path) -> bytes:
    """Fetch URL, transparently caching the raw response to disk by URL hash."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:24]
    cache_file = cache_dir / f"{key}.bin"
    if cache_file.exists():
        return cache_file.read_bytes()
    data = _get(url)
    cache_file.write_bytes(data)
    return data


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Delegates to the shared chunker in portfolio_architect.ingestion."""
    return _chunk_text(text, size=size, overlap=overlap)


def record_to_text(rec: dict) -> str:
    parts = [f"Title: {rec['title']}"]
    if rec.get("authors"):
        parts.append(f"Authors: {rec['authors']}")
    if rec.get("journal"):
        parts.append(f"Journal: {rec['journal']}")
    if rec.get("year"):
        parts.append(f"Year: {rec['year']}")
    if rec.get("doi"):
        parts.append(f"DOI: {rec['doi']}")
    if rec.get("conditions"):
        parts.append(f"Conditions: {rec['conditions']}")
    if rec.get("interventions"):
        parts.append(f"Interventions: {rec['interventions']}")
    if rec.get("phase"):
        parts.append(f"Phase: {rec['phase']}")
    if rec.get("status"):
        parts.append(f"Status: {rec['status']}")
    if rec.get("primary_outcome"):
        parts.append(f"Primary Outcome: {rec['primary_outcome']}")
    if rec.get("abstract"):
        parts.append(f"Abstract: {rec['abstract']}")
    return "\n".join(parts)


def deduplicate(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in records:
        sid = r["source_id"]
        if sid not in seen:
            seen.add(sid)
            out.append(r)
    return out


def cap_proportionally(records: list[dict], max_records: int) -> list[dict]:
    """Cap total records while preserving each source's share, so a flat
    list-order slice doesn't disproportionately cut whichever source was
    appended last (e.g. ClinicalTrials.gov, appended after PubMed)."""
    if len(records) <= max_records:
        return records
    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)
    out: list[dict] = []
    for src, recs in by_source.items():
        share = round(max_records * len(recs) / len(records))
        out.extend(recs[:share])
    return out[:max_records]


# ── PubMed ───────────────────────────────────────────────────────────────────

def pubmed_search(query: str, max_records: int, sort: str | None = None) -> list[str]:
    """Return PubMed IDs for the query, up to max_records. esearch caps a single
    page at 9,999, so we paginate with retstart to reach larger caps. `sort`
    (e.g. "pub_date") orders results — used to take the most-recent papers when
    the cap is below the total hit count."""
    ids: list[str] = []
    printed_total = False
    while len(ids) < max_records:
        page = min(9999, max_records - len(ids))
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": page,
            "retstart": len(ids),
            "retmode": "json",
            "usehistory": "y",
        }
        if sort:
            params["sort"] = sort
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY
        url = f"{NCBI_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
        # esearch responses are small and index-order can drift; fetch fresh
        # (not via the on-disk cache, which previously stored a corrupt page and
        # crashed the whole search). Skip a bad page instead of aborting.
        try:
            data = json.loads(_get(url))
        except Exception as e:
            print(f"  esearch page at retstart={len(ids)} failed ({e}); stopping pagination")
            break
        result = data.get("esearchresult", {})
        batch = result.get("idlist", [])
        if not printed_total:
            print(f"  PubMed: {int(result.get('count', 0))} total hits, fetching up to {max_records} IDs")
            printed_total = True
        if not batch:
            break
        ids.extend(batch)
        if len(batch) < page:
            break
    return ids[:max_records]


def pubmed_fetch_abstracts(pmids: list[str]) -> list[dict]:
    """Fetch abstracts for a list of PubMed IDs in batches of 200."""
    records = []
    batch_size = 200
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if NCBI_API_KEY:
            params["api_key"] = NCBI_API_KEY
        url = f"{NCBI_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
        cache_key = hashlib.sha256(url.encode()).hexdigest()[:24]
        cache_file = PUBMED_CACHE_DIR / f"{cache_key}.bin"
        if not cache_file.exists():
            time.sleep(PUBMED_DELAY)
        xml_bytes = _cached_get(url, PUBMED_CACHE_DIR)

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            continue

        for article in root.findall(".//PubmedArticle"):
            rec = _parse_pubmed_article(article)
            if rec:
                records.append(rec)

        print(f"  PubMed fetch: {min(i + batch_size, len(pmids))}/{len(pmids)}", end="\r")

    print()
    return records


def _parse_pubmed_article(article: ET.Element) -> dict | None:
    """Extract fields from a PubmedArticle XML element."""
    medline = article.find("MedlineCitation")
    if medline is None:
        return None

    art = medline.find("Article")
    if art is None:
        return None

    pmid_el = medline.find("PMID")
    pmid = pmid_el.text if pmid_el is not None else "unknown"

    title_el = art.find("ArticleTitle")
    title = ("".join(title_el.itertext()) if title_el is not None else "").strip()

    abstract_parts = []
    for ab in art.findall(".//AbstractText"):
        label = ab.get("Label", "")
        text = "".join(ab.itertext()).strip()
        if label:
            abstract_parts.append(f"{label}: {text}")
        else:
            abstract_parts.append(text)
    abstract = " ".join(abstract_parts).strip()

    if not title and not abstract:
        return None

    authors = []
    for author in art.findall(".//Author"):
        last = author.findtext("LastName", "")
        fore = author.findtext("ForeName", "") or author.findtext("Initials", "")
        if last:
            authors.append(f"{last} {fore}".strip())
    author_str = ", ".join(authors[:5])
    if len(authors) > 5:
        author_str += " et al."

    journal = art.findtext(".//Title", "").strip()
    pub_date = art.find(".//PubDate")
    year = ""
    if pub_date is not None:
        year = pub_date.findtext("Year", "") or (pub_date.findtext("MedlineDate", "") or "")[:4]

    doi = ""
    for id_el in article.findall(".//ArticleId"):
        if id_el.get("IdType") == "doi":
            doi = id_el.text or ""
            break

    return {
        "source": "pubmed",
        "source_id": f"pmid:{pmid}",
        "doc_type": "paper",
        "title": title,
        "abstract": abstract,
        "authors": author_str,
        "journal": journal,
        "year": year,
        "doi": doi,
    }


# ── ClinicalTrials.gov (API v2) ──────────────────────────────────────────────

def ctgov_fetch_studies(condition: str, max_records: int) -> list[dict]:
    """Fetch interventional drug/regimen trial records for a condition from CT.gov v2."""
    records: list[dict] = []
    page_token = None
    page_size = 100

    while len(records) < max_records:
        params = {
            "query.cond": condition,
            "filter.overallStatus": "COMPLETED,RECRUITING,ACTIVE_NOT_RECRUITING",
            "pageSize": min(page_size, max_records - len(records)),
            "fields": ",".join([
                "NCTId", "BriefTitle", "OfficialTitle", "Condition",
                "InterventionName", "InterventionType", "Phase", "OverallStatus",
                "PrimaryOutcomeMeasure", "StudyType", "StartDate",
                "LeadSponsorName", "BriefSummary",
            ]),
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"{CTGOV_BASE}?{urllib.parse.urlencode(params)}"
        try:
            raw = _cached_get(url, CTGOV_CACHE_DIR)
        except Exception as e:
            print(f"  CT.gov error ({condition!r}): {e}")
            break
        time.sleep(CTGOV_DELAY)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            break

        studies = data.get("studies", [])
        if not studies:
            break
        # Only fetch interventional (drug trial) studies — skip observational
        for study in studies:
            rec = _parse_ctgov_study(study)
            if rec and rec.get("study_type", "").upper() == "INTERVENTIONAL":
                records.append(rec)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return records


def _parse_ctgov_study(study: dict) -> dict | None:
    proto = study.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    design_mod = proto.get("designModule", {})
    cond_mod = proto.get("conditionsModule", {})
    arms_mod = proto.get("armsInterventionsModule", {})
    outcomes_mod = proto.get("outcomesModule", {})
    sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
    desc_mod = proto.get("descriptionModule", {})

    nct_id = ident.get("nctId")
    title = ident.get("briefTitle") or ident.get("officialTitle") or ""
    if not nct_id or not title:
        return None

    conditions = ", ".join(cond_mod.get("conditions", []) or [])

    interventions = []
    for iv in arms_mod.get("interventions", []) or []:
        name = iv.get("name", "")
        itype = iv.get("type", "")
        if name:
            interventions.append(f"{name} ({itype})" if itype else name)
    intervention_str = ", ".join(interventions)

    primary_outcomes = [
        po.get("measure", "") for po in outcomes_mod.get("primaryOutcomes", []) or []
    ]
    primary_outcome_str = "; ".join(filter(None, primary_outcomes))

    phases = design_mod.get("phases", []) or []
    phase_str = ", ".join(phases)
    study_type = design_mod.get("studyType", "")
    status = status_mod.get("overallStatus", "")
    sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")
    start_date = status_mod.get("startDateStruct", {}).get("date", "")
    year = start_date[:4] if start_date else ""
    abstract = desc_mod.get("briefSummary", "")

    return {
        "source": "clinicaltrials.gov",
        "source_id": f"nct:{nct_id}",
        "doc_type": "trial",
        "title": title,
        "abstract": abstract,
        "authors": sponsor,
        "journal": "ClinicalTrials.gov",
        "year": year,
        "doi": "",
        "conditions": conditions,
        "interventions": intervention_str,
        "phase": phase_str,
        "status": status,
        "primary_outcome": primary_outcome_str,
        "study_type": study_type,
    }


# ── Embedding ─────────────────────────────────────────────────────────────────

async def embed_project_chunks(pool, project_id):
    async with pool.acquire() as conn:
        unembedded = await conn.fetch(
            """SELECT c.id, c.document_id, c.content
               FROM chunks c
               WHERE c.project_id = ? AND c.embedding IS NULL
               ORDER BY c.created_at""",
            str(project_id),
        )

    if not unembedded:
        print("  No unembedded chunks.")
        return

    print(f"  Embedding {len(unembedded)} chunks in batches of {BATCH_SIZE}...")
    total = 0
    doc_ids: set[str] = set()

    for i in range(0, len(unembedded), BATCH_SIZE):
        batch = unembedded[i : i + BATCH_SIZE]
        texts = [r["content"] for r in batch]
        embeddings = await embed_batch(texts)

        async with pool.acquire() as conn:
            for row, emb in zip(batch, embeddings):
                await update_chunk_embedding(conn, row["id"], emb)
                doc_ids.add(row["document_id"])

        total += len(batch)
        print(f"  Embedded {total}/{len(unembedded)}...", end="\r")

    async with pool.acquire() as conn:
        for doc_id in doc_ids:
            await conn.execute(
                "UPDATE documents SET embedded = 1 WHERE id = ?", doc_id
            )

    print(f"\n  Embedded {total} chunks across {len(doc_ids)} documents.")


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(args) -> None:
    max_records = args.max_records
    do_embed = not args.no_embed

    print("=" * 65)
    print("  Women's Cancer Drug Evidence Ingestion — AI Portfolio Architect")
    print("=" * 65)

    print("\n2. Initialising database...")
    pool = await create_pool()
    await run_migrations(pool)
    print("  DB ready.")

    # ── Resume check: skip ingestion if project already exists ────────────
    project_id: str | None = None
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM projects WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            PROJECT_NAME,
        )
    if existing:
        project_id = existing["id"]
        async with pool.acquire() as conn:
            stats = await conn.fetchrow(
                """SELECT
                   (SELECT COUNT(*) FROM documents WHERE project_id = ?) AS docs,
                   (SELECT COUNT(*) FROM chunks   WHERE project_id = ? AND embedding IS NULL) AS unembedded""",
                project_id, project_id,
            )
        docs = stats["docs"] if stats else 0
        unembedded = stats["unembedded"] if stats else 0
        print(f"\n  Existing project found: {project_id}")
        print(f"  Documents: {docs}  |  Unembedded chunks: {unembedded}")
        if args.append:
            print("  --append: fetching + ingesting NEW records into this project "
                  "(existing docs are skipped via ON CONFLICT).")
        else:
            print("  Skipping fetch + ingest — resuming from embedding step.")

    if project_id is None or args.append:
        # ── 1. Collect records ────────────────────────────────────────────
        all_records: list[dict] = []

        if not args.ctgov_only:
            print(f"\n1a. Fetching PubMed records (since {PUBMED_START}, most recent first)...")
            pubmed_max = max_records if args.pubmed_only else int(max_records * 0.6)
            try:
                pmids = pubmed_search(PUBMED_QUERY, pubmed_max, sort="pub_date")
                if pmids:
                    pm_records = pubmed_fetch_abstracts(pmids)
                    print(f"  Got {len(pm_records)} PubMed records")
                    all_records.extend(pm_records)
            except Exception as e:
                print(f"  PubMed fetch failed: {e}")

            print("\n1b. Fetching PubMed landmark records (no date filter)...")
            for term in LANDMARK_SEARCHES:
                try:
                    pmids = pubmed_search(term, LANDMARK_MAX_PER_SEARCH)
                    if pmids:
                        recs = pubmed_fetch_abstracts(pmids)
                        print(f"  Landmark [{term[:50]}]: {len(recs)} records")
                        all_records.extend(recs)
                except Exception as e:
                    print(f"  Landmark search error ({term!r}): {e}")

        if not args.pubmed_only:
            print("\n1c. Fetching ClinicalTrials.gov records...")
            ctgov_max_per = max(50, (max_records - len(all_records)) // len(CTGOV_CONDITIONS))
            for cond in CTGOV_CONDITIONS:
                try:
                    recs = ctgov_fetch_studies(cond, ctgov_max_per)
                    print(f"  CT.gov [{cond}]: {len(recs)} records")
                    all_records.extend(recs)
                except Exception as e:
                    print(f"  CT.gov error ({cond}): {e}")

        all_records = deduplicate(all_records)
        all_records = cap_proportionally(all_records, max_records)

        if not all_records:
            print("\nNo records fetched. Check network access and API availability.")
            sys.exit(1)

        print(f"\nTotal unique records: {len(all_records)}")
        src_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for r in all_records:
            src_counts[r["source"]] = src_counts.get(r["source"], 0) + 1
            type_counts[r["doc_type"]] = type_counts.get(r["doc_type"], 0) + 1
        for src, n in src_counts.items():
            print(f"  source={src}: {n}")
        for dt, n in type_counts.items():
            print(f"  doc_type={dt}: {n}")

        # ── 3. Create project (only if new; --append reuses existing) ──────
        if project_id is None:
            print("\n3. Creating project...")
            async with pool.acquire() as conn:
                project = await insert_project(
                    conn,
                    name=PROJECT_NAME,
                    description=PROJECT_DESCRIPTION,
                    scope_statement=PROJECT_SCOPE,
                )
            project_id = project["id"]
            print(f"  Project ID: {project_id}")
        else:
            print(f"\n3. Appending to existing project {project_id}")

        # ── 4. Ingest records as documents + chunks ───────────────────────
        print(f"\n4. Ingesting {len(all_records)} records...")
        async with pool.acquire() as conn:
            new_docs = 0
            for idx, rec in enumerate(all_records):
                raw_text = record_to_text(rec)
                chunks = chunk_text(raw_text)
                if not chunks:
                    continue
                doc = await insert_document(
                    conn, project_id, rec["source_id"], raw_text, doc_type=rec["doc_type"]
                )
                # Skip chunk insertion when the document already exists (ON CONFLICT
                # returned the pre-existing row) — otherwise --append re-inserts
                # duplicate chunks for every overlapping paper.
                already = await conn.fetchrow(
                    "SELECT 1 FROM chunks WHERE document_id = ? LIMIT 1", doc["id"]
                )
                if already:
                    continue
                await insert_chunks(conn, doc["id"], project_id, chunks)
                new_docs += 1
                if (idx + 1) % 100 == 0:
                    print(f"  Ingested {idx + 1}/{len(all_records)} ({new_docs} new)...", end="\r")
            print(f"\n  New documents added: {new_docs}")
        print(f"\n  Ingested {len(all_records)} records.")

    # ── 5. Embed ──────────────────────────────────────────────────────────
    if do_embed:
        print("\n5. Embedding chunks via Nebius AI endpoint...")
        try:
            await embed_project_chunks(pool, project_id)
        except Exception as e:
            msg = str(e)
            is_conn_err = (
                "NEBIUS_EMBEDDING_URL" in msg
                or "nodename nor servname" in msg
                or "Connection error" in msg
                or "ConnectError" in type(e).__name__
            )
            is_model_err = "NotFoundError" in type(e).__name__ or "does not exist" in msg
            if is_conn_err:
                print("  Embedding endpoint unreachable — skipping.")
                print(f"  Cause: {type(e).__name__}: {msg[:120]}")
                print("  Check NEBIUS_EMBEDDING_URL in .env and that the endpoint is running.")
            elif is_model_err:
                print("  Embedding model not found on endpoint — skipping.")
                print(f"  Cause: {msg[:160]}")
                print("  Set EMBEDDING_MODEL in .env to match the model your endpoint serves.")
            else:
                raise
            print("  Vector search will fall back to keyword-only until chunks are embedded.")
    else:
        print("\n5. Skipping embedding (--no-embed).")

    # ── 6. Ingestion complete — trigger analysis separately ───────────────
    print(f"\n✅ Ingestion complete. Project ID: {project_id}")
    print("\nNext step — trigger LLM analysis via one of:")
    print(f"  • UI:  open http://localhost:8501 → Page 3 Research → Re-run Analysis")
    print(f"  • API: curl -X POST http://localhost:8000/projects/{project_id}/run")

    print("\n" + "=" * 65)
    print(f"Project ID : {project_id}")
    print(f"UI         : http://localhost:8501")
    print("=" * 65)

    await close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest women's cancer drug-therapy evidence into AI Portfolio Architect"
    )
    parser.add_argument("--max-records", type=int, default=3000, metavar="N",
                        help="Cap total records (default: 3000)")
    parser.add_argument("--pubmed-only", action="store_true",
                        help="Only fetch from PubMed")
    parser.add_argument("--ctgov-only", action="store_true",
                        help="Only fetch from ClinicalTrials.gov")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip embedding step")
    parser.add_argument("--append", action="store_true",
                        help="Fetch + ingest NEW records into the existing project "
                             "(instead of skipping when it already exists)")
    args = parser.parse_args()

    asyncio.run(main(args))
