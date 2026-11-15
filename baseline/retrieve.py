"""Plaintext top-k over the same tables Blindspot uses. int8 mode ranks exactly as Blindspot will.

PlainIndex covers one source (one document server). MultiIndex fans out over several, following the
multi-source privacy rules: every source is always queried and always returns exactly k chunks.
"""
from pathlib import Path

import numpy as np

from common.embedding import ARTIFACTS, embed_query_float, quantize
from common.tables import get_record, load_artifacts


class PlainIndex:
    def __init__(self, artifacts_dir=ARTIFACTS, float_path=None):
        self.manifest, table, self.store = load_artifacts(artifacts_dir)
        self.source = self.manifest.get("source_id", "medlineplus")
        self.source_name = self.manifest.get("source_name", "MedlinePlus (National Library of Medicine)")
        self.scale = float(self.manifest["quantization"]["scale"])
        self.table32 = table.astype(np.int32)
        self.float_vecs = np.load(float_path) if float_path and Path(float_path).exists() else None

    def search_vec(self, qvec: np.ndarray, k: int = 10, mode: str = "int8") -> list[tuple[int, float]]:
        if mode == "int8":
            raw = self.table32 @ quantize(qvec, self.scale).astype(np.int32)
            scores = raw / (self.scale * self.scale)
        elif mode == "float":
            if self.float_vecs is None:
                raise ValueError("float mode needs float_path (data/embeddings_*.npy)")
            scores = self.float_vecs @ qvec
        else:
            raise ValueError(f"unknown mode {mode!r}")
        top = np.argsort(-scores, kind="stable")[:k]
        return [(int(i), float(scores[i])) for i in top]

    def search(self, question: str, k: int = 10, mode: str = "int8") -> list[tuple[int, float]]:
        return self.search_vec(embed_query_float(question), k, mode)

    def chunks(self, hits: list[tuple[int, float]]) -> list[dict]:
        return [{**get_record(self.store, i), "score": s, "source": self.source, "source_name": self.source_name}
                for i, s in hits]

    def fetch(self, qvec: np.ndarray, k: int = 10, mode: str = "int8") -> list[dict]:
        return self.chunks(self.search_vec(qvec, k, mode))


def discover_sources(root=ARTIFACTS) -> list[Path]:
    """Source folders under root: subfolders holding a manifest.json, sorted by name."""
    return sorted(p.parent for p in Path(root).glob("*/manifest.json"))


class MultiIndex:
    def __init__(self, dirs: list[Path], float_paths: dict[str, Path] | None = None):
        self.indexes = []
        for d in dirs:
            idx = PlainIndex(d)
            fp = (float_paths or {}).get(idx.source)
            if fp and Path(fp).exists():
                idx.float_vecs = np.load(fp)
            self.indexes.append(idx)
        self.sources = [i.source for i in self.indexes]

    def fetch(self, qvec: np.ndarray, k: int = 10, mode: str = "int8") -> list[dict]:
        """Exactly k chunks from every source, merged by score (highest first)."""
        merged = [c for idx in self.indexes for c in idx.fetch(qvec, k, mode)]
        return sorted(merged, key=lambda c: -c["score"])
