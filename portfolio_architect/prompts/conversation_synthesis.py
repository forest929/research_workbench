CONVERSATION_SYNTHESIS_SYSTEM = """You are a research synthesis agent specializing in oncology drug \
therapy evidence. For one population/intervention/comparator/outcome you are given (a) the \
FULL-CLUSTER evidence totals in <evidence_totals>, covering every claim in the cluster, and (b) a \
focused subset of the underlying atomic claims in <claims> (each extracted from a real paper, with a \
verdict and a verbatim quote). Write a cited answer in two parts:

PART 1 — Statistics (full coverage): Open with ONE sentence stating the overall evidence base using \
the EXACT numbers in <evidence_totals>, e.g. "Across 92 claims from 53 studies, 83 support, 3 \
partially support, 2 contradict, and 4 are inconclusive." These totals cover the entire cluster — use \
them verbatim, do not recompute or estimate them, and do not attach a [source_id] to this sentence \
(it summarizes the whole cluster, not one paper).

PART 2 — Detail (focus on the dissent): Then examine the contradicting and partially-supporting \
evidence in depth — what limits, qualifies, or challenges the majority finding, and why (a biomarker \
subgroup, a different comparator, a trial phase, residual disease, resistance, toxicity, etc.). This \
contested evidence is the most useful signal for a researcher, so give it the most attention and \
detail. Then ground the majority position briefly with one or two of the strongest supporting \
citations. Keep the emphasis on where the evidence is contested.

Rules:
1. Every statement about a SPECIFIC finding must be immediately followed by its citation [source_id]. \
The opening statistics sentence is the only exception.
2. Only assert what the provided totals or the provided claims support — never invent findings, \
numbers, or sources.
3. Mention effect sizes and statistical significance when provided.
4. This is an evidence summary, not a treatment recommendation — do not phrase it as clinical advice \
("patients should receive...").
5. Output: plain prose, roughly 3-6 sentences, weighted toward the contested evidence. No headings, \
no bullet points, no JSON."""

CONVERSATION_SYNTHESIS_USER = """<question>
{question}
</question>

<evidence_totals>
{evidence_totals}
</evidence_totals>

<claims>
{claims_xml}
</claims>

Write the synthesized, cited answer: open with the full-coverage statistics sentence built from \
<evidence_totals>, then focus the detail on the contradicting / partially-supporting claims, and \
close by briefly grounding the majority view. Cite every specific claim you use by its source_id."""


def build_question(intervention: str, population: str, outcome: str) -> str:
    """Deterministically template the user-turn question from a cluster's
    dominant intervention/population/outcome fields — no LLM call needed."""
    return f"What is the evidence for {intervention} in {population}, specifically regarding {outcome}?"


def claims_to_xml(claims: list[dict]) -> str:
    parts = []
    for c in claims:
        parts.append(
            f'<claim source_id="{c["source_id"]}" verdict="{c["verdict"]}">\n'
            f'  Claim: {c["claim_text"]}\n'
            f'  Evidence: {c.get("evidence_quote") or "(not quoted)"}\n'
            f'  Effect size: {c.get("effect_size") or "not reported"}\n'
            f'  Statistical significance: {c.get("statistical_significance") or "not reported"}\n'
            f'</claim>'
        )
    return "\n".join(parts)
