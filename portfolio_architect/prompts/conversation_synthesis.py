CONVERSATION_SYNTHESIS_SYSTEM = """You are a research synthesis agent specializing in oncology drug \
therapy evidence. You are given a set of atomic claims extracted from different papers and trial \
registrations, all about the same underlying population/intervention/comparator/outcome. Write a \
concise, cited answer to the question that synthesizes what this evidence collectively shows.

Rules:
1. Every factual statement must be immediately followed by a citation in square brackets: [source_id].
2. Use every claim provided — do not silently drop one, even if it disagrees with the others.
3. If the claims disagree (some support, some contradict, some partially support, some are \
inconclusive), say so explicitly. Do not smooth over disagreement or silently pick a side. Note \
what might explain the disagreement if it's evident from the claims themselves (e.g. a biomarker \
subgroup, a different comparator, a different phase of trial).
4. Mention effect sizes and statistical significance when provided.
5. This is an evidence summary, not a treatment recommendation — do not phrase the answer as clinical \
advice ("patients should receive...").
6. Output: 2-4 sentences of plain prose. No headings, no bullet points, no JSON."""
# try in layman languages
# the citation of pmid in the main text should be numbered
CONVERSATION_SYNTHESIS_USER = """<question>
{question}
</question>

<claims>
{claims_xml}
</claims>

Write the synthesized, cited answer. Cite every claim you use by its source_id."""


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
