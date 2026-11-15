# Blindspot: detailed handoff

For a person or an AI agent picking this project up cold. Read this once, top to bottom, before changing anything. The short public overview is [`README.md`](../README.md).

Last updated: Nov 14, 2026, about 20:00 Central, on branch `person-c-client-ui`. The team's expanded task plan (C1 to C8) is tracked in section 12.

## 1. What this is, in one paragraph

Blindspot answers a sensitive question from a document library without the document server learning the question, the relevance scores, or which passages were read. The device embeds the question, encrypts it, and sends ciphertext. The server multiplies that ciphertext against every chunk's embedding and returns encrypted scores. The device decrypts, ranks, privately fetches the top 10 chunks, and a local language model writes a cited answer. It is a hackathon project (MadHacks 2026) over 2,101 chunks of public-domain MedlinePlus health topics.

## 2. Current state

| Area | State | Verified how |
| --- | --- | --- |
| Encrypted scoring (A) | Works. Hint mode is the default: about 3 KB up per question. | `make integration` passes on Linux at this commit. It passed on the demo Mac at an earlier commit (token mode). |
| Private fetch (A) | Trivial PIR by default (download the whole 4.3 MB store once). Real PIR is optional. | Same integration run; real PIR only by A. |
| Corpus and tables (B) | Built: 2,101 chunks, scale 127, little-endian records, corpus version `2026-11-14.2`. | A's server accepts them ("score range OK"). |
| Local answers (B) | `client/answer.py` with safe decline, via Ollama `llama3.2:3b`. | B's eval. Through the pipeline only with a stand-in model. |
| Client pipeline (C) | Works on the mock and on real crypto. Fails loudly, never falls back. | 44 Python tests; integration check; `demo/preflight.py`. |
| UI (C) | Works. Real path by default, mode badge on every answer, server view with plaintext contrast, Evidence and Who-sees-what tabs. | Driven end to end against the real crypto server (models off) with screenshots; failure cases exercised. |
| **Full system on the demo Mac with the real embedding model and the real LLM** | **Not yet run successfully.** | Last attempt failed on a Python path problem, since fixed in `make demo`. This is the next thing to do. |

All three people's work is merged on `person-c-client-ui`. `main` only has B's work so far.

## 3. People, ownership and branches

| Person | Owns | Branch |
| --- | --- | --- |
| A: crypto | `crypto-server/`, `client/crypto_client/`, `third_party/`, `Makefile`, `SETUP.md`, `DEPLOY.md`, `scripts/` (except `start_demo.sh`) | `person-a/crypto` |
| B: ML and content | `ingest/`, `common/`, `artifacts/`, `baseline/`, `client/answer.py`, `eval/`, `docs/contracts.md`, `pyproject.toml` | `B-ml-and-content` |
| C: client, UI, demo | `ui/`, `client/pipeline.py`, `client/embed.py`, `client/mock_crypto_client.py`, `client/answer_stub.py`, `client/canned.py`, `mock_server/`, `tools/`, `contracts.py`, `scripts/start_demo.sh`, `README.md`, `README_C.md`, this file | `person-c-client-ui` |

Rules that have been followed so far:

- **C's work goes only on `person-c-client-ui`.** Never commit to `main` or to A's or B's branches.
- **No force pushes.** History includes two throwaway push-test commits; leave them.
- **Merge A and B into C's branch, not the other way round.** Use `git merge --no-ff origin/<branch>`. Both have merged cleanly every time except the first B merge (see section 10).
- **Do not edit files another person owns** unless they ask. If their code needs a change, tell them. The one exception already made: `README.md` was A's status page and is now the project overview; A's text moved verbatim to `docs/crypto.md`.
- The product spec (`blind-rag-spec.md`) and the 18-hour work split are **not in this repository**. They live in the team's Claude Project. Ask for them if you need the original requirements.

## 4. How a question flows through the code

Entry point: `client/pipeline.py`, class `Pipeline`, method `ask_traced(question, on_stage=None)`. `ask(question)` is the same thing without the trace.

