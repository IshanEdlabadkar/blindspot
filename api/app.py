"""Thin API behind the Vault web UI (web/). It wraps what already works and adds no new privacy logic:
C's encrypted pipeline, B's traffic recorder search, and B's plaintext "normal RAG" server for contrast.

  uv run uvicorn api.app:app --port 8600          (or: ./web/demo.sh, which starts everything)

Env: BLIND_RAG_SERVERS (comma-separated; the wiretap relay ports when started by wiretap/demo.sh),
BLIND_RAG_PLAIN_SERVER (default http://127.0.0.1:9001), BLIND_RAG_WIRE_LOG (default data/wire/wire.jsonl).

POST /api/ask streams Server-Sent Events: start, stage x5 (as each step finishes), answer, plain (if
compare), proof (the traffic search), done; or error {stage, message, fix}.
"""
import json
import os
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from wiretap.proxy import read_records
from wiretap.search import question_words, search_traffic

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
HELPER = "http://127.0.0.1:8090/health"
OLLAMA = "http://localhost:11434/api/tags"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def configured_servers() -> list[str]:
    """BLIND_RAG_SERVERS / BLIND_RAG_SERVER, else every server in servers.remote.json (all four hosted ones)."""
    from client.multi import configured_servers as from_list
    return from_list()


def default_pipeline(servers: list[str]):
    from client.multi import MultiPipeline
    from client.pipeline import Pipeline
    return MultiPipeline(servers) if len(servers) > 1 else Pipeline(server=servers[0])


def default_plain_ask(url: str, question: str) -> dict:
    """Send the question, unencrypted, to the plaintext demo server and read back what it logged."""
    try:
        requests.post(url + "/ask", json={"question": question}, timeout=180).raise_for_status()
        mine = [e for e in requests.get(url + "/log", timeout=10).json() if e.get("question") == question]
        return {"entry": mine[-1]} if mine else {"error": "The normal server answered but logged nothing."}
    except requests.RequestException as e:
        return {"error": f"Normal (plaintext) server not reachable at {url}: {type(e).__name__}"}


def default_status_get(url: str) -> dict:
    from client import net
    r = net.get(url + "/v1/manifest", timeout=8)
    r.raise_for_status()
    return r.json()


class Ask(BaseModel):
    question: str
    compare: bool = True


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def make_app(servers=None, pipeline_factory=default_pipeline, plain_ask=default_plain_ask,
             plain_url=None, wire_log=None, status_get=default_status_get) -> FastAPI:
    app = FastAPI(title="Blind RAG API")

    @app.middleware("http")
    async def security_headers(request, call_next):
        # The page shows passages from servers we don't control. This policy lets it load code only from
        # this app and talk only to this API, so even an injected script couldn't send the question or
        # the answer anywhere else. Styles allow inline (the UI animates with style attributes).
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "font-src 'self' data:; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"   # source links don't tell sites where you came from
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return resp
    servers = servers or configured_servers()
    plain_url = plain_url or os.environ.get("BLIND_RAG_PLAIN_SERVER", "http://127.0.0.1:9001")
    wire_log = Path(wire_log or os.environ.get("BLIND_RAG_WIRE_LOG", ROOT / "data" / "wire" / "wire.jsonl"))
    state = {"pipeline": None}
    lock = threading.Lock()  # one question at a time: the pipeline holds per-session keys

    def pipeline():
        if state["pipeline"] is None:
            state["pipeline"] = pipeline_factory(servers)
        return state["pipeline"]

    @app.get("/api/status")
    def status():
        out = []
        for url in servers:
            try:
                m = status_get(url)
                out.append({"url": url, "ok": True, "name": m.get("source_name") or m.get("corpus_name") or url,
                            "num_chunks": m.get("num_chunks"), "corpus_version": m.get("corpus_version")})
            except Exception:  # noqa: BLE001
                out.append({"url": url, "ok": False, "name": url, "num_chunks": None, "corpus_version": None})

        def up(url):  # generous timeout: a busy laptop answers slowly, and "off" would be a false alarm
            try:
                return requests.get(url, timeout=10).ok
            except requests.RequestException:
                return False
        return {"servers": out, "helper": up(HELPER), "model": up(OLLAMA), "recording": wire_log.exists()}

    @app.post("/api/ask")
    def ask(body: Ask):
        q = body.question.strip()
        if not q:
            raise HTTPException(400, "Ask a question first.")

        def stream():
            with lock:
                since = utc_now()
                yield _sse("start", {"question": q, "since": since, "servers": servers})
                events: queue.Queue = queue.Queue()

                def run():
                    try:
                        result, trace = pipeline().ask_traced(
                            q, lambda name, secs: events.put(("stage", {"name": name, "seconds": secs})))
                        events.put(("answer", {"result": result, "trace": trace}))
                    except Exception as e:  # noqa: BLE001
                        events.put(("error", {"stage": getattr(e, "stage", "unexpected"),
                                              "message": getattr(e, "message", f"{type(e).__name__}: {e}"),
                                              "fix": getattr(e, "fix", "")}))
                threading.Thread(target=run, daemon=True).start()
                while True:
                    name, data = events.get()
                    yield _sse(name, data)
                    if name == "error":
                        return
                    if name == "answer":
                        break
                if body.compare:
                    yield _sse("plain", plain_ask(plain_url, q))
                routes = search_traffic(read_records(wire_log), q, since)
                yield _sse("proof", {"words": question_words(q), "routes": routes, "since": since,
                                     "recording": wire_log.exists()})
                yield _sse("done", {})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/wire")
    def wire(word: str, since: str | None = None):
        return {"word": word, "words": question_words(word),
                "routes": search_traffic(read_records(wire_log), word, since)}

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = DIST / path
            return FileResponse(f if path and f.is_file() else DIST / "index.html")

    return app


app = make_app()
