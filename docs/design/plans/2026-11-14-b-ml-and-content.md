# B: ML and Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Blind RAG's content side: MedlinePlus ingestion into the score table, fetch store and manifest; a plaintext baseline `ask_plain()`; the local-model `answer()` with citations and safe decline; and a retrieval and answer eval.

**Architecture:** Pure Python modules that talk through the files and shapes in `docs/contracts.md`. `common/` holds code shared with C (record format, embedding, table loading). `ingest/` turns the MedlinePlus XML into `artifacts/`. `baseline/` does plaintext int8 retrieval, which ranks exactly as Blind RAG will. `client/answer.py` calls Ollama. `eval/` measures recall and answer outcomes.

**Tech Stack:** Python 3.12 (via `uv`), numpy, sentence-transformers (`BAAI/bge-small-en-v1.5`), requests, Ollama with `llama3.2:3b`, pytest.

**Spec:** `docs/contracts.md` (agreed contracts) and the Blind RAG product spec (Nov 14, 2026), sections "Ingestion pipeline", "Client specification", "Accuracy and evaluation".

## Global Constraints

- Python `>=3.12,<3.13`, managed with `uv`; run everything as `uv run ...` from the repo root.
- Embedding model `BAAI/bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions, L2-normalized.
- Query prefix `"Represent this sentence for searching relevant passages: "` on questions only.
- Quantization `q = clip(round(v * scale), -127, 127)` as int8; `scale = 127 / max(|v|)` over the corpus.
- Records exactly 2,048 bytes: 2-byte big-endian length, compact UTF-8 JSON with keys `id, title, url, updated, text`, zero padding. JSON at most 2,046 bytes.
- Chunks at most 250 words with 40 words of overlap.
- Answer shape: `{"status", "answer", "citations": [{"id","title","url","updated","text","score"}], "timings"}`.
- Corpus: English MedlinePlus health topic summaries only (public domain), attributed "Source: MedlinePlus, National Library of Medicine".
- Local model `llama3.2:3b` through Ollama at `http://localhost:11434`, temperature 0.
- `data/` is git-ignored; `artifacts/` is committed.

## File structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore` | Environment and test config |
| `common/records.py` | Pack and unpack 2,048-byte fetch records |
| `common/embedding.py` | Model loading, `embed_texts`, `embed_query`, quantization |
| `common/tables.py` | Load and verify `artifacts/` |
| `ingest/extract.py` | MedlinePlus XML → pages with sections of plain-text paragraphs |
| `ingest/chunk.py` | Page → chunks of at most 250 words that fit a record |
| `ingest/build.py` | Download, extract, chunk, embed, write artifacts and manifest |
| `baseline/retrieve.py` | `PlainIndex`: int8 and float top-k over the tables |
| `baseline/ask_plain.py` | `ask_plain(question)` end to end |
| `client/answer.py` | `answer(question, chunks)` with Ollama, citations, decline |
| `eval/questions.jsonl` | 20 answerable and 5 unanswerable questions |
| `eval/run_eval.py` | Recall at k for float and int8; answer outcomes |
| `tests/` | One test file per module |

---

### Task 1: Project setup and record format

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `common/__init__.py`, `common/records.py`
- Test: `tests/test_records.py`

**Interfaces:**
- Produces: `RECORD_BYTES = 2048`, `MAX_JSON_BYTES = 2046`, `encode_chunk(chunk: dict) -> bytes`, `pack_record(chunk: dict) -> bytes`, `unpack_record(rec: bytes) -> dict`

- [ ] **Step 1: Write config files**

`pyproject.toml`:

```toml
[project]
name = "blindspot"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "numpy>=1.26",
    "requests>=2.31",
    "sentence-transformers>=3.0",
]

[dependency-groups]
dev = ["pytest>=8"]

[tool.uv]
package = false

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
markers = ["slow: downloads the embedding model or needs Ollama"]
addopts = "-m 'not slow'"
```

`.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
data/
```

- [ ] **Step 2: Write the failing test** (`tests/test_records.py`)

```python
import pytest
from common.records import MAX_JSON_BYTES, RECORD_BYTES, pack_record, unpack_record

CHUNK = {"id": 7, "title": "Asthma", "url": "https://medlineplus.gov/asthma.html",
         "updated": "2026-11-13", "text": "Asthma is a chronic disease — café ✓"}


def test_round_trip():
    rec = pack_record(CHUNK)
    assert len(rec) == RECORD_BYTES
    assert unpack_record(rec) == CHUNK


def test_layout_is_big_endian_length_then_json_then_zeros():
    rec = pack_record(CHUNK)
    n = int.from_bytes(rec[:2], "big")
    assert rec[2 + n:] == bytes(RECORD_BYTES - 2 - n)
    assert rec[2:2 + n].startswith(b'{"id":7,"title":"Asthma"')


def test_extra_keys_are_dropped():
    assert unpack_record(pack_record({**CHUNK, "embed_text": "x"})) == CHUNK


def test_too_long_raises():
    with pytest.raises(ValueError):
        pack_record({**CHUNK, "text": "x" * MAX_JSON_BYTES})
```

- [ ] **Step 3: Set up the environment and run the test to see it fail**

Run: `uv python install 3.12 && uv sync && uv run pytest tests/test_records.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 4: Implement** (`common/__init__.py` empty; `common/records.py`)

```python
"""Fixed-size fetch-store records (docs/contracts.md section 1)."""
import json

RECORD_BYTES = 2048
MAX_JSON_BYTES = RECORD_BYTES - 2
FIELDS = ("id", "title", "url", "updated", "text")


def encode_chunk(chunk: dict) -> bytes:
    obj = {k: chunk[k] for k in FIELDS}
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pack_record(chunk: dict) -> bytes:
    body = encode_chunk(chunk)
    if len(body) > MAX_JSON_BYTES:
        raise ValueError(f"chunk {chunk['id']} JSON is {len(body)} bytes; max is {MAX_JSON_BYTES}")
    return len(body).to_bytes(2, "big") + body + bytes(MAX_JSON_BYTES - len(body))


