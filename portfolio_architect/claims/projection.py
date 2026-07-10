"""Persisted 2D PCA projection model, so add-by-DOI can place a new cluster on
the SAME map axes the batch layout used (scripts/compute_cluster_coords.py).

The model = the training mean, the top-2 principal components, and the per-axis
min/span used to normalise into the frontend's [-1, 1] box. Stored as an .npz
file per project under data/.
"""

from pathlib import Path

import numpy as np

_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "projection_models"


def _model_path(project_id: str) -> Path:
    return _MODEL_DIR / f"{project_id}.npz"


def save_model(project_id: str, mean: np.ndarray, components: np.ndarray, bounds: list[tuple[float, float]]) -> None:
    """`components` is (dim, 2); `bounds` is [(min, span), (min, span)]."""
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(
        _model_path(project_id),
        mean=mean.astype(np.float32),
        components=components.astype(np.float32),
        bounds=np.array(bounds, dtype=np.float64),
    )


def project_point(project_id: str, embedding: list[float] | np.ndarray) -> tuple[float, float] | None:
    """Project a single embedding to normalised (x, y). Returns None if no model
    has been computed yet (caller should fall back, e.g. place near a neighbour)."""
    path = _model_path(project_id)
    if not path.exists():
        return None
    m = np.load(path)
    mean, comps, bounds = m["mean"], m["components"], m["bounds"]
    v = np.asarray(embedding, dtype=np.float32) - mean
    xy = v @ comps  # (2,)
    out = []
    for j in range(2):
        cmin, span = bounds[j]
        out.append(float(2 * (xy[j] - cmin) / (span or 1.0) - 1))
    return out[0], out[1]
