"""Benchmark the Blind RAG pipeline: accuracy, speed, and a full trace of every question.

Runs eval questions through the real client pipeline (encrypted scoring + private fetch + rerank +
local model), one or several document servers, and records for every question:

  * accuracy  - where the right page landed in the encrypted top-k, whether it reached the model's
                sources after rerank, whether it was cited, answered vs declined as expected, the
                988/911 notice, and (when the corpus is on this machine) an exact check that the
                decrypted scores equal the plaintext int8 scores for the same question;
  * speed     - every stage (embed, encrypt, score, fetch, rerank, model, checks), every HTTP request
                as seen by the client, and the same request as seen by the server (from its log),
                so network time = client round trip - server time;
  * trace     - the ordered list of everything that happened, with offsets, bytes and record ids.

Usage (with `make demo` running, so server + helper + Ollama are up):

  uv run python -m eval.bench                          # all questions, real answers, every configured server
  uv run python -m eval.bench --answer none            # retrieval only: no rerank/model, ~1 s for all questions
  uv run python -m eval.bench --limit 10 --repeat 3    # quick speed run, 3 runs per question
  uv run python -m eval.bench --servers http://127.0.0.1:8080,https://blindspot-cz2t.onrender.com
  uv run python -m eval.bench --compare eval/results/bench/A eval/results/bench/B

Writes eval/results/bench/<run>/ : traces.jsonl (one row per question run), summary.json,
report.md, report.html (self-contained; open it in a browser and click a question to see its trace).

Environment is the same as the UI's: BLIND_RAG_CRYPTO (default here: real), BLIND_RAG_FETCH,
BLIND_RAG_EMBED, BLIND_RAG_SERVERS / BLIND_RAG_SERVER.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import platform
import statistics
import subprocess
import sys
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BLIND_RAG_CRYPTO", "real")

import numpy as np  # noqa: E402
import requests  # noqa: E402

RESULTS = ROOT / "eval" / "results" / "bench"
ONE_TIME = {"/v1/fetch_store", "/v1/score_hint", "/v1/fetch_hint", "/v1/manifest"}
KS = (1, 3, 5, 10)


# ---------------------------------------------------------------- small helpers

def pct(values, p):
    """Nearest-rank percentile (no interpolation, so it is always a value that happened)."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return v[min(len(v), max(1, math.ceil(p / 100 * len(v)))) - 1]


def stats(values) -> dict | None:
    v = [x for x in values if x is not None]
    if not v:
        return None
    return {"n": len(v), "mean": round(statistics.fmean(v), 4), "p50": round(pct(v, 50), 4),
            "p95": round(pct(v, 95), 4), "min": round(min(v), 4), "max": round(max(v), 4)}


def frac(n, d):
    return {"n": n, "of": d, "pct": round(100 * n / d, 1) if d else None}


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _utc(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="milliseconds")


def _parse_utc(s: str) -> float:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def local_log(server: str) -> str | None:
    """make server logs to data/server.log (port 8080); other local ports: data/server-<port>.log if present."""
    port = requests.utils.urlparse(server).port or 80
    return str(ROOT / "data" / ("server.log" if port == 8080 else f"server-{port}.log"))


def is_local(server: str) -> bool:
    return any(h in server for h in ("127.0.0.1", "localhost", "[::1]"))


# ---------------------------------------------------------------- recording

