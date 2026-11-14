import numpy as np
import pytest
from common.embedding import DIM, compute_scale, quantize, score_to_cosine


def test_scale_maps_largest_value_to_127():
    v = np.array([[0.1, -0.4], [0.2, 0.3]], dtype=np.float32)
    s = compute_scale(v)
    assert s == pytest.approx(127 / 0.4)
    q = quantize(v, s)
    assert q.dtype == np.int8 and q.min() == -127


def test_quantize_clips_query_values_beyond_corpus_range():
    q = quantize(np.array([2.0, -2.0, 0.0], dtype=np.float32), 127.0)
    assert q.tolist() == [127, -127, 0]


def test_score_to_cosine_approximates_float_dot():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(2, DIM)).astype(np.float32)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    s = compute_scale(np.stack([a, b]))
    raw = int(quantize(a, s).astype(np.int32) @ quantize(b, s).astype(np.int32))
    assert score_to_cosine(raw, s) == pytest.approx(float(a @ b), abs=0.02)


@pytest.mark.slow
def test_real_model_is_normalized_and_ranks_sensibly():
    from common.embedding import embed_query_float, embed_texts
    docs = embed_texts(["Knee pain when climbing stairs", "How to file your tax return"])
    assert docs.shape == (2, DIM)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-3)
    q = embed_query_float("my knee hurts on stairs")
    assert q @ docs[0] > q @ docs[1]
