"""Device-side crypto for Blind RAG. Owner: Person A.

Contract for C's pipeline.py. The secret key lives only in the returned
Session object (memory only, never written or sent). C's mock implements the
same functions without encryption.

Flow for one question:
    sess, token = keygen(manifest)                 # can run while user types
    q_blob = encrypt_query(sess, int8_vec)
    -> POST /v1/score  {token, q_blob}  <- {token_answer, score_blob}
    scores = decrypt_scores(sess, token_answer, score_blob)
    for idx in top_k:
        sel = make_selector(sess, idx, n)
    -> POST /v1/fetch  {token, selectors}  <- {token_answer, record_blobs}
    record = decrypt_record(sess, token_answer, record_blob)   # exactly L bytes
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Session:
    """Opaque per-question secret state. Do not persist or log."""
    manifest: dict
    _handle: object = field(default=None, repr=False)


def keygen(manifest: dict) -> tuple[Session, bytes]:
    """Fresh secret key. Returns the session and the token blob to upload."""
    raise NotImplementedError


def encrypt_query(sess: Session, int8_vec: bytes) -> bytes:
    """d int8 values (bytes of length d) -> query ciphertext."""
    raise NotImplementedError


def decrypt_scores(sess: Session, token_answer: bytes, blob: bytes) -> list[int]:
    """Server's score ciphertext -> N signed integer scores."""
    raise NotImplementedError


def make_selector(sess: Session, index: int, n: int) -> bytes:
    """Encrypted one-hot selector for chunk `index` out of `n`."""
    raise NotImplementedError


def decrypt_record(sess: Session, token_answer: bytes, blob: bytes) -> bytes:
    """Server's record ciphertext -> exactly L bytes (length prefix + JSON + padding)."""
    raise NotImplementedError
