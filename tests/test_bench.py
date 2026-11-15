"""eval.bench end to end on the mock server (mock crypto, fake embedding, stub answers): no Go, no model."""
import json
import os
import pathlib
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["BLIND_RAG_EMBED"] = "fake"

from eval import bench  # noqa: E402
from mock_server.server import serve  # noqa: E402
from tools.make_dummy_tables import main as make_tables  # noqa: E402


@pytest.fixture(scope="module")
def servers(tmp_path_factory):
    out = []
    for _ in range(2):
        data = tmp_path_factory.mktemp("data")
        make_tables(out=data, n=300)
        httpd, _state = serve(data, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        out.append((f"http://127.0.0.1:{httpd.server_address[1]}", httpd))
    yield [u for u, _ in out]
    for _, h in out:
        h.shutdown()


@pytest.fixture()
def questions(tmp_path):
    qs = [{"id": "a1", "question": "What causes headaches?", "source_url": "https://x/none", "category": "basic",
           "expect": "answer", "urgent": None},
          {"id": "d1", "question": "Who won the football game?", "source_url": None, "category": "out_of_scope",
           "expect": "decline", "urgent": None}]
    p = tmp_path / "q.jsonl"
    p.write_text("\n".join(json.dumps(q) for q in qs) + "\n")
    return p


def run(tmp_path, questions, *extra):
    os.environ["BLIND_RAG_CRYPTO"] = "mock"
    out = tmp_path / "run"
    assert bench.main(["--questions", str(questions), "--out", str(out), "--server-log", "off", *extra]) == 0
    rows = [json.loads(ln) for ln in (out / "traces.jsonl").read_text().splitlines()]
    return out, rows, json.loads((out / "summary.json").read_text())


def test_single_server_trace_and_summary(tmp_path, servers, questions):
    out, rows, s = run(tmp_path, questions, "--servers", servers[0], "--answer", "stub", "--repeat", "2")
    assert len(rows) == 4 and not any(r["error"] for r in rows)
    r = rows[0]
    assert [sp["name"] for sp in r["trace"]["spans"]] == ["embedding", "encrypting", "scoring", "fetching", "answering"]
    assert len(r["trace"]["search"]) == r["trace"]["top_k"]          # always exactly k fetched
    assert any(q["endpoint"] == "/v1/score" for q in r["trace"]["requests"])
    assert r["bytes"]["up"] > 0 and r["bytes"]["down"] > 0
    assert s["accuracy"]["questions"] == 2 and s["accuracy"]["runs"] == 4
    assert s["accuracy"]["should_decline_declined"]["of"] == 1
    assert s["speed"]["stages_seconds"]["scoring"]["n"] == 3          # warm runs: all but the first
    assert s["privacy"]["fetched_per_server_always_k"] is True
    html = (out / "report.html").read_text()
    assert "Blind RAG benchmark" in html and '"rows"' in html and "</script>" in html
    assert "## Accuracy" in (out / "report.md").read_text()


def test_retrieval_only_and_multi_server(tmp_path, servers, questions):
    _, rows, s = run(tmp_path, questions, "--servers", ",".join(servers), "--answer", "none")
    r = rows[0]
    assert r["status"] == "skipped" and r["accuracy"]["behaved"] is None
    assert len(r["trace"]["servers"]) == 2
    assert {q["server"] for q in r["trace"]["requests"] if q["endpoint"] == "/v1/score"} == set(servers)
    assert all(p["fetched"] == r["trace"]["top_k"] for p in r["trace"]["per_server"])
    assert "behaved_as_expected" not in s["accuracy"]                 # nothing judged without answers


def test_server_log_join():
    rec_reqs = [{"server": "s", "endpoint": "/v1/score", "client_ms": 10.0, "response_bytes": 99,
                 "utc_start": 1000.0, "utc_end": 1000.01}]
    logs = bench.ServerLogs([], "off")
    logs.sources = {"s": ("file", None)}
    logs._read = lambda server: [
        {"ts": "x", "endpoint": "/v1/score", "response_bytes": 98, "latency_ms": 1, "_t": 1000.0},   # wrong size
        {"ts": "y", "endpoint": "/v1/score", "response_bytes": 99, "latency_ms": 4.0, "_t": 1000.004}]
    logs.join(rec_reqs)
    assert rec_reqs[0]["server_ms"] == 4.0 and rec_reqs[0]["network_ms"] == 6.0
    assert rec_reqs[0]["server_log_fields"] == ["endpoint", "latency_ms", "response_bytes", "ts"]


def test_percentiles():
    assert bench.pct([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5
    assert bench.pct([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert bench.stats([]) is None


def test_real_answer_path_is_traced(tmp_path, servers, questions, monkeypatch):
    """The real answer step, with the reranker and Ollama replaced: rerank and model show up in the trace."""
    from client import answer as A
    monkeypatch.setattr(A, "_default_rerank", lambda q, chunks: list(reversed(chunks)))
    monkeypatch.setattr(A, "ollama_chat", lambda prompt, *a, **kw: "Headaches have many causes [1].")
    monkeypatch.setattr(A.answer, "__defaults__", (A.ollama_chat, A.N_CONTEXT, -1.0, None))
    _, rows, s = run(tmp_path, questions, "--servers", servers[0], "--answer", "real")
    r = rows[0]
    names = [e["name"] for e in r["trace"]["answer_events"]]
    assert names == ["rerank", "model"]   # "What causes headaches?" has no distinctive term, so the model runs
    assert r["answer"]["raw_model_output"] == "Headaches have many causes [1]."   # the checker may still drop it
    assert r["trace"]["reranked"][0]["id"] == r["trace"]["search"][-1]["id"]
    assert set(r["speed"]["answer_parts"]) >= {"rerank", "checks"}
    assert "answer_parts_seconds" in s["speed"]


def test_source_selection_variants(monkeypatch):
    from client import answer as A
    for k in ("BLIND_RAG_N_CONTEXT", "BLIND_RAG_RERANK_MARGIN", "BLIND_RAG_MIN_SOURCES", "BLIND_RAG_ONE_PER_PAGE"):
        monkeypatch.delenv(k, raising=False)
    cs = [{"url": "p1", "rerank_score": 9.0}, {"url": "p1", "rerank_score": 8.0}, {"url": "p2", "rerank_score": 3.5},
          {"url": "p3", "rerank_score": 2.0}, {"url": "p4", "rerank_score": 1.0}, {"url": "p5", "rerank_score": 0.5}]
    assert [c["url"] for c in A.select_sources(cs)] == ["p1"]                # default: one per page, margin 5
    monkeypatch.setenv("BLIND_RAG_ONE_PER_PAGE", "0")
    assert [c["url"] for c in A.select_sources(cs)] == ["p1", "p1"]          # the old behavior
    monkeypatch.setenv("BLIND_RAG_MIN_SOURCES", "3")
    assert [c["url"] for c in A.select_sources(cs)] == ["p1", "p1", "p2"]
    monkeypatch.setenv("BLIND_RAG_ONE_PER_PAGE", "1")
    assert [c["url"] for c in A.select_sources(cs)] == ["p1", "p2", "p3"]
    cs2 = [{"url": "a", "rerank_score": 9.0}, {"url": "a", "rerank_score": 8.5}, {"url": "b", "rerank_score": 6.0}]
    monkeypatch.delenv("BLIND_RAG_MIN_SOURCES")
    monkeypatch.delenv("BLIND_RAG_ONE_PER_PAGE")
    assert [c["url"] for c in A.select_sources(cs2)] == ["a", "b"]           # a second page now fits
    monkeypatch.setenv("BLIND_RAG_RERANK_MARGIN", "8.6")
    monkeypatch.setenv("BLIND_RAG_N_CONTEXT", "8")
    assert [c["url"] for c in A.select_sources(cs)] == ["p1", "p2", "p3", "p4", "p5"]


def test_sources_sweep_metrics_and_llm_cache(tmp_path, servers, questions, monkeypatch):
    from client import answer as A
    monkeypatch.setenv("BLIND_RAG_N_CONTEXT", "")   # bench.main sets it; monkeypatch restores it after
    calls = []
    monkeypatch.setattr(A, "_default_rerank", lambda q, cs: [dict(c, rerank_score=10.0 - i) for i, c in enumerate(cs)])
    monkeypatch.setattr(A, "ollama_chat", lambda prompt, *a, **kw: calls.append(prompt) or "It has causes [1][2].")
    monkeypatch.setattr(A.answer, "__defaults__", (A.ollama_chat, A.N_CONTEXT, -1.0, None))
    monkeypatch.setattr(A, "_missing_terms", lambda *a, **k: False)
    cache = tmp_path / "llm.jsonl"
    _, rows, s = run(tmp_path, questions, "--servers", servers[0], "--answer", "real",
                     "--sources", "n=3", "--llm-cache", str(cache))
    y = rows[0]["synthesis"]
    assert y["sources"] == 3 and s["synthesis"]["sources_to_model"]["mean"] == 3
    assert s["meta"]["sources_config"] == "n=3" and s["meta"]["llm_cache"]["misses"] == len(calls) > 0
    n = len(calls)
    _, _, s2 = run(tmp_path / "again", questions, "--servers", servers[0], "--answer", "real",
                   "--sources", "n=3", "--llm-cache", str(cache))
    assert len(calls) == n and s2["meta"]["llm_cache"]["hits"] == n   # same sources: no model calls