class Recorder:
    """Collects the timeline of one question. Everything is relative to `t0` (perf_counter)."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.t0 = time.perf_counter()
        self.wall0 = time.time()
        self.requests: list[dict] = []
        self.events: list[dict] = []
        self.search: list[dict] = []       # chunks given to the answer step, search order
        self.reranked: list[dict] = []     # same chunks after the local rerank
        self.answer_detail: dict = {}
        self.crypto: list[dict] = []       # client-side crypto calls (key helper)

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def event(self, name: str, start: float, seconds: float, **extra):
        self.events.append({"name": name, "start": round(start, 4), "seconds": round(seconds, 4), **extra})


def instrument_session(session: requests.Session, server: str, rec: Recorder):
    """Time every HTTP request of one pipeline (body download included), without changing it."""
    if getattr(session, "_bench_instrumented", False):
        return
    orig = session.send

    def send(req, **kw):
        start, wall = rec.now(), time.time()
        t = time.perf_counter()
        r = orig(req, **kw)
        if not kw.get("stream"):
            _ = r.content
        dt = time.perf_counter() - t
        path = requests.utils.urlparse(req.url).path
        rec.requests.append({"server": server, "endpoint": path, "status": r.status_code,
                             "start": round(start, 4), "client_ms": round(dt * 1000, 2),
                             "request_bytes": len(req.body or b""), "response_bytes": len(r.content or b""),
                             "utc_start": wall, "utc_end": wall + dt})
        return r

    session.send = send
    session._bench_instrumented = True


class TimedCrypto:
    """Wraps the crypto client so the trace shows client-side crypto time (key helper calls) per call."""
    TIMED = {"encrypt_query", "decrypt_scores", "make_selector", "make_selectors", "decrypt_record", "decrypt_records"}

    def __init__(self, inner, rec: Recorder, server: str):
        self._inner, self._rec, self._server = inner, rec, server

    def __getattr__(self, name):
        fn = getattr(self._inner, name)
        if name not in self.TIMED or not callable(fn):
            return fn

        def timed(*a, **kw):
            s = self._rec.now()
            out = fn(*a, **kw)
            self._rec.crypto.append({"name": name, "server": self._server, "start": round(s, 4),
                                     "seconds": round(self._rec.now() - s, 4)})
            return out
        return timed


def chunk_view(ch: dict) -> dict:
    return {"id": ch.get("id"), "server": ch.get("server"), "url": ch.get("url"), "title": ch.get("title"),
            "score": round(float(ch.get("score", 0.0)), 4), "raw_score": ch.get("raw_score")}


def make_answer_fn(kind: str, rec: Recorder):
    """The answer step, wrapped so the trace sees the search order, the rerank order and model time."""
    if kind == "none":
        def skipped(question, chunks):
            rec.search = [chunk_view(c) for c in chunks]
            return {"status": "skipped", "declined": False, "answer": "", "citations": [], "urgent": None}
        return skipped
    if kind == "stub":
        from client import answer_stub

        def stub(question, chunks):
            rec.search = [chunk_view(c) for c in chunks]
            return answer_stub.answer(question, chunks)
        return stub

    from client import answer as A

    def rerank(question, chunks):
        s = rec.now()
        out = A._default_rerank(question, chunks)
        rec.event("rerank", s, rec.now() - s, model=A.RERANK_MODEL)
        rec.reranked = [chunk_view(c) for c in out]
        return out

    def llm(prompt, *a, **kw):
        s = rec.now()
        out = A.ollama_chat(prompt, *a, **kw)
        rec.event("model", s, rec.now() - s, model=A.MODEL, prompt_chars=len(prompt), output_chars=len(out))
        rec.answer_detail["raw_model_output"] = out
        return out

    def real(question, chunks):
        rec.search = [chunk_view(c) for c in chunks]
        return A.answer(question, chunks, llm=llm, rerank=rerank)
    return real


# ---------------------------------------------------------------- plaintext reference (exactness check)

class Reference:
    """Plaintext int8 scores computed on this machine from the same tables the server holds.

    Used only when a local artifacts folder has the same corpus_version as the server. The encrypted
    pipeline must reproduce these scores exactly (LWE decryption is exact when scores don't wrap)."""

    def __init__(self, manifests: dict[str, dict]):
        self.tables: dict[str, tuple] = {}
        local = {}
        for mf in [ROOT / "artifacts" / "manifest.json", *sorted((ROOT / "artifacts").glob("*/manifest.json"))]:
            try:
                m = json.loads(mf.read_text())
                local.setdefault(m["corpus_version"], mf.parent)
            except Exception:  # noqa: BLE001
                continue
        for server, m in manifests.items():
            d = local.get(m["corpus_version"])
            if d is None:
                continue
            try:
                table = np.fromfile(d / "score_table.bin", dtype=np.int8)
                n, dim = m["num_chunks"], m["embedding"]["dim"]
                if table.size == n * dim:
                    self.tables[server] = (table.reshape(n, dim).astype(np.int64), m, str(d.relative_to(ROOT)))
            except Exception:  # noqa: BLE001
                continue

    def available(self, server) -> bool:
        return server in self.tables

    def topk(self, server: str, question: str):
        from client import embed as emb
        import contracts as c
        table, m, _ = self.tables[server]
        q = emb.quantize(emb.embed(question, m["embedding"].get("query_prefix", c.QUERY_PREFIX)),
                         m["quantization"]["scale"]).astype(np.int64)
        scores = table @ q
        top = np.argsort(-scores, kind="stable")[: m["top_k"]]
        return [int(i) for i in top], [int(scores[i]) for i in top]


# ---------------------------------------------------------------- server log join

class ServerLogs:
    """What each server logged (ts, endpoint, response_bytes, latency_ms), matched to client requests."""

    def __init__(self, servers, spec: str | None):
        self.sources = {}
        self.used = set()
        if spec == "off":
            return
        for s in servers:
            if spec and spec != "auto":
                src = spec
            else:
                src = local_log(s) if is_local(s) else s + "/v1/server_log"
            if src.startswith("http"):
                self.sources[s] = ("url", src)
            elif src and pathlib.Path(src).exists():
                self.sources[s] = ("file", pathlib.Path(src))

    def _read(self, server) -> list[dict]:
        kind, src = self.sources[server]
        try:
            if kind == "url":
                r = requests.get(src, params={"n": 200}, timeout=20)
                if r.status_code != 200:
                    return []
                lines = r.text.splitlines()
            else:
                with open(src, "rb") as f:   # the tail is enough: one question makes a few lines
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 400_000))
                    lines = f.read().decode("utf-8", "replace").splitlines()
        except Exception:  # noqa: BLE001
            return []
        out = []
        for ln in lines:
            try:
                e = json.loads(ln)
                e["_t"] = _parse_utc(e["ts"])
                out.append(e)
            except Exception:  # noqa: BLE001
                continue
        return out

    def join(self, requests_: list[dict], slack: float = 5.0):
        """Fills server_ms / network_ms on each request when its log line is found. A log line matches
        on endpoint + response bytes, at the closest time within `slack` seconds (allows clock skew)."""
        by_server: dict[str, list[dict]] = {}
        for r in requests_:
            if r["server"] in self.sources:
                by_server.setdefault(r["server"], []).append(r)
        for server, reqs in by_server.items():
            log = self._read(server)
            for r in reqs:
                mid = (r["utc_start"] + r["utc_end"]) / 2
                best = None
                for e in log:
                    key = (server, e["ts"], e["endpoint"], e.get("response_bytes"))
                    if key in self.used or e["endpoint"] != r["endpoint"]:
                        continue
                    if e.get("response_bytes") != r["response_bytes"]:
                        continue
                    d = abs(e["_t"] - mid)
                    if d <= slack and (best is None or d < best[0]):
                        best = (d, e, key)
                if best:
                    self.used.add(best[2])
                    r["server_ms"] = round(float(best[1]["latency_ms"]), 2)
                    r["network_ms"] = round(max(0.0, r["client_ms"] - r["server_ms"]), 2)
                    r["server_log_fields"] = sorted(k for k in best[1] if not k.startswith("_"))


