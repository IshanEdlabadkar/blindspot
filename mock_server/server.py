"""Plaintext MOCK of A's Go crypto server. NOT PRIVATE. Never demo this as Blindspot.

Same three endpoints and the same log line as the real server, no encryption.

    python -m mock_server.server --data data --port 8080
"""
import argparse
import datetime
import json
import pathlib
import struct
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import contracts as c  # noqa: E402


class State:
    def __init__(self, data_dir, log_path):
        d = pathlib.Path(data_dir)
        self.manifest_bytes = (d / "manifest.json").read_bytes()
        self.manifest = json.loads(self.manifest_bytes)
        self.n = self.manifest["num_chunks"]
        self.L = self.manifest["pir"]["record_bytes"]
        self.table = np.fromfile(d / "score_table.bin", dtype=np.int8).reshape(self.n, c.DIM).astype(np.int32)
        self.store = (d / "fetch_store.bin").read_bytes()
        assert len(self.store) == self.n * self.L, "fetch_store.bin size does not match manifest"
        self.log_path = pathlib.Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, endpoint, response_bytes, t0):
        # Agreed log line. Timestamp, endpoint, response size, latency. No request bodies.
        line = json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "endpoint": endpoint,
            "response_bytes": response_bytes,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        })
        with open(self.log_path, "a") as f:
            f.write(line + "\n")


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        wbufsize = 1 << 16  # one write per response (avoids 40 ms Nagle stalls)

        def log_message(self, *a):  # silence default access log
            pass

        def _send(self, code, body, ctype, t0):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            state.log(self.path, len(body), t0)

        def do_GET(self):
            t0 = time.perf_counter()
            if self.path == "/v1/manifest":
                self._send(200, state.manifest_bytes, "application/json", t0)
            elif self.path == "/v1/fetch_store":
                # Gate-2 fallback only (trivial PIR): the whole store, so the server learns nothing.
                self._send(200, state.store, "application/octet-stream", t0)
            else:
                self._send(404, b"not found", "text/plain", t0)

        def do_POST(self):
            t0 = time.perf_counter()
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get(c.VERSION_HEADER) != state.manifest["corpus_version"]:
                return self._send(409, b"stale corpus_version", "text/plain", t0)
            if self.path == "/v1/score":
                if len(body) != c.DIM:
                    return self._send(400, b"bad query size", "text/plain", t0)
                q = np.frombuffer(body, dtype=np.int8).astype(np.int32)
                out = (state.table @ q).astype(c.SCORE_DTYPE).tobytes()
                self._send(200, out, "application/octet-stream", t0)
            elif self.path == "/v1/fetch":
                if len(body) != 4:
                    return self._send(400, b"bad selector size", "text/plain", t0)
                (i,) = struct.unpack("<I", body)
                if i >= state.n:
                    return self._send(400, b"index out of range", "text/plain", t0)
                self._send(200, state.store[i * state.L:(i + 1) * state.L], "application/octet-stream", t0)
            else:
                self._send(404, b"not found", "text/plain", t0)

    return Handler


def serve(data="data", port=8080, log=None, host="127.0.0.1"):
    state = State(data, log or pathlib.Path(data) / "server.log")
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    return httpd, state


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--log", default=None)
    a = p.parse_args()
    httpd, state = serve(a.data, a.port, a.log)
    print(f"MOCK server (plaintext, not private) on http://127.0.0.1:{a.port}  "
          f"N={state.n}  log={state.log_path}")
    httpd.serve_forever()
