import json
from uuid import UUID, uuid4

from portfolio_architect.db.pool import _ConnProxy


def _decode(row: dict) -> dict:
    """Decode JSON-encoded fields and normalise booleans."""
    if row is None:
        return row
    if isinstance(row.get("source_ids"), str):
        row["source_ids"] = json.loads(row["source_ids"])
    row["is_gold"] = bool(row.get("is_gold", 0))
    return row


async def insert_criteria(
    conn: _ConnProxy,
    project_id: UUID,
    workstream_run_id: UUID | None,
    criteria: list[dict],
) -> list[dict]:
    pid = str(project_id)
    wsid = str(workstream_run_id) if workstream_run_id else None
    rows = []
    for c in criteria:
        cid = str(uuid4())
        source_ids = json.dumps(c.get("source_ids", []))
        row = await conn.fetchrow(
            """
            INSERT INTO criteria
                (id, project_id, workstream_run_id, criterion_type, statement,
                 rationale, source_ids, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING *
            """,
            cid, pid, wsid,
            c.get("type", c.get("criterion_type", "inclusion")),
            c["statement"],
            c.get("rationale", ""),
            source_ids,
            c.get("confidence", 0.0),
        )
        rows.append(_decode(row))
    return rows


async def get_criteria(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM criteria WHERE project_id = ? ORDER BY criterion_type, created_at",
        str(project_id),
    )
    return [_decode(r) for r in rows]


async def get_gold_criteria(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM criteria WHERE project_id = ? AND is_gold = 1 ORDER BY gold_set_at",
        str(project_id),
    )
    return [_decode(r) for r in rows]


async def patch_criterion(
    conn: _ConnProxy,
    criterion_id: UUID,
    project_id: UUID,
    patch: dict,
) -> dict | None:
    updates: list[str] = []
    values: list = []

    if patch.get("statement") is not None:
        updates.append("statement = ?")
        values.append(patch["statement"])
    if patch.get("is_gold") is not None:
        updates.append("is_gold = ?")
        values.append(1 if patch["is_gold"] else 0)
        if patch["is_gold"]:
            updates.append("gold_set_at = datetime('now')")
    if patch.get("gold_note") is not None:
        updates.append("gold_note = ?")
        values.append(patch["gold_note"])

    cid, pid = str(criterion_id), str(project_id)

    if not updates:
        row = await conn.fetchrow(
            "SELECT * FROM criteria WHERE id = ? AND project_id = ?", cid, pid
        )
        return _decode(row) if row else None

    updates.append("updated_at = datetime('now')")
    values.extend([cid, pid])
    sql = f"UPDATE criteria SET {', '.join(updates)} WHERE id = ? AND project_id = ? RETURNING *"
    row = await conn.fetchrow(sql, *values)
    return _decode(row) if row else None


async def upsert_gold_label(conn: _ConnProxy, project_id: UUID, label_data: dict) -> dict:
    lid = str(uuid4())
    cid = str(label_data["criterion_id"]) if label_data.get("criterion_id") else None
    row = await conn.fetchrow(
        """
        INSERT INTO gold_labels
            (id, project_id, criterion_id, text_sample, label, note, is_hard_constraint, cluster_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        lid, str(project_id), cid,
        label_data["text_sample"],
        label_data["label"],
        label_data.get("note"),
        1 if label_data.get("is_hard_constraint", True) else 0,
        label_data.get("cluster_id"),
    )
    row["is_hard_constraint"] = bool(row["is_hard_constraint"])
    return row


async def delete_criterion(conn: _ConnProxy, criterion_id: UUID, project_id: UUID) -> bool:
    row = await conn.fetchrow(
        "SELECT id FROM criteria WHERE id = ? AND project_id = ?",
        str(criterion_id), str(project_id),
    )
    if not row:
        return False
    await conn.execute(
        "DELETE FROM criteria WHERE id = ? AND project_id = ?",
        str(criterion_id), str(project_id),
    )
    return True


async def get_gold_labels(conn: _ConnProxy, project_id: UUID) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM gold_labels WHERE project_id = ? ORDER BY created_at",
        str(project_id),
    )
    for r in rows:
        r["is_hard_constraint"] = bool(r["is_hard_constraint"])
    return rows