def unpack_record(rec: bytes) -> dict:
    if len(rec) != RECORD_BYTES:
        raise ValueError(f"record is {len(rec)} bytes; expected {RECORD_BYTES}")
    n = int.from_bytes(rec[:2], "big")
    return json.loads(rec[2:2 + n].decode("utf-8"))
```

- [ ] **Step 5: Run the test to see it pass**

Run: `uv run pytest tests/test_records.py -v` — Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore common/ tests/test_records.py docs/
git commit -m "Add project setup, shared contracts and fetch record format"
```

### Task 2: Embedding and quantization

**Files:**
- Create: `common/embedding.py`
- Test: `tests/test_embedding.py`

**Interfaces:**
- Produces: `MODEL_NAME`, `MODEL_REVISION`, `DIM`, `QUERY_PREFIX`, `ARTIFACTS: Path`, `embed_texts(texts: list[str]) -> np.ndarray (N,384) float32`, `embed_query_float(text) -> np.ndarray (384,) float32`, `compute_scale(vecs) -> float`, `quantize(vecs, scale) -> np.ndarray int8`, `embed_query(text, scale=None) -> np.ndarray (384,) int8`, `score_to_cosine(raw, scale) -> float`

- [ ] **Step 1: Write the failing test** (`tests/test_embedding.py`)

```python
import numpy as np
import pytest
from common.embedding import DIM, compute_scale, quantize, score_to_cosine


def test_scale_maps_largest_value_to_127():
    v = np.array([[0.1, -0.4], [0.2, 0.3]], dtype=np.float32)
    s = compute_scale(v)
    assert s == pytest.approx(127 / 0.4)
    q = quantize(v, s)
    assert q.dtype == np.int8 and q.min() == -127


def test_quantize_clips_query_values_beyond_corpus_range():
    q = quantize(np.array([2.0, -2.0, 0.0], dtype=np.float32), 127.0)
    assert q.tolist() == [127, -127, 0]


def test_score_to_cosine_approximates_float_dot():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(2, DIM)).astype(np.float32)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    s = compute_scale(np.stack([a, b]))
    raw = int(quantize(a, s).astype(np.int32) @ quantize(b, s).astype(np.int32))
    assert score_to_cosine(raw, s) == pytest.approx(float(a @ b), abs=0.02)


@pytest.mark.slow
def test_real_model_is_normalized_and_ranks_sensibly():
    from common.embedding import embed_query_float, embed_texts
    docs = embed_texts(["Knee pain when climbing stairs", "How to file your tax return"])
    assert docs.shape == (2, DIM)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1, atol=1e-3)
    q = embed_query_float("my knee hurts on stairs")
    assert q @ docs[0] > q @ docs[1]
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_embedding.py -v` — Expected: FAIL, `No module named 'common.embedding'`

- [ ] **Step 3: Implement** (`common/embedding.py`)

```python
"""Embedding and int8 quantization shared by ingestion and clients (docs/contracts.md section 2)."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
DIM = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")


def embed_texts(texts: list[str], batch_size: int = 64) -> np.ndarray:
    vecs = _model().encode(list(texts), batch_size=batch_size, normalize_embeddings=True,
                           convert_to_numpy=True, show_progress_bar=len(texts) > 200)
    return vecs.astype(np.float32)


def embed_query_float(text: str) -> np.ndarray:
    return embed_texts([QUERY_PREFIX + text])[0]


def compute_scale(vecs: np.ndarray) -> float:
    return float(127.0 / np.abs(vecs).max())


def quantize(vecs: np.ndarray, scale: float) -> np.ndarray:
    return np.clip(np.rint(vecs * scale), -127, 127).astype(np.int8)


@lru_cache(maxsize=4)
def manifest_scale(manifest_path: str | None = None) -> float:
    path = Path(manifest_path) if manifest_path else ARTIFACTS / "manifest.json"
    return float(json.loads(path.read_text())["quantization"]["scale"])


def embed_query(text: str, scale: float | None = None) -> np.ndarray:
    return quantize(embed_query_float(text), manifest_scale() if scale is None else scale)


def score_to_cosine(raw: int | float, scale: float) -> float:
    return float(raw) / (scale * scale)
```

- [ ] **Step 4: Run all embedding tests, including the slow model test once**

Run: `uv run pytest tests/test_embedding.py -v -m ''` — Expected: 4 passed (first run downloads about 130 MB)

- [ ] **Step 5: Commit**

```bash
git add common/embedding.py tests/test_embedding.py
git commit -m "Add pinned embedding model and int8 quantization"
```

### Task 3: Extract MedlinePlus XML

**Files:**
- Create: `ingest/__init__.py`, `ingest/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Produces: `parse_topics(xml_path) -> tuple[list[dict], str]`. Each page: `{"title": str, "url": str, "updated": "YYYY-MM-DD", "also_called": list[str], "sections": list[tuple[str | None, list[str]]]}`. The second value is the XML's generation date. The XML has no per-topic modified date, so `updated` is the date the content was generated.

- [ ] **Step 1: Write the failing test** (`tests/test_extract.py`)

```python
from ingest.extract import parse_topics

XML = """<?xml version="1.0"?>
<health-topics total="3" date-generated="11/13/2026 08:58:25">
 <health-topic title="Asthma" url="https://medlineplus.gov/asthma.html" id="1" language="English" date-created="01/01/2010">
  <also-called>Bronchial asthma</also-called>
  <full-summary>&lt;p&gt;Asthma is a &lt;a href="x"&gt;lung&lt;/a&gt; disease.&lt;/p&gt;
&lt;h3&gt;Symptoms&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Wheezing&lt;/li&gt;&lt;li&gt;Coughing&lt;/li&gt;&lt;/ul&gt;
&lt;table&gt;&lt;tr&gt;&lt;th&gt;Level&lt;/th&gt;&lt;th&gt;Meaning&lt;/th&gt;&lt;/tr&gt;&lt;/table&gt;</full-summary>
 </health-topic>
 <health-topic title="Asma" url="https://medlineplus.gov/spanish/asthma.html" id="2" language="Spanish" date-created="01/01/2010">
  <full-summary>&lt;p&gt;El asma&lt;/p&gt;</full-summary>
 </health-topic>
 <health-topic title="Empty" url="https://medlineplus.gov/empty.html" id="3" language="English" date-created="01/01/2010">
 </health-topic>
</health-topics>"""


