"""Search several Blind RAG document servers with one question, then answer once on the device.

    MultiPipeline(["https://health.example", "https://hr.example"]).ask_traced(question)

Same interface as client.pipeline.Pipeline (ask_traced, close, is_mock, fetch_mode, ...), so the UI and
the eval can use either. The user chooses which servers to search.

Privacy, per selected server:
  - it receives the same encrypted question every time and learns only that a question was asked;
  - it is always asked for exactly k records, so it cannot tell how relevant it was;
  - unselected servers receive nothing. (Someone who watches every server could see which ones were
    selected; the UI says so.)

Ranking: all selected servers must use the same embedding model, revision, dimension and quantization
scale (checked from their manifests), so their scores are directly comparable. The device merges the
S x k fetched chunks by score and gives the best k to the answer step, which reranks and checks them.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from client.pipeline import Pipeline, PipelineError, load_answer, load_crypto

ROOT = Path(__file__).resolve().parents[1]


def _compat_key(m: dict) -> tuple:
    e, q = m["embedding"], m["quantization"]
    return (e.get("model"), e.get("revision"), e.get("dim"), e.get("query_prefix"), q.get("scale"))


def server_list_file() -> Path:
    """servers.remote.json (the hosted servers, the default) or another list such as servers.json (local)."""
    f = os.environ.get("BLIND_RAG_SERVERS_FILE", "servers.remote.json")
    p = Path(f)
    return p if p.is_absolute() else ROOT / p


def configured_servers() -> list[str]:
    """Servers offered to the user: BLIND_RAG_SERVERS (comma-separated), else BLIND_RAG_SERVER, else the
    urls in the server list file (servers.remote.json, or BLIND_RAG_SERVERS_FILE), else the local default."""
    raw = os.environ.get("BLIND_RAG_SERVERS") or os.environ.get("BLIND_RAG_SERVER")
    if not raw:
        try:
            raw = ",".join(e["url"] for e in json.loads(server_list_file().read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            raw = ""
    raw = raw or "http://127.0.0.1:8080"
    out = []
    for s in raw.split(","):
        s = s.strip().rstrip("/")
        if s and s not in out:
            out.append(s)
    return out


class MultiPipeline:
    def __init__(self, servers, crypto=None, answer_fn=None, fetch_mode=None):
        servers = [s.rstrip("/") for s in servers]
        if not servers:
            raise PipelineError("servers", "No document server selected.", "Select at least one server.")
        if len(set(servers)) != len(servers):
            raise PipelineError("servers", "The same server is selected twice.", "Select each server once.")
        crypto = crypto or load_crypto()
        self.answer_fn = answer_fn or load_answer()
        self.pipes = [Pipeline(server=s, crypto=crypto, answer_fn=self.answer_fn, fetch_mode=fetch_mode)
                      for s in servers]
        self.servers = servers
        self.crypto = crypto
        self.crypto_kind = self.pipes[0].crypto_kind
        self.answer_kind = self.pipes[0].answer_kind
        self.fetch_mode = self.pipes[0].fetch_mode
        self.server = ", ".join(servers)
        self._pool = ThreadPoolExecutor(max_workers=len(servers))

    @property
    def is_mock(self) -> bool:
        return self.pipes[0].is_mock

    def manifests(self) -> list[dict]:
        """Load every selected server's manifest and check they can be ranked together."""
        ms = list(self._pool.map(lambda p: p.load_manifest(), self.pipes))
        ref = _compat_key(ms[0])
        bad = [(p.server, _compat_key(m)) for p, m in zip(self.pipes, ms) if _compat_key(m) != ref]
        if bad:
            detail = "; ".join(f"{srv}: model {k[0]} scale {k[4]}" for srv, k in bad)
            raise PipelineError("servers", f"These servers use a different embedding setup than {self.servers[0]} "
                                f"({ref[0]}, scale {ref[4]}), so their scores can't be merged: {detail}.",
                                "Deselect them, or search them separately.")
        return ms

    def ask_traced(self, question: str, on_stage=None):
        self.manifests()
        # Steps 1-7 on every selected server at once. Each fetches exactly its own k.
        results = list(self._pool.map(lambda p: p.retrieve(question), self.pipes))
        if on_stage:
            for name in ("embedding", "encrypting", "scoring", "fetching"):
                on_stage(name, max(t["timings"].get(name, 0.0) for _, t in results))

        merged = []
        for srv, (chunks, _t) in zip(self.servers, results):
            for ch in chunks:
                merged.append({**ch, "server": srv})
        # Scores are comparable (same model and scale everywhere). Ties break by record id, then server,
        # so the order is deterministic (and matches a single server holding all the records).
        def tie(ch):
            i = ch.get("id")
            return (0, i, "") if isinstance(i, int) else (1, 0, str(i))   # numeric ids compare as numbers
        merged.sort(key=lambda ch: (-ch["score"], tie(ch), self.servers.index(ch["server"])))
        # The same passage can come from two servers (e.g. the same corpus selected twice, local and remote):
        # keep its best-scoring copy only, so duplicates don't crowd out other sources.
        seen, unique = set(), []
        for ch in merged:
            key = (ch.get("url"), ch.get("text"))
            if key not in seen:
                seen.add(key)
                unique.append(ch)
        k = min(t["top_k"] for _, t in results)
        best = unique[:k]

        t0 = time.perf_counter()
        result = self.pipes[0]._answer(question, best)
        answering = round(time.perf_counter() - t0, 3)
        if on_stage:
            on_stage("answering", answering)
        traces = [t for _, t in results]
        # servers are searched in parallel, so each stage takes as long as the slowest server
        timings = {name: round(max(t["timings"].get(name, 0.0) for t in traces), 3)
                   for name in ("embedding", "encrypting", "scoring", "fetching")}
        timings["answering"] = answering
        trace = {
            "multi": True,
            "servers": [{"server": s, "corpus_version": t["corpus_version"], "num_chunks": t["num_chunks"],
                         "requests": t["requests"], "timings": t["timings"],
                         "fetched": len(t["top_ids"]),
                         "used": sum(1 for ch in best if ch["server"] == s)}
                        for s, t in zip(self.servers, traces)],
            "mock": traces[0]["mock"], "mode": traces[0]["mode"], "fetch_mode": self.fetch_mode,
            "server": self.server,
            "corpus_version": " + ".join(t["corpus_version"] for t in traces),
            "num_chunks": sum(t["num_chunks"] for t in traces), "top_k": k,
            "ciphertext_sample": traces[0].get("ciphertext_sample", ""),
            "started_utc": min(t["started_utc"] for t in traces),
            "ended_utc": max(t["ended_utc"] for t in traces),
            "requests": [{**r, "server": s} for s, t in zip(self.servers, traces) for r in t["requests"]],
            "timings": timings,
            # device-only: which records were used, as (server, id)
            "top_ids": [ch.get("id") for ch in best],
            "top_sources": [[ch["server"], ch.get("id")] for ch in best],
        }
        trace["upload_bytes"] = sum(r["request_bytes"] for r in trace["requests"])
        trace["download_bytes"] = sum(r["response_bytes"] for r in trace["requests"])
        trace["total_seconds"] = round(sum(timings.values()), 3)
        return result, trace

    def close(self):
        for p in self.pipes:
            p.close()
        self._pool.shutdown(wait=False)
