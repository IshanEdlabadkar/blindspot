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


def _source(tmp_path, sid, seed, n=30):
    from types import SimpleNamespace
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, 384)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    meta = SimpleNamespace(SOURCE_ID=sid, SOURCE_NAME=f"Source {sid}", CORPUS_NAME="c", ATTRIBUTION="a")
    chunks = [{"id": i, "title": f"{sid}{i}", "url": f"{sid}/{i}", "updated": "d", "text": "t", "embed_text": ""}
              for i in range(n)]
    write_artifacts(chunks, v, tmp_path / sid, "v", meta)
    return v


def test_fetch_tags_chunks_with_their_source(index):
    idx, v = index
    c = idx.fetch(v[3], k=2)
    assert len(c) == 2 and c[0]["id"] == 3 and c[0]["source"] == "medlineplus" and "score" in c[0]


def test_multi_index_takes_exactly_k_from_every_source_and_merges(tmp_path):
    from baseline.retrieve import MultiIndex, discover_sources
    _source(tmp_path, "a", 1)
    vb = _source(tmp_path, "b", 2)
    dirs = discover_sources(tmp_path)
    assert [d.name for d in dirs] == ["a", "b"]
    idx = MultiIndex(dirs)
    assert idx.sources == ["a", "b"]
    got = idx.fetch(vb[7], k=4)
    assert len(got) == 8
    assert sum(c["source"] == "a" for c in got) == 4 and sum(c["source"] == "b" for c in got) == 4
    assert (got[0]["source"], got[0]["id"], got[0]["source_name"]) == ("b", 7, "Source b")
    assert [c["score"] for c in got] == sorted((c["score"] for c in got), reverse=True)


def test_discover_ignores_folders_without_a_manifest(tmp_path):
    from baseline.retrieve import discover_sources
    (tmp_path / "junk").mkdir()
    assert discover_sources(tmp_path) == []


def test_float_mode_without_float_vectors_raises(index, tmp_path):
    with pytest.raises(ValueError):
        PlainIndex(tmp_path).search_vec(index[1][0], mode="float")
