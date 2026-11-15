> The Streamlit UI described below was removed; the app is now the React UI in `web/` (`make demo`). Kept as history.

# Person C: client, UI and demo

Everything here runs today on the plaintext mock. **The mock is not private. Never demo it as Blindspot.**

## Run it (3 terminals)

```bash
pip install -r requirements-c.txt
python tools/make_dummy_tables.py --out data          # dummy tables + manifest (share with A)
python -m mock_server.server --data data --port 8080  # mock of A's server
BLIND_RAG_CRYPTO=mock BLIND_RAG_ANSWER=stub BLIND_RAG_EMBED=fake streamlit run ui/app.py   # UI on the mock
python -m pytest tests -q                             # 6 checks, should all pass
```

## What is in here

| File | What it is | Replaced by |
| --- | --- | --- |
| `contracts.py` | Hour-0 contracts as code: sizes, byte order, wire format, record packing, answer shape | Stays; edit after hour 0 |
| `tools/make_dummy_tables.py` | 5,000 x 384 random int8 table, 5,000 dummy records, dummy manifest | B's real tables (hour 5) |
| `mock_server/server.py` | Plaintext `/v1/manifest`, `/v1/score`, `/v1/fetch`, writes the agreed log line | A's Go server |
| `client/mock_crypto_client.py` | The five functions, no encryption | A's `client/crypto_client` |
| `client/answer_stub.py` | First 300 chars of top chunk + three citations | B's `client/answer.py` |
| `client/canned.py` | Fixed answer, fixed decline on the word "decline" | UI layout only |
| `client/embed.py` | Question embed + int8 quantize; `fake` mode needs no model | Stays |
| `client/pipeline.py` | `ask()` and `ask_traced()`: embed, encrypt, score, rank, fetch k, answer | Stays |
| `ui/app.py` | Streamlit: chat, citations, status line, server-saw panel, attacker console | Stays; polish hours 13 to 16 |
| `eval/questions.jsonl` | 25 questions, each with a MedlinePlus source URL | Hand to B at hour 9 |

## Hour 0: bring these proposals (all in `contracts.py`)

1. **Byte order:** little-endian for the 2-byte record length and the int32 scores.
2. **Embedding:** B's `BAAI/bge-small-en-v1.5` at a pinned revision, L2-normalized, with B's query prefix on questions only. Quantize as `clip(round(x * scale), -127, 127)` with `scale` from the manifest.
3. **Wire format:** body is raw ciphertext bytes (`application/octet-stream`), corpus version in the `X-Corpus-Version` header, HTTP 409 when stale, one selector per `/v1/fetch` call and the client always sends 10.
4. **Crypto client signatures:** `keygen(manifest)`, `encrypt_query(key, int8_vec)`, `decrypt_scores(key, blob)`, `make_selector(key, index, N)`, `decrypt_record(key, blob)`.
5. **Answer shape:** `{"declined": bool, "answer": str, "citations": [{"id","title","url","text"}]}`. On a decline, `citations` holds the closest passages.
6. **`answer(question, chunks)`:** chunks arrive best score first, each `{"id","title","url","updated","text","score"}`.
7. **Log line:** JSON, `{"ts","endpoint","response_bytes","latency_ms"}`, one per line, to a file the UI can read.
8. **Fallback if Apple's library also fails:** `BLIND_RAG_FETCH=download` (trivial PIR) is already built; agree the fallback for scoring.

## Your checklist

- [x] Hours 1 to 3: Streamlit skeleton, mock server, mock crypto client
- [x] Hours 3 to 9: `pipeline.py` end to end on the mock, UI wired, server-saw panel on mock logs
- [x] 25 test questions with source URLs (all 25 URLs checked live on Nov 14)
- [ ] Hour 0: get the eight proposals above agreed, update `contracts.py`, commit
- [ ] Hour 5: point the mock at B's real tables (`--data <B's folder>`), unset `BLIND_RAG_EMBED`, sanity-check answers
- [ ] Hour 9: send `eval/questions.jsonl` to B
- [ ] Hours 9 to 13: `make server`, `make helper`, then `BLIND_RAG_CRYPTO=real BLIND_RAG_ANSWER=real streamlit run ui/app.py` (see SETUP.md; fetch switches to trivial PIR on its own)
- [ ] Gate 2 (hour 13): one question answered on the real server; if fetch fails, `BLIND_RAG_FETCH=download` (A must serve `GET /v1/fetch_store`)
- [ ] Hours 13 to 16: polish panel and status line, attacker console on real logs, slides
- [ ] Hours 16 to 18: freeze, backup video, rehearse the 3-minute script

## Known gaps

- The client does not verify the manifest's table hashes (it never holds the tables).
- The questions were written from page titles, not chunk text. Reword any that B's chunks cannot answer.
- The attacker console is a first version and only means something against the real server.
- The real embedding model path (`BLIND_RAG_EMBED=real`) has not been run yet; only `fake` was tested.

## Full system on the demo laptop (A + B + C merged)

Four terminals from the repo root. Ollama must be running with `llama3.2:3b` pulled (B's `client/answer.py`).

```bash
make server                       # A: real crypto server on B's artifacts/, log at data/server.log
make helper                       # A: key holder on this device
ollama serve                      # B: local model (skip if the Ollama app is already running)
BLIND_RAG_CRYPTO=real BLIND_RAG_ANSWER=real python3 -m streamlit run ui/app.py
```

To develop without crypto: `python3 -m mock_server.server --data artifacts --port 8080`, then run the UI with `BLIND_RAG_CRYPTO=mock BLIND_RAG_ANSWER=stub`. The UI defaults to the real path.

`eval/questions.jsonl` is B's set (the eval ran on it). C's 25 are in `eval/questions_c.jsonl`.
