# Blind RAG (blindspot)

Search a sensitive knowledge base without the server learning the question, the scores, or which documents were read.

**Setup for everyone: [SETUP.md](SETUP.md).** Contracts: `contracts.py` (C's branch) is the single source of truth.

| Person | Owns |
| --- | --- |
| A: Crypto | `crypto-server/`, `client/crypto_client/`, `third_party/` |
| B: ML and content | `ingest/`, `baseline/`, `client/answer.py`, `eval/run_eval.py` |
| C: Client, UI, demo | `ui/`, `client/pipeline.py`, mocks, `tools/make_dummy_tables.py`, `eval/questions.jsonl` |

## Crypto status (A)

- [x] Gate 1: encrypted dot product round-trips (4 x 8 toy, signed int8)
- [x] Encrypted scoring at 5,000 x 384: every score exact
- [x] Document server: `/v1/manifest`, `/v1/score`, `/v1/fetch_store`
- [x] crypto-helper + `client/crypto_client`: C's pipeline runs with `BLIND_RAG_CRYPTO=real`, same top 10 as the mock
- [x] Server accepts B's scale-127 tables (waiting on B's little-endian record fix for the full pipeline)
- [x] Background key preparation: encrypt 1.2 s -> 0.05 s
- [x] `make measure`: latency, bytes, CPU, log check
- [ ] Run `make measure` on the demo laptop (hours 13 to 16)

## Crypto design decisions

| Decision | Why |
| --- | --- |
| Tiptoe's `underhood` for scoring, P = 2^17 | Library's tuned setting. Normalized int8 scores (at most ~16,200) fit in ±65,536. |
| Token sent inside `/v1/score` | One round trip; the server stays stateless. |
| Fresh secret key per question | Reusing an LWE key across questions leaks. `crypto_client` does this inside `encrypt_query`, so C's pipeline needs no change. The helper prepares the next key in the background and refuses to use any key twice. |
| Fetch is trivial PIR (`GET /v1/fetch_store`) | Tiptoe's PIR needs a fresh ~33 MB key per fetch (~330 MB per question at k = 10). The whole store is 10 MB, downloaded once, and leaks nothing. |
| Python calls Go through a local helper process | Works the same on Mac and on Windows (WSL2). Keys stay in the helper's memory. |
| Public scoring seed = first 16 bytes of SHA-256(score table) | Server and client agree with no extra manifest field for B to write. The seed is public by design. |
| Little-endian everywhere | Matches `contracts.py`. |
| Fallback | If anything in crypto breaks, keep the mock path. No switch to Apple's library. |

## Library patches

`third_party/` holds Tiptoe's `underhood` and `simplepir`. They are patched for Go 1.24+, which rejects methods on cgo types (`T(0).Bitlen()` became `matrix.Bitlen[T]()`). `go.mod` points at them with `replace`.
