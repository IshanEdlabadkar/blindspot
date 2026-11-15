"""Pre-demo smoke test: the team's 8-step integration check, automated.

Run with the server and helper up (make demo in another terminal, or make server + make helper):

    make preflight                 # real crypto + real model, what the demo uses
    python3.12 demo/preflight.py --answer stub --embed fake    # plumbing only, no models

Exits non-zero if any check FAILS. SKIP means the check needs a piece that is switched off.
"""
import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--server", default=os.environ.get("BLIND_RAG_SERVER", "http://127.0.0.1:8080"))
ap.add_argument("--answer", choices=["real", "stub"], default="real")
ap.add_argument("--embed", choices=["real", "fake"], default=os.environ.get("BLIND_RAG_EMBED", "real"))
ap.add_argument("--question", default="How is chlamydia treated and can I get it again?")
ap.add_argument("--off-topic", default="Can my landlord evict me for reporting mold?")
ap.add_argument("--log", default=str(ROOT / "data" / "server.log"))
args = ap.parse_args()
os.environ["BLIND_RAG_EMBED"] = args.embed

import numpy as np  # noqa: E402
import requests  # noqa: E402

import contracts as c  # noqa: E402
from client import embed as emb  # noqa: E402
from client.pipeline import Pipeline, PipelineError, health, load_answer, load_crypto  # noqa: E402

results = []


def check(name, ok, detail=""):
    tag = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    results.append(tag)
    print(f"{tag}  {name}" + (f"  ({detail})" if detail else ""))


# 1. everything is up
for h in health(args.server, "real", args.answer):
    check(f"1. {h['name']} is up", h["ok"], h["detail"] + (f"; fix: {h['fix']}" if h["fix"] else ""))
if "FAIL" in results:
    sys.exit("Start the missing pieces (make demo) and run this again.")

# 2. manifest matches the local tables
m = requests.get(args.server + "/v1/manifest", timeout=10).json()
local = json.loads((ROOT / "artifacts" / "manifest.json").read_text())
check("2. corpus_version matches artifacts/", m["corpus_version"] == local["corpus_version"],
      f"server {m['corpus_version']}, local {local['corpus_version']}")
check("2. table hashes match artifacts/", m.get("hashes") == local.get("hashes"))
check("2. server is the encrypted one", "seed" in m.get("scoring", {}))

# 3. one answerable question through the real encrypted path
try:
    pipe = Pipeline(server=args.server, crypto=load_crypto("real"), answer_fn=load_answer(args.answer))
    result, trace = pipe.ask_traced(args.question)
except PipelineError as e:
    check("3. encrypted question completes", False, f"{e.stage}: {e.message} Fix: {e.fix}")
    sys.exit(1)
check("3. encrypted question completes", True,
      f"{trace['mode']['score']} scoring, {trace['mode']['fetch']} fetch, {trace['total_seconds']:.2f} s")
check("3. really encrypted, not mock", trace["mode"]["crypto"] == "real" and not trace["mock"])

# 4. encrypted ranking equals plaintext int8 scoring
n = m["num_chunks"]
table = np.fromfile(ROOT / "artifacts" / "score_table.bin", dtype=np.int8).reshape(n, c.DIM).astype(np.int32)
q = emb.quantize(emb.embed(args.question, m["embedding"].get("query_prefix", c.QUERY_PREFIX)),
                 m["quantization"]["scale"]).astype(np.int32)
plain_scores = table @ q
expect = np.argsort(-plain_scores, kind="stable")[:m["top_k"]].tolist()
check("4. encrypted top 10 equals plaintext top 10", trace["top_ids"] == expect, f"ids {trace['top_ids'][:5]}...")

# 5. citations resolve to real fetched chunks
store = (ROOT / "artifacts" / "fetch_store.bin").read_bytes()
L = m["pir"]["record_bytes"]
ok = bool(result["citations"])
for cit in result["citations"]:
    rec = c.unpack_record(store[cit["id"] * L:(cit["id"] + 1) * L])
    ok &= rec["title"] == cit["title"] and rec["url"] == cit["url"] and rec["text"] == cit["text"]
check("5. every citation is a real chunk (title, URL, text)", ok, f"{len(result['citations'])} citation(s)")
if args.answer == "real" and args.embed == "real":
    check("5. answerable question was answered", result["status"] == "answered", result["answer"][:80].replace("\n", " "))
else:
    check("5. answerable question was answered", None, "needs --answer real --embed real")

# 6. an off-topic question declines without a made-up answer
if args.answer == "real" and args.embed == "real":
    r2, _ = pipe.ask_traced(args.off_topic)
    check("6. off-topic question declines", r2["declined"], r2["answer"][:80].replace("\n", " "))
else:
    check("6. off-topic question declines", None, "needs --answer real --embed real")

# 7. the server log holds the four agreed fields and none of the question
log = pathlib.Path(args.log)
if log.exists():
    text = log.read_text()
    lines = [json.loads(x) for x in text.splitlines() if x.strip()]
    check("7. server log lines have only ts, endpoint, response_bytes, latency_ms",
          all(set(x) == set(c.LOG_FIELDS) for x in lines), f"{len(lines)} lines")
    words = [w for w in args.question.lower().split() if len(w) > 5]
    check("7. no word of the question is in the server log", not any(w in text.lower() for w in words))
else:
    check("7. server log readable", None, f"{log} not found (remote server?)")

# 8. warm numbers for the slide
t0 = time.perf_counter()
_, tr = pipe.ask_traced(args.question)
check("8. warm question", True, f"{time.perf_counter() - t0:.2f} s end to end, {tr['upload_bytes']:,} B up, "
                                 f"{tr['download_bytes']:,} B down, crypto {tr['timings']['encrypting'] + tr['timings']['scoring']:.3f} s")

print()
if "FAIL" in results:
    print("NOT READY: fix the FAIL lines above")
elif "SKIP" in results:
    print("PLUMBING OK, but model checks were skipped. Not demo-ready until this passes with no SKIP.")
else:
    print("READY FOR THE DEMO")
sys.exit(1 if "FAIL" in results else 0)
