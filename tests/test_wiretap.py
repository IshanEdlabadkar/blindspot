import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from wiretap.proxy import Relay, read_records


class Upstream(BaseHTTPRequestHandler):
    """A stand-in document server: echoes POST bodies reversed, serves a manifest naming its own URL."""

    def do_GET(self):
        if self.path == "/v1/manifest":
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            body = json.dumps({"scoring": {"hint_url": base + "/v1/score_hint"}}).encode()
        elif self.path == "/v1/score_hint":
            body = b"H" * 5000
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/stale":
            self.send_response(409)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        out = data[::-1] + self.headers.get("X-Corpus-Version", "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def relay(tmp_path):
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    upstream = f"http://127.0.0.1:{up.server_address[1]}"
    log = tmp_path / "wire.jsonl"
    r = Relay("health", ("127.0.0.1", 0), upstream, log)
    threading.Thread(target=r.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{r.server_address[1]}", upstream, log
    r.shutdown()
    up.shutdown()


def test_forwards_requests_and_responses_unchanged(relay):
    base, _, _ = relay
    body = bytes(range(256)) * 4
    r = requests.post(base + "/v1/score", data=body, headers={"X-Corpus-Version": "v7"})
    assert r.status_code == 200 and r.content == body[::-1] + b"v7"


def test_records_exact_request_bytes(relay):
    base, upstream, log = relay
    body = b"\x00\xffciphertext\x10"
    requests.post(base + "/v1/score?x=1", data=body)
    rec = read_records(log)[-1]
    assert rec["route"] == "health" and rec["upstream"] == upstream
    assert rec["method"] == "POST" and rec["path"] == "/v1/score?x=1"
    assert base64.b64decode(rec["body_b64"]) == body and rec["request_bytes"] == len(body)
    assert rec["status"] == 200 and rec["response_bytes"] == len(body)
    assert rec["ts"].endswith("Z")


def test_manifest_hint_url_is_rewritten_to_go_through_the_relay(relay):
    base, _, log = relay
    m = requests.get(base + "/v1/manifest").json()
    assert m["scoring"]["hint_url"] == base + "/v1/score_hint"
    assert len(requests.get(m["scoring"]["hint_url"]).content) == 5000
    assert [r["path"] for r in read_records(log)] == ["/v1/manifest", "/v1/score_hint"]


def test_error_statuses_pass_through(relay):
    base, _, _ = relay
    assert requests.post(base + "/stale", data=b"x").status_code == 409
    assert requests.get(base + "/nope").status_code == 404
