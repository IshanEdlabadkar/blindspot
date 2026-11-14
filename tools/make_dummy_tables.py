"""Write dummy score_table.bin, fetch_store.bin and manifest.json.

Stands in for B's real tables. Used by A and C until hour 5.

    python tools/make_dummy_tables.py --out data --n 5000
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import contracts as c  # noqa: E402


def sha(path):
    return "sha256:" + hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def main(out="data", n=5000, seed=0):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    table = rng.integers(-127, 128, size=(n, c.DIM), dtype=np.int8)
    table.tofile(out / "score_table.bin")  # N x 384 int8, row by row

    with open(out / "fetch_store.bin", "wb") as f:
        for i in range(n):
            f.write(c.pack_record({
                "id": i, "title": f"Chunk {i}", "url": f"https://example.org/{i}",
                "updated": "2026-01-01", "text": f"dummy text {i}",
            }))

    manifest = {
        "protocol": c.PROTOCOL,
        "corpus_version": "dummy.1",
        "corpus_name": "DUMMY random tables",
        "attribution": "Random data, not a real corpus",
        "embedding": {"model": c.EMBED_MODEL, "revision": c.EMBED_REVISION,
                      "dim": c.DIM, "normalize": "l2"},
        "quantization": {"type": "int8", "scale": c.QUANT_SCALE},
        "scoring": {"library": "<placeholder>", "params": "<placeholder>"},
        "pir": {"library": "<placeholder>", "params": "<placeholder>",
                "record_bytes": c.RECORD_BYTES},
        "num_chunks": n,
        "top_k": c.TOP_K,
        "hashes": {"score_table": sha(out / "score_table.bin"),
                   "fetch_store": sha(out / "fetch_store.bin")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {n} chunks to {out}/ (score_table.bin, fetch_store.bin, manifest.json)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data")
    p.add_argument("--n", type=int, default=5000)
    p.add_argument("--seed", type=int, default=0)
    main(**vars(p.parse_args()))
