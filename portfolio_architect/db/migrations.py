"""Idempotent CREATE TABLE / CREATE INDEX statements for SQLite. Safe to re-run."""

from portfolio_architect.db.pool import _Pool

# New columns added to existing tables via ALTER TABLE (errors are silently ignored on re-run)
ALTER_STATEMENTS = [
    "ALTER TABLE documents ADD COLUMN screening_status TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE documents ADD COLUMN llm_label TEXT",
    "ALTER TABLE documents ADD COLUMN llm_confidence REAL",
    "ALTER TABLE documents ADD COLUMN llm_reasoning TEXT",
    "ALTER TABLE documents ADD COLUMN doc_embedding TEXT",
    "ALTER TABLE documents ADD COLUMN research_question TEXT",
    "ALTER TABLE documents ADD COLUMN claims_extracted INTEGER NOT NULL DEFAULT 0",
    # Publication date as "YYYY-MM" (or "YYYY" when month unknown). Backfilled from
    # the PubMed XML cache by scripts/backfill_pub_dates.py.
    "ALTER TABLE documents ADD COLUMN pub_date TEXT",
    "ALTER TABLE claims ADD COLUMN cluster_id TEXT",
    "ALTER TABLE claim_clusters ADD COLUMN citations_valid INTEGER",
    # Precomputed 2D map coordinates (PCA over cluster centroids). Stored so the
    # map endpoint never has to load ~16k embeddings at request time.
    "ALTER TABLE claim_clusters ADD COLUMN coord_x REAL",
    "ALTER TABLE claim_clusters ADD COLUMN coord_y REAL",
    # Provenance for user-added (add-by-DOI) clusters + count of user claims that
    # joined an existing corpus cluster — drive the distinct "user" bubble style.
    "ALTER TABLE claim_clusters ADD COLUMN origin TEXT NOT NULL DEFAULT 'corpus'",
    "ALTER TABLE claim_clusters ADD COLUMN user_claim_count INTEGER NOT NULL DEFAULT 0",
    # Cached LLM-as-judge verdict (flat JSON) for the cluster's synthesized
    # answer — computed once on demand, then reused (one judge call per answer).
    "ALTER TABLE claim_clusters ADD COLUMN judge_json TEXT",
]

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id                   TEXT PRIMARY KEY,
        name                 TEXT NOT NULL,
        description          TEXT NOT NULL DEFAULT '',
        scope_statement      TEXT NOT NULL,
        state                TEXT NOT NULL DEFAULT 'onboarding',
        death_spiral_reason  TEXT,
        iteration_count      INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_created ON projects(created_at)",
    """
    CREATE TABLE IF NOT EXISTS documents (
        id           TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        source_id    TEXT NOT NULL,
        doc_type     TEXT NOT NULL DEFAULT 'paper',
        raw_content  TEXT NOT NULL,
        embedded     INTEGER NOT NULL DEFAULT 0,
        chunk_count  INTEGER NOT NULL DEFAULT 0,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id)",
    # Each project has exactly one copy of each source document — enforced at the DB level
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_project_source ON documents(project_id, source_id)",
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id           TEXT PRIMARY KEY,
        document_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        project_id   TEXT NOT NULL,
        chunk_index  INTEGER NOT NULL,
        content      TEXT NOT NULL,
        embedding    TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project_id)",
    # Without this, ON DELETE CASCADE from documents does a full chunks scan per
    # deleted document, making project deletion O(documents x chunks) — minutes on
    # a large corpus. This FK index turns each cascade into an index lookup.
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_no_embed ON chunks(project_id) WHERE embedding IS NULL",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_id UNINDEXED,
        project_id UNINDEXED,
        content,
        tokenize='porter ascii'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS criteria (
        id                TEXT PRIMARY KEY,
        project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        workstream_run_id TEXT,
        criterion_type    TEXT NOT NULL,
        statement         TEXT NOT NULL,
        rationale         TEXT NOT NULL,
        source_ids        TEXT NOT NULL DEFAULT '[]',
        confidence        REAL NOT NULL DEFAULT 0.0,
        is_gold           INTEGER NOT NULL DEFAULT 0,
        gold_note         TEXT,
        gold_set_at       TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_criteria_project ON criteria(project_id)",
    """
    CREATE TABLE IF NOT EXISTS gold_labels (
        id                  TEXT PRIMARY KEY,
        project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        criterion_id        TEXT REFERENCES criteria(id) ON DELETE SET NULL,
        text_sample         TEXT NOT NULL,
        label               TEXT NOT NULL,
        note                TEXT,
        is_hard_constraint  INTEGER NOT NULL DEFAULT 1,
        cluster_id          TEXT,
        created_at          TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gold_labels_project ON gold_labels(project_id)",
    """
    CREATE TABLE IF NOT EXISTS workstream_runs (
        id           TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        run_id       TEXT NOT NULL,
        workstream   TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        result_json  TEXT,
        error_msg    TEXT,
        started_at   TEXT,
        finished_at  TEXT,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ws_runs_project_run ON workstream_runs(project_id, run_id)",
    """
    CREATE TABLE IF NOT EXISTS judge_verdicts (
        id                          TEXT PRIMARY KEY,
        project_id                  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        run_id                      TEXT NOT NULL,
        stage                       TEXT NOT NULL,
        faithfulness_score          INTEGER,
        faithfulness_rationale      TEXT,
        problem_integrity_score     INTEGER,
        problem_integrity_rationale TEXT,
        citation_accuracy_score     INTEGER,
        citation_accuracy_rationale TEXT,
        uncertainty_score           INTEGER,
        uncertainty_rationale       TEXT,
        overall_score               INTEGER,
        verdict                     TEXT NOT NULL,
        death_spiral_reason         TEXT,
        raw_llm_response            TEXT,
        created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_judge_verdicts_run ON judge_verdicts(project_id, run_id)",
    """
    CREATE TABLE IF NOT EXISTS query_log (
        id                TEXT PRIMARY KEY,
        project_id        TEXT REFERENCES projects(id) ON DELETE SET NULL,
        call_type         TEXT NOT NULL,
        model             TEXT NOT NULL,
        prompt_tokens     INTEGER,
        completion_tokens INTEGER,
        total_tokens      INTEGER,
        latency_ms        INTEGER,
        success           INTEGER NOT NULL DEFAULT 1,
        error_msg         TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_query_log_project ON query_log(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at)",
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id                  TEXT PRIMARY KEY,
        project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        document_id         TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        llm_label           TEXT,
        llm_confidence      REAL,
        llm_reasoning       TEXT,
        human_label         TEXT NOT NULL,
        human_reason        TEXT,
        reason_code         TEXT,
        is_protocol_specific INTEGER NOT NULL DEFAULT 1,
        reviewer            TEXT,
        doc_embedding       TEXT,
        timestamp           TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_document ON decisions(document_id)",
    """
    CREATE TABLE IF NOT EXISTS disagreements (
        id              TEXT PRIMARY KEY,
        project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        document_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        llm_label       TEXT NOT NULL,
        human_label     TEXT NOT NULL,
        reason_code     TEXT,
        llm_confidence  REAL,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_disagreements_project ON disagreements(project_id)",
    """
    CREATE TABLE IF NOT EXISTS preference_observations (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        reason_code TEXT NOT NULL,
        label       TEXT NOT NULL,
        observation TEXT NOT NULL,
        count       INTEGER NOT NULL DEFAULT 1,
        last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(project_id, reason_code, label)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pref_obs_project ON preference_observations(project_id)",
    """
    CREATE TABLE IF NOT EXISTS claims (
        id                        TEXT PRIMARY KEY,
        project_id                TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        document_id               TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        claim_text                TEXT NOT NULL,
        population                TEXT,
        intervention              TEXT,
        comparator                TEXT,
        outcome                   TEXT,
        verdict                   TEXT NOT NULL,
        evidence_quote            TEXT,
        quote_verified            INTEGER NOT NULL DEFAULT 0,
        effect_size               TEXT,
        statistical_significance  TEXT,
        confidence                REAL,
        claim_embedding           TEXT,
        raw_llm_response          TEXT,
        created_at                TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_claims_document ON claims(document_id)",
    # Cluster lookups (workbench detail + centroid layout) filter/group by
    # cluster_id over a table whose rows carry a 4096-float embedding blob; without
    # this index every such query full-scans ~1 GB of pages (was ~2 min per call).
    "CREATE INDEX IF NOT EXISTS idx_claims_cluster ON claims(cluster_id)",
    """
    CREATE TABLE IF NOT EXISTS claim_clusters (
        id                      TEXT PRIMARY KEY,
        project_id              TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        intervention_key        TEXT NOT NULL,
        member_count            INTEGER NOT NULL,
        distinct_document_count INTEGER NOT NULL,
        verdict_mix_json        TEXT NOT NULL,
        question                TEXT,
        answer                  TEXT,
        created_at              TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_claim_clusters_project ON claim_clusters(project_id)",
    # Add-by-DOI background jobs: one row per user-submitted source, tracked so the
    # UI can poll status (fetch → extract → embed → cluster → done/failed).
    """
    CREATE TABLE IF NOT EXISTS user_sources (
        id            TEXT PRIMARY KEY,
        project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        doi           TEXT NOT NULL,
        source_id     TEXT,
        status        TEXT NOT NULL DEFAULT 'pending',
        message       TEXT,
        title         TEXT,
        claims_added  INTEGER NOT NULL DEFAULT 0,
        cluster_ids   TEXT NOT NULL DEFAULT '[]',
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_user_sources_project ON user_sources(project_id)",
    # Curated reading list: publications a researcher explicitly bookmarks while
    # reviewing clusters/conversations, or adds by DOI. Project-scoped, so each
    # project keeps its own separate curated set. UNIQUE(project_id, source_id)
    # makes save idempotent and lets ON CONFLICT upsert the note/title.
    """
    CREATE TABLE IF NOT EXISTS saved_publications (
        id          TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        source_id   TEXT NOT NULL,
        doi         TEXT,
        title       TEXT,
        note        TEXT,
        added_from  TEXT NOT NULL DEFAULT 'conversation',
        created_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_saved_pubs_project ON saved_publications(project_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_pubs_project_source ON saved_publications(project_id, source_id)",
    # Research-assistant Q&A history — every question + its cited, judged answer,
    # saved so a researcher can revisit past follow-ups. `payload_json` is the
    # full conversation-shaped result so the UI can re-render it exactly.
    """
    CREATE TABLE IF NOT EXISTS assistant_answers (
        id           TEXT PRIMARY KEY,
        project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        question     TEXT NOT NULL,
        answer       TEXT,
        payload_json TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_assistant_answers_project ON assistant_answers(project_id, created_at)",
    # Automatic drug-name canonicalization cache. `raw_key` is the cleaned
    # intervention string (output of normalize_intervention); `canonical` is the
    # LLM-assigned canonical name that groups its surface variants. Global (not
    # per-project) so a name canonicalized once is reused everywhere — this is
    # what makes the LLM pass one-time and the mapping deterministic.
    """
    CREATE TABLE IF NOT EXISTS drug_aliases (
        raw_key    TEXT PRIMARY KEY,
        canonical  TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


async def run_migrations(pool: _Pool, create_vector_index: bool = False) -> None:
    async with pool.acquire() as conn:
        for stmt in DDL_STATEMENTS:
            stmt = stmt.strip()
            if stmt:
                try:
                    await conn.execute(stmt)
                except Exception as e:
                    # Unique index creation will fail if duplicates exist — dedup first, then retry
                    if "UNIQUE" in stmt and "already exists" not in str(e).lower():
                        await conn.execute(
                            """
                            DELETE FROM documents
                            WHERE id NOT IN (
                                SELECT MIN(id) FROM documents
                                GROUP BY project_id, source_id
                            )
                            """
                        )
                        await conn.execute(stmt)
        # ALTER TABLE statements are not idempotent in SQLite; ignore duplicate column errors
        for stmt in ALTER_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception:
                pass

        # Per-project disease vocabulary. The ALTER + backfill are paired inside
        # one try: the UPDATE runs ONLY the first time the column is added (when
        # the ALTER succeeds), so existing projects get seeded with the
        # women's-cancer default while projects created later start unconfigured
        # (NULL) and are never retroactively seeded on subsequent boots.
        try:
            await conn.execute("ALTER TABLE projects ADD COLUMN disease_vocab_json TEXT")
            import json as _json
            from portfolio_architect.vocab import DEFAULT_DISEASE_VOCAB
            await conn.execute(
                "UPDATE projects SET disease_vocab_json = ? WHERE disease_vocab_json IS NULL",
                _json.dumps(DEFAULT_DISEASE_VOCAB),
            )
        except Exception:
            pass
    print("Migrations complete.")


async def list_tables(pool: _Pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT name FROM sqlite_master WHERE type IN ('table','shadow') ORDER BY name"
        )
    return [r["name"] for r in rows]