| Step | Code | Detail |
| --- | --- | --- |
| 1. Manifest | `Pipeline.load_manifest()` | `GET /v1/manifest`. Checks `protocol == "blind-rag/1"` and, in real embed mode, that the embedding model and dimension match `contracts.py`. Calls `crypto.keygen(manifest)`. Cached per pipeline. |
| 2. Embed | `client/embed.py: embed()` | `BAAI/bge-small-en-v1.5` at B's pinned revision, on CPU. The query prefix from the manifest is prepended to the question. L2-normalized. |
| 3. Quantize | `client/embed.py: quantize()` | `clip(round(v * scale), -127, 127)` as int8, with `scale` from the manifest (127). |
| 4. Encrypt | `crypto.encrypt_query(key, int8_vec)` | Returns the body for `/v1/score`. A's client makes a fresh secret key per question inside this call. |
| 5. Score | `POST /v1/score` | Header `X-Corpus-Version`. A 409 means the corpus changed: the pipeline reloads the manifest and retries once. |
| 6. Rank | `crypto.decrypt_scores(key, blob)` then `argsort` | N signed int32 scores. Top `top_k` (10), stable sort. |
| 7. Fetch | download mode or PIR mode | Download (default): `GET /v1/fetch_store` once per manifest, then slice records locally. PIR (`BLIND_RAG_FETCH=pir`): one `POST /v1/fetch_batch` carrying all k selectors, each with its own fresh key (`crypto.make_selectors` / `decrypt_records`). If the server has no batch endpoint (404) or the client has no `make_selectors` (the mock), it falls back to k single `POST /v1/fetch` calls. Always exactly k. |
| 8. Decode | `contracts.unpack_record()` | 2-byte little-endian length, JSON, zero padding. |
| 9. Score for answer | in `_run` | Each chunk gets `raw_score` (int) and `score` (cosine estimate, `raw / scale²`). B's decline threshold reads `score`. |
| 10. Answer | `answer_fn(question, chunks)` | B's `client.answer.answer` or C's stub. The result passes through `contracts.normalize_result()`. |

The **trace** returned next to the result is what the UI's server panel shows: `timings` per stage, `requests` (endpoint, bytes up, bytes down), `upload_bytes`, `download_bytes`, `ciphertext_sample` (first 48 bytes of the query body, hex), `top_ids` (device-only), `fetch_mode`, `mock`.

## 5. Contracts

`contracts.py` is the source of truth in code. `docs/contracts.md` is B's prose version; if they disagree, check with the team rather than guessing.

| Contract | Value |
| --- | --- |
| Score table | `score_table.bin`: N × 384 int8, row-major. Rows L2-normalized then `round(x * 127)`. |
| Fetch store | `fetch_store.bin`: N × 2,048 bytes. Each record: 2-byte **little-endian** length, compact UTF-8 JSON `{"id","title","url","updated","text"}`, zero padding. |
| Manifest | `manifest.json`: spec schema plus `embedding.query_prefix`. A's server adds `scoring.seed`, the scoring mode and hint URLs when it serves it. |
| Wire format | Binary bodies as `application/octet-stream`. Corpus version in the `X-Corpus-Version` header. Stale version gets HTTP 409. |
| Scores | N signed 32-bit little-endian integers after decryption. |
| Crypto client | `keygen(manifest)`, `encrypt_query(key, int8_vec)`, `decrypt_scores(key, blob)`, `make_selector(key, index, N)`, `decrypt_record(key, blob)`. Optional module attributes: `IS_MOCK`, `FETCH_MODE`. |
| Answer shape | `{"status": "answered" or "declined", "declined": bool, "answer": str, "citations": [{"id","title","url","text", ...}]}`. B's `answer()` returns `status` only; `normalize_result()` adds `declined`. On a decline, `citations` holds the closest passages. |
| Server log line | One JSON object per line: `ts`, `endpoint`, `response_bytes`, `latency_ms`. Never a request body. |
| Score limit | A's scheme holds scores in ±65,536 (P = 2^17). At scale 127 the worst case is about 16,400. A's server refuses to start on tables that could exceed the limit unless given `-allow-wrap`. |

## 6. Processes and endpoints

