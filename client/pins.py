"""Corpus pins: the hashes each document server is expected to serve, from the server list file.

servers.remote.json may carry, per server, "pin": {"corpus_version": ..., "score_table": "sha256:...",
"fetch_store": "sha256:..."}. Before a question is sent, the client checks the server's manifest against
it, and after downloading the fetch store it checks the bytes too. A server that serves something else
(compromised, or a swapped corpus) is refused instead of trusted. Servers without a pin are only checked
against their own manifest.

Update the pins after publishing a new corpus version:  python3 scripts/check_servers.py --pin
"""
from __future__ import annotations

import hashlib
import json

from client.multi import server_list_file


def _entries() -> list[dict]:
    files = [server_list_file()]
    remote = server_list_file().parent / "servers.remote.json"   # pins live here even when using another list
    if remote not in files:
        files.append(remote)
    out = []
    for f in files:
        try:
            out += json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return out


def pin_for(server: str, source_id: str | None = None) -> dict | None:
    """The pin for this server: by its URL, else by the source_id its manifest claims (so a server
    reached through the wiretap relay, or a local backup, is held to the same pin)."""
    entries = _entries()
    for e in entries:
        if e.get("url", "").rstrip("/") == server.rstrip("/") and e.get("pin"):
            return e["pin"]
    for e in entries:
        if source_id and e.get("id") == source_id and e.get("pin"):
            return e["pin"]
    return None


def check_manifest(server: str, manifest: dict) -> str | None:
    """None if the manifest matches the pin (or there is none), else what differs."""
    pin = pin_for(server, manifest.get("source_id"))
    if not pin:
        return None
    got = {"corpus_version": manifest.get("corpus_version"), **(manifest.get("hashes") or {})}
    bad = [k for k, v in pin.items() if got.get(k) != v]
    return None if not bad else ", ".join(f"{k}: pinned {pin[k]!r}, server says {got.get(k)!r}" for k in bad)


def sha256(blob: bytes) -> str:
    return "sha256:" + hashlib.sha256(blob).hexdigest()
