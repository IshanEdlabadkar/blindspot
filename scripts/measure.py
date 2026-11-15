"""Measure the crypto path against the spec's performance targets (hours 13 to 16).

Needs the document server and the crypto-helper running (make server, make helper).
Does not need the embedding model or the LLM: questions are random unit vectors,
which cost exactly the same to encrypt and score as real ones.

    make measure                         # 10 questions, 5 s "reading time" between them
    python3 scripts/measure.py --questions 20 --think 0

Writes data/measurements.md (paste into the spec's Measured column) and checks
that the server log holds only the four agreed fields and no request data.
"""
import argparse
import json
import os
import pathlib
import platform
import subprocess
import sys
import time

import numpy as np
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG_FIELDS = {"ts", "endpoint", "response_bytes", "latency_ms"}


def fmt_t(sec):
    return f"{sec*1000:.0f} ms" if sec < 1 else f"{sec:.2f} s"


def fmt_b(n):
    return f"{n/1e6:.1f} MB" if n >= 1e6 else f"{n/1e3:.1f} KB"


def server_pid(explicit):
    if explicit:
        return explicit
    try:
        out = subprocess.run(["pgrep", "-f", "crypto-server"], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        return None
    for pid in out:
        comm = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout.strip()
        if comm.endswith("crypto-server"):
            return int(pid)
    return None


def cpu_seconds(pid):
    """Total user+system CPU seconds of a process (Linux/WSL via /proc, macOS via ps)."""
    if pid is None:
        return None
    stat = pathlib.Path(f"/proc/{pid}/stat")
    if stat.exists():
        f = stat.read_text().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
    t = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    secs = 0.0
    for part in t.replace("-", ":").split(":"):
        secs = secs * 60 + float(part)
    return secs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=os.environ.get("BLIND_RAG_SERVER", "http://127.0.0.1:8080"))
    ap.add_argument("--questions", type=int, default=10)
    ap.add_argument("--think", type=float, default=5.0, help="seconds between questions (user reading)")
    ap.add_argument("--log", default=None,
                    help="server log: a file, or a URL (default: data/server.log for a local server, "
                         "<server>/v1/server_log for a remote one)")
    ap.add_argument("--server-pid", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "data" / "measurements.md"))
    ap.add_argument("--fetch", choices=["download", "pir", "pir-single"], default="download",
                    help="download = trivial PIR (default); pir = real PIR, all k selectors in one request; "
                         "pir-single = real PIR, one request per chunk")
    a = ap.parse_args()

    from client import crypto_client as cc

    http = requests.Session()
    local = any(h in a.server for h in ("127.0.0.1", "localhost"))
    if a.log is None:
        a.log = str(ROOT / "data" / "server.log") if local else a.server.rstrip("/") + "/v1/server_log"
    remote_log = a.log.startswith("http")

    def read_remote_log():
        r = http.get(a.log, params={"n": 200}, timeout=30)
        r.raise_for_status()
        return r.text.splitlines()

    log_path = pathlib.Path(a.log) if not remote_log else None
    log_start = (log_path.stat().st_size if log_path.exists() else 0) if log_path else 0
    remote_before = set(read_remote_log()) if remote_log else set()
    pid = server_pid(a.server_pid) if (local or a.server_pid) else None

    t0 = time.perf_counter()
    r = http.get(a.server + "/v1/manifest", timeout=30)
    r.raise_for_status()
    manifest, manifest_bytes = r.json(), len(r.content)
    n, d, k = manifest["num_chunks"], manifest["embedding"]["dim"], manifest["top_k"]
    scale = manifest["quantization"]["scale"]
    t = time.perf_counter()
    key = cc.keygen(manifest)
    keygen_secs = time.perf_counter() - t
    mode = getattr(key, "mode", "?")
    hint_bytes = manifest.get("scoring", {}).get("hint_bytes", 0) if mode == "hint" else 0

    t = time.perf_counter()
    store = http.get(a.server + "/v1/fetch_store", timeout=300).content
    store_secs, store_bytes = time.perf_counter() - t, len(store)
    setup_secs = time.perf_counter() - t0

    rng = np.random.default_rng(0)
    rows, sent_queries = [], []
    for i in range(a.questions):
        if i and a.think:
            time.sleep(a.think)
        v = rng.standard_normal(d)
        q = np.clip(np.rint(v / np.linalg.norm(v) * scale), -127, 127).astype(np.int8)
        sent_queries.append(q.tobytes())
        cpu0 = cpu_seconds(pid)
        t = time.perf_counter()
        body = cc.encrypt_query(key, q)
        t_enc = time.perf_counter() - t
        t = time.perf_counter()
        resp = http.post(a.server + "/v1/score", data=body, timeout=120, headers={
            "Content-Type": "application/octet-stream", "X-Corpus-Version": manifest["corpus_version"]})
        resp.raise_for_status()
        t_score = time.perf_counter() - t
        t = time.perf_counter()
        scores = cc.decrypt_scores(key, resp.content)
        top = np.argsort(-scores, kind="stable")[:k]
        L = manifest["pir"]["record_bytes"]
        f_up = f_down = 0
        if a.fetch == "pir":
            sels = cc.make_selectors(key, [int(j) for j in top], n)
            fr = http.post(a.server + "/v1/fetch_batch", data=sels, timeout=60, headers={
                "Content-Type": "application/octet-stream", "X-Corpus-Version": manifest["corpus_version"]})
            fr.raise_for_status()
            for j, rec in zip(top, cc.decrypt_records(key, fr.content)):
                assert rec == store[int(j) * L:(int(j) + 1) * L], "PIR record mismatch"
            f_up, f_down = len(sels), len(fr.content)
        elif a.fetch == "pir-single":
            for j in top:
                sel = cc.make_selector(key, int(j), n)
                fr = http.post(a.server + "/v1/fetch", data=sel, timeout=60, headers={
                    "Content-Type": "application/octet-stream", "X-Corpus-Version": manifest["corpus_version"]})
                fr.raise_for_status()
                rec = cc.decrypt_record(key, fr.content)
                assert rec == store[int(j) * L:(int(j) + 1) * L], "PIR record mismatch"
                f_up, f_down = f_up + len(sel), f_down + len(fr.content)
        else:
            _ = [store[int(j) * L:(int(j) + 1) * L] for j in top]
        t_dec = time.perf_counter() - t
        cpu1 = cpu_seconds(pid)  # scoring plus, in PIR mode, the k fetches
        rows.append({"encrypt": t_enc, "score_rt": t_score, "decrypt_rank_fetch": t_dec,
                     "total": t_enc + t_score + t_dec, "up": len(body) + f_up, "down": len(resp.content) + f_down,
                     "server_cpu": None if cpu0 is None else cpu1 - cpu0})
        print(f"q{i+1:02d}  encrypt {fmt_t(t_enc)}  score {fmt_t(t_score)}  decrypt+rank {fmt_t(t_dec)}  "
              f"total {fmt_t(rows[-1]['total'])}  up {fmt_b(len(body))}  down {fmt_b(len(resp.content))}")

    # Log check: only the agreed fields, nothing derived from requests.
    log_ok, log_note = True, "no log file found"
    new = None
    if remote_log:
        new = [ln for ln in read_remote_log() if ln not in remote_before]
    elif log_path.exists():
        new = log_path.read_bytes()[log_start:].decode("utf-8", "replace").splitlines()
    if new is not None:
        bad = [ln for ln in new if not ln.strip() or set(json.loads(ln)) != LOG_FIELDS]
        leaked = [q.hex()[:32] for q in sent_queries if q.hex()[:32] in "\n".join(new)]
        long_lines = [ln for ln in new if len(ln) > 300]
        log_ok = not bad and not leaked and not long_lines and len(new) >= a.questions
        log_note = (f"{len(new)} new lines, fields exactly {sorted(LOG_FIELDS)}, no query bytes"
                    if log_ok else f"PROBLEM: {len(bad)} lines with other fields, {len(leaked)} leaked queries, "
                                   f"{len(long_lines)} long lines")

    med = {key_: float(np.median([r[key_] for r in rows])) for key_ in rows[0] if rows[0][key_] is not None}
    cpu_note = ("n/a (server PID not found; pass --server-pid)" if "server_cpu" not in med
                else "< 10 core-ms (below the OS timer's resolution)" if med["server_cpu"] < 0.01
                else f"{med['server_cpu']*1000:.0f} core-ms" if med["server_cpu"] < 1 else f"{med['server_cpu']:.2f} core-s")
    lines = [
        f"# Blind RAG crypto measurements",
        "",
        f"Client: {platform.node()} ({platform.system()} {platform.machine()}), server: {a.server}, "
        f"N = {n}, d = {d}, k = {k}, {a.questions} questions, {a.think:g} s between questions. "
        f"Corpus {manifest['corpus_version']}. Scoring mode: **{mode}**, fetch: **{a.fetch}**. Medians.",
        "",
        "| Metric | Target | Measured | Met |",
        "| --- | --- | --- | --- |",
        f"| Encrypt on device | (not in spec) | {fmt_t(med['encrypt'])} | |",
        f"| Encrypted scoring round trip | < 2 s | {fmt_t(med['score_rt'])} | {'yes' if med['score_rt'] < 2 else 'no'} |",
        (f"| Private fetch of k = 10 (real PIR, {k} fetches{' in one request' if a.fetch == 'pir' else ''}) | < 3 s | "
         f"{fmt_t(med['decrypt_rank_fetch'])} per question, each record checked | "
         if a.fetch.startswith("pir") else
         f"| Private fetch of k = 10 (trivial PIR) | < 3 s | {fmt_t(med['decrypt_rank_fetch'])} per question, "
         f"plus {fmt_t(store_secs)} once for the {fmt_b(store_bytes)} store | ")
        + f"{'yes' if med['decrypt_rank_fetch'] < 3 else 'no'} |",
        f"| Crypto part of end-to-end latency | < 10 s total | {fmt_t(med['total'])} | {'yes' if med['total'] < 10 else 'no'} |",
        f"| Upload per query | < 5 MB | {fmt_b(med['up'])} | {'yes' if med['up'] < 5e6 else 'no'} |",
        f"| Download per query | < 20 MB | {fmt_b(med['down'])}, plus one-time downloads below | "
        f"{'yes' if med['down'] < 20e6 else 'no'} |",
        f"| Server CPU per query | < 2 core-s | {cpu_note} | "
        f"{'' if 'server_cpu' not in med else ('yes' if med['server_cpu'] < 2 else 'no')} |",
        f"| One-time manifest download | < 10 KB | {manifest_bytes/1e3:.1f} KB | {'yes' if manifest_bytes < 10e3 else 'no'} |",
        f"| Server log holds no request data | required | {log_note} | {'yes' if log_ok else 'NO'} |",
        "",
        f"One-time per corpus version: manifest {fmt_b(manifest_bytes)}, "
        + (f"scoring hint {fmt_b(hint_bytes)} (cached on disk after the first run), " if hint_bytes else "")
        + (f"fetch hint {fmt_b(manifest['pir'].get('hint_bytes', 0))} (real PIR; the {fmt_b(store_bytes)} store was "
           "downloaded here only to check every fetched record). " if a.fetch.startswith("pir") else f"fetch store {fmt_b(store_bytes)}. ")
        + f"Setup took {fmt_t(setup_secs)} (key setup {fmt_t(keygen_secs)}).",
        "Rerank and answer generation (B's part) are not included.",
    ]
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print(f"\nwrote {out}")
    sys.exit(0 if log_ok else 1)


if __name__ == "__main__":
    main()
