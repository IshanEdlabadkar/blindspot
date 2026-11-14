# Blind RAG (blindspot)

Search a sensitive knowledge base without the server learning the question, the scores, or which documents were read. See the product spec and the 18-hour work split.

| Person | Owns |
| --- | --- |
| A: Crypto | `crypto-server/`, `client/crypto_client/`, `third_party/` |
| B: ML and content | `ingest/`, `baseline/`, `client/answer.py`, `eval/run_eval.py` |
| C: Client, UI, demo | `ui/`, `client/pipeline.py`, mocks, `tools/make_dummy_tables.py`, `eval/questions.jsonl` |

## Setup (crypto)

```bash
./scripts/install_seal.sh          # Microsoft SEAL 4.1.1, needed by underhood (cgo)
cd crypto-server && go test ./blindcrypto -v
```

`third_party/` holds Tiptoe's `underhood` and `simplepir`, patched for Go 1.24+ (newer Go rejects methods on cgo types; `T(0).Bitlen()` became `matrix.Bitlen[T]()`). `go.mod` points at them with `replace`, so no network fetch is needed for those two.

Note: `third_party/underhood/rlwe/rlwe.go` and `third_party/simplepir/matrix/matrix.go` compile with `-march=native`. If that fails on your machine (some Apple Silicon toolchains), remove the flag.

## Status

- [x] Gate 1: encrypted dot product round-trips (4 x 8 toy, signed int8)
- [x] Encrypted scoring at full size: 5,000 x 384, every score exact, ~1 ms server compute per query
- [ ] `/v1/score` HTTP endpoint
- [ ] PIR fetch at `/v1/fetch`
- [ ] Python `crypto_client` bindings

## Hour-0 contracts (proposed; agree and edit)

### Table files (B writes, A reads)

- `data/score_table.bin`: N x 384 int8, row by row, no header.
- `data/fetch_store.bin`: N x 2048 bytes. Each record: 2-byte length, chunk JSON (UTF-8), zero padding.
- **Decided: the length prefix is little-endian unsigned 16-bit** (`struct.pack("<H", n)`).
- All integers on the wire are little-endian too.

### Embedding (B embeds chunks, C embeds questions)

384 dims, L2-normalized, then `round(x * 127)` clipped to [-127, 127] as int8.

**Why normalization matters for crypto:** scores are computed mod P = 2^17 and decoded into the range -65,536 to 65,536. Unit vectors at scale 127 give |score| of about 16,200 at most, so they always fit. Unnormalized full-range int8 rows can reach about 6.2 million and wrap around.

**Request to C:** make the dummy table rows unit-norm (normalize a random Gaussian vector, then quantize), not uniform random int8. Otherwise the dummy scores will not match plaintext.

### Endpoints (A builds real, C builds mock)

| Endpoint | Request body | Response body |
| --- | --- | --- |
| `GET /v1/manifest` | none | manifest JSON (spec schema) |
| `POST /v1/score` | `corpus_version`, token blob, encrypted query | token answer, N encrypted scores |
| `POST /v1/fetch` | `corpus_version`, token blob, k encrypted selectors | token answer, k encrypted records |

**Change from the spec:** underhood needs a per-query "token": the client sends an encrypted copy of a fresh secret key, and the server answers with a matching blob. It does not depend on the question and fits in the same request, so scoring stays one round trip.

**Bandwidth measured at N = 5,000:** upload is about 33 MB (token) plus 3 KB (query). Download is about 770 KB (token answer) plus 39 KB (scores). The spec's 5 MB upload target is not achievable with this library. The token can be sent while the user is still typing, so it costs bandwidth but not perceived latency.

Mock behavior is unchanged: C's mock can treat the token as empty bytes.

### crypto_client (A implements, C calls)

The spec's five functions, with one adjustment: `keygen` also returns the token to send, and `decrypt_scores` and `decrypt_record` take the server's token answer. See `client/crypto_client/__init__.py`.

### Server log line (A writes, C displays)

One JSON object per line: `{"ts": ISO8601, "endpoint": "/v1/score", "response_bytes": int, "latency_ms": float}`. No request bodies, ever.

### Fallback (decided)

Scoring stays on underhood (already working). If PIR fetch fails, use trivial PIR: the client downloads the whole fetch store (~10 MB) once. We are not switching to Apple's library.

### Decided by A

- Length prefix and all wire integers: little-endian.
- The token goes inside `/v1/score` and `/v1/fetch` (one round trip each, server stays stateless).
