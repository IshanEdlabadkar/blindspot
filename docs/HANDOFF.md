# Blind RAG: detailed handoff

For a person or an AI agent picking this project up cold. Read this once, top to bottom, before changing anything. The short public overview is [`README.md`](../README.md).

Last updated: Nov 14, 2026, about 19:30 Central, at commit `e06c906` plus this file, on branch `person-c-client-ui`.

## 1. What this is, in one paragraph

Blind RAG answers a sensitive question from a document library without the document server learning the question, the relevance scores, or which passages were read. The device embeds the question, encrypts it, and sends ciphertext. The server multiplies that ciphertext against every chunk's embedding and returns encrypted scores. The device decrypts, ranks, privately fetches the top 10 chunks, and a local language model writes a cited answer. It is a hackathon project (MadHacks 2026) over 2,101 chunks of public-domain MedlinePlus health topics.

## 2. Current state

| Area | State | Verified how |
| --- | --- | --- |
| Encrypted scoring (A) | Works. Hint mode is the default: about 3 KB up per question. | `make integration` passes on Linux at this commit. It passed on the demo Mac at an earlier commit (token mode). |
| Private fetch (A) | Trivial PIR by default (download the whole 4.3 MB store once). Real PIR is optional. | Same integration run; real PIR only by A. |
| Corpus and tables (B) | Built: 2,101 chunks, scale 127, little-endian records, corpus version `2026-11-14.2`. | A's server accepts them ("score range OK"). |
| Local answers (B) | `client/answer.py` with safe decline, via Ollama `llama3.2:3b`. | B's eval. Through the pipeline only with a stand-in model. |
| Client pipeline (C) | Works on the mock and on real crypto. | 37 Python tests; integration check. |
| UI (C) | Works. Chat by default, server view behind a toggle. | Driven end to end on the mock with screenshots. |
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
| 7. Fetch | download mode or PIR mode | Download: `GET /v1/fetch_store` once per manifest, then slice records locally. PIR: one `crypto.make_selector` + `POST /v1/fetch` + `crypto.decrypt_record` per chunk, always exactly k. |
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
| `BLIND_RAG_CRYPTO` | `mock`, `real` | `mock` | `real` imports A's `client.crypto_client`. |
| `BLIND_RAG_ANSWER` | `stub`, `real` | `stub` | `real` imports B's `client.answer`. |
| `BLIND_RAG_FETCH` | `pir`, `download` | from the crypto module's `FETCH_MODE`, else `pir` | A's client declares `download`. Set `pir` to use real PIR fetch. |
| `BLIND_RAG_EMBED` | `real`, `fake` | `real` | `fake` is a hash-based embedding: no model download, meaningless retrieval, fine for plumbing tests. |
| `BLIND_RAG_SERVER_LOG` | file path | `data/server.log` | Where the UI reads the server's log. |
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
| Python tests | `python3.12 -m pytest -q` | 37 tests. C's are in `tests/test_c_flow.py`: record round trip, pipeline ranking equals plaintext, exactly k fixed-size fetches, log has no request data, stale-version recovery, download fallback, canned output. Two slow tests are deselected by default (model download, Ollama). |
| Crypto tests | `make test` | A's Go unit and HTTP tests. Should print `ok` twice. |
| Integration | `make integration` | Starts real server, helper and mock on a normalized dummy corpus and checks the encrypted top 10 equals the plaintext top 10. Should end `ALL PASS`. |
| Measurements | `make measure` | With server and helper running: latency, bytes, CPU, and that the log holds only the four fields. Writes `data/measurements.md`. |
| Eval | `python -m eval.run_eval` (`--answers` to include the LLM) | B's recall and answer outcomes on `eval/questions.jsonl`. |

Run the Python tests and `make integration` after every merge from A or B.

## 10. Gotchas that have already cost time

