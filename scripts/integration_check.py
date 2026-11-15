"""End-to-end check: C's pipeline with A's real crypto vs C's plaintext mock.

Run from the repo root after A's and C's branches are merged:

    make integration

Starts the real server, the crypto-helper and C's mock on a normalized dummy
corpus, asks three questions through client/pipeline.py, and checks that the
real (encrypted) top-k equals the mock (plaintext) top-k.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

import numpy as np
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BLIND_RAG_EMBED", "fake")
DATA = ROOT / "data" / "integration"
BIN = ROOT / "crypto-server"


def wait(url, secs=60):
    for _ in range(secs * 4):
        try:
            requests.get(url, timeout=1)
            return
        except requests.RequestException:
            time.sleep(0.25)
    raise SystemExit(f"timed out waiting for {url}")


def main():
    from tools import make_dummy_tables
    # Normalized rows so encrypted scores never wrap (see SETUP.md). The tool writes the
    # manifest hashes after building the table, so the server's hash check passes.
    make_dummy_tables.main(out=str(DATA), n=5000, normalize=True)

    subprocess.run(["go", "build", "-o", "crypto-server", "."], cwd=BIN, check=True)
    subprocess.run(["go", "build", "-o", "crypto-helper", "./cmd/crypto-helper"], cwd=BIN, check=True)
    procs = [
        subprocess.Popen([str(BIN / "crypto-server"), "-data", str(DATA), "-addr", "127.0.0.1:18080"]),
        subprocess.Popen([str(BIN / "crypto-helper"), "-addr", "127.0.0.1:18090"]),
        subprocess.Popen([sys.executable, "-m", "mock_server.server", "--data", str(DATA),
                          "--port", "18081", "--log", str(DATA / "mock.log")], cwd=ROOT),
    ]
    try:
        os.environ["BLIND_RAG_HELPER"] = "http://127.0.0.1:18090"
        for u in ("http://127.0.0.1:18080/v1/manifest", "http://127.0.0.1:18090/health",
                  "http://127.0.0.1:18081/v1/manifest"):
            wait(u)
        from client.pipeline import Pipeline, load_crypto
        real = Pipeline(server="http://127.0.0.1:18080", crypto=load_crypto("real"), fetch_mode="download")
        mock = Pipeline(server="http://127.0.0.1:18081", crypto=load_crypto("mock"))
        ok = True
        for q in ["What are early signs of a miscarriage?", "Can I take FMLA leave?", "knee pain on stairs"]:
            _, tr = real.ask_traced(q)
            _, tm = mock.ask_traced(q)
            same = tr["top_ids"] == tm["top_ids"]
            ok &= same
            print(f"{'PASS' if same else 'FAIL'}  {q[:40]:40}  {tr['total_seconds']*1000:6.0f} ms  "
                  f"up {tr['upload_bytes']/1e3:8.1f} KB  down {tr['download_bytes']/1e3:8.1f} KB")
        print("ALL PASS" if ok else "MISMATCH between real and mock rankings")
        sys.exit(0 if ok else 1)
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
