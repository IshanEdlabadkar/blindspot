from common.records import MAX_JSON_BYTES, encode_chunk
from ingest.chunk import chunk_page


def page(sections, also=()):
    return {"title": "T", "url": "u", "updated": "2026-11-13", "also_called": list(also), "sections": sections}


def words(prefix, n):
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_short_page_is_one_chunk_with_heading_lines():
    chunks = chunk_page(page([(None, ["Intro text."]), ("Symptoms", ["- Cough"])], also=["A", "B"]))
    assert len(chunks) == 1
    assert chunks[0]["text"] == "Intro text.\nSymptoms\n- Cough"
    assert chunks[0]["embed_text"].startswith("T (also called: A, B)\n")


def test_long_page_respects_word_limit_and_overlaps():
    paras = [words(f"p{j}w", 100) for j in range(6)]
    chunks = chunk_page(page([(None, paras)]), max_words=250, overlap=40)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c["text"].split()) <= 250
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-40:] == second[:40]


def test_one_huge_paragraph_is_split():
    chunks = chunk_page(page([(None, [words("w", 1000)])]))
    assert all(len(c["text"].split()) <= 250 for c in chunks)
    assert {"w0", "w999"} <= set(" ".join(c["text"] for c in chunks).split())


def test_every_chunk_fits_a_record_even_with_long_words():
    chunks = chunk_page(page([(None, [" ".join(["x" * 30] * 200)])]))
    assert len(chunks) > 1
    for c in chunks:
        assert len(encode_chunk({**c, "id": 999999})) <= MAX_JSON_BYTES
