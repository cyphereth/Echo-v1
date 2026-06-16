import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np


def test_embed_returns_matrix_shape_and_dtype(monkeypatch):
    import radar.embeddings as E

    class _FakeModel:
        def encode(self, texts, normalize_embeddings, convert_to_numpy):
            return np.array([[float(len(t)), 0.0, 0.0] for t in texts], dtype=np.float32)

    # monkeypatch replaces the cached function object itself, so lru_cache is bypassed.
    monkeypatch.setattr(E, "_model", lambda: _FakeModel())
    out = E.embed(["a", "bb"])
    assert out.shape == (2, 3)
    assert out.dtype == np.float32


def test_embed_empty_returns_zero_rows():
    import radar.embeddings as E
    out = E.embed([])
    assert out.shape == (0, E.EMBED_DIM)