# ---------------------------------------------------------------- one question

def gold_rank(chunks: list[dict], gold: str | None):
    if not gold:
        return None
    return next((i for i, c in enumerate(chunks, 1) if c.get("url") == gold), None)


def run_question(pipe, q: dict, rec: Recorder, ref: Reference | None, logs: ServerLogs, n_context: int,
                 answer_kind: str, rep: int) -> dict:
    rec.reset()
    stage_marks = []

    def on_stage(name, secs):
        stage_marks.append((name, rec.now()))   # precise end time of each stage (the trace rounds to ms)

    err = None
    result, trace = None, {}
    try:
        result, trace = pipe.ask_traced(q["question"], on_stage=on_stage)
    except Exception as e:  # noqa: BLE001
        err = {"type": type(e).__name__, "message": str(e)[:500],
               "stage": getattr(e, "stage", None), "trace": traceback.format_exc(limit=4)}
    wall = rec.now()

    # Pipeline stages as consecutive spans (servers run in parallel, so multi-server stages are the slowest).
    if not getattr(pipe, "pipes", None) and stage_marks:   # one server: stages from our own clock
        timings, prev = {}, 0.0
        for name, end in stage_marks:
            timings[name] = end - prev
            prev = end
    else:   # several servers run in parallel; their trace has each stage's slowest server
        timings = trace.get("timings") or {}
    spans, t = [], 0.0
    for name, secs in timings.items():
        spans.append({"name": name, "start": round(t, 4), "seconds": round(secs, 4)})
        t += secs
    # Inside "answering": rerank, model, and the rest (citation checks, safety, formatting).
    sub = {e["name"]: e["seconds"] for e in rec.events}
    if "answering" in timings and sub:
        sub["checks"] = round(max(0.0, timings["answering"] - sum(sub.values())), 4)

    logs.join(rec.requests)
    for r in rec.requests:
        r["one_time"] = r["endpoint"] in ONE_TIME
        r.pop("utc_start", None), r.pop("utc_end", None)

    status = (result or {}).get("status", "error" if err else None)
    answered = status == "answered"
    cited = [c.get("url") for c in (result or {}).get("citations", [])] if answered else []
    gold = q.get("source_url")
    expect = q.get("expect")
    rank = gold_rank(rec.search, gold)
    ctx = rec.reranked[:n_context] if rec.reranked else rec.search[:n_context]
    urgent_got = ((result or {}).get("urgent") or {}).get("kind")

    # Exactness: decrypted encrypted scores vs plaintext int8 scores (single corpus per server).
    parity = None
    if ref is not None and rec.search and not err:
        home = pipe_server(pipe)
        checks = []
        for server in dict.fromkeys(c.get("server") or home for c in rec.search):
            if not ref.available(server):
                continue
            ids, raw = ref.topk(server, q["question"])
            exp = dict(zip(ids, raw))
            mine = [c for c in rec.search if (c.get("server") or home) == server]
            exact = all(c["id"] in exp and c["raw_score"] == exp[c["id"]] for c in mine)
            # one server: the whole top-k, in order; several: what this server contributed is in its top-k
            match = [c["id"] for c in mine] == ids if len(rec.search) == len(mine) else all(c["id"] in exp for c in mine)
            checks.append({"server": server, "reference_top_ids": ids, "scores_exact": exact, "top_ids_match": match})
        if checks:
            parity = {"servers": checks, "exact": all(c["scores_exact"] for c in checks),
                      "top_ids_match": all(c["top_ids_match"] for c in checks)}

    per_q = [r for r in rec.requests if not r["one_time"]]
    return {
        "id": q.get("id"), "rep": rep, "question": q["question"], "category": q.get("category"),
        "split": q.get("split"), "expect": expect, "gold_url": gold,
        "status": status, "error": err,
        "accuracy": {
            "behaved": None if status in ("skipped", None) or err else (answered == (expect == "answer")),
            "gold_rank": rank,
            "gold_in_topk": (rank is not None) if gold else None,
            "gold_in_context": (any(c.get("url") == gold for c in ctx)) if gold and rec.search else None,
            "gold_cited": (gold in cited) if gold and answered else (False if gold and status == "declined" else None),
            "urgent_expected": q.get("urgent"), "urgent": urgent_got,
            "urgent_ok": None if status in ("skipped", None) else urgent_got == q.get("urgent"),
            "removed_sentences": ((result or {}).get("checks") or {}).get("removed_sentences"),
            "parity": parity,
        },
        "speed": {
            "wall_seconds": round(wall, 4),
            "stages": {k: round(v, 4) for k, v in timings.items()},
            "answer_parts": sub,
            "client_crypto": {k: round(sum(c["seconds"] for c in rec.crypto if c["name"] == k), 4)
                              for k in dict.fromkeys(c["name"] for c in rec.crypto)},
            "request_client_ms": round(sum(r["client_ms"] for r in per_q), 2),
            "request_server_ms": round(sum(r.get("server_ms", 0) for r in per_q), 2) if per_q and all("server_ms" in r for r in per_q) else None,
        },
        "bytes": {"up": sum(r["request_bytes"] for r in per_q), "down": sum(r["response_bytes"] for r in per_q),
                  "one_time_down": sum(r["response_bytes"] for r in rec.requests if r["one_time"])},
        "trace": {
            "started_utc": _utc(rec.wall0), "mode": trace.get("mode"), "fetch_mode": trace.get("fetch_mode"),
            "servers": [s["server"] for s in trace.get("servers", [])] or [pipe_server(pipe)],
            "corpus_version": trace.get("corpus_version"), "top_k": trace.get("top_k"),
            "spans": spans, "answer_events": rec.events, "crypto_calls": rec.crypto, "requests": rec.requests,
            "search": rec.search, "reranked": rec.reranked[:n_context] if rec.reranked else None,
            "per_server": [{k: s[k] for k in ("server", "fetched", "used")} for s in trace.get("servers", [])],
            "ciphertext_sample": (trace.get("ciphertext_sample") or "")[:32],
        },
        "answer": {"text": (result or {}).get("answer"), "citations": cited,
                   "raw_model_output": rec.answer_detail.get("raw_model_output")},
        "answer_kind": answer_kind,
    }


