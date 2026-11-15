# Setup

Maintained by A. Updated whenever a piece lands that changes what you need to install or run. **Check the changelog at the bottom after every pull.**

## Who needs what

| | A (Windows) | B (Mac) | C (Mac, demo laptop) |
| --- | --- | --- | --- |
| Git, Python 3.11+ | Yes | Yes | Yes |
| Go 1.22+ and Microsoft SEAL | Yes, inside WSL2 | **No** | Yes (runs the crypto-helper) |
| ML stack (sentence-transformers, Ollama) | No | Yes | Yes |

B never needs the crypto toolchain. B's whole contract with crypto is the three files in `data/` (format below).

## Mac (B and C)

```bash
xcode-select --install                  # C/C++ compiler, once
brew install go cmake python@3.12
git clone https://github.com/IshanEdlabadkar/blindspot && cd blindspot
```

C only, once, for the crypto parts:

```bash
make seal        # builds Microsoft SEAL 4.1.1 into /usr/local (~5 min, asks for sudo)
make test        # should print "ok" twice
```

If the build fails with an error mentioning `-march=native`, run `./scripts/fix_march.sh`, then `make test` again.

## Windows (A): use WSL2

The crypto code wraps a C++ library through cgo, which does not build cleanly on native Windows. Run it in WSL2. Servers started there are reachable from Windows at `http://localhost:8080`.

In PowerShell as administrator, once: `wsl --install -d Ubuntu`. Then in the Ubuntu terminal:

```bash
sudo apt update && sudo apt install -y build-essential cmake git golang-go python3 python3-pip python3-numpy python3-requests
go version       # needs 1.22 or newer
git clone https://github.com/IshanEdlabadkar/blindspot ~/blindspot && cd ~/blindspot
make seal && make test
```

Keep the repo inside the WSL filesystem (`~/blindspot`), not under `/mnt/c/`. Builds there are much slower.

