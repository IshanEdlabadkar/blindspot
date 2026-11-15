"""Build a larger corpus: MedlinePlus health topics plus extra public-domain sources.

    python3.12 -m ingest.build_multi                       # -> artifacts-expanded/
    python3.12 -m ingest.build_multi --sources medlineplus,genetics
    python3.12 -m ingest.build_multi --dry-run             # download + chunk, print counts, no embedding

Writes a separate folder, so artifacts/ (the corpus the demo and eval use) is untouched.
Serve it with:  make stop && make demo DATA=artifacts-expanded
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from ingest.build import DATA, download, latest_xml_url, write_artifacts
from ingest.chunk import chunk_page
from ingest.extract import parse_topics
from ingest.sources import ATTRIBUTION, COLLECTORS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "artifacts-expanded"
MAX_CHUNKS = 10_000  # spec v1 target: every chunk is scored on every question


def collect(sources: list[str], raw_dir: Path, xml: Path | None = None) -> tuple[list[dict], str]:
    pages, generated = [], time.strftime("%Y-%m-%d")
    for name in sources:
        if name == "medlineplus":
            got, generated = parse_topics(xml or download(latest_xml_url(), raw_dir))
            for p in got:
                p["source"] = "medlineplus"
        else:
            got = COLLECTORS[name](raw_dir)
        print(f"  {name}: {len(got)} pages")
        pages += got
    # The same URL from two sources would be the same page twice: keep the first.
    seen, out = set(), []
    for p in pages:
        if p["url"] and p["url"] not in seen:
            seen.add(p["url"])
            out.append(p)
    return out, generated


def build_chunks(pages: list[dict]) -> list[dict]:
    """Same as ingest.build.build_chunks, keeping each chunk's source for the counts."""
    chunks = []
    for page in pages:
        for c in chunk_page(page):
            c["id"], c["source"] = len(chunks), page.get("source", "medlineplus")
            chunks.append(c)
    return chunks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default="medlineplus,genetics,myhealthfinder",
                    help=f"comma list from: medlineplus, {', '.join(COLLECTORS)}")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--xml", type=Path, help="local MedlinePlus health-topics XML (default: download)")
    ap.add_argument("--corpus-version", help="default: <MedlinePlus XML date>.x<number of sources>")
    ap.add_argument("--dry-run", action="store_true", help="collect and chunk only; print counts")
    args = ap.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    bad = [s for s in sources if s != "medlineplus" and s not in COLLECTORS]
    if bad:
        raise SystemExit(f"unknown source(s): {bad}")
    print("collecting:")
    pages, generated = collect(sources, DATA / "raw", args.xml)
    chunks = build_chunks(pages)
    per = Counter(c.get("source", "?") for c in chunks)
    print(f"{len(pages)} pages -> {len(chunks)} chunks  ({', '.join(f'{k} {v}' for k, v in per.items())})")
    if len(chunks) > MAX_CHUNKS:
        print(f"WARNING: {len(chunks)} chunks is over the spec's ~{MAX_CHUNKS:,}; every question scores every chunk.")
    if args.dry_run:
        return

    vecs = embed(chunks)
    version = args.corpus_version or f"{generated}.x{len(sources)}"
    m = write_artifacts(chunks, vecs, args.out, version)
    m["corpus_name"] = "Public-domain health library: " + ", ".join(ATTRIBUTION[s] for s in sources)
    m["attribution"] = "Sources: " + "; ".join(ATTRIBUTION[s] for s in sources)
    m["sources"] = {s: per.get(s, 0) for s in sources}
    (Path(args.out) / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    DATA.mkdir(exist_ok=True)
    np.save(DATA / f"embeddings_f32_{Path(args.out).name}.npy", vecs)  # data/ is not committed
    print(f"wrote {args.out}: corpus_version {version}, {len(chunks)} chunks, scale {m['quantization']['scale']}")


def embed(chunks):
    from common.embedding import embed_texts
    return embed_texts([c["embed_text"] for c in chunks])


if __name__ == "__main__":
    main()
