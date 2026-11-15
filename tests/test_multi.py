"""MultiPipeline: merge across servers, fixed k per server, embedding compatibility. No servers needed."""
import pytest

from client import mock_crypto_client
from client.multi import MultiPipeline, configured_servers
from client.pipeline import PipelineError

MAN = {"protocol": "blind-rag/1", "corpus_version": "v", "num_chunks": 100, "top_k": 3,
       "embedding": {"model": "BAAI/bge-small-en-v1.5", "revision": "r", "dim": 384, "query_prefix": "p"},
       "quantization": {"scale": 127}}


def make(servers, chunks_by_server, manifests=None, answer=None):
    seen = {}

    def ans(q, chunks):
        seen["chunks"] = chunks
        return {"status": "answered", "answer": "a", "citations": []}

    m = MultiPipeline(servers, crypto=mock_crypto_client, answer_fn=answer or ans)
    for i, p in enumerate(m.pipes):
        man = (manifests or {}).get(p.server, MAN)
        p.load_manifest = lambda force=False, man=man: man
        chunks = chunks_by_server[p.server]
        p.retrieve = lambda q, on_stage=None, chunks=chunks, man=man: (
            [dict(c) for c in chunks],
            {"timings": {"scoring": 0.1}, "requests": [{"endpoint": "/v1/score", "request_bytes": 1, "response_bytes": 2}],
             "corpus_version": man["corpus_version"], "num_chunks": man["num_chunks"], "top_k": man["top_k"],
             "top_ids": [c["id"] for c in chunks], "mock": True, "mode": {}, "started_utc": "1", "ended_utc": "2"})
    return m, seen


def ch(i, s):
    return {"id": i, "title": f"t{i}", "url": f"u{i}", "updated": "d", "text": f"x{i}", "score": s}


def test_merges_by_score_and_answers_once_with_top_k():
    m, seen = make(["http://a", "http://b"], {"http://a": [ch(1, .9), ch(2, .5), ch(3, .4)],
                                              "http://b": [ch(7, .8), ch(8, .7), ch(9, .1)]})
    r, t = m.ask_traced("q")
    assert [c["id"] for c in seen["chunks"]] == [1, 7, 8]
    assert [c["server"] for c in seen["chunks"]] == ["http://a", "http://b", "http://b"]
    assert t["multi"] and t["top_sources"] == [["http://a", 1], ["http://b", 7], ["http://b", 8]]
    assert [(s["fetched"], s["used"]) for s in t["servers"]] == [(3, 1), (3, 2)]   # each fetched exactly k
    assert {r["server"] for r in t["requests"]} == {"http://a", "http://b"}


def test_ties_break_by_numeric_record_id():
    m, seen = make(["http://a", "http://b"], {"http://a": [ch(1026, .5)], "http://b": [ch(633, .5)]})
    m.ask_traced("q")
    assert [c["id"] for c in seen["chunks"]][:2] == [633, 1026]


def test_refuses_servers_with_a_different_embedding_setup():
    other = {**MAN, "embedding": {**MAN["embedding"], "model": "other/model"}}
    m, _ = make(["http://a", "http://b"], {"http://a": [ch(1, .9)], "http://b": [ch(2, .8)]},
                manifests={"http://b": other})
    with pytest.raises(PipelineError, match="different embedding setup"):
        m.ask_traced("q")


def test_scale_mismatch_is_refused_too():
    other = {**MAN, "quantization": {"scale": 200}}
    m, _ = make(["http://a", "http://b"], {"http://a": [ch(1, .9)], "http://b": [ch(2, .8)]},
                manifests={"http://b": other})
    with pytest.raises(PipelineError):
        m.ask_traced("q")


def test_needs_distinct_non_empty_selection():
    with pytest.raises(PipelineError):
        MultiPipeline([], crypto=mock_crypto_client, answer_fn=lambda q, c: {})
    with pytest.raises(PipelineError):
        MultiPipeline(["http://a", "http://a/"], crypto=mock_crypto_client, answer_fn=lambda q, c: {})


def test_configured_servers(monkeypatch):
    monkeypatch.setenv("BLIND_RAG_SERVERS", "http://a/, http://b,http://a")
    assert configured_servers() == ["http://a", "http://b"]
    monkeypatch.delenv("BLIND_RAG_SERVERS")
    monkeypatch.setenv("BLIND_RAG_SERVER", "http://c")
    assert configured_servers() == ["http://c"]
