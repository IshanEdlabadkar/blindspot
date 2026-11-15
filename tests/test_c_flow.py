"""End-to-end check of C's flow on the mock.  Run:  python -m pytest tests -q"""
import json
import os
import pathlib
import sys
import threading

import types

import numpy as np
import pytest
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["BLIND_RAG_EMBED"] = "fake"

import contracts as c  # noqa: E402
from client import canned, embed  # noqa: E402
from client.evidence import supporting_excerpt  # noqa: E402
from client.pipeline import Pipeline, PipelineError, health  # noqa: E402
from mock_server.server import serve  # noqa: E402
from tools.make_dummy_tables import main as make_tables  # noqa: E402

N = 500


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    make_tables(out=data, n=N)
    httpd, state = serve(data, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", data, state
    httpd.shutdown()


def test_record_roundtrip():
    ch = {"id": 7, "title": "T", "url": "u", "updated": "2026-01-01", "text": "héllo"}
    blob = c.pack_record(ch)
    assert len(blob) == c.RECORD_BYTES and c.unpack_record(blob) == ch


def test_ask_matches_plaintext(server):
    url, data, _ = server
    question = "What are early signs of a miscarriage?"
    result, trace = Pipeline(server=url).ask_traced(question)

    table = np.fromfile(data / "score_table.bin", dtype=np.int8).reshape(N, c.DIM).astype(np.int32)
    q = embed.quantize(embed.embed(question)).astype(np.int32)
    expect = np.argsort(-(table @ q), kind="stable")[:c.TOP_K].tolist()

    assert trace["top_ids"] == expect
    assert [x["id"] for x in result["citations"]] == expect[:3]   # fetched the right records
    assert result["declined"] is False and result["answer"]
    assert set(result["citations"][0]) == set(c.CITATION_FIELDS)
    fetches = [r for r in trace["requests"] if r["endpoint"] == "/v1/fetch"]
    assert len(fetches) == c.TOP_K                                # always exactly k
    assert {r["response_bytes"] for r in fetches} == {c.RECORD_BYTES}  # fixed size


def test_log_has_no_bodies(server):
    url, _, state = server
    Pipeline(server=url).ask_traced("secret question zebra")
    lines = [json.loads(x) for x in state.log_path.read_text().splitlines()]
    assert lines and all(set(x) == set(c.LOG_FIELDS) for x in lines)
    assert "zebra" not in state.log_path.read_text()


def test_stale_version_recovers(server):
    url, _, state = server
    p = Pipeline(server=url)
    p.load_manifest()
    p.manifest["corpus_version"] = "old"
    result, _ = p.ask_traced("anything")
    assert p.manifest["corpus_version"] == state.manifest["corpus_version"] and result["answer"]


def test_download_fallback_same_result(server):
    url, _, _ = server
    a, _ = Pipeline(server=url).ask_traced("knee pain on stairs")
    b, tr = Pipeline(server=url, fetch_mode="download").ask_traced("knee pain on stairs")
    assert a == b and not any(r["endpoint"] == "/v1/fetch" for r in tr["requests"])


def test_canned():
    assert canned.ask("hello")["declined"] is False
    assert canned.ask("please decline")["declined"] is True


# ---- honest modes and failure handling (C2, C5) ----

def test_trace_reports_what_really_ran(server):
    url, _, _ = server
    _, trace = Pipeline(server=url).ask_traced("anything")
    assert trace["mode"]["crypto"] == "mock" and trace["mode"]["answer"] == "stub" and trace["mock"] is True
    assert trace["started_utc"] <= trace["ended_utc"]


class _FakeHTTP:
    """Stands in for requests.Session: serves one manifest and records any POST."""
    def __init__(self, manifest):
        self.manifest, self.posts = manifest, []

    def get(self, url, **kw):
        return types.SimpleNamespace(status_code=200, json=lambda: self.manifest, raise_for_status=lambda: None)

    def post(self, url, **kw):
        self.posts.append(url)
        raise AssertionError("nothing may be sent")

    def close(self):
        pass


def test_mock_client_never_sends_plaintext_to_real_server(server):
    url, _, state = server
    real_manifest = dict(state.manifest, scoring={"seed": "00" * 16})
    p = Pipeline(server=url)
    p.http = _FakeHTTP(real_manifest)
    with pytest.raises(PipelineError) as e:
        p.ask_traced("secret question")
    assert "unencrypted" in e.value.message and p.http.posts == []


def test_real_client_refuses_the_mock_server(server):
    url, _, _ = server
    fake_real = types.SimpleNamespace(IS_MOCK=False, keygen=lambda m: None)
    with pytest.raises(PipelineError) as e:
        Pipeline(server=url, crypto=fake_real).ask_traced("q")
    assert "mock" in e.value.message


def test_server_down_is_a_clear_error():
    with pytest.raises(PipelineError) as e:
        Pipeline(server="http://127.0.0.1:9").ask_traced("q")
    assert e.value.stage == "manifest" and "make demo" in e.value.fix


def test_model_down_is_a_clear_error_not_a_fallback(server):
    url, _, _ = server

    def dead_model(question, chunks):
        raise requests.ConnectionError("ollama not running")

    with pytest.raises(PipelineError) as e:
        Pipeline(server=url, answer_fn=dead_model).ask_traced("q")
    assert e.value.stage == "answering" and "ollama" in e.value.fix


def test_health_names_the_mock_server(server):
    url, _, _ = server
    items = health(url, "mock", "stub")
    assert items[0]["ok"] and "MOCK" in items[0]["detail"]
    assert health("http://127.0.0.1:9", "mock", "stub")[0]["ok"] is False


def test_supporting_excerpt_is_verbatim_from_source():
    src = "Asthma is a chronic disease. Inhalers deliver medicine to the lungs quickly. See your provider."
    ans = "Inhalers get medicine into your lungs quickly [1]. Something else [2]."
    assert supporting_excerpt(ans, 1, src) == "Inhalers deliver medicine to the lungs quickly."
    assert supporting_excerpt("zzz qqq", 1, src) == ""


def test_batched_fetch_used_when_client_supports_it_and_404_falls_back(server):
    """A crypto client with make_selectors tries /v1/fetch_batch; the mock server has none (404),
    so the pipeline falls back to one-by-one fetches and still returns the right records."""
    url, _, _ = server
    import client.mock_crypto_client as mock
    calls = []
    batch = types.SimpleNamespace(
        IS_MOCK=True, keygen=mock.keygen, encrypt_query=mock.encrypt_query, decrypt_scores=mock.decrypt_scores,
        make_selector=mock.make_selector, decrypt_record=mock.decrypt_record,
        make_selectors=lambda key, idx, n: calls.append(list(idx)) or b"".join(mock.make_selector(key, i, n) for i in idx),
        decrypt_records=lambda key, blob: [])
    a, _ = Pipeline(server=url, fetch_mode="pir").ask_traced("knee pain on stairs")
    b, tr = Pipeline(server=url, crypto=batch, fetch_mode="pir").ask_traced("knee pain on stairs")
    assert len(calls) == 1 and len(calls[0]) == c.TOP_K           # the batch was attempted, with exactly k
    assert a == b                                                   # fallback fetched the same records
    assert sum(r["endpoint"] == "/v1/fetch" for r in tr["requests"]) == c.TOP_K
