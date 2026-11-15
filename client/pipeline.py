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
import datetime
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


class PipelineError(RuntimeError):
    """A failure the UI can show as is: which stage broke and how to fix it.

    The pipeline never switches to a weaker mode on failure (no mock, no plaintext).
    """

    def __init__(self, stage: str, message: str, fix: str = ""):
        super().__init__(message)
        self.stage, self.message, self.fix = stage, message, fix


OLLAMA_TAGS = "http://localhost:11434/api/tags"


def _get(url, timeout=1.5):
    try:
        r = requests.get(url, timeout=timeout)
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def health(server: str, crypto_kind: str = "real", answer_kind: str = "real") -> list:
    """Live status of what this mode needs: [{"name", "ok", "detail", "fix"}]."""
    out = []
    r = _get(server.rstrip("/") + "/v1/manifest", 3)
    if r is None:
        out.append({"name": "Document server", "ok": False, "detail": f"not reachable at {server}",
                    "fix": "make demo  (or: make server)"})
    else:
        m = r.json()
        kind = "encrypted-search server" if "seed" in m.get("scoring", {}) else "PLAINTEXT MOCK server"
        out.append({"name": "Document server", "ok": True, "fix": "",
                    "detail": f"{kind}, corpus {m.get('corpus_version')}, {m.get('num_chunks'):,} chunks"})
    if crypto_kind == "real":
        url = _env("BLIND_RAG_HELPER", "http://127.0.0.1:8090").rstrip("/")
        ok = _get(url + "/health") is not None
        out.append({"name": "Key helper", "ok": ok, "detail": "keys in memory on this device" if ok
                    else f"not reachable at {url}", "fix": "" if ok else "make demo  (or: make helper)"})
    if answer_kind == "real":
        r = _get(OLLAMA_TAGS)
        if r is None:
            out.append({"name": "Local model", "ok": False, "detail": "Ollama is not running",
                        "fix": "brew services start ollama"})
        else:
            names = [x.get("name", "") for x in r.json().get("models", [])]
            ok = any(n.startswith("llama3.2:3b") for n in names)
            out.append({"name": "Local model", "ok": ok, "detail": "llama3.2:3b ready" if ok
                        else "Ollama is running but llama3.2:3b is not pulled",
                        "fix": "" if ok else "ollama pull llama3.2:3b"})
    return out


