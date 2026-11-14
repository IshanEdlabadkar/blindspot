"""End-to-end check of C's flow on the mock.  Run:  python -m pytest tests -q"""
import json
import os
import pathlib
import sys
import threading

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["BLIND_RAG_EMBED"] = "fake"

import contracts as c  # noqa: E402
from client import canned, embed  # noqa: E402
from client.pipeline import Pipeline  # noqa: E402
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
