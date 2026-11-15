"""Embed and quantize the question exactly as the manifest says.

BLIND_RAG_EMBED=real (default) uses the pinned sentence-transformers model.
BLIND_RAG_EMBED=fake uses a deterministic hash embedding: no download, fine on
the dummy tables where retrieval is meaningless anyway.
"""
import hashlib
import os

import numpy as np

import contracts as c

_model = None


def mode() -> str:
    return os.environ.get("BLIND_RAG_EMBED", "real")


def _fake(text: str) -> np.ndarray:
    v = np.zeros(c.DIM, dtype=np.float32)
    for tok in text.lower().split() or [""]:
        seed = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "little")
        v += np.random.default_rng(seed).standard_normal(c.DIM).astype(np.float32)
    return v


def embed(text: str, prefix: str = c.QUERY_PREFIX) -> np.ndarray:
    """Question -> 384 float32, L2-normalized. The prefix goes on questions only."""
    global _model
    if mode() == "fake":
        v = _fake(text)
    else:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(c.EMBED_MODEL, revision=c.EMBED_REVISION, device="cpu")
        v = np.asarray(_model.encode(prefix + text), dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def quantize(vec: np.ndarray, scale: float = c.QUANT_SCALE) -> np.ndarray:
    """Same formula as B's common/embedding.quantize: clip to int8 range whatever the scale."""
    return np.clip(np.rint(vec * scale), -127, 127).astype(np.int8)


def warm():
    embed("warm up")