**If WSL says "Catastrophic failure, Error code: Wsl/Service/E_UNEXPECTED"** (seen on A's laptop):

1. PowerShell as admin: `wsl --shutdown`, `wsl --update`, then `wsl -d Ubuntu`.
2. If Ubuntu opens as `root` or the username prompt keeps failing, create the user by hand. Usernames must be lowercase.
   ```bash
   adduser --gecos "" ishan && usermod -aG sudo ishan
   printf '[user]\ndefault=ishan\n' > /etc/wsl.conf
   exit
   ```
   Then `wsl --shutdown` and `wsl -d Ubuntu` in PowerShell.
3. "Failed to detect nested virtualization support" is a harmless warning; ignore it.

Verified on A's Windows laptop (WSL2, Ubuntu): `make test` passes.

## Data files (B writes, the server reads)

The server reads these three files from `artifacts/` by default (B's folder). For C's dummy tables: `make server DATA=data`.

| File | Format |
| --- | --- |
| `manifest.json` | Spec schema. Must have `corpus_version`, `num_chunks`, `embedding.dim`, `pir.record_bytes`. |
| `score_table.bin` | N x 384 int8, row by row. **Rows L2-normalized, then `round(x * 127)`: the scale is exactly 127**, and the manifest says `quantization.scale: 127`. A larger scale lets close matches overflow the encrypted math and vanish from the top 10, so the server refuses to start. (`-allow-wrap` overrides this, for random dummy tables only.) |
| `fetch_store.bin` | N x 2048 bytes. **2-byte length prefix is little-endian**; use `contracts.pack_record()`. |

## Switching C's pipeline to real crypto

Three processes, each in its own terminal:

```bash
make server      # A's document server :8080 on artifacts/, ~3 s to start, log at data/server.log
make helper      # asker-side key holder :8090 (on the demo laptop)
BLIND_RAG_CRYPTO=real BLIND_RAG_FETCH=download streamlit run ui/app.py
```

- **`BLIND_RAG_FETCH=download` is required with real crypto.** Fetch is trivial PIR: the client downloads the whole 10 MB store once and reads chunks locally.
- The UI reads `data/server.log` by default, which is where the real server writes too.
- To check everything at once after merging: `make integration`. It runs C's pipeline with real crypto and with the mock, and checks that both return the same top 10 chunks. Last run: ALL PASS, about 4 s per question.

## Measuring (hours 13 to 16)

With `make server` and `make helper` running, `make measure` asks 10 random questions (5 s apart, like a user reading), prints timings, and writes `data/measurements.md` in the spec's format. It also fails if the server log holds anything but the four agreed fields. Run it on the demo laptop for the real numbers.

Last run, on B's corpus (2,101 chunks), a 2-vCPU cloud VM, medians, hint mode (the default):

| | Value |
| --- | --- |
| Crypto part of a question (encrypt + score + decrypt + fetch) | ~6 ms |
| Upload / download per question | 3.1 KB / 16.8 KB |
| Server CPU per question | < 10 ms |
| One-time per corpus version | 17.2 MB scoring hint (cached in `~/.cache/blind-rag/`) + 4.3 MB fetch store |
| Server log | only the four agreed fields, no query data |

Every spec performance target is met. With real PIR fetch (`BLIND_RAG_FETCH=pir`, or `make measure` with `--fetch pir`): about 0.55 s and 171 KB up / 99 KB down per question, plus an 8.4 MB fetch hint once. Every fetched chunk is checked byte for byte.

Token mode (`BLIND_RAG_SCORE_MODE=token`) is the old path: 34 MB up and ~2.7 s per question, kept as a fallback.

## Benchmark: accuracy, speed and a trace of every question

With `make demo` running (server + helper + Ollama), `make bench` runs every question in `eval/questions.jsonl` through the real client pipeline (the same one the UI uses) and writes `eval/results/bench/<run>/`:

- `report.html`: open it in a browser. Summary tiles, where the time goes, a sortable table of questions ("problems only" filter), and, for the clicked question, a waterfall of every stage, every key-helper call and every HTTP request (client round trip vs the server's own time from its log), the encrypted top-k with the right page marked, the sources after rerank, and the answer.
- `report.md`, `summary.json`, `traces.jsonl` (one row per question run: everything above, as data).

What it measures:

| Area | Measured |
| --- | --- |
| Accuracy | right page in encrypted top 1/3/5/10, in the model's sources after rerank, cited; answered vs declined as expected; wrong answers; 988/911 notice; sentences removed by the checker; per category |
| Exactness | when `artifacts/` holds the server's corpus version: decrypted scores equal the plaintext int8 scores, and the encrypted top-k equals the plaintext top-k |
| Speed | p50/p95 per stage (embed, encrypt, score, fetch, rerank, model, checks), per key-helper call, per endpoint (client, server, network); cold first question vs warm |
| Bytes / privacy | up/down per question, one-time downloads, server log has only the four fields, exactly k fetched from every selected server |

Useful variants (`ARGS=` passes options through `make`):

```
make bench-quick                                   # retrieval only, no model: ~1 s per question
make bench ARGS="--limit 10 --repeat 3"            # speed: 3 runs per question
make bench ARGS="--fetch pir"                      # real PIR fetch instead of the trivial download
make bench ARGS="--servers http://127.0.0.1:8080,https://blindspot-cz2t.onrender.com"
make bench ARGS="--category urgent"                # one category (or --ids q001,q002, --split test)
python3 -m eval.bench --compare eval/results/bench/RUN_A eval/results/bench/RUN_B   # side-by-side table
```

Runs are not committed (`eval/results/bench/` is ignored); copy a report somewhere if you want to keep it. B's `eval.run_eval` and `eval.scorecard` stay the source for the quality scorecard; the bench adds the encrypted path, timings and traces.

## Changelog

- **Nov 15 (`bench`):** `make bench` / `make bench-quick`: accuracy, speed per stage and a clickable per-question trace (`eval/results/bench/<run>/report.html`). No setup beyond `make demo`; see "Benchmark" above.
- **Nov 14, 21:45 (`integration`):** **search several document servers**: pick them in the sidebar, or set `BLIND_RAG_SERVERS=https://a,https://b`. Each selected server gets the same encrypted question and exactly 10 fetches; results merge on the device. See "Searching several document servers" in `docs/crypto.md`.
- **Nov 14, 20:25:** **batched real PIR fetch:** `POST /v1/fetch_batch` carries all k selectors in one round trip (each still under its own fresh key), and the helper keeps a pool of prepared fetch keys. Real-PIR fetch for a question drops from ~0.5 s to ~25 ms locally, and saves ~1 s of round trips against Render. `crypto_client.make_selectors()` / `decrypt_records()`; `make measure --fetch pir` uses it. **C:** to use it in the pipeline, see "Batched PIR fetch" in `docs/crypto.md`. Restart `make helper` after pulling.
- **Nov 14, 20:10:** remote deployment (Dockerfile, Render config, `DEPLOY.md`, Databricks publish script) moved to the **`deploy/render`** branch; `main` runs locally only. The server's URL/folder loader and live reload stay on `main`. `scripts/fix_march.sh` now strips `-march=native` from every file that sets it (it missed two).
- **Nov 14, 19:40:** **the corpus is no longer in the Docker image.** The server loads it from the provider's storage, either a folder (`-data`) or a URL (`BLIND_RAG_DATA_URL`, such as a Databricks volume). It checks the manifest's sha256 hashes and swaps in new `corpus_version`s live. **B:** `scripts/publish_corpus.sh` uploads `artifacts/` to Databricks (see DEPLOY.md). Locally nothing changes: `make server` still reads `artifacts/`, and now also reloads when B rebuilds it.
- **Nov 14, 19:20:** **real PIR fetch** (optional): `POST /v1/fetch` (one encrypted selector per call, as in `contracts.py`) and `GET /v1/fetch_hint` (8.4 MB, once). C's pipeline uses it with `BLIND_RAG_FETCH=pir`, with no code change. Trivial PIR stays the default, since it's cheaper at this size. Server switch: `BLIND_RAG_PIR=0` turns it off.
- **Nov 14, 19:15:** remote deployment: `Dockerfile`, `render.yaml` and **[DEPLOY.md](DEPLOY.md)**. New server switches: `BLIND_RAG_TOKEN_MODE=0` (hint mode only, ~100 MB RAM instead of ~650 MB) and `BLIND_RAG_PUBLIC_LOG=1` (`GET /v1/server_log`). The server honors `$PORT`. **C:** see "What C needs to change" in DEPLOY.md.
- **Nov 14, 19:05:** **hint mode** is the default: the client downloads a 17 MB public scoring hint once per corpus (cached on disk), then each question is 3 KB up, 17 KB down, ~6 ms. The client falls back to the old token mode automatically if anything goes wrong. Pull and restart `make server` and `make helper`; C's code is unchanged.
- **Nov 14, 18:15:** the helper prepares the next question's key in the background (`BLIND_RAG_PREPARE=0` turns it off), so encrypting takes 0.05 s instead of 1.2 s. Added `make measure`. No changes needed in C's code; restart `make helper` after pulling.
- **Nov 14, 17:40:** server reads `artifacts/` by default (`make server DATA=data` for dummy tables) and logs to `data/server.log`. It refuses tables whose scale can overflow. **B: rebuild with scale 127 and a little-endian length prefix** (see Data files).
- **Nov 14, 17:20:** `make test` verified on A's Windows laptop (WSL2). Added the WSL "Catastrophic failure" fix.
- **Nov 14, 17:10:** aligned with C's `contracts.py`: `X-Corpus-Version` header, log to `data/server.log` with the four agreed fields. Added the crypto-helper and real `client/crypto_client`, plus `make helper` and `make integration`.
- **Nov 14, 17:00:** document server with `/v1/manifest`, `/v1/score`, `/v1/fetch_store`. Fetch is trivial PIR. `make seal`, `make test`, `make server`.
