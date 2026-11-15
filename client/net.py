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
