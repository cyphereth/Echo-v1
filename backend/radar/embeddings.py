from __future__ import annotations
from functools import lru_cache
import numpy as np

_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def _model():
    # Imported lazily so tests can monkeypatch _model without importing torch.
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(_MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    """(len(texts), EMBED_DIM) float32, L2-normalized.

    e5 expects a task prefix; we treat posts as 'passage'.
    """
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    prefixed = [f"passage: {t or ''}" for t in texts]
    vecs = _model().encode(
        prefixed, normalize_embeddings=True, convert_to_numpy=True
    )
    return np.asarray(vecs, dtype=np.float32)