def test_parse_topics(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text(XML)
    pages, generated = parse_topics(p)
    assert generated == "2026-11-13"
    assert [pg["title"] for pg in pages] == ["Asthma"]
    pg = pages[0]
    assert pg["updated"] == "2026-11-13"
    assert pg["also_called"] == ["Bronchial asthma"]
    assert pg["sections"] == [
        (None, ["Asthma is a lung disease."]),
        ("Symptoms", ["- Wheezing", "- Coughing", "Level | Meaning"]),
    ]
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_extract.py -v` — Expected: FAIL, `No module named 'ingest'`

- [ ] **Step 3: Implement** (`ingest/__init__.py` empty; `ingest/extract.py`)

```python
"""MedlinePlus health-topics XML -> pages of plain-text sections."""
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser


class _SummaryParser(HTMLParser):
    """Turns summary HTML into [(heading or None, [paragraph, ...]), ...]."""

    BLOCK = {"p", "li", "h2", "h3", "h4", "tr"}
    HEADINGS = {"h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[list] = [[None, []]]
        self.buf: list[str] = []
        self.tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self._flush()
            self.tag = tag
        elif tag in ("td", "th") and "".join(self.buf).strip():
            self.buf.append(" | ")
        elif tag == "br":
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        self.buf.append(data)

    def _flush(self):
        text = " ".join("".join(self.buf).split())
        tag, self.buf, self.tag = self.tag, [], None
        if not text:
            return
        if tag in self.HEADINGS:
            self.sections.append([text, []])
        else:
            self.sections[-1][1].append(("- " if tag == "li" else "") + text)

    def close(self):
        super().close()
        self._flush()


def html_to_sections(html: str) -> list[tuple[str | None, list[str]]]:
    p = _SummaryParser()
    p.feed(html)
    p.close()
    return [(h, paras) for h, paras in p.sections if paras]


def parse_topics(xml_path) -> tuple[list[dict], str]:
    root = ET.parse(xml_path).getroot()
    generated = datetime.strptime(root.get("date-generated"), "%m/%d/%Y %H:%M:%S").date().isoformat()
    pages = []
    for t in root.findall("health-topic"):
        if t.get("language") != "English":
            continue
        summary = t.find("full-summary")
        if summary is None or not (summary.text or "").strip():
            continue
        pages.append({
            "title": t.get("title"),
            "url": t.get("url"),
            "updated": generated,
            "also_called": [a.text.strip() for a in t.findall("also-called") if a.text and a.text.strip()],
            "sections": html_to_sections(summary.text),
        })
    return pages, generated
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/test_extract.py -v` — Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add ingest/ tests/test_extract.py
git commit -m "Extract English MedlinePlus topics into plain-text sections"
```

### Task 4: Chunking

**Files:**
- Create: `ingest/chunk.py`
- Test: `tests/test_chunk.py`

**Interfaces:**
- Consumes: page dict from Task 3; `encode_chunk`, `MAX_JSON_BYTES` from Task 1.
- Produces: `chunk_page(page, max_words=250, overlap=40) -> list[dict]`, each `{"title", "url", "updated", "text", "embed_text"}` (no `id`). `embed_text` is title, "also called" names, then text.

- [ ] **Step 1: Write the failing test** (`tests/test_chunk.py`)

```python
from common.records import MAX_JSON_BYTES, encode_chunk
from ingest.chunk import chunk_page


def page(sections, also=()):
    return {"title": "T", "url": "u", "updated": "2026-11-13", "also_called": list(also), "sections": sections}


def words(prefix, n):
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_short_page_is_one_chunk_with_heading_lines():
    chunks = chunk_page(page([(None, ["Intro text."]), ("Symptoms", ["- Cough"])], also=["A", "B"]))
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Intro text.\nSymptoms\n- Cough"
    assert chunks[0]["embed_text"].startswith("T (also called: A, B)\n")


def test_long_page_respects_word_limit_and_overlaps():
    paras = [words(f"p{j}w", 100) for j in range(6)]
    chunks = chunk_page(page([(None, paras)]), max_words=250, overlap=40)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c["text"].split()) <= 250
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-40:] == second[:40]


def test_one_huge_paragraph_is_split():
    chunks = chunk_page(page([(None, [words("w", 1000)])]))
    assert all(len(c["text"].split()) <= 250 for c in chunks)
    assert {"w0", "w999"} <= set(" ".join(c["text"] for c in chunks).split())


def test_every_chunk_fits_a_record_even_with_long_words():
    chunks = chunk_page(page([(None, [" ".join(["x" * 30] * 200)])]))
    assert len(chunks) > 1
    for c in chunks:
        assert len(encode_chunk({**c, "id": 999999})) <= MAX_JSON_BYTES
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_chunk.py -v` — Expected: FAIL, `No module named 'ingest.chunk'`

- [ ] **Step 3: Implement** (`ingest/chunk.py`)

```python
"""Page -> chunks of at most max_words words that fit a 2,048-byte record."""
from common.records import MAX_JSON_BYTES, encode_chunk


def _pieces(lines: list[str], limit: int) -> list[str]:
    out = []
    for line in lines:
        w = line.split()
        if len(w) <= limit:
            out.append(line)
        else:
            out += [" ".join(w[i:i + limit]) for i in range(0, len(w), limit)]
    return out


def _windows(lines: list[str], max_words: int, overlap: int) -> list[str]:
    chunks, cur, n = [], [], 0
    for piece in _pieces(lines, max_words - overlap):
        k = len(piece.split())
        if cur and n + k > max_words:
            chunks.append(cur)
            tail = " ".join(" ".join(cur).split()[-overlap:]) if overlap else ""
            cur, n = ([tail], len(tail.split())) if tail else ([], 0)
        cur.append(piece)
        n += k
    if cur:
        chunks.append(cur)
    return ["\n".join(c) for c in chunks]


def _make(page: dict, text: str) -> dict:
    head = page["title"]
    if page["also_called"]:
        head += f" (also called: {', '.join(page['also_called'])})"
    return {"title": page["title"], "url": page["url"], "updated": page["updated"],
            "text": text, "embed_text": f"{head}\n{text}"}


def _fit(page: dict, text: str) -> list[dict]:
    chunk = _make(page, text)
    if len(encode_chunk({**chunk, "id": 999999})) <= MAX_JSON_BYTES:
        return [chunk]
    w = text.split()
    if len(w) < 2:
        raise ValueError(f"cannot fit a single word into a record: {page['url']}")
    half = len(w) // 2
    return _fit(page, " ".join(w[:half])) + _fit(page, " ".join(w[half:]))


def chunk_page(page: dict, max_words: int = 250, overlap: int = 40) -> list[dict]:
    lines = []
    for heading, paras in page["sections"]:
        if heading:
            lines.append(heading)
        lines += paras
    return [c for body in _windows(lines, max_words, overlap) for c in _fit(page, body)]
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/test_chunk.py -v` — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add ingest/chunk.py tests/test_chunk.py
git commit -m "Chunk pages to 250 words with 40-word overlap, fitted to records"
```

### Task 5: Build and load artifacts

**Files:**
- Create: `ingest/build.py`, `common/tables.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: Tasks 1 to 4.
- Produces: `write_artifacts(chunks, vecs, out_dir, corpus_version) -> dict` (manifest); `load_artifacts(dir=ARTIFACTS) -> (manifest: dict, score_table: np.ndarray (N,384) int8, store: bytes)`; `get_record(store, i) -> dict`; `verify_hashes(manifest, dir) -> None` (raises on mismatch). CLI: `uv run python -m ingest.build` writes `artifacts/{score_table.bin, fetch_store.bin, chunks.jsonl, manifest.json}` and `data/embeddings_f32.npy`.

- [ ] **Step 1: Write the failing test** (`tests/test_build.py`)

```python
import json
import numpy as np
import pytest
from common.records import RECORD_BYTES
from common.tables import get_record, load_artifacts, verify_hashes
from ingest.build import write_artifacts


def fake(n=5):
    chunks = [{"id": i, "title": f"T{i}", "url": f"https://x/{i}", "updated": "2026-11-13",
               "text": f"text {i}", "embed_text": f"T{i}\ntext {i}"} for i in range(n)]
    v = np.random.default_rng(1).normal(size=(n, 384)).astype(np.float32)
    return chunks, v / np.linalg.norm(v, axis=1, keepdims=True)


def test_artifacts_round_trip(tmp_path):
    chunks, vecs = fake()
    m = write_artifacts(chunks, vecs, tmp_path, "2026-11-13.1")
    assert (tmp_path / "score_table.bin").stat().st_size == 5 * 384
    assert (tmp_path / "fetch_store.bin").stat().st_size == 5 * RECORD_BYTES
    assert m["num_chunks"] == 5 and m["pir"]["record_bytes"] == RECORD_BYTES
    assert json.loads((tmp_path / "manifest.json").read_text()) == m

    m2, table, store = load_artifacts(tmp_path)
    verify_hashes(m2, tmp_path)
    assert table.shape == (5, 384) and table.dtype == np.int8
    assert np.abs(table).max() == 127
    assert get_record(store, 3) == {k: chunks[3][k] for k in ("id", "title", "url", "updated", "text")}
    lines = (tmp_path / "chunks.jsonl").read_text().splitlines()
    assert json.loads(lines[4])["id"] == 4


def test_hash_mismatch_raises(tmp_path):
    chunks, vecs = fake()
    m = write_artifacts(chunks, vecs, tmp_path, "v")
    (tmp_path / "score_table.bin").write_bytes(bytes(5 * 384))
    with pytest.raises(ValueError):
        verify_hashes(m, tmp_path)
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_build.py -v` — Expected: FAIL, `No module named 'common.tables'`

- [ ] **Step 3: Implement** `common/tables.py`

```python
"""Load and verify the artifacts/ tables (docs/contracts.md sections 1, 3, 8)."""
import hashlib
import json
from pathlib import Path

import numpy as np

from common.embedding import ARTIFACTS
from common.records import RECORD_BYTES, unpack_record


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_artifacts(artifacts_dir=ARTIFACTS):
    d = Path(artifacts_dir)
    m = json.loads((d / "manifest.json").read_text())
    n, dim, size = m["num_chunks"], m["embedding"]["dim"], m["pir"]["record_bytes"]
    table = np.fromfile(d / "score_table.bin", dtype=np.int8)
    if table.size != n * dim:
        raise ValueError(f"score table has {table.size} values; expected {n * dim}")
    store = (d / "fetch_store.bin").read_bytes()
    if len(store) != n * size:
        raise ValueError(f"fetch store has {len(store)} bytes; expected {n * size}")
    return m, table.reshape(n, dim), store


def get_record(store: bytes, i: int) -> dict:
    return unpack_record(store[i * RECORD_BYTES:(i + 1) * RECORD_BYTES])


def verify_hashes(manifest: dict, artifacts_dir=ARTIFACTS) -> None:
    d = Path(artifacts_dir)
    for key, name in (("score_table", "score_table.bin"), ("fetch_store", "fetch_store.bin")):
        if sha256_file(d / name) != manifest["hashes"][key]:
            raise ValueError(f"{name} does not match the manifest hash")
```

- [ ] **Step 4: Implement** `ingest/build.py`

```python
"""Offline pipeline: MedlinePlus XML -> artifacts/ (score table, fetch store, manifest)."""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import requests

from common.embedding import (ARTIFACTS, DIM, MODEL_NAME, MODEL_REVISION, QUERY_PREFIX,
                              compute_scale, embed_texts, quantize)
from common.records import RECORD_BYTES, pack_record
from common.tables import sha256_file
from ingest.chunk import chunk_page
from ingest.extract import parse_topics

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
XML_INDEX = "https://medlineplus.gov/xml.html"
XML_LINK = re.compile(r"https://medlineplus\.gov/xml/mplus_topics_\d{4}-\d{2}-\d{2}\.xml")


def latest_xml_url() -> str:
    html = requests.get(XML_INDEX, timeout=30).text
    urls = sorted(set(XML_LINK.findall(html)))
    if not urls:
        raise RuntimeError(f"no health-topics XML link found on {XML_INDEX}")
    return urls[-1]


def download(url: str, raw_dir: Path) -> Path:
    dest = raw_dir / url.rsplit("/", 1)[1]
    if not dest.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def build_chunks(pages: list[dict]) -> list[dict]:
    chunks = []
    for page in pages:
        for c in chunk_page(page):
            c["id"] = len(chunks)
            chunks.append(c)
    return chunks


def write_artifacts(chunks: list[dict], vecs: np.ndarray, out_dir, corpus_version: str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scale = compute_scale(vecs)
    (out / "score_table.bin").write_bytes(quantize(vecs, scale).tobytes(order="C"))
    with open(out / "fetch_store.bin", "wb") as f:
        for c in chunks:
            f.write(pack_record(c))
    with open(out / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            row = {k: c[k] for k in ("id", "title", "url", "updated", "text")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "protocol": "blind-rag/1",
        "corpus_version": corpus_version,
        "corpus_name": "MedlinePlus health topics (public domain subset)",
        "attribution": "Source: MedlinePlus, National Library of Medicine",
        "embedding": {"model": MODEL_NAME, "revision": MODEL_REVISION, "dim": DIM,
                      "normalize": "l2", "query_prefix": QUERY_PREFIX},
        "quantization": {"type": "int8", "scale": scale},
        "scoring": {"library": "set by crypto server", "params": "set by crypto server"},
        "pir": {"library": "set by crypto server", "params": "set by crypto server",
                "record_bytes": RECORD_BYTES},
        "num_chunks": len(chunks),
        "top_k": 10,
        "hashes": {"score_table": sha256_file(out / "score_table.bin"),
                   "fetch_store": sha256_file(out / "fetch_store.bin")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xml", type=Path, help="local MedlinePlus XML (default: download the latest)")
    ap.add_argument("--out", type=Path, default=ARTIFACTS)
    args = ap.parse_args()

    xml = args.xml or download(latest_xml_url(), DATA / "raw")
    pages, generated = parse_topics(xml)
    chunks = build_chunks(pages)
    words = [len(c["text"].split()) for c in chunks]
    print(f"{len(pages)} pages -> {len(chunks)} chunks; words per chunk mean {np.mean(words):.0f}, max {max(words)}")

    vecs = embed_texts([c["embed_text"] for c in chunks])
    DATA.mkdir(exist_ok=True)
    np.save(DATA / "embeddings_f32.npy", vecs)
    m = write_artifacts(chunks, vecs, args.out, f"{generated}.1")
    print(f"wrote {args.out}: corpus_version {m['corpus_version']}, scale {m['quantization']['scale']:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest -v` — Expected: all pass

- [ ] **Step 6: Run the real build and check it**

Run: `uv run python -m ingest.build --xml data/raw/mplus_topics_2026-11-13.xml`
Expected: about 1,014 pages and roughly 2,000 to 3,000 chunks; `artifacts/` holds four files; `fetch_store.bin` size is `num_chunks * 2048`.

Run: `uv run python -c "from common.tables import *; m,t,s=load_artifacts(); verify_hashes(m); print(m['num_chunks'], get_record(s, 0)['title'])"`
Expected: the chunk count and `A1C`.

- [ ] **Step 7: Commit and push**

```bash
git add common/tables.py ingest/build.py tests/test_build.py artifacts/
git commit -m "Build MedlinePlus artifacts: score table, fetch store, manifest"
git push -u origin B-ml-and-content
```

Tell A and C the artifacts are on the branch (contract section 8 says `main`; merge or PR when the team agrees).

### Task 6: Plaintext retrieval index

**Files:**
- Create: `baseline/__init__.py`, `baseline/retrieve.py`
- Test: `tests/test_retrieve.py`

**Interfaces:**
- Consumes: `load_artifacts`, `get_record`, `quantize`, `embed_query_float`.
- Produces: `PlainIndex(artifacts_dir=ARTIFACTS, float_path=None)` with `.search_vec(qvec: np.ndarray float32 (384,), k=10, mode="int8"|"float") -> list[tuple[int, float]]` (id, cosine estimate), `.search(question, k, mode)`, `.chunks(hits) -> list[dict]` (record plus `"score"`), `.manifest`, `.scale`.

- [ ] **Step 1: Write the failing test** (`tests/test_retrieve.py`)

```python
import numpy as np
import pytest
from baseline.retrieve import PlainIndex
from ingest.build import write_artifacts


@pytest.fixture
def index(tmp_path):
    rng = np.random.default_rng(2)
    v = rng.normal(size=(50, 384)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    chunks = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"t{i}",
               "embed_text": ""} for i in range(50)]
    write_artifacts(chunks, v, tmp_path, "v")
    np.save(tmp_path / "f.npy", v)
    return PlainIndex(tmp_path, float_path=tmp_path / "f.npy"), v


def test_exact_vector_ranks_first_in_both_modes(index):
    idx, v = index
    for mode in ("int8", "float"):
        hits = idx.search_vec(v[17], k=5, mode=mode)
        assert hits[0][0] == 17 and len(hits) == 5
        assert hits[0][1] == pytest.approx(1.0, abs=0.03)
        assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_chunks_carry_record_and_score(index):
    idx, v = index
    c = idx.chunks(idx.search_vec(v[3], k=1))[0]
    assert c["id"] == 3 and c["title"] == "T3" and "score" in c


def test_float_mode_without_float_vectors_raises(index, tmp_path):
    with pytest.raises(ValueError):
        PlainIndex(tmp_path).search_vec(index[1][0], mode="float")
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_retrieve.py -v` — Expected: FAIL, `No module named 'baseline'`

- [ ] **Step 3: Implement** (`baseline/__init__.py` empty; `baseline/retrieve.py`)

```python
"""Plaintext top-k over the same tables Blind RAG uses. int8 mode ranks exactly as Blind RAG will."""
from pathlib import Path

import numpy as np

from common.embedding import ARTIFACTS, embed_query_float, quantize
from common.tables import get_record, load_artifacts


class PlainIndex:
    def __init__(self, artifacts_dir=ARTIFACTS, float_path=None):
        self.manifest, table, self.store = load_artifacts(artifacts_dir)
        self.scale = float(self.manifest["quantization"]["scale"])
        self.table32 = table.astype(np.int32)
        self.float_vecs = np.load(float_path) if float_path and Path(float_path).exists() else None

    def search_vec(self, qvec: np.ndarray, k: int = 10, mode: str = "int8") -> list[tuple[int, float]]:
        if mode == "int8":
            raw = self.table32 @ quantize(qvec, self.scale).astype(np.int32)
            scores = raw / (self.scale * self.scale)
        elif mode == "float":
            if self.float_vecs is None:
                raise ValueError("float mode needs float_path (data/embeddings_f32.npy)")
            scores = self.float_vecs @ qvec
        else:
            raise ValueError(f"unknown mode {mode!r}")
        top = np.argsort(-scores, kind="stable")[:k]
        return [(int(i), float(scores[i])) for i in top]

    def search(self, question: str, k: int = 10, mode: str = "int8") -> list[tuple[int, float]]:
        return self.search_vec(embed_query_float(question), k, mode)

    def chunks(self, hits: list[tuple[int, float]]) -> list[dict]:
        return [{**get_record(self.store, i), "score": s} for i, s in hits]
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/test_retrieve.py -v` — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add baseline/ tests/test_retrieve.py
git commit -m "Add plaintext int8 and float retrieval over the artifacts"
```

### Task 7: Local answer with citations and safe decline

**Files:**
- Create: `client/__init__.py` (only if missing), `client/answer.py`
- Test: `tests/test_answer.py`

**Interfaces:**
- Consumes: chunk dicts in rank order (`id, title, url, updated, text`, optional `score` as a cosine estimate).
- Produces: `answer(question, chunks, llm=ollama_generate, n_context=5, min_score=MIN_SCORE) -> dict` in the contract's answer shape; `ollama_generate(prompt) -> str`; constants `DECLINE_MESSAGE`, `DISCLAIMER`, `MIN_SCORE`.

- [ ] **Step 1: Write the failing test** (`tests/test_answer.py`)

```python
from client.answer import DECLINE_MESSAGE, DISCLAIMER, answer

CHUNKS = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"fact {i}",
           "score": 0.8 - i * 0.01} for i in range(10)]