def pipe_server(pipe) -> str:
    return getattr(pipe, "server", "")


# ---------------------------------------------------------------- summary

def summarize(rows: list[dict], meta: dict) -> dict:
    ok = [r for r in rows if not r["error"]]
    qs = [r for r in ok if r["rep"] == 0]   # accuracy: one run per question (repeats are for speed)
    pos = [r for r in qs if r["gold_url"]]
    exp_ans = [r for r in qs if r["expect"] == "answer"]
    exp_dec = [r for r in qs if r["expect"] == "decline"]
    judged = [r for r in qs if r["accuracy"]["behaved"] is not None]
    A = lambda r, k: r["accuracy"][k]  # noqa: E731

    acc = {
        "questions": len(qs), "runs": len(rows), "errors": len(rows) - len(ok),
        "recall_at": {str(k): frac(sum(1 for r in pos if A(r, "gold_rank") and A(r, "gold_rank") <= k), len(pos))
                      for k in KS},
        "gold_in_fetched": frac(sum(1 for r in pos if A(r, "gold_rank")), len(pos)),
        "gold_in_model_sources": frac(sum(1 for r in pos if A(r, "gold_in_context")), len(pos)),
    }
    if judged:
        acc.update({
            "behaved_as_expected": frac(sum(A(r, "behaved") for r in judged), len(judged)),
            "answerable_answered": frac(sum(r["status"] == "answered" for r in exp_ans), len(exp_ans)),
            "answerable_cited_right_page": frac(sum(bool(A(r, "gold_cited")) for r in exp_ans if r["gold_url"]),
                                                sum(1 for r in exp_ans if r["gold_url"])),
            "should_decline_declined": frac(sum(r["status"] == "declined" for r in exp_dec), len(exp_dec)),
            "wrong_answers": frac(sum(r["status"] == "answered" for r in exp_dec), len(exp_dec)),
            "urgent_notice_correct": frac(sum(bool(A(r, "urgent_ok")) for r in judged), len(judged)),
            "sentences_removed_by_checker": sum(A(r, "removed_sentences") or 0 for r in judged),
        })
    par = [A(r, "parity") for r in qs if A(r, "parity")]
    if par:
        acc["encrypted_scores_exact"] = frac(sum(p["exact"] for p in par), len(par))
        acc["encrypted_topk_matches_plaintext"] = frac(sum(p["top_ids_match"] for p in par), len(par))
    cats = {}
    for r in qs:
        c = cats.setdefault(r["category"] or "?", {"n": 0, "behaved": 0, "judged": 0, "gold_in_topk": 0, "with_gold": 0})
        c["n"] += 1
        if A(r, "behaved") is not None:
            c["judged"] += 1
            c["behaved"] += bool(A(r, "behaved"))
        if r["gold_url"]:
            c["with_gold"] += 1
            c["gold_in_topk"] += bool(A(r, "gold_in_topk"))
    acc["by_category"] = cats

    # Speed: question 1 is cold (model load, caches); report warm runs separately.
    warm = ok[1:] if len(ok) > 1 else ok
    stage_names = []
    for r in ok:
        for k in r["speed"]["stages"]:
            if k not in stage_names:
                stage_names.append(k)
    part_names = sorted({k for r in ok for k in r["speed"]["answer_parts"]})
    endpoints = sorted({q["endpoint"] for r in ok for q in r["trace"]["requests"]})
    speed = {
        "cold_first_question_seconds": ok[0]["speed"]["wall_seconds"] if ok else None,
        "wall_seconds": stats(r["speed"]["wall_seconds"] for r in warm),
        "stages_seconds": {k: stats(r["speed"]["stages"].get(k) for r in warm) for k in stage_names},
        "answer_parts_seconds": {k: stats(r["speed"]["answer_parts"].get(k) for r in warm) for k in part_names},
        "client_crypto_seconds": {k: stats(r["speed"]["client_crypto"].get(k) for r in warm)
                                  for k in sorted({k for r in ok for k in r["speed"]["client_crypto"]})},
        "retrieval_seconds": stats(sum(v for k, v in r["speed"]["stages"].items() if k != "answering") for r in warm),
        "endpoints_ms": {},
    }
    for ep in endpoints:
        reqs = [q for r in warm for q in r["trace"]["requests"] if q["endpoint"] == ep] or \
               [q for r in ok for q in r["trace"]["requests"] if q["endpoint"] == ep]
        speed["endpoints_ms"][ep] = {
            "count": len(reqs),
            "client": stats(q["client_ms"] for q in reqs),
            "server": stats(q.get("server_ms") for q in reqs),
            "network": stats(q.get("network_ms") for q in reqs),
            "response_bytes": stats(q["response_bytes"] for q in reqs),
        }
    byt = {"up_per_question": stats(r["bytes"]["up"] for r in ok),
           "down_per_question": stats(r["bytes"]["down"] for r in ok),
           "one_time_down": sum(r["bytes"]["one_time_down"] for r in ok)}
    logged = [q for r in ok for q in r["trace"]["requests"] if "server_log_fields" in q]
    privacy = {
        "server_log_lines_matched": f"{len(logged)}/{sum(len(r['trace']['requests']) for r in ok)}",
        "server_log_fields": sorted({f for q in logged for f in q["server_log_fields"]}),
        "server_log_only_allowed_fields": all(set(q["server_log_fields"]) <= {"ts", "endpoint", "response_bytes", "latency_ms"}
                                              for q in logged) if logged else None,
        "requests_per_question_per_server": stats(
            len([q for q in r["trace"]["requests"] if not q["one_time"]]) / max(1, len(r["trace"]["servers"])) for r in ok),
        "fetched_per_server_always_k": all(
            all(s["fetched"] == r["trace"]["top_k"] for s in r["trace"]["per_server"]) if r["trace"]["per_server"]
            else len(r["trace"]["search"]) == r["trace"]["top_k"] for r in ok) if ok else None,
    }
    return {"meta": meta, "accuracy": acc, "speed": speed, "bytes": byt, "privacy": privacy}


