#!/usr/bin/env python3
"""
Ingest global warming / climate change research papers from PubMed and arXiv
into the AI Portfolio Architect platform.

This script handles data ingestion and embedding ONLY.
LLM analysis (criteria extraction, judge) is triggered separately via:
  - UI: Page 3 Research → Re-run Analysis
  - API: POST /projects/{id}/run

Sources:
  - PubMed  (NCBI E-utilities, free, no key required for <3 req/s)
  - arXiv   (REST API, free, no auth)

Usage:
    python scripts/ingest_global_warming.py [--max-records N]

Options:
    --max-records N      Cap total records ingested (default: 2000)
    --pubmed-only        Only fetch from PubMed
    --arxiv-only         Only fetch from arXiv
    --no-embed           Skip embedding (useful for offline testing)
"""

import argparse
import asyncio
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
ARXIV_BASE = "https://export.arxiv.org/api/query"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")  # optional; increases rate limit

# Rate limiting
PUBMED_DELAY = 0.35 if not NCBI_API_KEY else 0.12   # seconds between NCBI calls
ARXIV_DELAY = 3.0                                     # arXiv asks for 3 s delay

# Search terms
PUBMED_QUERY = (
    '("global warming"[Title/Abstract] OR "climate change"[Title/Abstract] OR '
    '"greenhouse gas"[Title/Abstract] OR "carbon dioxide emissions"[Title/Abstract] OR '
    '"sea level rise"[Title/Abstract] OR "Arctic ice"[Title/Abstract] OR '
    '"climate model"[Title/Abstract] OR "carbon capture"[Title/Abstract] OR '
    '"climate adaptation"[Title/Abstract] OR "climate mitigation"[Title/Abstract]) '
    'AND ("2019/01/01"[Date - Publication] : "3000"[Date - Publication])'
)

ARXIV_SEARCHES = [
    # category + keyword searches
    ("cat:physics.ao-ph", "climate change global warming"),
    ("cat:physics.geo-ph", "global warming temperature"),
    ("cat:eess.SP", "climate change prediction"),
    ("cat:q-bio.PE", "climate change ecosystem"),
    ("", "global warming sea level rise arctic"),
    ("", "carbon capture sequestration climate"),
    ("", "renewable energy climate mitigation"),
    ("", "extreme weather events global warming"),
]