def test_answer_cites_and_renumbers():
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        return "Fact three [3]. Fact one [1][3]. Bogus [9]."

    r = answer("q?", CHUNKS, llm=llm)
    assert r["status"] == "answered"
    assert [c["id"] for c in r["citations"]] == [0, 2]
    assert r["answer"].startswith("Fact three [2]. Fact one [1][2]. Bogus .")
    assert r["answer"].endswith(DISCLAIMER)
    assert "[5] T4" in seen["prompt"] and "[6]" not in seen["prompt"]
    assert "answer_ms" in r["timings"]


def test_no_answer_from_model_declines_with_closest_passages():
    r = answer("q?", CHUNKS, llm=lambda p: "NO_ANSWER")
    assert r["status"] == "declined" and r["answer"].startswith(DECLINE_MESSAGE)
    assert [c["id"] for c in r["citations"]] == [0, 1, 2]


def test_uncited_answer_declines():
    assert answer("q?", CHUNKS, llm=lambda p: "Some unsupported text.")["status"] == "declined"


def test_low_retrieval_score_declines_without_calling_model():
    low = [{**c, "score": 0.1} for c in CHUNKS]
    def boom(p):
        raise AssertionError("model should not be called")
    assert answer("q?", low, llm=boom, min_score=0.5)["status"] == "declined"