# ---------------------------------------------------------------- reports

def _f(x):
    return "" if x is None else (f"{x['n']}/{x['of']} ({x['pct']:.0f}%)" if x["of"] else "n/a")


def _s(st, unit="s", scale=1.0, nd=2):
    if not st:
        return "n/a"
    return f"{st['p50'] * scale:.{nd}f} / {st['p95'] * scale:.{nd}f} {unit}"


def _kb(n):
    if n is None:
        return "n/a"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1048576:.2f} MB"


def report_md(summary: dict) -> str:
    m, a, s, b, p = summary["meta"], summary["accuracy"], summary["speed"], summary["bytes"], summary["privacy"]
    L = [f"# Blind RAG benchmark: {m['name']}", "",
         f"`{m['commit']}` ({m['branch']}) · {m['started_utc']} · {m['host']}  ",
         f"servers: {', '.join(m['servers'])} · corpus {m['corpus']} · crypto `{m['crypto']}` · fetch `{m['fetch']}` "
         f"· embed `{m['embed']}` · answers `{m['answer']}`  ",
         f"{a['questions']} questions × {m['repeat']} run(s), {a['errors']} errors · setup (manifest + keys + hints) "
         f"{m['setup_seconds']:.2f} s", "",
         "## Accuracy", "", "| Metric | Value |", "|---|---|"]
    for k in KS:
        L.append(f"| Right page in encrypted top {k} | {_f(a['recall_at'][str(k)])} |")
    L.append(f"| Right page anywhere in what was fetched (k per server) | {_f(a['gold_in_fetched'])} |")
    L.append(f"| Right page among the model's sources (after rerank) | {_f(a['gold_in_model_sources'])} |")
    for key, label in (("answerable_answered", "Answerable questions answered"),
                       ("answerable_cited_right_page", "Answerable questions citing the right page"),
                       ("should_decline_declined", "Should-decline questions declined"),
                       ("wrong_answers", "Wrong answers (answered when it should decline)"),
                       ("behaved_as_expected", "Behaved as expected (all)"),
                       ("urgent_notice_correct", "988/911 notice correct"),
                       ("encrypted_scores_exact", "Decrypted scores == plaintext int8 scores (exact)"),
                       ("encrypted_topk_matches_plaintext", "Encrypted top-k == plaintext top-k")):
        if key in a:
            L.append(f"| {label} | {_f(a[key])} |")
    if "sentences_removed_by_checker" in a:
        L.append(f"| Unsupported sentences removed by the citation checker | {a['sentences_removed_by_checker']} |")
    L += ["", "| Category | Behaved | Right page in top-k |", "|---|---|---|"]
    for c, v in sorted(a["by_category"].items()):
        b_ = f"{v['behaved']}/{v['judged']}" if v["judged"] else "–"
        g_ = f"{v['gold_in_topk']}/{v['with_gold']}" if v["with_gold"] else "–"
        L.append(f"| {c} | {b_} | {g_} |")
    L += ["", "## Speed (p50 / p95, warm runs)", "",
          f"Cold first question: {s['cold_first_question_seconds']:.3f} s · whole question: {_s(s['wall_seconds'])} · "
          f"retrieval only (embed → fetch): {_s(s['retrieval_seconds'], 'ms', 1000, 0)}", "",
          "| Stage | p50 / p95 | mean |", "|---|---|---|"]
    for k, st in s["stages_seconds"].items():
        L.append(f"| {k} | {_s(st, 'ms', 1000, 1)} | {st['mean'] * 1000:.1f} ms |" if st else f"| {k} | n/a | |")
    for k, st in s["answer_parts_seconds"].items():
        L.append(f"| answering → {k} | {_s(st, 'ms', 1000, 1)} | {st['mean'] * 1000:.1f} ms |" if st else "")
    for k, st in s["client_crypto_seconds"].items():
        L.append(f"| client crypto → {k} | {_s(st, 'ms', 1000, 1)} | {st['mean'] * 1000:.1f} ms |" if st else "")
    L += ["", "| Endpoint | calls | client round trip | server (from its log) | network + client I/O | response |",
          "|---|---|---|---|---|---|"]
    for ep, v in s["endpoints_ms"].items():
        L.append(f"| `{ep}` | {v['count']} | {_s(v['client'], 'ms', 1, 1)} | {_s(v['server'], 'ms', 1, 1)} | "
                 f"{_s(v['network'], 'ms', 1, 1)} | {_kb(v['response_bytes']['p50']) if v['response_bytes'] else 'n/a'} |")
    L += ["", "## Bytes and what the server saw", "",
          f"Per question: up {_kb(b['up_per_question']['p50']) if b['up_per_question'] else 'n/a'}, "
          f"down {_kb(b['down_per_question']['p50']) if b['down_per_question'] else 'n/a'} (median) · "
          f"one-time downloads during the run: {_kb(b['one_time_down'])}", "",
          f"- Server log lines matched to client requests: {p['server_log_lines_matched']}",
          f"- Fields the server logged: {', '.join(p['server_log_fields']) or 'n/a'} "
          f"(only the four allowed: {p['server_log_only_allowed_fields']})",
          f"- Exactly k records fetched from every selected server on every question: {p['fetched_per_server_always_k']}",
          "", "Per-question traces: `report.html` (click a question) or `traces.jsonl`."]
    return "\n".join(x for x in L if x is not None) + "\n"