1. **`python3` on the demo Mac is the wrong Python.** Installing Ollama through Homebrew added Python 3.15 and repointed `python3` at it. The packages live in Python 3.12 from python.org (`/Library/Frameworks/Python.framework/Versions/3.12`). Use `python3.12`, or `make demo`, which detects this. There is no `python` command at all.
2. **`make demo` reuses a server or helper already on :8080 or :8090.** After pulling changes to A's code, stop the old ones first or you will test old binaries. This matters right now: the Mac may still be running a pre-hint-mode server and helper.
3. **A long-running command holds its terminal.** `make server` and `make helper` never return. Use separate terminal tabs, or `make demo`.
4. **A's real server rejects C's dummy tables.** `tools/make_dummy_tables.py` writes random rows, which can overflow the score limit. Use the mock for dummy data, or start A's server with `-allow-wrap`. `scripts/integration_check.py` normalizes the dummy table itself.
5. **The first B merge needed adapting.** B originally used a big-endian length prefix, scale 278.67, `bge-small` instead of the placeholder model, a `status` field instead of `declined`, and expected a cosine score. All are resolved (B rebuilt; C's pipeline adapted). If B changes `answer()` or the manifest again, re-check these five points.
6. **`eval/questions.jsonl` is B's set,** because B's eval ran on it. C's original 25 are in `eval/questions_c.jsonl` and are unused.
7. **An AI agent cannot type into terminal apps through computer use.** Give the human one command to paste, or add a Makefile target.
8. **The demo Mac had a clone inside a clone** (`~/blindspot/blindspot`). Work in `~/blindspot`. Delete the inner folder if it is still there, so it is never committed.
9. **`third_party/` is patched.** Tiptoe's libraries are modified for Go 1.24+. Do not replace them with upstream copies.
10. **First real question is slow.** The embedding model downloads from Hugging Face, the scoring hint (17 MB) downloads once, and Ollama loads the model.

## 11. The UI

`ui/app.py`, one Streamlit file, rendered mostly as custom HTML and CSS (classes prefixed `br-`).

- **Default view:** brand header, optional mock banner, chat turns (question bubble, status chips, answer card with expandable sources), input form.
- **Toggle "Show what the server saw":** adds a dark right-hand panel (`st.container(key="server_pane")`) with the ciphertext sample, bytes sent and received, total time, and the tail of the server log. Under it, a collapsed **attacker console**: guess which of five questions was asked from what the server holds.
- **Sidebar (collapsed):** backend (Pipeline or Canned), server URL, current modes, and "New session", which wipes the key and history.
- A `Pipeline` is kept in `st.session_state` per browser session.
- Colours and the Streamlit theme are in `.streamlit/config.toml`. The design source is a Claude design canvas (direction A, "Split screen"); the two alternatives were not built.
- All user and server text is escaped with `html.escape` before going into HTML. Source links render only for `http(s)` URLs. Keep that.

Known flaws: the text input is slightly shorter than the "Ask privately" button; the README screenshots show the mock banner.

## 12. Open work for C, in priority order

1. **Run the full system on the demo Mac** with real embedding and real LLM (`git pull`, stop old server and helper, `make demo`). Fix whatever breaks. Nothing below matters until this works.
2. **Run `make measure` on the demo Mac** and record the numbers (A is waiting on this).
3. **Remote server support, requested by A in `DEPLOY.md`:** (a) let `BLIND_RAG_SERVER_LOG` be a URL and read `GET <server>/v1/server_log?n=50`; (b) make `start_demo.sh` skip starting a local server when `BLIND_RAG_SERVER` points elsewhere.
4. **Demo step 1, the contrast:** show B's plaintext server (`baseline/server.py`, port 8001, `GET /log`) logging the question in the clear, next to Blind RAG's log. Not wired into the UI.
5. **Attacker console on real logs:** it exists but has only been exercised on the mock.
6. **Replace the README screenshots** with real-mode ones (no mock banner).
7. **Slides, backup video, and rehearsal** of the 3-minute script (section 13).
8. **Get `person-c-client-ui` merged into `main`** by pull request once the team agrees, so GitHub's front page shows the real README.

## 13. Demo script (3 minutes, from the spec)

1. **The problem (20 s).** Ask a normal RAG server a sensitive question. Its log shows the full question and the documents returned.
2. **Same question, Blind RAG (40 s).** Same quality answer with citations. Flip the toggle: the server log shows only sizes and timings.
3. **Attacker console (40 s).** Hand a judge the server's view. They cannot tell which of five questions was asked.
4. **Numbers (40 s).** Recall at 10 versus plaintext, latency, bytes per query, all measured.
5. **Close (20 s).** "The server can't leak, sell or hand over a question it never had."

Record a backup video of every step.

## 14. Things not to claim

- Do not call Blind RAG the first private RAG system. It builds on Tiptoe, SimplePIR and related research.
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
| How B built the corpus | `ingest/`, `docs/superpowers/plans/2026-11-14-b-ml-and-content.md` |
| Eval results | `eval/results/` |