def test_chunks_without_scores_skip_threshold():
    plain = [{k: v for k, v in c.items() if k != "score"} for c in CHUNKS]
    r = answer("q?", plain, llm=lambda p: "Yes [1].", min_score=0.99)
    assert r["status"] == "answered" and r["citations"][0]["score"] == 0.0
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_answer.py -v` — Expected: FAIL, `No module named 'client.answer'`

- [ ] **Step 3: Implement** `client/answer.py`

```python
"""Local-model answer with citations and safe decline (docs/contracts.md section 6)."""
import re
import time

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"
N_CONTEXT = 5
MIN_SCORE = 0.55  # cosine estimate of the top chunk; tuned in Task 9
DECLINE_MESSAGE = "I couldn't find a reliable source for this in the library. The closest passages are below."
DISCLAIMER = "This is general health information, not medical advice."

PROMPT = """You answer health questions using ONLY the numbered sources below.
Rules:
- Use only facts stated in the sources. Do not add outside knowledge.
- After each sentence, cite the source numbers it came from, like [1] or [2][3].
- If the sources do not answer the question, reply with exactly: NO_ANSWER
- Answer in plain language, in under 150 words.

Sources:
{sources}

Question: {question}
Answer:"""


def ollama_generate(prompt: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: float = 180) -> str:
    r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False,
                                 "options": {"temperature": 0}}, timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