def write_html(out: pathlib.Path, rows: list[dict], summary: dict):
    from eval.bench_html import render
    (out / "report.html").write_text(render(rows, summary, report_md(summary)), encoding="utf-8")


# ---------------------------------------------------------------- compare

def compare(dirs: list[pathlib.Path]):
    sums = [json.loads((d / "summary.json").read_text()) for d in dirs]

    def flat(sm):
        a, s, b = sm["accuracy"], sm["speed"], sm["bytes"]
        out = {f"recall@{k}": a["recall_at"][str(k)]["pct"] for k in KS}
        out["gold in model sources %"] = a["gold_in_model_sources"]["pct"]
        for k in ("answerable_answered", "answerable_cited_right_page", "should_decline_declined",
                  "wrong_answers", "behaved_as_expected", "encrypted_scores_exact"):
            if k in a:
                out[k + " %"] = a[k]["pct"]
        out["wall p50 s"] = (s["wall_seconds"] or {}).get("p50")
        out["wall p95 s"] = (s["wall_seconds"] or {}).get("p95")
        out["retrieval p50 ms"] = round(s["retrieval_seconds"]["p50"] * 1000, 1) if s["retrieval_seconds"] else None
        for k, st in s["stages_seconds"].items():
            out[f"{k} p50 ms"] = round(st["p50"] * 1000, 1) if st else None
        out["up/question B"] = (b["up_per_question"] or {}).get("p50")
        out["down/question B"] = (b["down_per_question"] or {}).get("p50")
        return out

    flats = [flat(s) for s in sums]
    keys = list(dict.fromkeys(k for f in flats for k in f))
    print("| metric | " + " | ".join(s["meta"]["name"] for s in sums) + " |")
    print("|---|" + "---|" * len(sums))
    for k in keys:
        print(f"| {k} | " + " | ".join("" if f.get(k) is None else str(f.get(k)) for f in flats) + " |")


