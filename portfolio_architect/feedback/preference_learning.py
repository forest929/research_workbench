"""Detect reviewer preferences from feedback patterns and generate prompt guidance text."""

from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy

_THRESHOLD = 3  # minimum occurrences before a pattern is surfaced

REASON_LABELS = {
    "REVIEW_ARTICLE": "review articles",
    "SIMULATION_ONLY": "simulation-only studies",
    "GREENHOUSE_ONLY": "greenhouse-only experiments",
    "WRONG_POPULATION": "wrong population",
    "WRONG_INTERVENTION": "wrong intervention",
    "WRONG_OUTCOME": "wrong outcome",
    "PROTOCOL_PAPER": "protocol or registration papers",
    "DUPLICATE": "duplicate records",
    "LANGUAGE": "non-English papers",
    "DATE": "papers outside the date range",
    "NO_ABSTRACT": "papers without an abstract",
    "OTHER": "other reasons",
}


def _observation_text(reason_code: str, label: str, count: int) -> str:
    reason_desc = REASON_LABELS.get(reason_code, reason_code.lower().replace("_", " "))
    action = "included" if label == "include" else "excluded"
    return (
        f"Reviewers have consistently {action} {reason_desc} "
        f"({count} times). Apply this pattern to similar papers."
    )


async def update_preferences(
    conn: _ConnProxy,
    project_id: UUID,
    reason_code: str | None,
    human_label: str,
) -> None:
    """Upsert a preference observation after each human decision with a reason code."""
    if not reason_code:
        return
    pid = str(project_id)
    existing = await conn.fetch(
        "SELECT id, count FROM preference_observations WHERE project_id = ? AND reason_code = ? AND label = ?",
        pid, reason_code, human_label,
    )
    if existing:
        new_count = existing[0]["count"] + 1
        obs_text = _observation_text(reason_code, human_label, new_count)
        await conn.execute(
            """UPDATE preference_observations
               SET count = ?, observation = ?, last_seen = datetime('now')
               WHERE id = ?""",
            new_count, obs_text, existing[0]["id"],
        )
    else:
        obs_text = _observation_text(reason_code, human_label, 1)
        await conn.execute(
            """INSERT INTO preference_observations
                   (id, project_id, reason_code, label, observation, count)
               VALUES (?, ?, ?, ?, ?, 1)""",
            str(uuid4()), pid, reason_code, human_label, obs_text,
        )


async def get_preferences(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    """Return preference observations that have hit the threshold."""
    rows = await conn.fetch(
        """SELECT reason_code, label, observation, count
           FROM preference_observations
           WHERE project_id = ? AND count >= ?
           ORDER BY count DESC""",
        str(project_id), _THRESHOLD,
    )
    return [dict(r) for r in rows]


async def build_guidance_text(conn: _ConnProxy, project_id: UUID) -> str:
    """Return a short block of reviewer-preference guidance to inject into prompts."""
    prefs = await get_preferences(conn, project_id)
    if not prefs:
        return ""
    lines = ["Observed reviewer preferences for this project:"]
    for p in prefs:
        lines.append(f"- {p['observation']}")
    return "\n".join(lines)
