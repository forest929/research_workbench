"""Artifact Layer: render a living Markdown report with margin annotations.

Margin annotations are rendered as blockquotes immediately after each claim,
linking every statement back to its source_ids.
"""

import asyncpg
from uuid import UUID
from datetime import datetime

from portfolio_architect.db.projects import get_project
from portfolio_architect.db.criteria import get_criteria
from portfolio_architect.db.judge_verdicts import get_latest_verdict


def _score_badge(score: int | None) -> str:
    if score is None:
        return ""
    if score >= 4:
        return f"**{score}/5** ✓"
    if score >= 3:
        return f"**{score}/5** ~"
    return f"**{score}/5** ✗"


def _verdict_badge(verdict: str | None) -> str:
    if verdict == "pass":
        return "> **VERDICT: PASS** — Criteria are grounded and scope-faithful."
    if verdict == "death_spiral":
        return "> **VERDICT: DEATH SPIRAL** — Unresolvable contradictions detected. Human intervention required."
    return "> **VERDICT: FAIL** — One or more quality dimensions scored below threshold."


async def render_report(conn: asyncpg.Connection, project_id: UUID) -> str:
    project = await get_project(conn, project_id)
    if not project:
        return "# Error\n\nProject not found."

    criteria = await get_criteria(conn, project_id)
    verdict = await get_latest_verdict(conn, project_id)

    inclusions = [c for c in criteria if c["criterion_type"] == "inclusion"]
    exclusions = [c for c in criteria if c["criterion_type"] == "exclusion"]
    gold_criteria = [c for c in criteria if c["is_gold"]]

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Portfolio Scope Report: {project['name']}",
        f"",
        f"*Generated {now} · Iteration {project['iteration_count']} · State: `{project['state']}`*",
        f"",
        f"---",
        f"",
        f"## Research Scope Statement",
        f"",
        f"> {project['scope_statement']}",
        f"",
        f"---",
        f"",
    ]

    # Judge scorecard
    if verdict:
        lines += [
            "## Quality Assessment (LLM-as-Judge)",
            "",
            f"| Dimension | Score | Rationale |",
            f"|-----------|-------|-----------|",
        ]
        dims = [
            ("Faithfulness / Groundedness", "faithfulness_score", "faithfulness_rationale"),
            ("Problem-Statement Integrity", "problem_integrity_score", "problem_integrity_rationale"),
            ("Citation Accuracy", "citation_accuracy_score", "citation_accuracy_rationale"),
            ("Transparency of Uncertainty", "uncertainty_score", "uncertainty_rationale"),
        ]
        for label, score_key, rationale_key in dims:
            score = verdict.get(score_key)
            rationale = verdict.get(rationale_key, "")
            badge = _score_badge(score)
            lines.append(f"| {label} | {badge} | {rationale} |")

        lines += [
            f"",
            f"**Overall: {_score_badge(verdict.get('overall_score'))}**",
            f"",
            _verdict_badge(verdict.get("verdict")),
            f"",
            "---",
            "",
        ]

    # Inclusion criteria
    lines += [
        "## Inclusion Criteria",
        "",
        f"*{len(inclusions)} criteria extracted.*",
        "",
    ]
    for i, c in enumerate(inclusions, 1):
        gold_tag = " 🔒 **[GOLD VALUE]**" if c["is_gold"] else ""
        sources = ", ".join(f"`{sid}`" for sid in (c["source_ids"] or []))
        lines += [
            f"### I{i}.{gold_tag} {c['statement']}",
            f"",
            f"{c['rationale']}",
            f"",
            f"> **Sources:** {sources or '_none cited_'}",
        ]
        if c.get("gold_note"):
            lines.append(f"> **Analyst note:** {c['gold_note']}")
        lines.append("")

    lines += ["---", "", "## Exclusion Criteria", "", f"*{len(exclusions)} criteria extracted.*", ""]
    for i, c in enumerate(exclusions, 1):
        gold_tag = " 🔒 **[GOLD VALUE]**" if c["is_gold"] else ""
        sources = ", ".join(f"`{sid}`" for sid in (c["source_ids"] or []))
        lines += [
            f"### E{i}.{gold_tag} {c['statement']}",
            f"",
            f"{c['rationale']}",
            f"",
            f"> **Sources:** {sources or '_none cited_'}",
        ]
        if c.get("gold_note"):
            lines.append(f"> **Analyst note:** {c['gold_note']}")
        lines.append("")

    # Gold values summary
    if gold_criteria:
        lines += [
            "---",
            "",
            "## Gold Values (Hard Constraints)",
            "",
            "*The following criteria are locked by human review and cannot be overridden by agents:*",
            "",
        ]
        for c in gold_criteria:
            tag = "I" if c["criterion_type"] == "inclusion" else "E"
            lines.append(f"- **[{tag}]** {c['statement']}")
            if c.get("gold_note"):
                lines.append(f"  - *Analyst note: {c['gold_note']}*")
        lines.append("")

    # Death spiral notice
    if project.get("death_spiral_reason"):
        lines += [
            "---",
            "",
            "> ⚠️ **DEATH SPIRAL DETECTED**",
            f"> {project['death_spiral_reason']}",
            "> Human resolution required before the next analysis run.",
            "",
        ]

    lines += [
        "---",
        "",
        "*This report was generated by the AI Portfolio Architect. "
        "All criteria are grounded in source documents provided to the system. "
        "This is a research tool, not a compliance or legal instrument.*",
    ]

    return "\n".join(lines)
