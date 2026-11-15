import numpy as np
import pytest
from common.embedding import DIM, SCALE, quantize, score_to_cosine


def test_scale_is_fixed_at_127():
    assert SCALE == 127
    q = quantize(np.array([[0.1, -0.4], [0.2, 1.0]], dtype=np.float32), SCALE)
    assert q.dtype == np.int8
    assert q.tolist() == [[13, -51], [25, 127]]


def test_quantize_clips_query_values_beyond_corpus_range():
    q = quantize(np.array([2.0, -2.0, 0.0], dtype=np.float32), 127.0)
    assert q.tolist() == [127, -127, 0]


def test_score_to_cosine_approximates_float_dot():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(2, DIM)).astype(np.float32)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    raw = int(quantize(a, SCALE).astype(np.int32) @ quantize(b, SCALE).astype(np.int32))
    assert score_to_cosine(raw, SCALE) == pytest.approx(float(a @ b), abs=0.03)


@pytest.mark.slow
def test_real_model_is_normalized_and_ranks_sensibly():
    from common.embedding import embed_query_float, embed_texts
    docs = embed_texts(["Knee pain when climbing stairs", "How to file your tax return"])
    assert docs.shape == (2, DIM)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-3)
    q = embed_query_float("my knee hurts on stairs")
    assert q @ docs[0] > q @ docs[1]
