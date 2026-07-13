"""Claim clustering: group claims about the same underlying hypothesis across
papers, via intervention blocking + within-block cosine-similarity clustering.

Blocking by normalized intervention keeps unrelated drugs from ever being
compared (cheap, precision-improving). Within a block, pairwise cosine
similarity is computed with numpy (already a project dependency) rather than
the pure-Python loops used in feedback/decision_memory.py and
ranking/active_learning.py — those operate over at most dozens of validated
decisions, while claim blocks here can run into the hundreds at 4096-dim
embeddings (Qwen3-Embedding-8B), where a vectorized matrix product is
meaningfully faster than nested Python loops.
"""

import re
from uuid import UUID

import numpy as np

from portfolio_architect.db.pool import _ConnProxy
from portfolio_architect.embedding import codec
from portfolio_architect.db.claim_clusters import get_claims_with_embeddings, insert_cluster

SIMILARITY_THRESHOLD = 0.82
MIN_DISTINCT_DOCUMENTS = 2

# Below this many distinct claim-bearing documents, similarity sub-clustering +
# the >=2-document rule leave almost every claim as an isolated singleton (a small
# corpus rarely has two papers making a near-identical claim about the same drug).
# In that regime we fall back to drug-level clustering: one cluster per drug, so
# the map shows drug groupings instead of scattered points. Adjustable knob.
SMALL_CORPUS_MAX_DOCS = 50

# Normalized intervention keys that mean "no drug intervention" — observational /
# biomarker / prognostic studies where the LLM set intervention to "None (...)" or
# "Null (...)". These are out of scope for a drug→evidence map: without this guard
# they collapse hundreds of unrelated observational claims into giant, meaningless
# "none"/"null" clusters. Excluded from both multi-source and singleton clustering.
NON_INTERVENTION_KEYS = {"none", "null", "unknown", ""}

def normalize_intervention(intervention: str | None) -> str:
    """Cleaned blocking key: lowercase, strip parenthetical annotations and
    punctuation. This is the RAW key; surface variants of one drug are unified
    afterwards by the LLM-built canonical map (see claims/drug_normalizer.py),
    not by hardcoded alias/word-form tables."""
    if not intervention:
        return "unknown"
    text = re.sub(r"\([^)]*\)", "", intervention)  # strip "(DRUG)" / "(BIOLOGICAL)" etc.
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return text or "unknown"


def block_key(intervention: str | None, canonical: dict[str, str] | None = None) -> str:
    """The blocking key a claim clusters under: the cleaned raw key, mapped
    through the LLM-built canonical map when one is supplied."""
    raw = normalize_intervention(intervention)
    return canonical.get(raw, raw) if canonical else raw


def build_blocks(claims: list[dict], canonical: dict[str, str] | None = None) -> dict[str, list[dict]]:
    blocks: dict[str, list[dict]] = {}
    for c in claims:
        key = block_key(c.get("intervention"), canonical)
        blocks.setdefault(key, []).append(c)
    return blocks


class _UnionFind:
    def __init__(self, items: list[str]):
        self.parent = {item: item for item in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_block(claims: list[dict], threshold: float = SIMILARITY_THRESHOLD) -> list[list[dict]]:
    """Cluster claims within a single intervention block via cosine-similarity
    union-find. Returns a list of clusters (each a list of claim dicts)."""
    if len(claims) < 2:
        return [[c] for c in claims]

    ids = [c["id"] for c in claims]
    matrix = np.array([codec.decode(c["claim_embedding"]) for c in claims], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    normalized = matrix / norms
    sims = normalized @ normalized.T  # cosine similarity matrix

    uf = _UnionFind(ids)
    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            if sims[i, j] >= threshold:
                uf.union(ids[i], ids[j])

    groups: dict[str, list[dict]] = {}
    for c in claims:
        root = uf.find(c["id"])
        groups.setdefault(root, []).append(c)
    return list(groups.values())


async def cluster_project_claims(
    conn: _ConnProxy,
    project_id: UUID,
    threshold: float = SIMILARITY_THRESHOLD,
    min_documents: int = MIN_DISTINCT_DOCUMENTS,
    verified_only: bool = False,
    exclude_trials: bool = False,
) -> list[dict]:
    """Cluster all embedded claims for a project, persist clusters with
    >= min_documents distinct source documents, and return the created rows.
    Pass verified_only/exclude_trials to build a verified, PubMed-only set."""
    claims = await get_claims_with_embeddings(
        conn, project_id, verified_only=verified_only, exclude_trials=exclude_trials
    )
    # Automatic drug-name canonicalization (LLM, cached) so surface variants of a
    # drug ("HPV vaccination"/"vaccine"/"vaccines", brand vs generic) block
    # together. Local import avoids a circular dependency at module load.
    from portfolio_architect.claims.drug_normalizer import build_canonical_map
    canonical = await build_canonical_map(
        conn, {normalize_intervention(c.get("intervention")) for c in claims},
        project_id=project_id,
    )
    blocks = build_blocks(claims, canonical)

    # On a small corpus, group each drug's claims into a single drug-level cluster
    # (skip the within-drug similarity split and the >=2-document rule) so the map
    # shows one node per drug instead of a scatter of singletons.
    small_corpus = len({c["document_id"] for c in claims}) <= SMALL_CORPUS_MAX_DOCS
    effective_min_documents = 1 if small_corpus else min_documents

    created = []
    for intervention_key, block_claims in blocks.items():
        if intervention_key in NON_INTERVENTION_KEYS:
            continue  # observational / no-drug claims — not a drug cluster
        groups = [block_claims] if small_corpus else cluster_block(block_claims, threshold)
        for group in groups:
            doc_ids = {c["document_id"] for c in group}
            if len(group) < 2 or len(doc_ids) < effective_min_documents:
                continue
            verdict_mix: dict[str, int] = {}
            for c in group:
                verdict_mix[c["verdict"]] = verdict_mix.get(c["verdict"], 0) + 1
            row = await insert_cluster(
                conn, project_id, intervention_key,
                [c["id"] for c in group], len(doc_ids), verdict_mix,
            )
            created.append(row)
    return created


async def add_singleton_clusters(
    conn: _ConnProxy, project_id: UUID, exclude_trials: bool = False
) -> list[dict]:
    """Turn each currently-unclustered, quote-verified claim into its own
    single-member cluster, so it flows through the same conversation-
    synthesis pipeline as multi-paper clusters. Run this *after*
    cluster_project_claims() so genuinely multi-paper claims aren't
    downgraded to singletons. `exclude_trials` keeps trial-sourced claims out."""
    trial_filter = "AND d.doc_type != 'trial'" if exclude_trials else ""
    rows = await conn.fetch(
        f"""
        SELECT c.*, d.doc_type FROM claims c JOIN documents d ON c.document_id = d.id
        WHERE c.project_id = ? AND c.cluster_id IS NULL AND c.quote_verified = 1 {trial_filter}
        """,
        str(project_id),
    )
    # Reuse the canonical map the main pass already cached (cache-only — no LLM),
    # so a leftover single-paper drug shows under the same canonical name.
    from portfolio_architect.claims.drug_normalizer import load_aliases
    canonical = await load_aliases(
        conn, [normalize_intervention(c.get("intervention")) for c in rows]
    )
    created = []
    for c in rows:
        intervention_key = block_key(c.get("intervention"), canonical)
        if intervention_key in NON_INTERVENTION_KEYS:
            continue  # observational / no-drug claims — keep off the map
        row = await insert_cluster(
            conn, project_id, intervention_key,
            [c["id"]], 1, {c["verdict"]: 1},
        )
        created.append(row)
    return created
