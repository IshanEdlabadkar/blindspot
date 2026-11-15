"""Hour-0 contracts. Everything A, B and C must agree on lives here.

PROPOSED values are marked. Change them here once, in hour 0, and nowhere else.
"""
import json
import struct

PROTOCOL = "blind-rag/1"
DIM = 384
RECORD_BYTES = 2048
TOP_K = 10
QUANT_SCALE = 127

# PROPOSED: little-endian everywhere.
LEN_FMT = "<H"        # 2-byte record length prefix (B writes, A reads)
SCORE_DTYPE = "<i4"   # decrypted scores: N signed 32-bit integers

# Embedding: B's pinned model. B embeds chunks with it, C embeds questions.
# The manifest is the source of truth for scale and query prefix; these are the defaults.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # questions only

# PROPOSED wire format for /v1/score and /v1/fetch:
#   request : Content-Type application/octet-stream, body = ciphertext bytes,
#             header X-Corpus-Version = manifest["corpus_version"]
#   response: application/octet-stream, body = ciphertext bytes
#   stale version -> HTTP 409, client reloads the manifest and retries once
#   /v1/fetch takes ONE selector per request; the client always sends exactly k.
VERSION_HEADER = "X-Corpus-Version"

# Server log line: one JSON object per line, never a request body.
#   {"ts": "...Z", "endpoint": "/v1/score", "response_bytes": 20000, "latency_ms": 3.1}
LOG_FIELDS = ("ts", "endpoint", "response_bytes", "latency_ms")

CHUNK_FIELDS = ("id", "title", "url", "updated", "text")
CITATION_FIELDS = ("id", "title", "url", "text")

DISCLAIMER = "This tool gives information, not medical advice."
DECLINE_TEXT = "I could not find a reliable source for that. Here are the closest passages."


def pack_record(chunk: dict, L: int = RECORD_BYTES) -> bytes:
    """Chunk dict -> exactly L bytes: 2-byte length, JSON, zero padding."""
    body = json.dumps({k: chunk[k] for k in CHUNK_FIELDS}, ensure_ascii=False).encode("utf-8")
    if len(body) > L - 2:
        raise ValueError(f"chunk {chunk.get('id')} is {len(body)} bytes, max {L - 2}; split it")
    return struct.pack(LEN_FMT, len(body)) + body + b"\x00" * (L - 2 - len(body))


def unpack_record(blob: bytes) -> dict:
    """L bytes -> chunk dict."""
    (n,) = struct.unpack(LEN_FMT, blob[:2])
    return json.loads(blob[2:2 + n].decode("utf-8"))


def _cite(chunk: dict) -> dict:
    return {k: chunk.get(k) for k in CITATION_FIELDS}


def make_answer(text: str, chunks: list) -> dict:
    """The answer shape returned by ask(), ask_plain() and answer().

    B's answer() returns "status": "answered" | "declined"; the UI reads "declined".
    Both keys are always present (see normalize_result).
    """
    return {"status": "answered", "declined": False, "answer": text, "citations": [_cite(c) for c in chunks]}


def make_decline(closest: list, text: str = DECLINE_TEXT) -> dict:
    """Same shape; citations hold the closest passages to show instead."""
    return {"status": "declined", "declined": True, "answer": text, "citations": [_cite(c) for c in closest]}


def normalize_result(result: dict) -> dict:
    """Make any answer() result carry both "status" and "declined"."""
    declined = bool(result.get("declined", result.get("status") == "declined"))
    result["declined"] = declined
    result.setdefault("status", "declined" if declined else "answered")
    return result