| Process | Start | Port | Notes |
| --- | --- | --- | --- |
| Document server (A, Go) | `make server` | 8080 | Reads `artifacts/` by default (`make server DATA=data` for dummy tables). Logs to `data/server.log`. About 3 s startup. |
| Crypto-helper (A, Go) | `make helper` | 8090 | Runs on the asker's device. Holds secret keys in memory only. Python talks to it over localhost. |
| Ollama (B's dependency) | `brew services start ollama` | 11434 | Model `llama3.2:3b`. |
| UI (C, Streamlit) | `make demo` or `python3.12 -m streamlit run ui/app.py` | 8501 | |
| Mock server (C, Python) | `python3.12 -m mock_server.server --data artifacts --port 8080` | 8080 | Plaintext. Same endpoints. **Not private.** |
| Plaintext demo server (B) | `python -m baseline.server` | 8001 | The "normal RAG server" for demo step 1. Logs questions in the clear. Not wired into the UI yet. |

Document server endpoints: `GET /v1/manifest`, `POST /v1/score`, `GET /v1/score_hint`, `GET /v1/fetch_store`, and when enabled `POST /v1/fetch`, `GET /v1/fetch_hint`, `GET /v1/server_log`.

The mock serves only `/v1/manifest`, `/v1/score`, `/v1/fetch` and `/v1/fetch_store`.

## 7. Environment variables

Read by C's code:

| Variable | Values | Default | Effect |
| --- | --- | --- | --- |
| `BLIND_RAG_SERVER` | URL | `http://127.0.0.1:8080` | Document server the pipeline talks to. |
| `BLIND_RAG_CRYPTO` | `mock`, `real` | `mock` in the pipeline library, **`real` in the UI** | `real` imports A's `client.crypto_client`. |
| `BLIND_RAG_ANSWER` | `stub`, `real` | `stub` in the pipeline library, **`real` in the UI** | `real` imports B's `client.answer`. |
| `BLIND_RAG_FETCH` | `pir`, `download` | from the crypto module's `FETCH_MODE`, else `pir` | A's client declares `download`. Set `pir` to use real PIR fetch. |
| `BLIND_RAG_EMBED` | `real`, `fake` | `real` | `fake` is a hash-based embedding: no model download, meaningless retrieval, fine for plumbing tests. |
| `BLIND_RAG_SERVER_LOG` | file path or URL | `data/server.log` for a local server, `<server>/v1/server_log` for a remote one | Where the UI reads the server's log. |
| `BLIND_RAG_PLAIN_SERVER` | URL | `http://127.0.0.1:8001` | B's plaintext demo server, for the log contrast. |
| `PLAIN` | `1` | off | `start_demo.sh` also starts the plaintext server (`make demo-compare`). |
| `PYTHON` | interpreter path | auto-detected | Used by `scripts/start_demo.sh` only. |
| `DATA` | folder | `artifacts` | Used by `make server` and `start_demo.sh`. |

`make demo` sets `BLIND_RAG_CRYPTO=real` and `BLIND_RAG_ANSWER=real` (the second can be overridden).

Read by A's code: `BLIND_RAG_HELPER` (helper URL), `BLIND_RAG_SCORE_MODE` (`hint` or `token`), `BLIND_RAG_PREPARE` (`0` turns off background key preparation), `BLIND_RAG_HINT_CACHE` (default `~/.cache/blind-rag`), and on the server `BLIND_RAG_TOKEN_MODE`, `BLIND_RAG_PIR`, `BLIND_RAG_PUBLIC_LOG`, `PORT`. See `SETUP.md` and `DEPLOY.md`.

## 8. Setup and running

Full instructions are in `SETUP.md`. The short version for the demo Mac, which is already set up:

```bash
cd ~/blindspot
git pull
make demo
```

`make demo` (`scripts/start_demo.sh`) finds a Python that has the packages, builds the Go binaries, starts the server and helper unless they already answer on their ports, warns if Ollama is down, then runs the UI. Ctrl+C stops what it started.

Run modes, from least to most real:

| Mode | Command | Needs |
| --- | --- | --- |
| Canned UI | UI sidebar, Backend = "Canned" | Nothing |
| Mock, fake embedding | mock server + `BLIND_RAG_EMBED=fake` UI | Python only |
| Mock, real embedding and LLM | mock server + `BLIND_RAG_ANSWER=real` UI | + sentence-transformers, Ollama |
| Real crypto | `make demo` | + Go, SEAL |

## 9. Tests and checks

| Check | Command | What it proves |
| --- | --- | --- |
| Python tests | `python3.12 -m pytest -q` | B's and the team's tests. C's own unit tests were removed; C's code is checked by `make integration` and `make preflight`. Two slow tests are deselected by default (model download, Ollama). |
| Crypto tests | `make test` | A's Go unit and HTTP tests. Should print `ok` twice. |
| Integration | `make integration` | Starts real server, helper and mock on a normalized dummy corpus and checks the encrypted top 10 equals the plaintext top 10. Should end `ALL PASS`. |
| Measurements | `make measure` | With server and helper running: latency, bytes, CPU, and that the log holds only the four fields. Writes `data/measurements.md`. |
| Eval | `python -m eval.run_eval` (`--answers` to include the LLM) | B's recall and answer outcomes on `eval/questions.jsonl`. |

Run the Python tests and `make integration` after every merge from A or B.

## 10. Gotchas that have already cost time

1. **`python3` on the demo Mac is the wrong Python.** Installing Ollama through Homebrew added Python 3.15 and repointed `python3` at it. The packages live in Python 3.12 from python.org (`/Library/Frameworks/Python.framework/Versions/3.12`). Use `python3.12`, or `make demo`, which detects this. There is no `python` command at all.
2. **`make demo` reuses a server or helper already on :8080 or :8090.** After pulling changes to A's code, run `make stop` first or you will test old binaries. This matters right now: the Mac may still be running a pre-hint-mode server and helper.
3. **A long-running command holds its terminal.** `make server` and `make helper` never return. Use separate terminal tabs, or `make demo`.
4. **A's real server rejects C's dummy tables.** `tools/make_dummy_tables.py` writes random rows, which can overflow the score limit. Use the mock for dummy data, or start A's server with `-allow-wrap`. `scripts/integration_check.py` normalizes the dummy table itself.
5. **The first B merge needed adapting.** B originally used a big-endian length prefix, scale 278.67, `bge-small` instead of the placeholder model, a `status` field instead of `declined`, and expected a cosine score. All are resolved (B rebuilt; C's pipeline adapted). If B changes `answer()` or the manifest again, re-check these five points.
6. **`eval/questions.jsonl` is B's set,** because B's eval ran on it. C's original 25 are in `eval/questions_c.jsonl` and are unused.
7. **An AI agent cannot type into terminal apps through computer use.** Give the human one command to paste, or add a Makefile target.
8. **The demo Mac had a clone inside a clone** (`~/blindspot/blindspot`). Work in `~/blindspot`. Delete the inner folder if it is still there, so it is never committed.
9. **`third_party/` is patched.** Tiptoe's libraries are modified for Go 1.24+. Do not replace them with upstream copies.
10. **First real question is slow.** The embedding model downloads from Hugging Face, the scoring hint (17 MB) downloads once, and Ollama loads the model.

## 11. The UI

`ui/app.py`, one Streamlit file, rendered mostly as custom HTML and CSS (classes prefixed `br-`). The layout follows directions G and D on the team's design canvas: a conversation with **Burrow** (Blindspot's own original badger character, inline SVG in `locket()`; name in `MASCOT`), who greets the user and delivers each answer as a chat message, and a two-receipt comparison when the server toggle is on.

- **Real by default.** The UI sets `BLIND_RAG_CRYPTO=real` and `BLIND_RAG_ANSWER=real` unless you set them. The mock must be asked for.
- **Status pill** in the header: green when every system is up, amber in mock or canned mode, red when something is down (problems are then listed with their fixes, never hidden). Full mode text and health rows are in **System details**.
- **Welcome message** from Burrow and three suggested questions (clicking one asks it).
- **Mode badge.** In System details: what the next question will run as. On every answer: what really ran, read from the trace (`REAL ENCRYPTED SEARCH`, `MOCK · NOT PRIVATE` or `CANNED`), plus scoring mode, fetch mode (download-all is labelled "not PIR"), and whether a real model and real embedding were used.
- **Health strip.** Document server, key helper and local model, each with a fix command when down (`client.pipeline.health`, cached 8 s).
- **Ask tab.** Chat turns with an answer card. Each source shows title, link, date, similarity, the closest sentence from the source (`client/evidence.py`, a word-overlap pointer, verbatim) and the full passage. Declines get an amber "No reliable source found" card.
- **Failures.** A `PipelineError` becomes a red box naming the stage and the fix. Nothing is retried in a weaker mode.
- **Toggle "Show what the server saw".** Two receipts above the conversation: what a normal server kept (from B's plaintext server's log, only when **Also ask a normal server** is ticked) and what Blindspot's server kept (its own log lines for that question, the question as redaction bars, the ciphertext sample, bytes). Both are read from the servers; nothing is drawn by hand.
- **Attacker console**, under the panel: guess which of five questions was asked.
- **Evidence tab.** Live numbers from this session, A's `data/measurements.md` if `make measure` has run (otherwise "Not measured yet"), and B's eval files with denominators.
- **Who sees what tab.** Device, network and server views, what stays visible, how fetch works, and what is not claimed.
- **Sidebar (collapsed):** backend (Pipeline or Canned), server URLs, requested modes, "New session".
- All user and server text is escaped with `html.escape` before going into HTML. Source links render only for `http(s)` URLs. Keep that.

Safety guards in `client/pipeline.py`: a mock client refuses to send to a real server (it would leak the plain embedding), and a real client refuses a mock server.

## 12. The expanded task plan for C (C1 to C8)

| Task | State | What remains |
| --- | --- | --- |
| C1 Real encrypted path | Code done. Pipeline + UI run real crypto on B's tables with the same top 10 as plaintext. | **Run it on the demo Mac with the real embedding model and LLM.** Not yet done. |
| C2 No mislabeled mock | Done. Badges from the trace, refusal guards, no fallback. Tested. | Nothing. |
| C3 Server-saw comparison | Done against a stand-in for B's plaintext server (same `/ask` and `/log` API). | Run with B's real `baseline.server` (`make demo-compare`). |
| C4 Inspectable evidence | Done. | Judge the excerpt quality on real answers. |
| C5 UX and recovery | Done: health strip, stage errors with fixes, timeouts. Two failures exercised. | Ollama-down error path is unit-tested only. |
| C6 Benchmark cards | Done. Reads `data/measurements.md` and `eval/results/`. | Run `make measure` on the Mac. Add A's `eval/crypto_metrics.csv` and B's scorecard when they exist. |
| C7 Threat-model view | Done in the UI. | A slide version. |
| C8 Final demo | `demo/` has the script, prompts, runbook and `make preflight`. | Record the backup video and capture real screenshots on the Mac. Slides. |

Other open items:

1. **Run `make preflight` on the demo Mac** until it prints READY FOR THE DEMO with no SKIP.
2. **Get PR #4 (`person-c-client-ui` into `main`) merged** so GitHub's front page shows the README.
3. **Replace the README screenshots** in `docs/img/` with real-mode ones.
4. B needs `client.pipeline:ask` for the full-pipeline eval (B2). It exists: `from client.pipeline import ask`, with `BLIND_RAG_CRYPTO=real BLIND_RAG_ANSWER=real` set.

## 13. Demo script (3 minutes, from the spec)

1. **The problem (20 s).** Ask a normal RAG server a sensitive question. Its log shows the full question and the documents returned.
2. **Same question, Blindspot (40 s).** Same quality answer with citations. Flip the toggle: the server log shows only sizes and timings.
3. **Attacker console (40 s).** Hand a judge the server's view. They cannot tell which of five questions was asked.
4. **Numbers (40 s).** Recall at 10 versus plaintext, latency, bytes per query, all measured.
5. **Close (20 s).** "The server can't leak, sell or hand over a question it never had."

Record a backup video of every step.

## 14. Things not to claim

- Do not call Blindspot the first private RAG system. It builds on Tiptoe, SimplePIR and related research.
- Do not demo the mock as private. The UI shows a banner in mock mode for this reason.
- Do not say the server learns nothing at all. It sees timing, IP address and sizes.
- Breach statistics in the pitch come from healthcare organizations, not from AI chatbots.
- The cryptography is research-grade and unreviewed.

## 15. Where to look

| Need | File |
| --- | --- |
| Install anything | `SETUP.md` |
| Crypto status, parameters, design decisions | `docs/crypto.md`, `client/crypto_client/__init__.py` docstring |
| Remote deployment | `DEPLOY.md` |
| File and answer formats in prose | `docs/contracts.md` |
| C's run commands and checklist | `README_C.md` |
| Presenting: script, prompts, runbook | `demo/` |
| How B built the corpus | `ingest/`, `docs/superpowers/plans/2026-11-14-b-ml-and-content.md` |
| Adding sources (Genetics, MyHealthfinder) | `docs/corpus.md`, `make corpus-expanded` |
| Eval results | `eval/results/` |
