"""Client pipeline: embed -> encrypt -> score -> rank -> fetch -> answer.

ask(question) returns the agreed answer shape. ask_traced() also returns what
went over the wire, for the UI's "What the server saw" panel.

Swaps (env vars, no code changes):
  BLIND_RAG_SERVER  http://127.0.0.1:8080        mock or A's real server
  BLIND_RAG_CRYPTO  mock | real                  real imports client.crypto_client (A)
  BLIND_RAG_ANSWER  stub | real                  real imports client.answer (B)
  BLIND_RAG_FETCH   pir | download               download = trivial-PIR fallback (gate 2)
  BLIND_RAG_EMBED   real | fake                  see client/embed.py
"""
import importlib
import os
import pathlib
import sys
import time

import numpy as np
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import contracts as c  # noqa: E402
from client import embed as emb  # noqa: E402

STAGES = ("embedding", "encrypting", "scoring", "fetching", "answering")


def _env(name, default):
    return os.environ.get(name, default)


def load_crypto(kind=None):
    kind = kind or _env("BLIND_RAG_CRYPTO", "mock")
    return importlib.import_module("client.crypto_client" if kind == "real" else "client.mock_crypto_client")


def load_answer(kind=None):
    kind = kind or _env("BLIND_RAG_ANSWER", "stub")
    return importlib.import_module("client.answer" if kind == "real" else "client.answer_stub").answer


class StaleCorpus(Exception):
    pass


class Pipeline:
    def __init__(self, server=None, crypto=None, answer_fn=None, fetch_mode=None):
        self.server = (server or _env("BLIND_RAG_SERVER", "http://127.0.0.1:8080")).rstrip("/")
        self.crypto = crypto or load_crypto()
        self.answer_fn = answer_fn or load_answer()
        # A's real crypto_client declares FETCH_MODE = "download" (trivial PIR); the env var still wins.
        self.fetch_mode = (fetch_mode or os.environ.get("BLIND_RAG_FETCH")
                           or getattr(self.crypto, "FETCH_MODE", "pir"))
        self.http = requests.Session()
        self.manifest = None
        self.key = None            # session key: memory only, never written or sent
        self._store = None         # whole fetch store, download mode only

    @property
    def is_mock(self) -> bool:
        return bool(getattr(self.crypto, "IS_MOCK", False))

    # 1-2. manifest and keys
    def load_manifest(self, force=False) -> dict:
        if self.manifest is None or force:
            r = self.http.get(self.server + "/v1/manifest", timeout=30)
            r.raise_for_status()
            m = r.json()
            if m.get("protocol") != c.PROTOCOL:
                raise RuntimeError(f"unsupported protocol {m.get('protocol')!r}")
            e = m["embedding"]
            if emb.mode() == "real" and (e["model"], e["dim"]) != (c.EMBED_MODEL, c.DIM):
                raise RuntimeError(f"server embedding {e['model']} does not match local {c.EMBED_MODEL}")
            self.manifest, self._store = m, None
            self.key = self.crypto.keygen(m)
        return self.manifest

    def _post(self, path, body) -> bytes:
        r = self.http.post(self.server + path, data=body, timeout=120, headers={
            "Content-Type": "application/octet-stream",
            c.VERSION_HEADER: self.manifest["corpus_version"]})
        if r.status_code == 409:
            raise StaleCorpus()
        r.raise_for_status()
        return r.content

    def ask_traced(self, question: str, on_stage=None):
        try:
            return self._run(question, on_stage)
        except StaleCorpus:  # corpus changed: reload manifest, retry once
            self.load_manifest(force=True)
            return self._run(question, on_stage)

    def _run(self, question, on_stage):
        m = self.load_manifest()
        n, k = m["num_chunks"], m["top_k"]
        trace = {"mock": self.is_mock, "fetch_mode": self.fetch_mode, "server": self.server,
                 "corpus_version": m["corpus_version"], "num_chunks": n, "top_k": k,
                 "timings": {}, "requests": []}
        t = [time.perf_counter()]

        def stage(name):
            now = time.perf_counter()
            trace["timings"][name] = round(now - t[0], 3)
            t[0] = now
            if on_stage:
                on_stage(name, trace["timings"][name])

        def sent(endpoint, up, down):
            trace["requests"].append({"endpoint": endpoint, "request_bytes": up, "response_bytes": down})

        # 3. embed and quantize
        q = emb.quantize(emb.embed(question, m["embedding"].get("query_prefix", c.QUERY_PREFIX)),
                         m["quantization"]["scale"])
        stage("embedding")

        # 4. encrypt
        ct = self.crypto.encrypt_query(self.key, q)
        trace["ciphertext_sample"] = ct[:48].hex()
        stage("encrypting")

        # 5-6. score every chunk, decrypt, rank locally, take exactly k
        blob = self._post("/v1/score", ct)
        sent("/v1/score", len(ct), len(blob))
        scores = np.asarray(self.crypto.decrypt_scores(self.key, blob))[:n]
        top = np.argsort(-scores, kind="stable")[:k]
        stage("scoring")

        # 7. private fetch: always exactly k, one selector each
        chunks = []
        if self.fetch_mode == "download":
            if self._store is None:
                r = self.http.get(self.server + "/v1/fetch_store", timeout=300)
                r.raise_for_status()
                self._store = r.content
                sent("/v1/fetch_store", 0, len(self._store))
            L = m["pir"]["record_bytes"]
            for i in top:
                chunks.append(c.unpack_record(self._store[int(i) * L:(int(i) + 1) * L]))
        else:
            for i in top:
                sel = self.crypto.make_selector(self.key, int(i), n)
                rec = self._post("/v1/fetch", sel)
                sent("/v1/fetch", len(sel), len(rec))
                chunks.append(c.unpack_record(self.crypto.decrypt_record(self.key, rec)))
        for ch, i in zip(chunks, top):
            ch["score"] = int(scores[i])
        stage("fetching")

        # 8-9. rerank and answer (B's answer() does both, and the safe decline)
        result = self.answer_fn(question, chunks)
        stage("answering")

        trace["upload_bytes"] = sum(r["request_bytes"] for r in trace["requests"])
        trace["download_bytes"] = sum(r["response_bytes"] for r in trace["requests"])
        trace["total_seconds"] = round(sum(trace["timings"].values()), 3)
        trace["top_ids"] = [int(i) for i in top]   # device-only; shown as "what only you know"
        return result, trace

    def close(self):
        """10. Wipe: drop key and cached data."""
        self.key = self.manifest = self._store = None
        self.http.close()


_default = None


def ask(question: str) -> dict:
    """Plaintext question -> answer shape (see contracts.make_answer / make_decline)."""
    global _default
    if _default is None:
        _default = Pipeline()
    return _default.ask_traced(question)[0]


if __name__ == "__main__":
    import json
    res, tr = Pipeline().ask_traced(" ".join(sys.argv[1:]) or "What are early signs of a miscarriage?")
    print(json.dumps(res, indent=2)[:1500])
    print(json.dumps({k: v for k, v in tr.items() if k != "requests"}, indent=2))
