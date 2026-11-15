import base64
import json

from fastapi.testclient import TestClient

from api.app import make_app
from client.pipeline import PipelineError

RESULT = {"status": "answered", "answer": "Antibiotics can cure it [1].", "urgent": None,
          "citations": [{"id": 3, "title": "Chlamydia Infections", "url": "u", "updated": "d", "text": "t",
                         "score": 0.7, "excerpt": "Antibiotics can cure it."}],
          "timings": {"answer_ms": 10.0}}
TRACE = {"multi": True, "total_seconds": 1.5, "upload_bytes": 6160, "download_bytes": 20000,
         "servers": [{"server": "http://127.0.0.1:9080", "requests": [{"endpoint": "/v1/score",
                                                                       "request_bytes": 3080, "response_bytes": 16824}]}]}


class FakePipeline:
    def __init__(self, fail=False):
        self.fail = fail

    def ask_traced(self, question, on_stage=None):
        for name, secs in (("embedding", 0.4), ("encrypting", 0.03), ("scoring", 0.05), ("fetching", 0.04)):
            on_stage(name, secs)
        if self.fail:
            raise PipelineError("scoring", "Server answered 500", "restart it")
        on_stage("answering", 1.2)
        return RESULT, TRACE


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def wire_line(route, body, ts="2099-01-01T00:00:00.000Z"):
    return json.dumps({"ts": ts, "route": route, "upstream": "u", "method": "POST", "path": "/ask",
                       "request_bytes": len(body), "body_b64": base64.b64encode(body).decode(),
                       "status": 200, "response_bytes": 1}) + "\n"


def client(tmp_path, fail=False, plain=None):
    wire = tmp_path / "wire.jsonl"
    app = make_app(servers=["http://127.0.0.1:9080"], wire_log=wire,
                   pipeline_factory=lambda servers: FakePipeline(fail),
                   plain_ask=plain or (lambda url, q: {"entry": {"question": q, "returned": []}}),
                   status_get=lambda url: {"source_name": "MedlinePlus", "num_chunks": 2101,
                                           "corpus_version": "v"})
    return TestClient(app), wire


def test_ask_streams_stages_then_answer_then_plain_then_proof(tmp_path):
    c, wire = client(tmp_path)
    wire.write_text(wire_line("medlineplus", b"\x00\x80\x01\xffcipher") +
                    wire_line("plain", json.dumps({"question": "how is chlamydia treated"}).encode()))
    r = c.post("/api/ask", json={"question": "How is chlamydia treated?", "compare": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    names = [e for e, _ in ev]
    assert names == ["start", "stage", "stage", "stage", "stage", "stage", "answer", "plain", "proof", "done"]
    assert [d["name"] for e, d in ev if e == "stage"] == ["embedding", "encrypting", "scoring", "fetching",
                                                           "answering"]
    answer = dict(ev)["answer"]
    assert answer["result"]["citations"][0]["excerpt"] == "Antibiotics can cure it."
    assert answer["trace"]["servers"][0]["requests"][0]["request_bytes"] == 3080
    proof = dict(ev)["proof"]
    assert proof["words"] == ["chlamydia", "treated"] and proof["recording"] is True
    routes = {p["route"]: p for p in proof["routes"]}
    assert routes["medlineplus"]["found"] == [] and routes["plain"]["found"] == ["chlamydia", "treated"]


def test_proof_only_counts_traffic_since_the_question(tmp_path):
    c, wire = client(tmp_path)
    wire.write_text(wire_line("plain", b'{"question": "chlamydia treated"}', ts="2000-01-01T00:00:00.000Z"))
    ev = dict(events(c.post("/api/ask", json={"question": "chlamydia treated", "compare": False}).text))
    assert "plain" not in ev and ev["proof"]["routes"] == []


def test_pipeline_error_is_streamed_as_an_error_event(tmp_path):
    c, _ = client(tmp_path, fail=True)
    ev = events(c.post("/api/ask", json={"question": "x y z w"}).text)
    assert ev[-1] == ("error", {"stage": "scoring", "message": "Server answered 500", "fix": "restart it"})


def test_empty_question_is_rejected(tmp_path):
    c, _ = client(tmp_path)
    assert c.post("/api/ask", json={"question": "   "}).status_code == 400


def test_status_lists_servers_with_names(tmp_path):
    c, _ = client(tmp_path)
    s = c.get("/api/status").json()
    assert s["servers"] == [{"url": "http://127.0.0.1:9080", "ok": True, "name": "MedlinePlus",
                             "num_chunks": 2101, "corpus_version": "v"}]


def test_wire_search_for_any_word(tmp_path):
    c, wire = client(tmp_path)
    wire.write_text(wire_line("plain", b'{"question": "my friend zebulon"}') + wire_line("fmla", b"\x01\x02\x03"))
    got = {r["route"]: r["found"] for r in c.get("/api/wire", params={"word": "Zebulon"}).json()["routes"]}
    assert got == {"plain": ["zebulon"], "fmla": []}
