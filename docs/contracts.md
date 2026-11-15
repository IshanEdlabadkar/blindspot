# Blind RAG: shared contracts

Agreed in hour 0. Every placeholder and every real component follows these, so the real piece replaces the placeholder without code changes. Change a contract only after telling the other two people.

| Contract | Owner | Used by |
|---|---|---|
| Table files | B writes | A reads |
| Embedding and quantization | B | B (chunks), C (questions) |
| Manifest | B and A | A, C |
| Crypto client signatures | A | C |
| Endpoints | A (real), C (mock) | C |
| Answer function and answer shape | B | C, UI, eval |
| Server log line | A | C (server-saw panel) |

## 1. Table files

Both files have no header. Row `i` is chunk id `i`. Chunk ids run 0 to N−1 with no gaps. N is `num_chunks` in the manifest.

### `score_table.bin`

N × 384 signed int8 values, row by row (row-major). Size: exactly `N * 384` bytes.

### `fetch_store.bin`

N records of exactly 2,048 bytes each. Size: exactly `N * 2048` bytes.

| Bytes | Content |
|---|---|
| 0–1 | Length `n` of the JSON, unsigned 16-bit, little-endian (changed from big-endian in corpus version 2026-11-14.2) |
| 2 to 2+n | Chunk JSON, UTF-8 |
| 2+n to 2047 | Zero bytes |

Chunk JSON, written compactly (`separators=(",", ":")`, `ensure_ascii=False`):

```json
{"id": 0, "title": "Asthma", "url": "https://medlineplus.gov/asthma.html", "updated": "2026-10-02", "text": "..."}
```

`n` is at most 2,046. Ingestion caps chunks at about 250 words with about 40 words of overlap, and splits any chunk whose record would not fit.

Decoding a record in Python:

```python
n = int.from_bytes(rec[0:2], "little")
chunk = json.loads(rec[2:2 + n].decode("utf-8"))
```

## 2. Embedding and quantization

Implemented once in `common/embedding.py`. C imports it and does not re-implement it.

| Setting | Value |
|---|---|
| Model | `BAAI/bge-small-en-v1.5` |
| Revision | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |
| Dimension | 384 |
| Normalization | L2 |
| Query prefix | `"Represent this sentence for searching relevant passages: "` (questions only, not chunks) |
| Quantization | `q = clip(round(v * scale), -127, 127)` as int8 |
| `scale` | Fixed at 127 (`common.embedding.SCALE`), also written to the manifest |

Functions:

```python
embed_query(text: str) -> np.ndarray    # shape (384,), dtype int8, uses the manifest's scale
embed_texts(texts: list[str]) -> np.ndarray  # shape (N, 384), float32, L2-normalized (ingestion only)
```

The plaintext score of chunk `i` is `int32(score_table[i]) · int32(q)`. Its absolute value is at most 384 × 127 × 127 = 6,193,536, so it fits in int32. A's plaintext modulus must cover this range.

## 3. Manifest (`manifest.json`)

Schema from the spec.

| Field | Filled by |
|---|---|
| `protocol`, `corpus_version`, `corpus_name`, `attribution` | B |
| `embedding` (`model`, `revision`, `dim`, `normalize`, `query_prefix`) | B |
| `quantization` (`type`: `"int8"`, `scale`: 127) | B |
| `num_chunks`, `top_k` (10) | B |
| `pir.record_bytes` (2048) | B |
| `hashes.score_table`, `hashes.fetch_store` (`"sha256:<hex>"` of the file bytes) | B |
| `scoring` (`library`, `params`), `pir` (`library`, `params`) | A |

## 4. Crypto client (A implements, C calls)

As in the spec:

```python
keygen(manifest) -> key
encrypt_query(key, int8_vec) -> bytes
decrypt_scores(key, blob) -> list[int]        # N scores
make_selector(key, index, N) -> bytes
decrypt_record(key, blob) -> bytes            # exactly 2,048 bytes
```

## 5. Endpoints

| Endpoint | Method | Request | Response |
|---|---|---|---|
| `/v1/manifest` | GET | none | Manifest JSON |
| `/v1/score` | POST | `corpus_version` + encrypted query (`application/octet-stream`) | Encrypted scores for all N chunks, fixed size |
| `/v1/fetch` | POST | `corpus_version` + encrypted selector | Encrypted 2,048-byte record, fixed size |

A stale `corpus_version` returns HTTP 409.

## 6. Answer function and answer shape

```python
answer(question: str, chunks: list[dict]) -> dict   # chunks: decoded records, in rank order
```

Pass all k = 10 chunks; `answer()` uses the first 5 as sources. Each chunk may also carry `score`, the cosine estimate `raw_int_score / scale**2` (`common.embedding.score_to_cosine`). When it is present, `answer()` declines without calling the model if the top score is below `MIN_SCORE`.

`ask()`, `ask_plain()` and `answer()` all return this shape:

```python
{
    "status": "answered" | "declined",
    "answer": str,           # on decline: the "couldn't find a reliable source" message
    "citations": [           # on answer: the cited chunks; on decline: the closest passages
        {"id": int, "title": str, "url": str, "updated": str, "text": str, "score": float}
    ],
    "timings": {"embed_ms": float, "retrieve_ms": float, "answer_ms": float},  # optional keys
}
```

## 7. Server log line

One line per request: timestamp, endpoint, response size in bytes, latency in ms. Never the request body.

## 8. Where the tables live

`data/` is git-ignored for working files. Release tables (`score_table.bin`, `fetch_store.bin`, `manifest.json`, `chunks.jsonl`, about 12 MB in total) are committed to `artifacts/` so A and C get them with `git pull`. Until then, everyone uses the dummy tables from `tools/make_dummy_tables.py`.
