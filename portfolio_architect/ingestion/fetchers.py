"""Literature fetchers: Google Scholar (primary) + arXiv (secondary).

Google Scholar is fetched via `scholarly` (no API key needed).
arXiv uses the public Atom API.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ARXIV_BASE = "https://export.arxiv.org/api/query"
ARXIV_DELAY = 3.0
ARXIV_NS = "http://www.w3.org/2005/Atom"
_USER_AGENT = "AI-Portfolio-Architect/1.0 (research)"


# ---------------------------------------------------------------------------
# Google Scholar via scholarly
# ---------------------------------------------------------------------------

def scholar_fetch(query: str, max_records: int = 200, progress_cb=None) -> list[dict]:
    """Fetch records from Google Scholar using the scholarly scraper."""
    try:
        from scholarly import scholarly as _scholarly
    except ImportError:
        return []

    records: list[dict] = []
    try:
        search_gen = _scholarly.search_pubs(query)
        for i, pub in enumerate(search_gen):
            if i >= max_records:
                break
            rec = _parse_scholar_pub(pub)
            if rec:
                records.append(rec)
            if progress_cb and i % 10 == 0:
                progress_cb("scholar_fetch", len(records))
            # scholarly already rate-limits internally; small extra pause
            time.sleep(0.3)
    except Exception:
        pass

    return records


def _parse_scholar_pub(pub: dict) -> dict | None:
    bib = pub.get("bib", {})
    title = (bib.get("title") or "").strip()
    abstract = (bib.get("abstract") or "").strip()
    if not title:
        return None

    authors_raw = bib.get("author") or []
    if isinstance(authors_raw, str):
        authors_raw = [a.strip() for a in authors_raw.split(" and ")]
    author_str = ", ".join(authors_raw[:5]) + (" et al." if len(authors_raw) > 5 else "")

    year = str(bib.get("pub_year") or bib.get("year") or "")
    journal = (bib.get("journal") or bib.get("venue") or bib.get("booktitle") or "").strip()
    doi = (pub.get("eprint_url") or "").strip()
    pub_url = pub.get("pub_url") or ""
    scholar_id = pub.get("scholar_id") or pub.get("url") or pub_url

    # Build a stable source_id
    if scholar_id:
        # Use a short hash of the scholar_id so it stays compact
        import hashlib
        sid = "scholar:" + hashlib.md5(scholar_id.encode()).hexdigest()[:12]
    else:
        import hashlib
        sid = "scholar:" + hashlib.md5(title.encode()).hexdigest()[:12]

    return {
        "source": "scholar",
        "source_id": sid,
        "title": title,
        "abstract": abstract,
        "authors": author_str,
        "journal": journal,
        "year": year,
        "doi": doi,
        "url": pub_url,
    }


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def _get(url: str, retries: int = 3) -> bytes:
    headers = {"User-Agent": _USER_AGENT}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt * 5)
            else:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Failed after {retries} retries: {url}")


def arxiv_fetch(query: str, max_records: int = 200, progress_cb=None) -> list[dict]:
    records: list[dict] = []
    batch = 100
    start = 0
    while start < max_records:
        params = {
            "search_query": f"all:{query}",
            "start": start,
            "max_results": min(batch, max_records - start),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}"
        try:
            xml_bytes = _get(url)
        except Exception:
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
        if progress_cb:
            progress_cb("arxiv_fetch", len(records))
        start += len(entries)
        if len(entries) < batch:
            break
    return records


def _parse_arxiv_entry(entry: ET.Element) -> dict | None:
    ns = ARXIV_NS
    id_el = entry.find(f"{{{ns}}}id")
    if id_el is None or not id_el.text:
        return None
    raw_id = id_el.text.strip().rstrip("/")
    arxiv_id = raw_id.split("/abs/")[-1] if "/abs/" in raw_id else raw_id.split("/")[-1]
    title_el = entry.find(f"{{{ns}}}title")
    title = ("".join(title_el.itertext()) if title_el is not None else "").strip().replace("\n", " ")
    summary_el = entry.find(f"{{{ns}}}summary")
    abstract = ("".join(summary_el.itertext()) if summary_el is not None else "").strip().replace("\n", " ")
    if not title and not abstract:
        return None
    authors = []
    for a in entry.findall(f"{{{ns}}}author"):
        n = a.find(f"{{{ns}}}name")
        if n is not None and n.text:
            authors.append(n.text.strip())
    author_str = ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")
    published_el = entry.find(f"{{{ns}}}published")
    year = published_el.text[:4] if published_el is not None and published_el.text else ""
    cats = [c.get("term", "") for c in entry.findall(f"{{{ns}}}category")]
    cat_str = ", ".join(filter(None, cats[:3]))
    pub_url = f"https://arxiv.org/abs/{arxiv_id}"
    return {
        "source": "arxiv",
        "source_id": f"arxiv:{arxiv_id}",
        "title": title,
        "abstract": abstract,
        "authors": author_str,
        "journal": f"arXiv [{cat_str}]",
        "year": year,
        "doi": f"10.48550/arXiv.{arxiv_id}",
        "url": pub_url,
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def record_to_text(rec: dict) -> str:
    parts = [f"Title: {rec['title']}"]
    for k, label in [("authors", "Authors"), ("journal", "Journal"), ("year", "Year"), ("doi", "DOI")]:
        if rec.get(k):
            parts.append(f"{label}: {rec[k]}")
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