def _cite(c: dict) -> dict:
    return {**{k: c[k] for k in ("id", "title", "url", "updated", "text")}, "score": float(c.get("score", 0.0))}


def _result(status: str, text: str, citations: list[dict], t0: float) -> dict:
    return {"status": status, "answer": f"{text}\n\n{DISCLAIMER}", "citations": citations,
            "timings": {"answer_ms": (time.perf_counter() - t0) * 1000}}


def answer(question: str, chunks: list[dict], llm=ollama_generate,
           n_context: int = N_CONTEXT, min_score: float = MIN_SCORE) -> dict:
    t0 = time.perf_counter()
    ctx = chunks[:n_context]
    decline = lambda: _result("declined", DECLINE_MESSAGE, [_cite(c) for c in chunks[:3]], t0)
    if not ctx or ("score" in ctx[0] and ctx[0]["score"] < min_score):
        return decline()

    sources = "\n\n".join(f"[{i}] {c['title']}\n{c['text']}" for i, c in enumerate(ctx, 1))
    text = llm(PROMPT.format(sources=sources, question=question))
    if not text or "NO_ANSWER" in text.upper():
        return decline()

    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 1 <= int(n) <= len(ctx)})
    if not used:
        return decline()
    renumber = {n: i for i, n in enumerate(used, 1)}

    def fix(m):
        n = int(m.group(1))
        return f"[{renumber[n]}]" if n in renumber else ""

    return _result("answered", re.sub(r"\[(\d+)\]", fix, text), [_cite(ctx[n - 1]) for n in used], t0)