# ---------------------------------------------------------------- main

def load_questions(path: pathlib.Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def build_pipeline(servers, answer_fn, fetch):
    from client.multi import MultiPipeline
    from client.pipeline import Pipeline
    if len(servers) == 1:
        return Pipeline(server=servers[0], answer_fn=answer_fn, fetch_mode=fetch), None
    mp = MultiPipeline(servers, answer_fn=answer_fn, fetch_mode=fetch)
    return mp, mp.pipes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", type=pathlib.Path, default=ROOT / "eval" / "questions.jsonl")
    ap.add_argument("--limit", type=int, help="first N questions only")
    ap.add_argument("--ids", help="comma-separated question ids")
    ap.add_argument("--category", help="only this category (e.g. urgent, fmla)")
    ap.add_argument("--split", help="only this split (tune | test)")
    ap.add_argument("--servers", help="comma-separated document servers (default: BLIND_RAG_SERVERS / BLIND_RAG_SERVER)")
    ap.add_argument("--fetch", choices=["download", "pir"], help="default: BLIND_RAG_FETCH, else the pipeline's default")
    ap.add_argument("--answer", choices=["real", "stub", "none"], default=os.environ.get("BLIND_RAG_ANSWER", "real"),
                    help="real = rerank + local model (default); none = retrieval only")
    ap.add_argument("--repeat", type=int, default=1, help="runs per question (speed); accuracy uses the first")
    ap.add_argument("--server-log", default="auto",
                    help="auto (data/server.log for local, <server>/v1/server_log for remote) | off | file | URL")
    ap.add_argument("--name", help="run label (default: timestamp + settings)")
    ap.add_argument("--out", type=pathlib.Path, help="output folder (default eval/results/bench/<name>)")
    ap.add_argument("--compare", nargs="+", type=pathlib.Path, help="print a comparison of finished runs and exit")
    a = ap.parse_args(argv)

    if a.compare:
        compare(a.compare)
        return 0

    from client.multi import configured_servers
    from client import embed as emb
    servers = [s.strip().rstrip("/") for s in a.servers.split(",")] if a.servers else configured_servers()
    if a.fetch:
        os.environ["BLIND_RAG_FETCH"] = a.fetch

    qs = load_questions(a.questions)
    if a.ids:
        want = set(a.ids.split(","))
        qs = [q for q in qs if q["id"] in want]
    if a.category:
        qs = [q for q in qs if q.get("category") == a.category]
    if a.split:
        qs = [q for q in qs if q.get("split") == a.split]
    if a.limit:
        qs = qs[: a.limit]
    if not qs:
        print("no questions selected", file=sys.stderr)
        return 2

    rec = Recorder()
    answer_fn = make_answer_fn(a.answer, rec)
    pipe, pipes = build_pipeline(servers, answer_fn, a.fetch)
    for p in pipes or [pipe]:
        instrument_session(p.http, p.server, rec)
        p.answer_kind = a.answer
        p.crypto = TimedCrypto(p.crypto, rec, p.server)

    t = time.perf_counter()
    manifests = {}
    for p in pipes or [pipe]:
        manifests[p.server] = p.load_manifest()
    if pipes:
        pipe.manifests()   # embedding-compatibility check across servers
    setup = time.perf_counter() - t
    from client.answer import N_CONTEXT

    started = datetime.datetime.now(datetime.timezone.utc)
    name = a.name or started.strftime("%Y%m%d-%H%M%S") + f"-{a.answer}-{pipe.fetch_mode}-{len(servers)}srv"
    out = a.out or RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    ref = Reference(manifests)
    logs = ServerLogs(servers, a.server_log)
    meta = {
        "name": name, "started_utc": started.isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "--short", "HEAD"), "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "host": f"{platform.system()} {platform.machine()} · Python {platform.python_version()}",
        "servers": servers, "corpus": " + ".join(f"{m['corpus_version']} ({m['num_chunks']})" for m in manifests.values()),
        "crypto": pipe.crypto_kind, "fetch": pipe.fetch_mode, "embed": emb.mode(), "answer": a.answer,
        "repeat": a.repeat, "setup_seconds": round(setup, 3), "questions_file": str(a.questions.relative_to(ROOT))
        if a.questions.is_absolute() and ROOT in a.questions.parents else str(a.questions),
        "reference_tables": {s: v[2] for s, v in ref.tables.items()},
        "log_sources": {s: str(v[1]) for s, v in logs.sources.items()},
    }
    print(f"bench {name}: {len(qs)} questions x {a.repeat} on {', '.join(servers)} "
          f"(crypto {pipe.crypto_kind}, fetch {pipe.fetch_mode}, answers {a.answer}); setup {setup:.2f}s", flush=True)

    rows = []
    with open(out / "traces.jsonl", "w", encoding="utf-8") as f:
        for i, q in enumerate(qs):
            for rep in range(a.repeat):
                row = run_question(pipe, q, rec, ref, logs, N_CONTEXT, a.answer, rep)
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                acc = row["accuracy"]
                flag = "ERR " if row["error"] else ("ok  " if acc["behaved"] else ("MISS" if acc["behaved"] is False else "    "))
                ex = "" if not acc["parity"] else (" exact" if acc["parity"]["exact"] else " SCORE-MISMATCH")
                print(f"  {row['id']:>6} r{rep} {row['speed']['wall_seconds']:7.2f}s {str(row['status']):9} {flag} "
                      f"rank={acc['gold_rank']}{ex}  {q['question'][:56]}", flush=True)
    summary = summarize(rows, meta)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    md = report_md(summary)
    (out / "report.md").write_text(md)
    write_html(out, rows, summary)
    try:
        pipe.close()
    except Exception:  # noqa: BLE001
        pass
    print("\n" + md)
    print(f"wrote {out.relative_to(ROOT) if ROOT in out.parents else out}/ (report.html, report.md, summary.json, traces.jsonl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
