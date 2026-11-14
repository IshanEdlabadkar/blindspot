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
