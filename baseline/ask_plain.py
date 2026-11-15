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
