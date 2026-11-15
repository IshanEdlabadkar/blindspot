"""Real crypto_client (Person A). Same five functions as client/mock_crypto_client.py.

Selected by C's pipeline with BLIND_RAG_CRYPTO=real. Needs the local helper:

    make helper            # Go process on this device, http://127.0.0.1:8090

Secret keys live only inside the helper's memory. This module never sees them.

Every encrypt_query() uses a FRESH secret key, even though the pipeline calls
keygen() once per manifest: reusing one key across questions would leak.

Speed: building a key and its ~33 MB token takes ~1 s and does not depend on
the question, so the helper prepares the next key in the background (at
keygen and after each question). If it isn't ready or has expired,
encrypt_query falls back to making one on the spot. Set
BLIND_RAG_PREPARE=0 to turn this off.

Fetch is trivial PIR, so make_selector() and decrypt_record() are not used.
Run the pipeline with BLIND_RAG_FETCH=download.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

IS_MOCK = False
FETCH_MODE = "download"   # trivial PIR; see README

HELPER_URL = os.environ.get("BLIND_RAG_HELPER", "http://127.0.0.1:8090").rstrip("/")
SCORE_DTYPE = "<i4"
PREPARE = os.environ.get("BLIND_RAG_PREPARE", "1") != "0"


class Key:
    """Per-manifest session. Holds public parameters and the helper handle of
    the current question's one-time key (the key itself stays in the helper)."""

    def __init__(self, manifest: dict):
        scoring = manifest.get("scoring", {})
        if "seed" not in scoring:
            raise RuntimeError(
                "manifest has no scoring.seed: this is not A's real server "
                "(the mock server needs BLIND_RAG_CRYPTO=mock)")
        self.seed = scoring["seed"]
        self.n = int(manifest["num_chunks"])
        self.d = int(manifest["embedding"]["dim"])
        self.handle: str | None = None
        self.http = requests.Session()
        self._pool = ThreadPoolExecutor(max_workers=1) if PREPARE else None
        self._next = None            # Future -> handle of a prepared, unused key
        self._lock = threading.Lock()

    def _params(self):
        return {"seed": self.seed, "n": self.n, "d": self.d}

    def prepare_next(self):
        """Start building the next question's key in the background."""
        if self._pool is None:
            return
        with self._lock:
            if self._next is None:
                self._next = self._pool.submit(_prepare, self._params())

    def take_prepared(self):
        """Handle of a prepared key, or None. Waits if one is being built."""
        with self._lock:
            fut, self._next = self._next, None
        if fut is None:
            return None
        try:
            return fut.result(timeout=60)
        except Exception:
            return None

    def __repr__(self):  # never print anything secret-adjacent
        return f"<crypto_client.Key n={self.n} d={self.d}>"


def _prepare(params) -> str:
    # Own connection: requests.Session is not thread-safe.
    r = requests.post(HELPER_URL + "/prepare", params=params, timeout=60)
    r.raise_for_status()
    return r.headers["X-Handle"]


def _check_helper(http):
    try:
        http.get(HELPER_URL + "/health", timeout=3).raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(
            f"crypto-helper not reachable at {HELPER_URL}. Start it with `make helper` "
            f"(see SETUP.md), or set BLIND_RAG_HELPER.") from e


def keygen(manifest=None) -> Key:
    """Session for this manifest. Fresh secret keys are made per question in encrypt_query."""
    key = Key(manifest or {})
    _check_helper(key.http)
    key.prepare_next()
    return key


def encrypt_query(key: Key, int8_vec) -> bytes:
    """d int8 values -> body for POST /v1/score (fresh one-time key + encrypted query, ~34 MB)."""
    vec = np.asarray(int8_vec, dtype=np.int8)
    if vec.shape != (key.d,):
        raise ValueError(f"query must be {key.d} int8 values, got shape {vec.shape}")
    r = None
    handle = key.take_prepared()
    if handle:
        r = key.http.post(HELPER_URL + "/encrypt", params={"handle": handle},
                          data=vec.tobytes(), timeout=120)
        if r.status_code == 404:  # expired (10 min) or helper restarted
            r = None
    if r is None:
        r = key.http.post(HELPER_URL + "/encrypt", params=key._params(),
                          data=vec.tobytes(), timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"crypto-helper /encrypt: {r.status_code} {r.text.strip()}")
    key.handle = r.headers["X-Handle"]
    return r.content


def decrypt_scores(key: Key, blob: bytes):
    """/v1/score response -> N signed int32 scores. Wipes that question's key."""
    if key.handle is None:
        raise RuntimeError("decrypt_scores called before encrypt_query")
    handle, key.handle = key.handle, None
    r = key.http.post(HELPER_URL + "/decrypt", params={"handle": handle}, data=blob, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"crypto-helper /decrypt: {r.status_code} {r.text.strip()}")
    key.prepare_next()  # get the next question's key ready while the user reads
    return np.frombuffer(r.content, dtype=SCORE_DTYPE)


def make_selector(key: Key, index: int, N: int) -> bytes:
    raise RuntimeError("Fetch is trivial PIR with the real server: set BLIND_RAG_FETCH=download")


def decrypt_record(key: Key, blob: bytes) -> bytes:
    raise RuntimeError("Fetch is trivial PIR with the real server: set BLIND_RAG_FETCH=download")
