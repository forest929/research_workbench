"""Add-by-DOI pipeline: resolve a DOI, extract claims, embed them, and attach
each to the nearest existing claim cluster (or spin up a new *user* cluster).

Runs in the background off `POST /workbench/add-source`. Every stage updates the
`user_sources` row so the UI can poll. User-touched clusters are marked so the
map can render them with a distinct bubble style — a live view of what the user
is adding.
"""

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from uuid import uuid4

import numpy as np

from portfolio_architect.claims import projection
from portfolio_architect.claims.clustering import normalize_intervention, NON_INTERVENTION_KEYS, SIMILARITY_THRESHOLD
from portfolio_architect.claims.extraction import run_one
from portfolio_architect.db.documents import insert_document
from portfolio_architect.db.saved_publications import save_publication
from portfolio_architect.embedding import client as embedding
from portfolio_architect.embedding import codec

_UA = {"User-Agent": "AI-Portfolio-Architect/1.0 (research; contact kexinwang929@gmail.com)"}
_NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_MONTHS = {m: f"{i:02d}" for i, m in enumerate(
    ["", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _clean_doi(raw: str) -> str:
    d = raw.strip()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = re.sub(r"^doi:", "", d, flags=re.I)
    return d.strip()


# ── DOI → record (PubMed primary, Crossref fallback) ─────────────────────────

def _resolve_via_pubmed(doi: str) -> dict | None:
    url = f"{_NCBI}/esearch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "term": f"{doi}[DOI]", "retmode": "json"})
    try:
        ids = json.loads(_get(url)).get("esearchresult", {}).get("idlist", [])
    except Exception:
        return None
    if not ids:
        return None
    pmid = ids[0]
    xml = _get(f"{_NCBI}/efetch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"}))
    try:
        art = ET.fromstring(xml).find(".//PubmedArticle")
    except ET.ParseError:
        return None
    if art is None:
        return None
    title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
    abstract = " ".join("".join(a.itertext()) for a in art.findall(".//AbstractText"))
    journal = art.findtext(".//Journal/Title", "")
    pd = art.find(".//PubDate")
    year = pd.findtext("Year", "") if pd is not None else ""
    month = _MONTHS.get((pd.findtext("Month", "") or "").strip().lower()[:3]) if pd is not None else None
    return {
        "source_id": f"pmid:{pmid}", "title": title, "abstract": abstract,
        "journal": journal, "year": year, "doi": doi,
        "pub_date": f"{year}-{month}" if year and month else (year or None),
    }


def _resolve_via_crossref(doi: str) -> dict | None:
    try:
        msg = json.loads(_get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")).get("message", {})
    except Exception:
        return None
    title = (msg.get("title") or [""])[0]
    abstract = re.sub(r"<[^>]+>", "", msg.get("abstract", "") or "")  # strip JATS tags
    parts = (msg.get("issued", {}).get("date-parts") or [[None]])[0]
    year = str(parts[0]) if parts and parts[0] else ""
    month = f"{parts[1]:02d}" if len(parts) > 1 and parts[1] else None
    return {
        "source_id": f"doi:{doi}", "title": title, "abstract": abstract,
        "journal": (msg.get("container-title") or [""])[0], "year": year, "doi": doi,
        "pub_date": f"{year}-{month}" if year and month else (year or None),
    }


def _record_to_text(rec: dict) -> str:
    parts = [f"Title: {rec['title']}"]
    if rec.get("journal"):
        parts.append(f"Journal: {rec['journal']}")
    if rec.get("year"):
        parts.append(f"Year: {rec['year']}")
    if rec.get("doi"):
        parts.append(f"DOI: {rec['doi']}")
    if rec.get("abstract"):
        parts.append(f"Abstract: {rec['abstract']}")
    return "\n".join(parts)


# ── cluster assignment ───────────────────────────────────────────────────────

async def _best_cluster_for(conn, project_id, intervention_key: str, vec: np.ndarray) -> str | None:
    """Nearest existing cluster (same intervention block) by cosine of the new
    claim vs candidate members. Returns cluster_id if within threshold, else None.

    Vectorized: decode all candidate embeddings into one (n, dim) matrix and take
    the cosine against the query in a single numpy op, rather than a Python loop
    of per-row cosines over up to 4000 4096-dim vectors."""
    rows = await conn.fetch(
        """
        SELECT c.cluster_id, c.claim_embedding
        FROM claims c JOIN claim_clusters cc ON c.cluster_id = cc.id
        WHERE cc.project_id = ? AND cc.intervention_key = ? AND c.claim_embedding IS NOT NULL
        LIMIT 4000
        """,
        str(project_id), intervention_key,
    )
    if not rows:
        return None
    mat = np.array([codec.decode(r["claim_embedding"]) for r in rows], dtype=np.float32)  # (n, dim)
    q = np.asarray(vec, dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1)
    norms[norms == 0] = 1e-9
    sims = (mat @ q) / (norms * (np.linalg.norm(q) or 1e-9))
    best = int(np.argmax(sims))
    return rows[best]["cluster_id"] if float(sims[best]) >= SIMILARITY_THRESHOLD else None


async def _attach_to_cluster(conn, cluster_id: str, claim_id: str, verdict: str) -> None:
    await conn.execute("UPDATE claims SET cluster_id = ? WHERE id = ?", cluster_id, claim_id)
    row = await conn.fetchrow("SELECT verdict_mix_json, member_count FROM claim_clusters WHERE id = ?", cluster_id)
    mix = json.loads(row["verdict_mix_json"] or "{}")
    mix[verdict] = mix.get(verdict, 0) + 1
    docs = await conn.fetchrow(
        "SELECT COUNT(DISTINCT document_id) n FROM claims WHERE cluster_id = ?", cluster_id)
    await conn.execute(
        "UPDATE claim_clusters SET member_count = member_count + 1, distinct_document_count = ?, "
        "verdict_mix_json = ?, user_claim_count = user_claim_count + 1 WHERE id = ?",
        docs["n"], json.dumps(mix), cluster_id,
    )


async def _new_user_cluster(conn, project_id, intervention_key, claim_id, verdict, vec) -> str:
    cid = str(uuid4())
    xy = projection.project_point(str(project_id), vec)
    x, y = xy if xy else (0.0, 0.0)
    await conn.execute(
        """
        INSERT INTO claim_clusters
            (id, project_id, intervention_key, member_count, distinct_document_count,
             verdict_mix_json, coord_x, coord_y, origin, user_claim_count)
        VALUES (?, ?, ?, 1, 1, ?, ?, ?, 'user', 1)
        """,
        cid, str(project_id), intervention_key, json.dumps({verdict: 1}), x, y,
    )
    await conn.execute("UPDATE claims SET cluster_id = ? WHERE id = ?", cid, claim_id)
    return cid


# ── orchestration ────────────────────────────────────────────────────────────

async def _set_status(pool, us_id, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE user_sources SET {cols} WHERE id = ?", *fields.values(), us_id)


async def process_source(pool, project_id, user_source_id: str, doi: str) -> None:
    """Full pipeline for one submitted DOI. Never raises — failures are recorded
    on the user_sources row as status='failed'."""
    doi = _clean_doi(doi)
    try:
        await _set_status(pool, user_source_id, status="fetching", message="Resolving DOI…")
        rec = _resolve_via_pubmed(doi) or _resolve_via_crossref(doi)
        if not rec or not (rec.get("abstract") or "").strip():
            await _set_status(pool, user_source_id, status="failed",
                              message="Could not find an abstract for this DOI (PubMed/Crossref).")
            return

        # Bookmark the resolved publication into the project's curated reading
        # list right away — a DOI the user pastes lands in their list even if
        # downstream claim extraction later yields nothing.
        try:
            async with pool.acquire() as conn:
                await save_publication(
                    conn, project_id, rec["source_id"], doi=doi,
                    title=rec.get("title"), added_from="doi",
                )
        except Exception:
            pass

        async with pool.acquire() as conn:
            doc = await insert_document(conn, project_id, rec["source_id"], _record_to_text(rec), doc_type="paper")
            if rec.get("pub_date"):
                await conn.execute("UPDATE documents SET pub_date = ? WHERE id = ?", rec["pub_date"], doc["id"])
            already = await conn.fetchrow(
                "SELECT COUNT(*) n FROM claims WHERE document_id = ?", doc["id"])
        if already["n"] > 0:
            # Already ingested — don't fail; locate its claims' clusters so the UI
            # can highlight where this source already lives on the map.
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT cluster_id FROM claims WHERE document_id = ? AND cluster_id IS NOT NULL",
                    doc["id"],
                )
            cids = [r["cluster_id"] for r in rows]
            await _set_status(
                pool, user_source_id, status="existing", source_id=rec["source_id"],
                title=rec["title"], cluster_ids=json.dumps(cids),
                message=f"Already in the corpus — in {len(cids)} cluster(s). Locate on map.",
            )
            return

        await _set_status(pool, user_source_id, status="extracting", source_id=rec["source_id"],
                          title=rec["title"], message="Extracting claims…")
        async with pool.acquire() as conn:
            result = await run_one(conn, project_id, doc)
        claims = [c for c in result.get("claims", []) if c.get("quote_verified")]
        if not claims:
            await _set_status(pool, user_source_id, status="failed",
                              message="No verified claims could be extracted from this source.")
            return

        # Persist claims and capture their ids.
        async with pool.acquire() as conn:
            inserted = []
            for c in claims:
                cid = str(uuid4())
                await conn.execute(
                    """INSERT INTO claims (id, project_id, document_id, claim_text, population,
                       intervention, comparator, outcome, verdict, evidence_quote, quote_verified,
                       effect_size, statistical_significance, confidence, raw_llm_response)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?,?)""",
                    cid, str(project_id), doc["id"], c["claim"], c.get("population"),
                    c.get("intervention"), c.get("comparator"), c.get("outcome"), c["verdict"],
                    c.get("evidence_quote"), c.get("effect_size"), c.get("statistical_significance"),
                    c.get("confidence"), c.get("raw_llm_response"),
                )
                inserted.append({**c, "id": cid})
            await conn.execute(
                "UPDATE documents SET claims_extracted = 1 WHERE id = ?", doc["id"])

        await _set_status(pool, user_source_id, status="embedding",
                          message=f"Embedding {len(inserted)} claims…")
        texts = [c["claim"] for c in inserted]
        vecs = await embedding.embed_batch(texts)
        async with pool.acquire() as conn:
            for c, v in zip(inserted, vecs):
                await conn.execute("UPDATE claims SET claim_embedding = ? WHERE id = ?",
                                   codec.encode(v), c["id"])
                c["vec"] = np.array(v, dtype=np.float32)

        await _set_status(pool, user_source_id, status="clustering",
                          message="Finding closest clusters…")
        touched: set[str] = set()
        async with pool.acquire() as conn:
            for c in inserted:
                key = normalize_intervention(c.get("intervention"))
                if key in NON_INTERVENTION_KEYS:
                    key = "user-submitted"
                target = await _best_cluster_for(conn, project_id, key, c["vec"])
                if target:
                    await _attach_to_cluster(conn, target, c["id"], c["verdict"])
                    touched.add(target)
                else:
                    new_id = await _new_user_cluster(conn, project_id, key, c["id"], c["verdict"], c["vec"])
                    touched.add(new_id)

        await _set_status(
            pool, user_source_id, status="done",
            claims_added=len(inserted), cluster_ids=json.dumps(list(touched)),
            message=f"Added {len(inserted)} claims across {len(touched)} cluster(s).",
        )
        # Invalidate the workbench caches so the map/singles reflect the new data.
        try:
            from api.routers import workbench
            workbench.invalidate_caches(str(project_id))
        except Exception:
            pass
    except Exception as e:  # never let the background task crash silently
        await _set_status(pool, user_source_id, status="failed", message=f"Error: {e}")
