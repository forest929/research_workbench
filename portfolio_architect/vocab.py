"""Disease vocabulary — the controlled term set used to tag/filter clusters by
disease in the workbench.

The vocabulary is **per project** (stored as `projects.disease_vocab_json`), not
a global constant, so a project on any topic tags with its own terms rather than
inheriting the women's-cancer set. `DEFAULT_DISEASE_VOCAB` below is only the seed
backfilled onto projects that existed when the column was first added; projects
created afterwards start unconfigured (empty) until a vocabulary is set.

Shape: ``{ key: {"label": str, "keywords": [str, ...]} }``.
"""

DEFAULT_DISEASE_VOCAB: dict[str, dict] = {
    "breast": {"label": "Breast cancer", "keywords": ["breast"]},
    "ovarian": {"label": "Ovarian cancer", "keywords": ["ovarian", "ovary", "fallopian", "peritoneal"]},
    "cervical": {"label": "Cervical cancer", "keywords": ["cervical", "cervix"]},
    "endometrial": {"label": "Endometrial / uterine cancer", "keywords": ["endometrial", "endometrium", "uterine", "uterus"]},
}

# Curated catalog matched against a new project's scope/name/description to seed a
# starter disease vocabulary, so the disease filter isn't empty on day one. The
# women's-cancer set (the demo domain) plus common cancers for other topics.
# Only diseases whose keywords actually appear in the text are seeded; a project
# on an unrelated topic gets nothing and configures its own via "Edit diseases".
_STARTER_DISEASE_CATALOG: dict[str, dict] = {
    **DEFAULT_DISEASE_VOCAB,
    "lung": {"label": "Lung cancer", "keywords": ["lung", "nsclc", "sclc"]},
    "colorectal": {"label": "Colorectal cancer", "keywords": ["colorectal", "colon", "rectal"]},
    "prostate": {"label": "Prostate cancer", "keywords": ["prostate"]},
    "pancreatic": {"label": "Pancreatic cancer", "keywords": ["pancreatic", "pancreas"]},
    "gastric": {"label": "Gastric cancer", "keywords": ["gastric", "stomach"]},
    "melanoma": {"label": "Melanoma", "keywords": ["melanoma"]},
    "leukemia": {"label": "Leukemia", "keywords": ["leukemia", "leukaemia"]},
    "lymphoma": {"label": "Lymphoma", "keywords": ["lymphoma"]},
    "glioma": {"label": "Glioma / brain cancer", "keywords": ["glioma", "glioblastoma"]},
}


def infer_starter_vocab(*texts: str) -> dict[str, dict]:
    """Seed a starter disease vocabulary by matching the catalog against the
    project's scope statement / name / description. Deterministic (no LLM).
    Returns {} when nothing matches — the caller then leaves the project
    unconfigured, exactly as before."""
    hay = " ".join(t for t in texts if t).lower()
    if not hay.strip():
        return {}
    out: dict[str, dict] = {}
    for key, meta in _STARTER_DISEASE_CATALOG.items():
        if any(kw in hay for kw in meta["keywords"]):
            out[key] = {"label": meta["label"], "keywords": list(meta["keywords"])}
    return out


def parse_vocab(raw: str | None) -> dict[str, dict]:
    """Parse a stored `disease_vocab_json` into a normalized vocab dict. Returns
    {} when unset or malformed — callers treat empty as 'disease filtering off'."""
    import json
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for key, meta in data.items():
        if not isinstance(meta, dict):
            continue
        label = str(meta.get("label") or key)
        kws = meta.get("keywords") or []
        if isinstance(kws, str):
            kws = [kws]
        kws = [str(k).strip().lower() for k in kws if str(k).strip()]
        if kws:
            out[str(key)] = {"label": label, "keywords": kws}
    return out
