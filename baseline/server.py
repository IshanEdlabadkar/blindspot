"""The "normal RAG server" for demo step 1: it reads every question in plain text, and its log shows it.

Run:  uv run python -m baseline.server            (http://127.0.0.1:8001)
API:  POST /ask  {"question": "..."}  -> answer shape from docs/contracts.md
      GET  /log                        -> recent log entries (JSON list), for the UI's log pane
      GET  /health
"""
import argparse
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "plain_server.log"


class PlainServer(ThreadingHTTPServer):
    def __init__(self, address, ask_fn, log_path=LOG_PATH, keep: int = 200):
        super().__init__(address, _Handler)
        self.ask_fn = ask_fn
        self.log_path = Path(log_path)
        self.recent: deque = deque(maxlen=keep)
        self.lock = threading.Lock()

    def log_entry(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False)
        with self.lock:
            self.recent.append(entry)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        print(line, flush=True)


class _Handler(BaseHTTPRequestHandler):
    server: PlainServer

    def _send(self, code: int, obj=None) -> None:
        body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if obj is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        if self.path == "/log":
            with self.server.lock:
                return self._send(200, list(self.server.recent))
        if self.path == "/health":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/ask":
            return self._send(404, {"error": "not found"})
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            question = json.loads(raw)["question"].strip()
        except (ValueError, KeyError, TypeError, AttributeError):
            question = ""
        if not question:
            return self._send(400, {"error": 'send JSON {"question": "..."}'})

        t0 = time.perf_counter()
        result = self.server.ask_fn(question)
        self.server.log_entry({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "endpoint": "/ask",
            "client": self.client_address[0],
            "question": question,
            "status": result["status"],
            "returned": [{"title": c["title"], "url": c["url"]} for c in result["citations"]],
            "latency_ms": round((time.perf_counter() - t0) * 1000),
        })
        self._send(200, result)

    def log_message(self, *args):  # the JSON log line above replaces the default access log
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()

    from baseline.ask_plain import ask_plain, default_index
    from client.answer import ollama_generate
    from common.embedding import embed_query_float

    print("warming up the embedder and local model...", flush=True)
    default_index()
    embed_query_float("warm up")
    ollama_generate("Say OK.")

    srv = PlainServer((args.host, args.port), ask_plain)
    print(f"plaintext RAG server on http://{args.host}:{args.port}  (log: {srv.log_path})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
