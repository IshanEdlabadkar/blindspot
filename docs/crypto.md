# Crypto status and design decisions (Person A)

Search a sensitive knowledge base without the server learning the question, the scores, or which documents were read.

**Setup for everyone: [SETUP.md](SETUP.md).** Remote server: [DEPLOY.md](DEPLOY.md). Contracts: `contracts.py` (C's branch) is the single source of truth.

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
- [x] Hint-mode scoring: 3 KB up, ~6 ms per question; every spec performance target met
- [x] Real PIR fetch (optional, `BLIND_RAG_FETCH=pir`): 10 private fetches per question, chunks byte-identical to trivial PIR
- [x] Remote deploy: Render runs code only; the corpus lives in the provider's storage (Databricks volume), hash-checked and hot-swapped by `corpus_version` (image not yet built; first Render build is its test)
- [ ] Run `make measure` on the demo laptop (hours 13 to 16)

## Crypto design decisions

| Decision | Why |
| --- | --- |
| Tiptoe's `underhood` for scoring, P = 2^17 | Library's tuned setting. Normalized int8 scores (at most ~16,200) fit in ±65,536. |
| Hint mode by default | The scoring hint (DB x A) is public and the same for every user, so the device downloads it once per corpus (17 MB, low 32 bits dropped, error bound 2^42 vs a 2^46 limit). Each question is then a fresh secret, 3 KB up and 17 KB down, with no token. |
| Token mode as fallback | Tiptoe's underhood: no hint download, but a ~33 MB token per question, sent inside `/v1/score`. Used automatically if the hint can't be loaded. |
| Fresh secret key per question | Reusing an LWE key across questions leaks. `crypto_client` does this inside `encrypt_query`, so C's pipeline needs no change. The helper prepares the next key in the background and refuses to use any key twice. |
| Fetch: trivial PIR by default (`GET /v1/fetch_store`) | The whole store (4.3 MB) is downloaded once and leaks nothing. At 2,101 chunks that is cheaper than real PIR's one-time hint. |
| Real PIR fetch as an option (`POST /v1/fetch`) | SimplePIR with the hint downloaded once (8.4 MB): every chunk in its own column, 16 bits per element, so a fetch is 17 KB up and 8 KB down. It scales to large corpora where downloading everything is not an option. (Tiptoe's own PIR was ruled out: ~33 MB token per fetch.) |
| Python calls Go through a local helper process | Works the same on Mac and on Windows (WSL2). Keys stay in the helper's memory. |
| Public scoring seed = first 16 bytes of SHA-256(score table) | Server and client agree with no extra manifest field for B to write. The seed is public by design. |
| Corpus loaded from the provider's storage, never shipped with the code | The provider's ingestion publishes to their storage; the server verifies hashes and swaps in new versions live, per the spec's update flow. |
| Little-endian everywhere | Matches `contracts.py`. |
| Fallback | If anything in crypto breaks, keep the mock path. No switch to Apple's library. |

## Library patches

`third_party/` holds Tiptoe's `underhood` and `simplepir`. They are patched for Go 1.24+, which rejects methods on cgo types (`T(0).Bitlen()` became `matrix.Bitlen[T]()`). `go.mod` points at them with `replace`.

## Batched PIR fetch (for C's pipeline)

`crypto_client` exposes `make_selectors(key, indexes, N)` and `decrypt_records(key, blob)`, and the server has `POST /v1/fetch_batch`. In `client/pipeline.py`'s real-PIR branch, this replaces the 10 round trips with one (the mock has no `make_selectors`, so it keeps the old loop):

```python
else:  # fetch_mode == "pir"
    if hasattr(self.crypto, "make_selectors"):
        sels = self.crypto.make_selectors(self.key, [int(i) for i in top], n)
        blob = self._post("/v1/fetch_batch", sels)
        sent("/v1/fetch_batch", len(sels), len(blob))
        chunks = [c.unpack_record(r) for r in self.crypto.decrypt_records(self.key, blob)]
    else:
        ...  # existing per-chunk loop
```

Measured against Render (real PIR, k = 10): one request per chunk took ~1.2 s per question, almost all network round trips. Batched, it's one round trip.
