#!/usr/bin/env python3
"""
Precompute 2D map coordinates for every claim cluster (multi-source AND
singleton) and store them in claim_clusters.coord_x / coord_y.

The workbench map shows all verified claims — ~16k bubbles once singletons are
included — so it cannot afford to load 16k 4096-dim embeddings and run PCA on
every request. This one-off (pure-compute, no LLM) step does it offline:
one representative embedding per cluster → PCA to 2D via the covariance /
eigendecomposition route (cheap: a 4096×4096 eigh instead of an SVD over a
16k×4096 matrix). Re-run any time clustering changes.

Usage:
    python scripts/compute_cluster_coords.py --project-id <id>
"""

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from dotenv import load_dotenv
load_dotenv()

from portfolio_architect.db.pool import create_pool, close_pool
from portfolio_architect.db.migrations import run_migrations
from portfolio_architect.embedding import codec


async def main(args) -> None:
    project_id = str(UUID(args.project_id))
    pool = await create_pool()
    await run_migrations(pool)
    try:
        async with pool.acquire() as conn:
            # One representative embedding per cluster (GROUP BY over the
            # cluster_id index). Small columns + a single blob per group.
            rows = await conn.fetch(
                "SELECT cluster_id, claim_embedding FROM claims "
                "WHERE project_id = ? AND cluster_id IS NOT NULL "
                "AND claim_embedding IS NOT NULL GROUP BY cluster_id",
                project_id,
            )
        print(f"Loaded {len(rows)} cluster representatives; parsing embeddings...")
        ids = [r["cluster_id"] for r in rows]
        mat = np.array([codec.decode(r["claim_embedding"]) for r in rows], dtype=np.float32)
        print(f"Matrix {mat.shape}; computing top-2 PCA via covariance eigendecomposition...")

        mean = mat.mean(axis=0)
        centered = mat - mean
        cov = centered.T @ centered                     # (dim, dim)
        eigvals, eigvecs = np.linalg.eigh(cov)          # ascending eigenvalues
        top2 = eigvecs[:, -2:]                           # two largest components
        coords = centered @ top2                         # (n, 2)

        # Normalise to a stable [-1, 1] box so the frontend layout is consistent.
        bounds = []
        for j in range(2):
            col = coords[:, j]
            cmin = float(col.min()); span = float(col.max() - col.min()) or 1.0
            coords[:, j] = 2 * (col - cmin) / span - 1
            bounds.append((cmin, span))

        # Persist the projection model so add-by-DOI can place new clusters on the
        # SAME axes (see portfolio_architect/claims/projection.py).
        from portfolio_architect.claims.projection import save_model
        save_model(project_id, mean, top2, bounds)
        print("Saved PCA projection model.")

        async with pool.acquire() as conn:
            await conn.executemany(
                "UPDATE claim_clusters SET coord_x = ?, coord_y = ? WHERE id = ?",
                [(float(coords[i, 0]), float(coords[i, 1]), ids[i]) for i in range(len(ids))],
            )
        print(f"Stored coordinates for {len(ids)} clusters.")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Precompute 2D map coordinates for clusters.")
    p.add_argument("--project-id", required=True)
    asyncio.run(main(p.parse_args()))
