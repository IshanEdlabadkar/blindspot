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
