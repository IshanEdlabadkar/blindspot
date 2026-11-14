import pytest
from common.records import MAX_JSON_BYTES, RECORD_BYTES, pack_record, unpack_record

CHUNK = {"id": 7, "title": "Asthma", "url": "https://medlineplus.gov/asthma.html",
         "updated": "2026-11-13", "text": "Asthma is a chronic disease — café ✓"}


def test_round_trip():
    rec = pack_record(CHUNK)
    assert len(rec) == RECORD_BYTES
    assert unpack_record(rec) == CHUNK


def test_layout_is_little_endian_length_then_json_then_zeros():
    rec = pack_record(CHUNK)
    n = int.from_bytes(rec[:2], "little")
    assert rec[0] == n & 0xFF and rec[1] == n >> 8
    assert rec[2 + n:] == bytes(RECORD_BYTES - 2 - n)
    assert rec[2:2 + n].startswith(b'{"id":7,"title":"Asthma"')


def test_extra_keys_are_dropped():
    assert unpack_record(pack_record({**CHUNK, "embed_text": "x"})) == CHUNK


def test_too_long_raises():
    with pytest.raises(ValueError):
        pack_record({**CHUNK, "text": "x" * MAX_JSON_BYTES})