class Pipeline:
    def __init__(self, server=None, crypto=None, answer_fn=None, fetch_mode=None):
        self.server = (server or _env("BLIND_RAG_SERVER", "http://127.0.0.1:8080")).rstrip("/")
        self.crypto = crypto or load_crypto()
        self.answer_fn = answer_fn or load_answer()
        # What is REALLY loaded, read from the objects, never from what was asked for.
        self.crypto_kind = "mock" if getattr(self.crypto, "IS_MOCK", False) else "real"
        self.answer_kind = "stub" if getattr(self.answer_fn, "__module__", "").endswith("answer_stub") else "real"
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
            try:
                r = self.http.get(self.server + "/v1/manifest", timeout=30)
                r.raise_for_status()
            except requests.RequestException as e:
                raise PipelineError("manifest", f"Document server not reachable at {self.server}.",
                                    "Start it with: make demo  (or: make server)") from e
            m = r.json()
            server_is_real = "seed" in m.get("scoring", {})
            if self.crypto_kind == "mock" and server_is_real:
                raise PipelineError("manifest", "Refusing to send an unencrypted question to the real server.",
                                    "Run with BLIND_RAG_CRYPTO=real (make demo), or point the mock client at the mock server.")
            if self.crypto_kind == "real" and not server_is_real:
                raise PipelineError("manifest", f"{self.server} is the plaintext mock server, not the encrypted one.",
                                    "Stop the mock and start the real server: make demo")
            if m.get("protocol") != c.PROTOCOL:
                raise RuntimeError(f"unsupported protocol {m.get('protocol')!r}")
            e = m["embedding"]
            if emb.mode() == "real" and (e["model"], e["dim"]) != (c.EMBED_MODEL, c.DIM):
                raise RuntimeError(f"server embedding {e['model']} does not match local {c.EMBED_MODEL}")
            self.manifest, self._store = m, None
            try:
                self.key = self.crypto.keygen(m)
            except Exception as e:  # noqa: BLE001
                raise PipelineError("keys", str(e), "Start the key helper: make demo  (or: make helper)") from e
        return self.manifest

    def _post(self, path, body) -> bytes:
        try:
            r = self.http.post(self.server + path, data=body, timeout=120, headers={
                "Content-Type": "application/octet-stream",
                c.VERSION_HEADER: self.manifest["corpus_version"]})
        except requests.Timeout as e:
            raise PipelineError(path, f"The server took too long on {path}.", "Check the server terminal, then ask again.") from e
        except requests.RequestException as e:
            raise PipelineError(path, f"Lost the connection to {self.server} during {path}.",
                                "Check the server is still running: make demo") from e
        if r.status_code == 409:
            raise StaleCorpus()
        if r.status_code != 200:
            raise PipelineError(path, f"Server answered {r.status_code} on {path}: {r.text.strip()[:200]}",
                                "The client and server may be on different versions: git pull, restart both.")
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
        mode = {"crypto": self.crypto_kind, "fetch": self.fetch_mode, "answer": self.answer_kind,
                "embed": emb.mode(), "score": ""}
        trace = {"mock": self.is_mock, "mode": mode, "fetch_mode": self.fetch_mode, "server": self.server,
                 "corpus_version": m["corpus_version"], "num_chunks": n, "top_k": k,
                 "timings": {}, "requests": []}
        trace["started_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
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
        try:
            q = emb.quantize(emb.embed(question, m["embedding"].get("query_prefix", c.QUERY_PREFIX)),
                             m["quantization"]["scale"])
        except Exception as e:  # noqa: BLE001
            raise PipelineError("embedding", f"Could not load the embedding model: {e}",
                                "pip install sentence-transformers; the first run needs internet to download it.") from e
        stage("embedding")

        # 4. encrypt
        try:
            ct = self.crypto.encrypt_query(self.key, q)
        except Exception as e:  # noqa: BLE001
            raise PipelineError("encrypting", str(e), "Check the key helper: make demo  (or: make helper)") from e
        trace["ciphertext_sample"] = ct[:48].hex()
        stage("encrypting")

        # 5-6. score every chunk, decrypt, rank locally, take exactly k
        blob = self._post("/v1/score", ct)
        sent("/v1/score", len(ct), len(blob))
        try:
            scores = np.asarray(self.crypto.decrypt_scores(self.key, blob))[:n]
        except Exception as e:  # noqa: BLE001
            raise PipelineError("scoring", f"Could not decrypt the scores: {e}",
                                "Restart the helper and server (make stop, then make demo).") from e
        if len(scores) != n:
            raise PipelineError("scoring", f"Expected {n} scores, got {len(scores)}.",
                                "Client and server disagree on the corpus: git pull, restart both.")
        mode["score"] = str(getattr(self.key, "mode", "") or "")   # what A's client really used: hint | token
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
        # B's answer() declines on a cosine estimate: raw int score / scale^2.
        scale = float(m["quantization"]["scale"])
        for ch, i in zip(chunks, top):
            ch["raw_score"] = int(scores[i])
            ch["score"] = float(scores[i]) / (scale * scale)
        stage("fetching")

        # 8-9. rerank and answer (B's answer() does both, and the safe decline)
        try:
            result = c.normalize_result(self.answer_fn(question, chunks))
        except requests.ConnectionError as e:
            raise PipelineError("answering", "The local model is not running, so no answer was written.",
                                "brew services start ollama   then: ollama pull llama3.2:3b") from e
        except requests.Timeout as e:
            raise PipelineError("answering", "The local model took too long to answer.",
                                "Ask again; the first answer after a start is the slowest.") from e
        except requests.HTTPError as e:
            raise PipelineError("answering", f"The local model returned an error: {e}",
                                "ollama pull llama3.2:3b") from e
        stage("answering")

        trace["ended_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
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