```

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/test_answer.py -v` — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add client/answer.py tests/test_answer.py
git commit -m "Add local-model answer with citations and safe decline"
```

### Task 8: `ask_plain()` end to end

**Files:**
- Create: `baseline/ask_plain.py`
- Test: `tests/test_ask_plain.py`

**Interfaces:**
- Consumes: `PlainIndex`, `answer`, `embed_query_float`.
- Produces: `ask_plain(question, k=10, mode="int8", index=None, answer_fn=answer) -> dict` in the answer shape, with `timings` keys `embed_ms`, `retrieve_ms`, `answer_ms`. CLI: `uv run python -m baseline.ask_plain "question"`.

- [ ] **Step 1: Write the failing test** (`tests/test_ask_plain.py`)

```python
import numpy as np
import pytest
from baseline import ask_plain as mod
from baseline.retrieve import PlainIndex
from ingest.build import write_artifacts


def test_ask_plain_wires_retrieval_into_answer(tmp_path, monkeypatch):
    v = np.eye(384, dtype=np.float32)[:20]
    chunks = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"t{i}",
               "embed_text": ""} for i in range(20)]
    write_artifacts(chunks, v, tmp_path, "v")
    monkeypatch.setattr(mod, "embed_query_float", lambda q: v[4])
    got = {}

    def fake_answer(q, cs):
        got["ids"] = [c["id"] for c in cs]
        return {"status": "answered", "answer": "a", "citations": [], "timings": {"answer_ms": 1.0}}

    r = mod.ask_plain("q", k=10, index=PlainIndex(tmp_path), answer_fn=fake_answer)
    assert got["ids"][0] == 4 and len(got["ids"]) == 10
    assert set(r["timings"]) == {"embed_ms", "retrieve_ms", "answer_ms"}


@pytest.mark.slow
def test_real_question_end_to_end():
    r = mod.ask_plain("What is an A1C test?")
    assert r["status"] in ("answered", "declined")
    assert all("url" in c for c in r["citations"])
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/test_ask_plain.py -v` — Expected: FAIL, `cannot import name 'ask_plain'`

- [ ] **Step 3: Implement** `baseline/ask_plain.py`

```python
"""Plaintext RAG over the same chunks: the 'normal server' side of the demo and the eval baseline."""
import json
import sys
import time
from pathlib import Path

from baseline.retrieve import PlainIndex
from client.answer import answer
from common.embedding import embed_query_float

FLOAT_PATH = Path(__file__).resolve().parent.parent / "data" / "embeddings_f32.npy"
_index: PlainIndex | None = None


def default_index() -> PlainIndex:
    global _index
    if _index is None:
        _index = PlainIndex(float_path=FLOAT_PATH)
    return _index


def ask_plain(question: str, k: int = 10, mode: str = "int8", index: PlainIndex | None = None,
              answer_fn=answer) -> dict:
    idx = index or default_index()
    t0 = time.perf_counter()
    qvec = embed_query_float(question)
    t1 = time.perf_counter()
    chunks = idx.chunks(idx.search_vec(qvec, k, mode))
    t2 = time.perf_counter()
    result = answer_fn(question, chunks)
    result.setdefault("timings", {}).update(embed_ms=(t1 - t0) * 1000, retrieve_ms=(t2 - t1) * 1000)
    return result


if __name__ == "__main__":
    print(json.dumps(ask_plain(" ".join(sys.argv[1:])), indent=2, ensure_ascii=False))
```

- [ ] **Step 4: Run unit tests, then the real end-to-end test with Ollama running**

Run: `uv run pytest tests/test_ask_plain.py -v` — Expected: 1 passed, 1 deselected
Run: `uv run pytest tests/test_ask_plain.py -v -m slow` — Expected: 1 passed
Run: `uv run python -m baseline.ask_plain "Can I take FMLA leave for a pregnancy complication?"` — inspect the answer and citations by eye.

- [ ] **Step 5: Commit and push**

```bash
git add baseline/ask_plain.py tests/test_ask_plain.py
git commit -m "Add ask_plain: plaintext RAG baseline end to end"
git push
```

### Task 9: Test questions and eval

**Files:**
- Create: `eval/__init__.py`, `eval/questions.jsonl`, `eval/run_eval.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `PlainIndex`, `ask_plain`, `embed_query_float`, `artifacts/chunks.jsonl`.
- Produces: `first_rank(urls: list[str], gold: str) -> int | None` (1-based), `recall_table(ranks: list[int | None], ks=(1,5,10,20)) -> dict[int, float]`. CLI `uv run python -m eval.run_eval [--answers]` writes `eval/results/retrieval.csv` and, with `--answers`, `eval/results/answers.jsonl`.
- Question format, one per line: `{"question": str, "source_url": str | null}`. `null` marks a question the corpus cannot answer, which should decline.

