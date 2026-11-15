"""Check every document server in a server list: reachable, right corpus, compatible, log fields.

  python3 scripts/check_servers.py                       # servers.remote.json (the hosted servers)
  python3 scripts/check_servers.py servers.json          # the local list
  python3 scripts/check_servers.py --pin                 # after a check passes: record each server's corpus
                                                         # version and hashes as its pin (client/pins.py)

For each server: the manifest loads; its source_id matches the list; it is the real encrypted server
(hint mode, PIR on); its embedding and quantization match the first server's (so scores can be merged);
its corpus_version and hashes match the repo backup in artifacts/<id>/ (if there is one); and
GET /v1/server_log (if public) holds only ts, endpoint, response_bytes, latency_ms.
Exit code 0 only if every check passes.
"""
import json
import pathlib
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOWED = {"ts", "endpoint", "response_bytes", "latency_ms"}


def main():
    args = [a for a in sys.argv[1:] if a != "--pin"]
    do_pin = "--pin" in sys.argv[1:]
    lst = pathlib.Path(args[0] if args else ROOT / "servers.remote.json")
    entries = json.loads(lst.read_text())
    print(f"Checking {len(entries)} servers from {lst.name} (a sleeping free server can take ~1 min to wake)\n")
    failures, ref = 0, None
    for e in entries:
        url, sid = e["url"].rstrip("/"), e["id"]
        problems, notes = [], []
        t = time.perf_counter()
        try:
            r = requests.get(url + "/v1/manifest", timeout=90)
            r.raise_for_status()
            m = r.json()
        except Exception as ex:  # noqa: BLE001
            print(f"FAIL {sid:15} {url}\n     manifest not reachable: {ex}\n")
            failures += 1
            continue
        secs = time.perf_counter() - t
        sc = m.get("scoring", {})
        if m.get("source_id", sid) != sid:
            problems.append(f"serves source_id {m.get('source_id')!r}, list says {sid!r}")
        if "seed" not in sc:
            problems.append("not the encrypted server (no scoring seed)")
        if sc.get("mode") != "hint":
            problems.append(f"scoring mode {sc.get('mode')!r}, expected 'hint'")
        if "simplepir" not in json.dumps(m.get("pir", {})):
            notes.append("real PIR fetch is off (download fetch still works)")
        key = (m["embedding"].get("model"), m["embedding"].get("revision"), m["embedding"].get("dim"),
               m["embedding"].get("query_prefix"), m["quantization"].get("scale"))
        ref = ref or key
        if key != ref:
            problems.append(f"embedding/quantization differ from the first server: {key}")
        backup = ROOT / "artifacts" / sid / "manifest.json"
        if backup.exists():
            b = json.loads(backup.read_text())
            if b["corpus_version"] != m["corpus_version"] or b["hashes"] != m.get("hashes", b["hashes"]):
                problems.append(f"differs from the repo backup: server {m['corpus_version']}, backup {b['corpus_version']}")
            else:
                notes.append("matches repo backup")
        else:
            notes.append("no repo backup")
        try:
            lg = requests.get(url + "/v1/server_log", params={"n": 50}, timeout=30)
            if lg.status_code == 200:
                lines = [json.loads(x) for x in lg.text.splitlines() if x.strip()]
                extra = set().union(*(set(x) for x in lines)) - ALLOWED if lines else set()
                if extra:
                    problems.append(f"server log has extra fields: {sorted(extra)}")
                else:
                    notes.append(f"log: {len(lines)} lines, only the 4 fields")
            else:
                notes.append(f"public log off ({lg.status_code})")
        except Exception as ex:  # noqa: BLE001
            notes.append(f"log not readable: {ex}")
        pin = e.get("pin")
        if pin:
            got = {"corpus_version": m["corpus_version"], **(m.get("hashes") or {})}
            off = [k for k, v in pin.items() if got.get(k) != v]
            if off and not do_pin:
                problems.append(f"does not match its pin in {lst.name}: {', '.join(off)} "
                                f"(published a new version on purpose? rerun with --pin)")
            elif not off:
                notes.append("matches its pin")
        if do_pin and not problems:
            e["pin"] = {"corpus_version": m["corpus_version"], **(m.get("hashes") or {})}
            notes.append("pinned")
        status = "ok  " if not problems else "FAIL"
        failures += bool(problems)
        print(f"{status} {sid:15} {m['corpus_version']}  {m['num_chunks']:>5} chunks  {secs:5.1f}s  {url}")
        for p in problems:
            print(f"     ✗ {p}")
        print(f"     {'; '.join(notes)}\n")
    if do_pin and not failures:
        lst.write_text("[\n" + ",\n".join("  " + json.dumps(e) for e in entries) + "\n]\n")
        print(f"pins written to {lst.name}: commit it so every client checks them")
    print("ALL SERVERS OK" if not failures else f"{failures} server(s) with problems")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
