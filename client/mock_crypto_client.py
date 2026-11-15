"""MOCK of A's crypto_client: the same five functions, no encryption. NOT PRIVATE."""
import struct

import numpy as np

import contracts as c

IS_MOCK = True


def keygen(manifest=None) -> bytes:
    return b""


def encrypt_query(key, int8_vec) -> bytes:
    return np.asarray(int8_vec, dtype=np.int8).tobytes()


def decrypt_scores(key, blob: bytes):
    return np.frombuffer(blob, dtype=c.SCORE_DTYPE)


def make_selector(key, index: int, N: int) -> bytes:
    return struct.pack("<I", int(index))


def decrypt_record(key, blob: bytes) -> bytes:
    return blob
