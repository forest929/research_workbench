#!/usr/bin/env python3
"""
Backfill documents.pub_date ("YYYY-MM", or "YYYY" when month is unknown).

PubMed publication dates aren't stored structurally — the ingest only kept the
year, inside raw_content. This re-parses the cached efetch XML
(data/raw_cache/pubmed/*.bin) to recover Year + Month per PMID, and falls back to
the "Year: YYYY" line in raw_content for any document not found in the cache.

Pure local parse, no network. Re-run any time.

Usage:
    python scripts/backfill_pub_dates.py --project-id <id>
"""

import argparse
import asyncio
import glob
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations

CACHE_DIR = Path(__file__).parent.parent / "data" / "raw_cache" / "pubmed"

_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _month_num(m: str | None) -> str | None:
    if not m:
        return None
    m = m.strip().lower()
    if m[:3] in _MONTHS:
        return _MONTHS[m[:3]]
    if m.isdigit() and 1 <= int(m) <= 12:
        return f"{int(m):02d}"
    return None


def _pub_date_from_article(art: ET.Element) -> tuple[str, str | None] | None:
    pd = art.find(".//PubDate")
    if pd is None:
        return None
    year = pd.findtext("Year")
    month = _month_num(pd.findtext("Month"))
    if not year:
        medline = pd.findtext("MedlineDate") or ""  # e.g. "2024 Jan-Feb"
        ym = re.match(r"(\d{4})\s*([A-Za-z]{3})?", medline)
        if ym:
            year = ym.group(1)
            month = _month_num(ym.group(2))
    if not year:
        return None
    return year, month


def _scan_cache() -> dict[str, str]:
    """pmid -> 'YYYY-MM' or 'YYYY' from every cached efetch XML."""
    out: dict[str, str] = {}
    for f in glob.glob(str(CACHE_DIR / "*.bin")):
        try:
            root = ET.fromstring(Path(f).read_bytes())
        except ET.ParseError:
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//MedlineCitation/PMID")
            if not pmid:
                continue
            parsed = _pub_date_from_article(art)
            if parsed:
                year, month = parsed
                out[pmid] = f"{year}-{month}" if month else year
    return out


async def main(args) -> None:
    project_id = str(UUID(args.project_id))
    print("Scanning PubMed cache for publication dates...")
    pmid_dates = _scan_cache()
    print(f"  recovered dates for {len(pmid_dates)} PMIDs from cache")

    pool = await create_pool()
    await run_migrations(pool)
    try:
        async with pool.acquire() as conn:
            docs = await conn.fetch(
                "SELECT id, source_id, raw_content FROM documents "
                "WHERE project_id = ? AND doc_type = 'paper'",
                project_id,
            )
            updates = []
            from_cache = from_text = 0
            for d in docs:
                sid = d["source_id"] or ""
                pmid = sid[5:] if sid.startswith("pmid:") else None
                date = pmid_dates.get(pmid) if pmid else None
                if date:
                    from_cache += 1
                else:
                    m = re.search(r"Year:\s*(\d{4})", d["raw_content"] or "")
                    if m:
                        date = m.group(1)
                        from_text += 1
                if date:
                    updates.append((date, d["id"]))
            await conn.executemany(
                "UPDATE documents SET pub_date = ? WHERE id = ?", updates
            )
        print(f"  updated {len(updates)} documents "
              f"({from_cache} from cache with month, {from_text} year-only from text)")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Backfill documents.pub_date from the PubMed cache.")
    p.add_argument("--project-id", required=True)
    asyncio.run(main(p.parse_args()))