PROJECT_NAME = "Global Warming Research Landscape 2019–2025"
PROJECT_DESCRIPTION = (
    "A systematic portfolio analysis of peer-reviewed and preprint research on global warming "
    "and climate change, covering: temperature trends, sea level rise, Arctic/Antarctic ice, "
    "greenhouse gas emissions, carbon capture, climate modelling, adaptation/mitigation "
    "strategies, extreme weather, and renewable energy transitions."
)
PROJECT_SCOPE = (
    "What are the major research themes, evidence bases, and emerging topics in global warming "
    "and climate change science from 2019–2025? Identify the dominant research portfolios "
    "(e.g., sea level rise, Arctic ice loss, carbon capture, climate policy, extreme weather "
    "events, renewable energy, ecosystem impacts) and characterise what evidence is strongest, "
    "what is contested, and where evidence gaps remain."
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
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Failed after {retries} retries: {url}")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Delegates to the shared chunker in portfolio_architect.ingestion."""
    return _chunk_text(text, size=size, overlap=overlap)


# ── PubMed ───────────────────────────────────────────────────────────────────

def pubmed_search(query: str, max_records: int) -> list[str]:
    """Return list of PubMed IDs for the query (up to max_records)."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": min(max_records, 9999),
        "retmode": "json",
        "usehistory": "y",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = f"{NCBI_BASE}/esearch.fcgi?{urllib.parse.urlencode(params)}"
    data = json.loads(_get(url))
    ids = data.get("esearchresult", {}).get("idlist", [])
    total = int(data.get("esearchresult", {}).get("count", 0))
    print(f"  PubMed: {total} total hits, fetching {len(ids)} IDs")
    return ids


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
        xml_bytes = _get(url)
        time.sleep(PUBMED_DELAY)

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
        year = pub_date.findtext("Year", "") or pub_date.findtext("MedlineDate", "")[:4]

    doi = ""
    for id_el in article.findall(".//ArticleId"):
        if id_el.get("IdType") == "doi":
            doi = id_el.text or ""
            break

    return {
        "source": "pubmed",
        "source_id": f"pmid:{pmid}",
        "title": title,
        "abstract": abstract,
        "authors": author_str,
        "journal": journal,
        "year": year,
        "doi": doi,
    }


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
    if rec.get("abstract"):
        parts.append(f"Abstract: {rec['abstract']}")
    return "\n".join(parts)


# ── arXiv ────────────────────────────────────────────────────────────────────

ARXIV_NS = "http://www.w3.org/2005/Atom"


def arxiv_fetch(cat: str, query: str, max_per_search: int = 200) -> list[dict]:
    """Fetch arXiv records for a category + query combination."""
    records = []
    batch = 100
    start = 0

    if cat:
        search_query = f"{cat} AND all:{query}"
    else:
        search_query = f"all:{query}"

    while start < max_per_search:
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": min(batch, max_per_search - start),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}"
        try:
            xml_bytes = _get(url)
        except Exception as e:
            print(f"  arXiv error ({cat!r}, {query!r}): {e}")
            break

        time.sleep(ARXIV_DELAY)

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            break

        entries = root.findall(f"{{{ARXIV_NS}}}entry")
        if not entries:
            break

        for entry in entries:
            rec = _parse_arxiv_entry(entry)
            if rec:
                records.append(rec)

        start += len(entries)
        if len(entries) < batch:
            break

    return records


def _parse_arxiv_entry(entry: ET.Element) -> dict | None:
    ns = ARXIV_NS

    arxiv_id_el = entry.find(f"{{{ns}}}id")
    if arxiv_id_el is None or not arxiv_id_el.text:
        return None
    raw_id = arxiv_id_el.text.strip().rstrip("/")
    arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id.split("/")[-1]

    title_el = entry.find(f"{{{ns}}}title")
    title = ("".join(title_el.itertext()) if title_el is not None else "").strip().replace("\n", " ")

    summary_el = entry.find(f"{{{ns}}}summary")
    abstract = ("".join(summary_el.itertext()) if summary_el is not None else "").strip().replace("\n", " ")

    if not title and not abstract:
        return None

    authors = []
    for author_el in entry.findall(f"{{{ns}}}author"):
        name_el = author_el.find(f"{{{ns}}}name")
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())
    author_str = ", ".join(authors[:5])
    if len(authors) > 5:
        author_str += " et al."

    published_el = entry.find(f"{{{ns}}}published")
    year = ""
    if published_el is not None and published_el.text:
        year = published_el.text[:4]

    cats = []
    for cat_el in entry.findall(f"{{{ns}}}category"):
        term = cat_el.get("term", "")
        if term:
            cats.append(term)
    category_str = ", ".join(cats[:3])

    return {
        "source": "arxiv",
        "source_id": f"arxiv:{arxiv_id}",
        "title": title,
        "abstract": abstract,
        "authors": author_str,
        "journal": f"arXiv [{category_str}]",
        "year": year,
        "doi": f"10.48550/arXiv.{arxiv_id}",
    }


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in records:
        sid = r["source_id"]
        if sid not in seen:
            seen.add(sid)
            out.append(r)
    return out


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
    print("  Global Warming Research Ingestion — AI Portfolio Architect")
    print("=" * 65)

    # ── 1. Collect records ────────────────────────────────────────────────
    # ── 2. Init DB ────────────────────────────────────────────────────────
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
        print("  Skipping fetch + ingest — resuming from embedding step.")

    if project_id is None:
        # ── 1. Collect records ────────────────────────────────────────────
        all_records: list[dict] = []

        if not args.arxiv_only:
            print("\n1a. Fetching PubMed records...")
            pubmed_max = max_records if args.pubmed_only else max_records // 2
            try:
                pmids = pubmed_search(PUBMED_QUERY, pubmed_max)
                if pmids:
                    pm_records = pubmed_fetch_abstracts(pmids)
                    print(f"  Got {len(pm_records)} PubMed records")
                    all_records.extend(pm_records)
            except Exception as e:
                print(f"  PubMed fetch failed: {e}")

        if not args.pubmed_only:
            print("\n1b. Fetching arXiv records...")
            arxiv_max_per = max(30, (max_records - len(all_records)) // len(ARXIV_SEARCHES))
            for cat, query in ARXIV_SEARCHES:
                try:
                    recs = arxiv_fetch(cat, query, max_per_search=arxiv_max_per)
                    print(f"  arXiv [{cat or 'all'} / {query[:40]}]: {len(recs)} records")
                    all_records.extend(recs)
                except Exception as e:
                    print(f"  arXiv error: {e}")

        all_records = deduplicate(all_records)
        if len(all_records) > max_records:
            all_records = all_records[:max_records]

        if not all_records:
            print("\nNo records fetched. Check network access and API availability.")
            sys.exit(1)

        print(f"\nTotal unique records: {len(all_records)}")
        src_counts: dict[str, int] = {}
        for r in all_records:
            src_counts[r["source"]] = src_counts.get(r["source"], 0) + 1
        for src, n in src_counts.items():
            print(f"  {src}: {n}")

        # ── 3. Create project ─────────────────────────────────────────────
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

        # ── 4. Ingest records as documents + chunks ───────────────────────
        print(f"\n4. Ingesting {len(all_records)} records...")
        async with pool.acquire() as conn:
            for idx, rec in enumerate(all_records):
                raw_text = record_to_text(rec)
                chunks = chunk_text(raw_text)
                if not chunks:
                    continue
                doc = await insert_document(conn, project_id, rec["source_id"], raw_text)
                await insert_chunks(conn, doc["id"], project_id, chunks)
                if (idx + 1) % 100 == 0:
                    print(f"  Ingested {idx + 1}/{len(all_records)}...", end="\r")
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
        description="Ingest global warming research into AI Portfolio Architect"
    )
    parser.add_argument("--max-records", type=int, default=2000, metavar="N",
                        help="Cap total records (default: 2000)")
    parser.add_argument("--pubmed-only", action="store_true",
                        help="Only fetch from PubMed")
    parser.add_argument("--arxiv-only", action="store_true",
                        help="Only fetch from arXiv")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip embedding step")
    args = parser.parse_args()

    asyncio.run(main(args))
