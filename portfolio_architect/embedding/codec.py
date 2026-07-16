"""Compact, fast storage codec for embedding vectors.

Embeddings were originally stored as JSON text — readable, but ~4× larger than
the raw floats and slow to parse (`json.loads` on a 4096-float claim vector is a
real cost at corpus scale, and it's on the hot cluster/retrieval paths). We now
store them as packed little-endian float32 bytes, which SQLite keeps as a BLOB
even in a TEXT-affinity column (BLOB values are never coerced by TEXT affinity).

`decode` accepts BOTH the new float32 bytes and legacy JSON text, so existing
rows keep working with or without the one-off migration
(`scripts/migrate_embeddings_to_blob.py`). Writers should always use `encode`.
"""

import json

import numpy as np

_DTYPE = "<f4"  # little-endian float32 — stable across the x86/ARM hosts we run on


def encode(vec):
    """Encode a vector for storage in the active backend's embedding column.

    - **SQLite:** packed little-endian float32 `bytes` (kept as a BLOB in the
      TEXT-affinity `embedding` column).
    - **Postgres:** a float32 `ndarray` — the column is `pgvector.vector` and the
      registered pgvector codec serializes the array. This keeps every call site
      (`codec.encode(vec)`) backend-agnostic.
    """
    arr = np.asarray(vec, dtype=_DTYPE)
    from portfolio_architect.config import get_settings

    if get_settings().db_backend == "postgres":
        return arr
    return arr.tobytes()


def decode(blob) -> np.ndarray | None:
    """Decode a stored embedding to a float32 ndarray. Accepts float32 bytes
    (SQLite BLOB), an ndarray/list (Postgres pgvector read), legacy JSON text, or
    None (→ None)."""
    if blob is None:
        return None
    if isinstance(blob, np.ndarray):
        return blob.astype(_DTYPE, copy=False)
    if isinstance(blob, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(blob), dtype=_DTYPE)
    if isinstance(blob, (list, tuple)):
        return np.asarray(blob, dtype=np.float32)
    return np.asarray(json.loads(blob), dtype=np.float32)  # legacy JSON text


def decode_list(blob) -> list[float] | None:
    """As `decode`, but returns a plain Python list (for the list-based k-NN /
    cosine helpers that predate numpy on those paths)."""
    arr = decode(blob)
    return None if arr is None else arr.tolist()
