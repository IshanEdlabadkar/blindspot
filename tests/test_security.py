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
