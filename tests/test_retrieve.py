import numpy as np
import pytest
from baseline.retrieve import PlainIndex
from ingest.build import write_artifacts


@pytest.fixture
def index(tmp_path):
    rng = np.random.default_rng(2)
    v = rng.normal(size=(50, 384)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    chunks = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"t{i}",
               "embed_text": ""} for i in range(50)]
    write_artifacts(chunks, v, tmp_path, "v")
    np.save(tmp_path / "f.npy", v)
    return PlainIndex(tmp_path, float_path=tmp_path / "f.npy"), v


def test_exact_vector_ranks_first_in_both_modes(index):
    idx, v = index
    for mode in ("int8", "float"):
        hits = idx.search_vec(v[17], k=5, mode=mode)
        assert hits[0][0] == 17 and len(hits) == 5
        assert hits[0][1] == pytest.approx(1.0, abs=0.03)
        assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_chunks_carry_record_and_score(index):
    idx, v = index
    c = idx.chunks(idx.search_vec(v[3], k=1))[0]
    assert c["id"] == 3 and c["title"] == "T3" and "score" in c


def test_float_mode_without_float_vectors_raises(index, tmp_path):
    with pytest.raises(ValueError):
        PlainIndex(tmp_path).search_vec(index[1][0], mode="float")
