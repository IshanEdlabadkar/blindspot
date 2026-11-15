import json
import numpy as np
import pytest
from common.records import RECORD_BYTES
from common.tables import get_record, load_artifacts, verify_hashes
from ingest.build import write_artifacts


def fake(n=5):
    chunks = [{"id": i, "title": f"T{i}", "url": f"https://x/{i}", "updated": "2026-11-13",
               "text": f"text {i}", "embed_text": f"T{i}\ntext {i}"} for i in range(n)]
    v = np.random.default_rng(1).normal(size=(n, 384)).astype(np.float32)
    return chunks, v / np.linalg.norm(v, axis=1, keepdims=True)


def test_artifacts_round_trip(tmp_path):
    chunks, vecs = fake()
    m = write_artifacts(chunks, vecs, tmp_path, "2026-11-13.1")
    assert (tmp_path / "score_table.bin").stat().st_size == 5 * 384
    assert (tmp_path / "fetch_store.bin").stat().st_size == 5 * RECORD_BYTES
    assert m["num_chunks"] == 5 and m["pir"]["record_bytes"] == RECORD_BYTES
    assert m["quantization"] == {"type": "int8", "scale": 127}
    assert json.loads((tmp_path / "manifest.json").read_text()) == m

    m2, table, store = load_artifacts(tmp_path)
    verify_hashes(m2, tmp_path)
    assert table.shape == (5, 384) and table.dtype == np.int8
    assert np.array_equal(table, np.clip(np.rint(vecs * 127), -127, 127).astype(np.int8))
    assert get_record(store, 3) == {k: chunks[3][k] for k in ("id", "title", "url", "updated", "text")}
    lines = (tmp_path / "chunks.jsonl").read_text().splitlines()
    assert json.loads(lines[4])["id"] == 4


def test_hash_mismatch_raises(tmp_path):
    chunks, vecs = fake()
    m = write_artifacts(chunks, vecs, tmp_path, "v")
    (tmp_path / "score_table.bin").write_bytes(bytes(5 * 384))
    with pytest.raises(ValueError):
        verify_hashes(m, tmp_path)
