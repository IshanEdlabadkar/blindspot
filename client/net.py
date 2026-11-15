"""HTTP to the document servers with identical, minimal headers from every client.

Python's requests library names itself and its version in User-Agent, and its Accept-Encoding depends
on which compression packages happen to be installed. Both help a server tell askers apart. Every Blind
RAG client sends exactly these headers instead, so to a server all askers look the same. (This hides
nothing about the IP address; that needs a relay. See docs/security.md.)
"""
from __future__ import annotations

import requests

UNIFORM_HEADERS = {"User-Agent": "blind-rag", "Accept": "*/*", "Accept-Encoding": "identity",
                   "Connection": "keep-alive"}


def session(cls=requests.Session) -> requests.Session:
    s = cls()
    s.headers.clear()
    s.headers.update(UNIFORM_HEADERS)
    return s


def get(url: str, **kw) -> requests.Response:
    with session() as s:
        return s.get(url, **kw)


LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")


def insecure_remote(url: str) -> bool:
    """True for a plain-http URL to another machine. Those are refused (BLIND_RAG_ALLOW_HTTP=1 overrides):
    the question is encrypted either way, but plain http lets anyone on the path read the passages
    coming back and tamper with the manifest. Plain http to this machine (local servers, relays) is fine."""
    import os
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.scheme == "http" and (u.hostname or "") not in LOOPBACK and os.environ.get("BLIND_RAG_ALLOW_HTTP") != "1"