- [ ] **Step 1: Write questions.** 20 answerable questions in plain patient wording that avoids the topic title, each with its MedlinePlus topic URL; include exact-term ones (a drug or test name). 5 unanswerable ones (for example tax law, car repair, a drug not in MedlinePlus topics). Pick topics by browsing `artifacts/chunks.jsonl`.

- [ ] **Step 2: Write the failing test** (`tests/test_eval.py`)

```python
import json
from pathlib import Path
from eval.run_eval import first_rank, recall_table

ROOT = Path(__file__).resolve().parent.parent


def test_first_rank_and_recall():
    assert first_rank(["a", "b", "b"], "b") == 2
    assert first_rank(["a"], "z") is None
    assert recall_table([1, 3, None, 12], ks=(1, 5, 20)) == {1: 0.25, 5: 0.5, 20: 0.75}


def test_every_gold_url_is_in_the_corpus():
    urls = {json.loads(l)["url"] for l in (ROOT / "artifacts/chunks.jsonl").read_text().splitlines()}
    qs = [json.loads(l) for l in (ROOT / "eval/questions.jsonl").read_text().splitlines() if l.strip()]
    assert len(qs) >= 25
    missing = [q["source_url"] for q in qs if q["source_url"] and q["source_url"] not in urls]
    assert not missing
```

- [ ] **Step 3: Run to see it fail**

Run: `uv run pytest tests/test_eval.py -v` — Expected: FAIL, `No module named 'eval.run_eval'`

- [ ] **Step 4: Implement** (`eval/__init__.py` empty; `eval/run_eval.py`)

```python
"""Retrieval recall (float vs int8) and answer outcomes over eval/questions.jsonl."""
import argparse
import csv
import json
from pathlib import Path

from baseline.ask_plain import ask_plain, default_index
from common.embedding import embed_query_float

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
KS = (1, 5, 10, 20)


def first_rank(urls: list[str], gold: str) -> int | None:
    return next((i for i, u in enumerate(urls, 1) if u == gold), None)


def recall_table(ranks: list[int | None], ks=KS) -> dict[int, float]:
    return {k: sum(r is not None and r <= k for r in ranks) / len(ranks) for k in ks}


def load_questions() -> list[dict]:
    lines = (ROOT / "eval" / "questions.jsonl").read_text().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def run_retrieval(questions: list[dict]) -> list[dict]:
    idx = default_index()
    rows = []
    for q in (q for q in questions if q["source_url"]):
        qvec = embed_query_float(q["question"])
        row = {"question": q["question"], "gold": q["source_url"]}
        for mode in ("float", "int8"):
            urls = [c["url"] for c in idx.chunks(idx.search_vec(qvec, max(KS), mode))]
            row[f"{mode}_rank"] = first_rank(urls, q["source_url"])
        rows.append(row)
    return rows


def run_answers(questions: list[dict]) -> list[dict]:
    out = []
    for q in questions:
        r = ask_plain(q["question"])
        cited = [c["url"] for c in r["citations"]] if r["status"] == "answered" else []
        out.append({**q, "status": r["status"], "gold_cited": q["source_url"] in cited if q["source_url"] else None,
                    "answer": r["answer"], "cited": cited, "timings": r["timings"], "grade": ""})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--answers", action="store_true", help="also run ask_plain with the local model")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    questions = load_questions()

    rows = run_retrieval(questions)
    with open(RESULTS / "retrieval.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Recall over {len(rows)} answerable questions")
    print("mode   " + "  ".join(f"@{k:<4}" for k in KS))
    for mode in ("float", "int8"):
        rec = recall_table([r[f"{mode}_rank"] for r in rows])
        print(f"{mode:6} " + "  ".join(f"{rec[k]:.2f} " for k in KS))

    if args.answers:
        out = run_answers(questions)
        with open(RESULTS / "answers.jsonl", "w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        ans = [r for r in out if r["source_url"]]
        neg = [r for r in out if not r["source_url"]]
        print(f"Answerable: {sum(r['status'] == 'answered' for r in ans)}/{len(ans)} answered, "
              f"{sum(bool(r['gold_cited']) for r in ans)} cite the right page")
        print(f"Unanswerable: {sum(r['status'] == 'declined' for r in neg)}/{len(neg)} declined")
        ms = sorted(sum(r["timings"].values()) for r in out)
        print(f"Median latency {ms[len(ms) // 2] / 1000:.1f} s")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests and the eval**

Run: `uv run pytest -v` — Expected: all pass
Run: `uv run python -m eval.run_eval --answers` — Expected: recall table plus answer summary.

- [ ] **Step 6: Tune `MIN_SCORE`.** Look at the top-1 cosine of answerable versus unanswerable questions in `answers.jsonl` (rerun retrieval if needed). Set `MIN_SCORE` in `client/answer.py` between the two groups, favouring fewer wrong answers. Rerun the eval.

- [ ] **Step 7: Commit and push**

```bash
git add eval/ tests/test_eval.py client/answer.py
git commit -m "Add eval questions, recall and answer eval; tune decline threshold"
git push
```

### Task 10 (only if ahead at hour 9): Cross-encoder rerank

Add `cross-encoder/ms-marco-MiniLM-L-6-v2` in `client/answer.py` before building `ctx`: rerank the k chunks against the question, keep the best `n_context`, and decline when the best rerank score is below a threshold tuned the same way as Task 9 Step 6. Add an `int8+rerank` row to `run_eval.py`. Write the test first with a fake reranker passed as a parameter, as `llm` is.
