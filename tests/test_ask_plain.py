import numpy as np
import pytest
from baseline import ask_plain as mod
from baseline.retrieve import PlainIndex
from ingest.build import write_artifacts


def test_ask_plain_wires_retrieval_into_answer(tmp_path, monkeypatch):
    v = np.eye(384, dtype=np.float32)[:20]
    chunks = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"t{i}",
               "embed_text": ""} for i in range(20)]
    write_artifacts(chunks, v, tmp_path, "v")
    monkeypatch.setattr(mod, "embed_query_float", lambda q: v[4])
    got = {}

    def fake_answer(q, cs):
        got["ids"] = [c["id"] for c in cs]
        return {"status": "answered", "answer": "a", "citations": [], "timings": {"answer_ms": 1.0}}

    r = mod.ask_plain("q", k=10, index=PlainIndex(tmp_path), answer_fn=fake_answer)
    assert got["ids"][0] == 4 and len(got["ids"]) == 10
    assert set(r["timings"]) == {"embed_ms", "retrieve_ms", "answer_ms"}


@pytest.mark.slow
def test_real_question_end_to_end():
    r = mod.ask_plain("What is an A1C test?")
    assert r["status"] in ("answered", "declined")
    assert all("url" in c for c in r["citations"])
