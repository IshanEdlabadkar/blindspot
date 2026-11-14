"""Fixed-size fetch-store records (docs/contracts.md section 1)."""
import json

RECORD_BYTES = 2048
MAX_JSON_BYTES = RECORD_BYTES - 2
FIELDS = ("id", "title", "url", "updated", "text")


def encode_chunk(chunk: dict) -> bytes:
    obj = {k: chunk[k] for k in FIELDS}
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pack_record(chunk: dict) -> bytes:
    body = encode_chunk(chunk)
    if len(body) > MAX_JSON_BYTES:
        raise ValueError(f"chunk {chunk['id']} JSON is {len(body)} bytes; max is {MAX_JSON_BYTES}")
    return len(body).to_bytes(2, "big") + body + bytes(MAX_JSON_BYTES - len(body))


def unpack_record(rec: bytes) -> dict:
    if len(rec) != RECORD_BYTES:
        raise ValueError(f"record is {len(rec)} bytes; expected {RECORD_BYTES}")
    n = int.from_bytes(rec[:2], "big")
    return json.loads(rec[2:2 + n].decode("utf-8"))
