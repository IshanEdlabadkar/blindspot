"""Offline pipeline: one source -> its artifacts (score table, fetch store, chunks, manifest).

  uv run python -m ingest.build                       # MedlinePlus -> artifacts/ (the original single server)
  uv run python -m ingest.build --source fmla         # FMLA regulations -> artifacts/fmla/
  uv run python -m ingest.build --source medlineplus  # MedlinePlus -> artifacts/medlineplus/
"""
import argparse
import json
from pathlib import Path

import numpy as np

from common.embedding import ARTIFACTS, DIM, MODEL_NAME, MODEL_REVISION, QUERY_PREFIX, SCALE, embed_texts, quantize
from common.records import RECORD_BYTES, pack_record
from common.tables import sha256_file
from ingest import sources
from ingest.chunk import chunk_page

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def build_chunks(pages: list[dict]) -> list[dict]:
    chunks = []
    for page in pages:
        for c in chunk_page(page):
            c["id"] = len(chunks)
            chunks.append(c)
    return chunks


def write_artifacts(chunks: list[dict], vecs: np.ndarray, out_dir, corpus_version: str, source=None) -> dict:
    source = source or sources.get("medlineplus")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "score_table.bin").write_bytes(quantize(vecs, SCALE).tobytes(order="C"))
    with open(out / "fetch_store.bin", "wb") as f:
        for c in chunks:
            f.write(pack_record(c))
    with open(out / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            row = {k: c[k] for k in ("id", "title", "url", "updated", "text")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "protocol": "blind-rag/1",
        "source_id": source.SOURCE_ID,
        "source_name": source.SOURCE_NAME,
        "corpus_version": corpus_version,
        "corpus_name": source.CORPUS_NAME,
        "attribution": source.ATTRIBUTION,
        "embedding": {"model": MODEL_NAME, "revision": MODEL_REVISION, "dim": DIM,
                      "normalize": "l2", "query_prefix": QUERY_PREFIX},
        "quantization": {"type": "int8", "scale": SCALE},
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=sorted(sources.ALL),
                    help="source to build into artifacts/<source>/ (default: MedlinePlus into artifacts/)")
    ap.add_argument("--input", "--xml", dest="input", type=Path, help="local raw file (default: download)")
    ap.add_argument("--out", type=Path, help="output folder (default: artifacts/ or artifacts/<source>/)")
    ap.add_argument("--corpus-version", help="manifest corpus_version; bump it whenever the tables change "
                                              "(default: <source date>.1)")
    args = ap.parse_args()

    source = sources.get(args.source or "medlineplus")
    out = args.out or (ARTIFACTS / source.SOURCE_ID if args.source else ARTIFACTS)
    raw = args.input or source.fetch(DATA / "raw")
    pages, date = source.parse(raw)
    chunks = build_chunks(pages)
    words = [len(c["text"].split()) for c in chunks]
    print(f"{source.SOURCE_ID}: {len(pages)} pages -> {len(chunks)} chunks; "
          f"words per chunk mean {np.mean(words):.0f}, max {max(words)}")

    vecs = embed_texts([c["embed_text"] for c in chunks])
    DATA.mkdir(exist_ok=True)
    np.save(DATA / ("embeddings_f32.npy" if not args.source else f"embeddings_{source.SOURCE_ID}.npy"), vecs)
    m = write_artifacts(chunks, vecs, out, args.corpus_version or f"{date}.1", source)
    print(f"wrote {out}: corpus_version {m['corpus_version']}, {m['num_chunks']} chunks")


if __name__ == "__main__":
    main()
