"""Automatic drug-name canonicalization via a single cached LLM pass.

Replaces the old hardcoded alias / word-form maps. A project's DISTINCT cleaned
intervention strings are sent to the LLM once; it groups surface variants
(plural/singular, "vaccination"/"vaccine", brand vs generic like
"Lynparza"/"olaparib") under one canonical name while keeping genuinely distinct
drugs and regimens apart (adjuvant vs neoadjuvant, mono- vs combination therapy,
quadrivalent vs nonavalent vaccine). Results are cached in the global
`drug_aliases` table, so re-runs and other projects reuse them for free and the
mapping is deterministic after first fill.

Used by clustering to block claims by canonical drug rather than raw string.
"""

import json

from portfolio_architect.db.pool import _ConnProxy
from portfolio_architect.llm import client as llm
from portfolio_architect.claims.clustering import NON_INTERVENTION_KEYS

# Cost guard: on a dense corpus the intervention field is essentially unique per
# claim (thousands of distinct strings), where canonicalization is both expensive
# and low-value (similarity clustering already groups within a drug). Above this
# many distinct names we skip the LLM pass and fall back to the cleaned key.
MAX_CANONICALIZE = 300
_BATCH = 60

_SYSTEM = """You canonicalize clinical trial intervention names for grouping.

Given a list of intervention strings, return STRICT JSON mapping each EXACT input \
string to a canonical name, so that surface variants of the SAME intervention \
share one canonical value:
- plural/singular and word forms ("HPV vaccines"/"HPV vaccination" -> "HPV vaccine")
- brand vs generic ("Lynparza" -> "olaparib", "Keytruda" -> "pembrolizumab")
- trivial punctuation/casing differences

KEEP these DISTINCT (do NOT merge):
- different drugs, and different product variants (quadrivalent vs nonavalent HPV vaccine)
- different regimens: "adjuvant" vs "neoadjuvant"; monotherapy vs a named combination
- non-drug interventions ("MRI", "surgery", "radiotherapy") — return them unchanged

Return ONLY a JSON object, no prose, no markdown fences:
{"<exact input>": "<canonical name>", ...}
Include every input string as a key."""


async def _llm_batch(names: list[str], conn: _ConnProxy | None = None,
                     project_id=None) -> dict[str, str]:
    user = "Canonicalize these intervention names:\n" + "\n".join(f"- {n}" for n in names)
    try:
        raw = await llm.generate(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            temperature=0.0, call_type="drug_canonicalization",
            conn=conn, project_id=project_id,
        )
    except Exception:
        return {}
    return _parse(raw, names)


def _parse(raw: str, names: list[str]) -> dict[str, str]:
    """Defensive JSON parse — unparseable output yields an empty map (caller then
    falls back to the raw key), never a crash."""
    text = (raw or "").strip()
    if text.startswith("```"):
        for seg in text.split("```")[1:]:
            s = seg.lstrip("json").strip()
            if s.startswith("{"):
                text = s
                break
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j > i:
            text = text[i:j + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    known = set(names)
    out: dict[str, str] = {}
    for k, v in parsed.items():
        if k in known and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


async def load_aliases(conn: _ConnProxy, raw_keys: list[str]) -> dict[str, str]:
    """Cache-only lookup: return the canonical for any of `raw_keys` already in
    the alias table (no LLM). Used by the singleton pass after the main pass has
    filled the cache."""
    keys = [k for k in {*raw_keys} if k and k not in NON_INTERVENTION_KEYS]
    if not keys:
        return {}
    placeholders = ",".join("?" * len(keys))
    rows = await conn.fetch(
        f"SELECT raw_key, canonical FROM drug_aliases WHERE raw_key IN ({placeholders})", *keys
    )
    return {r["raw_key"]: r["canonical"] for r in rows}


async def build_canonical_map(conn: _ConnProxy, raw_keys, project_id=None) -> dict[str, str]:
    """Return {raw_key -> canonical} for the given cleaned intervention keys,
    filling any uncached ones via the LLM (batched) and persisting them. Skips the
    LLM entirely on a dense corpus (> MAX_CANONICALIZE distinct names) or if the
    call fails, falling back to the raw key so clustering still works."""
    keys = sorted({k for k in raw_keys if k and k not in NON_INTERVENTION_KEYS})
    cached = await load_aliases(conn, keys)
    missing = [k for k in keys if k not in cached]

    if missing and len(keys) <= MAX_CANONICALIZE:
        for i in range(0, len(missing), _BATCH):
            batch = missing[i:i + _BATCH]
            mapping = await _llm_batch(batch, conn=conn, project_id=project_id)
            for raw in batch:
                if raw not in mapping:
                    continue  # LLM omitted / batch failed — don't cache a non-answer,
                              # fall back to the raw key and retry on the next build
                # Lowercase the canonical so it matches the existing lowercase
                # intervention_key convention and blocks consistently across batches.
                canon = mapping[raw].strip().lower() or raw
                from portfolio_architect.db.pool import is_postgres
                if is_postgres():
                    await conn.execute(
                        "INSERT INTO drug_aliases (raw_key, canonical) VALUES (?, ?) "
                        "ON CONFLICT (raw_key) DO UPDATE SET canonical = EXCLUDED.canonical",
                        raw, canon,
                    )
                else:
                    await conn.execute(
                        "INSERT OR REPLACE INTO drug_aliases (raw_key, canonical) VALUES (?, ?)",
                        raw, canon,
                    )
                cached[raw] = canon

    return {k: cached.get(k, k) for k in keys}
