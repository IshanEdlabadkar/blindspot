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
