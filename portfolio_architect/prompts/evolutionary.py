MUTATION_SYSTEM = """You are a labeling function engineer. Your job is to improve a Python \
labeling function that assigns "inclusion", "exclusion", or "ambiguous" to text samples, \
guided by portfolio criteria.

Generate {n} improved variants. Each variant must:
- Be a complete Python function named label_text(text: str, criteria: list[dict]) -> str
- Return exactly one of: "inclusion", "exclusion", "ambiguous"
- Handle at least one of the failure cases better than the current function
- Be valid Python 3.12 syntax (will be exec()d and tested)
- Not import any external libraries; only stdlib is available

Output: strict JSON only.
{{
  "mutations": [
    {{
      "code": "<complete Python function as a string>",
      "rationale": "one sentence: what edge case this targets",
      "edge_case_targeted": "description of the failure case being fixed"
    }}
  ]
}}"""

MUTATION_USER = """<gold_labels>
{gold_labels_json}
</gold_labels>

<current_labeling_function>
{current_fn_code}
</current_labeling_function>

<failure_cases>
{failure_cases_json}
</failure_cases>

Generate exactly {n} mutation variants. Return only the JSON object."""

DISCREPANCY_SYSTEM = """You are a research scope mediator. You receive two competing scope \
definitions and must identify points of semantic friction — where wording, evidence \
interpretation, or scope boundaries conflict.

Output: strict JSON only.
{
  "friction_points": [
    {
      "summary": "one sentence",
      "position_a": "Team A's position",
      "position_b": "Team B's position",
      "friction_type": "wording" | "evidence_interpretation" | "scope_boundary" | "contradictory"
    }
  ],
  "recommendation": "one paragraph on how to resolve the tensions"
}"""

DISCREPANCY_USER = """<definition label="{label_a}">
{definition_a}
</definition>

<definition label="{label_b}">
{definition_b}
</definition>

Identify all points of semantic friction. Return only the JSON object."""

DEFAULT_LABELING_FUNCTION = '''def label_text(text: str, criteria: list[dict]) -> str:
    """Baseline labeling function. Uses keyword matching against criteria statements."""
    text_lower = text.lower()
    inclusion_hits = 0
    exclusion_hits = 0
    for criterion in criteria:
        statement_lower = criterion.get("statement", "").lower()
        keywords = [w for w in statement_lower.split() if len(w) > 4]
        matches = sum(1 for kw in keywords if kw in text_lower)
        if matches >= 2:
            if criterion.get("type") == "inclusion":
                inclusion_hits += 1
            elif criterion.get("type") == "exclusion":
                exclusion_hits += 1
    if exclusion_hits > inclusion_hits:
        return "exclusion"
    if inclusion_hits > 0:
        return "inclusion"
    return "ambiguous"
'''
