"""Security layers on the client: corpus pins, fetch-store check, helper token only to the helper."""
import json

import pytest

from client import pins
from client import crypto_client as cc


@pytest.fixture()
def lists(tmp_path, monkeypatch):
    remote = tmp_path / "servers.remote.json"
    remote.write_text(json.dumps([{"id": "med", "url": "https://med.example", "pin": {
        "corpus_version": "v1", "score_table": "sha256:aa", "fetch_store": "sha256:bb"}}]))
    monkeypatch.setenv("BLIND_RAG_SERVERS_FILE", str(remote))
    return remote


def test_pin_matches_and_mismatches(lists):
    good = {"corpus_version": "v1", "hashes": {"score_table": "sha256:aa", "fetch_store": "sha256:bb"}}
    assert pins.check_manifest("https://med.example/", good) is None
    swapped = {"corpus_version": "v1", "hashes": {"score_table": "sha256:aa", "fetch_store": "sha256:EVIL"}}
    assert "fetch_store" in pins.check_manifest("https://med.example", swapped)


def test_pin_follows_source_id_through_relays_and_backups(lists):
    # a wiretap relay or a local backup has another URL, but the same source_id: same pin
    relayed = {"source_id": "med", "corpus_version": "v2", "hashes": {}}
    assert "corpus_version" in pins.check_manifest("http://127.0.0.1:9080", relayed)
    assert pins.check_manifest("http://127.0.0.1:9080", {"source_id": "unpinned"}) is None


def test_token_goes_to_the_helper_only(tmp_path, monkeypatch):
    f = tmp_path / "helper-token"
    f.write_text("s3cret\n")
    monkeypatch.setenv("BLIND_RAG_HELPER_TOKEN_FILE", str(f))
    assert cc._helper_headers(cc.HELPER_URL + "/encrypt") == {"X-Blind-RAG-Token": "s3cret"}
    assert cc._helper_headers("https://blindspot-cz2t.onrender.com/v1/score_hint") == {}
    f.write_text("rotated")                      # restarted helper: re-read on every call
    assert cc._helper_headers(cc.HELPER_URL + "/hint") == {"X-Blind-RAG-Token": "rotated"}


def test_hosted_servers_are_pinned():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for e in json.loads((root / "servers.remote.json").read_text()):
        backup = json.loads((root / "artifacts" / e["id"] / "manifest.json").read_text())
        assert e["pin"] == {"corpus_version": backup["corpus_version"], **backup["hashes"]}, e["id"]


def test_server_traffic_has_uniform_minimal_headers():
    from client import net
    s = net.session()
    assert dict(s.headers) == net.UNIFORM_HEADERS
    assert "python-requests" not in s.headers["User-Agent"]
    k = cc.Key({"scoring": {"seed": "00", "mode": "hint"}, "num_chunks": 1, "embedding": {"dim": 384}})
    assert dict(k.http.headers) == net.UNIFORM_HEADERS   # the hint download to a server, too


def test_web_ui_sends_a_strict_content_security_policy():
    from fastapi.testclient import TestClient
    from api.app import make_app
    app = make_app(servers=["http://127.0.0.1:1"], status_get=lambda url: None)
    r = TestClient(app).get("/api/status")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Referrer-Policy"] == "no-referrer"
