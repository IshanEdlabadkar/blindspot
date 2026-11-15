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


def test_merges_by_score_and_answers_once_with_every_fetched_passage():
    m, seen = make(["http://a", "http://b"], {"http://a": [ch(1, .9), ch(2, .5), ch(3, .4)],
                                              "http://b": [ch(7, .8), ch(8, .7), ch(9, .1)]})
    r, t = m.ask_traced("q")
    # all S x k passages, by score: the answer step reranks them (contracts.md section 9)
    assert [c["id"] for c in seen["chunks"]] == [1, 7, 8, 2, 3, 9]
    assert [c["server"] for c in seen["chunks"]][:3] == ["http://a", "http://b", "http://b"]
    assert t["multi"] and t["top_sources"][:3] == [["http://a", 1], ["http://b", 7], ["http://b", 8]]
    assert [(s["fetched"], s["used"]) for s in t["servers"]] == [(3, 3), (3, 3)]   # each fetched exactly k
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


def test_configured_servers_from_list_file(monkeypatch, tmp_path):
    monkeypatch.delenv("BLIND_RAG_SERVERS", raising=False)
    monkeypatch.delenv("BLIND_RAG_SERVER", raising=False)
    f = tmp_path / "s.json"
    f.write_text('[{"id": "a", "name": "A", "url": "https://a.example/"}, {"id": "b", "name": "B", "url": "http://b:1"}]')
    monkeypatch.setenv("BLIND_RAG_SERVERS_FILE", str(f))
    assert configured_servers() == ["https://a.example", "http://b:1"]
    monkeypatch.setenv("BLIND_RAG_SERVERS_FILE", str(tmp_path / "missing.json"))
    assert configured_servers() == ["http://127.0.0.1:8080"]


def test_same_passage_from_two_servers_is_used_once():
    same = [ch(1, .9), ch(2, .8), ch(3, .7)]
    m, seen = make(["http://local", "http://remote"], {"http://local": same, "http://remote": same})
    m.ask_traced("q")
    assert [c["id"] for c in seen["chunks"]] == [1, 2, 3]
    assert [c["server"] for c in seen["chunks"]] == ["http://local"] * 3


def test_question_embedded_once_across_servers(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from client import embed as emb
    monkeypatch.setenv("BLIND_RAG_EMBED", "fake")
    calls = []
    real = emb._fake
    monkeypatch.setattr(emb, "_fake", lambda t: calls.append(t) or real(t))
    with ThreadPoolExecutor(4) as ex:
        vs = list(ex.map(lambda _: emb.embed("a question asked once, searched on four servers"), range(4)))
    assert len(calls) == 1 and all((v == vs[0]).all() for v in vs)
    vs[0][0] = 99.0                                  # callers get copies, never the cached array
    assert emb.embed("a question asked once, searched on four servers")[0] != 99.0
