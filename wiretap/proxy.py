"""Recording relay for the demo: app -> relay -> document server, forwarding every request unchanged
and saving its exact bytes to a JSONL file on this laptop.

  uv run python -m wiretap.proxy \\
      --route medlineplus:9080=http://127.0.0.1:8080 \\
      --route fmla:9081=http://127.0.0.1:8081 \\
      --route plain:9001=http://127.0.0.1:8001

Then point the app at the relay ports (BLIND_RAG_SERVERS=http://127.0.0.1:9080,http://127.0.0.1:9081,
BLIND_RAG_PLAIN_SERVER=http://127.0.0.1:9001). Upstreams may be remote (https://...onrender.com).

The server builds scoring.hint_url from the address it was reached at; the relay rewrites the
upstream's address to its own inside /v1/manifest, so that download goes through the relay too and
every request the app makes to a server is recorded.
"""
import argparse
import base64
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

DEFAULT_LOG = Path(__file__).resolve().parent.parent / "data" / "wire" / "wire.jsonl"
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length", "content-encoding"}


def read_records(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


class Relay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, route: str, address, upstream: str, log_path=DEFAULT_LOG):
        super().__init__(address, _Handler)
        self.route = route
        self.upstream = upstream.rstrip("/")
        self.log_path = Path(log_path)
        self.lock = threading.Lock()
        self.session = requests.Session()

    @property
    def base(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def record(self, entry: dict) -> None:
        with self.lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")


class _Handler(BaseHTTPRequestHandler):
    server: Relay
    protocol_version = "HTTP/1.1"

    def _relay(self):
        srv = self.server
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        try:
            r = srv.session.request(self.command, srv.upstream + self.path, data=body or None,
                                    headers=headers, timeout=300)
            status, content, rheaders = r.status_code, r.content, r.headers
        except requests.RequestException as e:
            status, content, rheaders = 502, f"wiretap: upstream {srv.upstream} unreachable: {e}".encode(), {}
        if self.path.startswith("/v1/manifest") and status == 200:
            content = content.replace(srv.upstream.encode(), srv.base.encode())
        srv.record({
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "route": srv.route, "upstream": srv.upstream, "method": self.command, "path": self.path,
            "request_bytes": len(body), "body_b64": base64.b64encode(body).decode(),
            "status": status, "response_bytes": len(content),
        })
        self.send_response(status)
        for k, v in rheaders.items():
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    do_GET = do_POST = do_PUT = do_DELETE = _relay

    def log_message(self, *args):
        pass


def parse_route(spec: str) -> tuple[str, int, str]:
    """'name:port=upstream' -> (name, port, upstream)."""
    left, upstream = spec.split("=", 1)
    name, port = left.split(":", 1)
    return name, int(port), upstream


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--route", action="append", required=True, help="name:port=upstream_url (repeatable)")
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--fresh", action="store_true", help="start with an empty recording")
    args = ap.parse_args()
    if args.fresh and args.log.exists():
        args.log.unlink()
    relays = []
    for spec in args.route:
        name, port, upstream = parse_route(spec)
        r = Relay(name, ("127.0.0.1", port), upstream, args.log)
        threading.Thread(target=r.serve_forever, daemon=True).start()
        relays.append(r)
        print(f"wiretap {name}: {r.base} -> {upstream}", flush=True)
    print(f"recording to {args.log}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
