import json
import threading

import pytest
import requests

from baseline.server import PlainServer


def fake_ask(question):
    return {"status": "answered", "answer": "a",
            "citations": [{"id": 1, "title": "Asthma", "url": "u1", "updated": "d", "text": "t", "score": 0.9}],
            "timings": {"answer_ms": 1.0}}


@pytest.fixture
def server(tmp_path):
    srv = PlainServer(("127.0.0.1", 0), fake_ask, tmp_path / "log.jsonl")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path / "log.jsonl"
    srv.shutdown()
    srv.server_close()


def test_ask_answers_and_logs_the_plaintext_question(server):
    base, log_file = server
    r = requests.post(base + "/ask", json={"question": "Am I having a miscarriage?"})
    assert r.status_code == 200 and r.json()["answer"] == "a"

    entry = requests.get(base + "/log").json()[-1]
    assert entry["question"] == "Am I having a miscarriage?"
    assert entry["returned"] == [{"title": "Asthma", "url": "u1"}]
    assert entry["endpoint"] == "/ask" and entry["status"] == "answered" and "latency_ms" in entry
    assert json.loads(log_file.read_text().splitlines()[-1])["question"] == "Am I having a miscarriage?"


def test_bad_requests_are_rejected(server):
    base, _ = server
    assert requests.post(base + "/ask", data="not json").status_code == 400
    assert requests.post(base + "/ask", json={"question": "  "}).status_code == 400
    assert requests.get(base + "/nope").status_code == 404


def test_cors_preflight_allowed(server):
    base, _ = server
    r = requests.options(base + "/ask")
    assert r.status_code == 204 and r.headers["Access-Control-Allow-Origin"] == "*"
