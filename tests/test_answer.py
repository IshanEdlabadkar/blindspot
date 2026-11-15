import pytest

from client import answer as answer_mod
from client.answer import DECLINE_MESSAGE, DISCLAIMER, answer
from client.safety import CRISIS_MESSAGE, EMERGENCY_MESSAGE


@pytest.fixture(autouse=True)
def no_real_reranker(monkeypatch):
    """Unit tests keep retrieval order; the real cross-encoder is covered by the slow test."""
    monkeypatch.setattr(answer_mod, "_default_rerank", lambda q, chunks: list(chunks))


def test_reranker_order_decides_which_chunks_the_model_sees():
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        return "Fact seven [1]."

    def move_seven_first(q, chunks):
        return [chunks[7]] + [c for c in chunks if c["id"] != 7]

    r = answer("q?", CHUNKS, llm=llm, rerank=move_seven_first)
    assert "[1] T7" in seen["prompt"]
    assert r["status"] == "answered" and r["citations"][0]["id"] == 7


def test_score_threshold_uses_search_score_of_top_retrieved_chunk():
    chunks = [{**c, "score": 0.9 if c["id"] == 0 else 0.1} for c in CHUNKS]
    r = answer("q?", chunks, llm=lambda p: "Fact nine [1].", min_score=0.5,
               rerank=lambda q, cs: list(reversed(cs)))
    assert r["status"] == "answered"


@pytest.mark.slow
def test_real_reranker_puts_fractures_first_for_broken_shoulder():
    shoulder = {"id": 1, "title": "Dislocated Shoulder", "url": "u1", "updated": "d",
                "text": "A dislocated shoulder happens when the upper arm bone pops out of the socket."}
    fracture = {"id": 2, "title": "Fractures", "url": "u2", "updated": "d",
                "text": "A fracture is a broken bone. Symptoms include pain, swelling and a bone that looks out of place."}
    ranked = answer_mod.rerank_chunks("I think I broke a bone in my shoulder", [shoulder, fracture])
    assert ranked[0]["id"] == 2 and "rerank_score" in ranked[0]

CHUNKS = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"fact {i}",
           "score": 0.8 - i * 0.01} for i in range(10)]

A1C = {"id": 40, "title": "A1C", "url": "https://medlineplus.gov/a1c.html", "updated": "d", "score": 0.8,
       "text": "A1C is a blood test for type 2 diabetes. It measures your average blood sugar level over "
               "the past 3 months. Doctors may use the A1C alone or with other diabetes tests."}
KNEE = {"id": 41, "title": "Knee", "url": "u41", "updated": "d", "score": 0.7,
        "text": "Osteoarthritis is the most common disease affecting the knee. Cartilage wears away."}


def test_ollama_request_keeps_model_loaded_and_caps_length(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": " ok "}

    def fake_post(url, json, timeout):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(answer_mod.requests, "post", fake_post)
    assert answer_mod.ollama_generate("p") == "ok"
    assert sent["keep_alive"] == "30m"
    assert sent["options"] == {"temperature": 0, "num_predict": 256}


def test_answer_cites_renumbers_and_drops_bad_citations():
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        return "Fact three [3]. Fact one [1][3]. Bogus [9]."

    r = answer("q?", CHUNKS, llm=llm)
    assert r["status"] == "answered"
    assert [c["id"] for c in r["citations"]] == [0, 2]
    assert r["answer"].startswith("Fact three [2]. Fact one [1][2].")
    assert "Bogus" not in r["answer"]
    assert r["answer"].endswith(DISCLAIMER)
    assert "[5] T4" in seen["prompt"] and "[6]" not in seen["prompt"]
    assert "answer_ms" in r["timings"]
    assert r["urgent"] is None


def test_unsupported_sentence_is_removed_and_counted():
    out = ("A1C measures your average blood sugar over the past 3 months [1]. "
           "It also cures arthritis instantly [1].")
    r = answer("What does A1C measure?", [A1C, KNEE], llm=lambda p: out)
    assert r["status"] == "answered"
    assert "average blood sugar" in r["answer"] and "cures" not in r["answer"]
    assert r["checks"]["removed_sentences"] == 1


def test_citation_to_the_wrong_source_is_removed():
    r = answer("q?", [A1C, KNEE], llm=lambda p: "A1C measures your average blood sugar [2].")
    assert r["status"] == "declined"


def test_uncited_answer_declines_and_no_citation_is_invented():
    copied = "It measures your average blood sugar level over the past 3 months."
    r = answer("q?", [A1C, KNEE], llm=lambda p: copied)
    assert r["status"] == "declined"


def test_citation_written_after_the_period_belongs_to_that_sentence():
    r = answer("q?", [A1C, KNEE], llm=lambda p: "A1C measures average blood sugar. [1] Cartilage wears away. [2]")
    assert r["status"] == "answered"
    assert [c["id"] for c in r["citations"]] == [40, 41]
    assert r["answer"].startswith("A1C measures average blood sugar. [1] Cartilage wears away. [2]")


def test_citation_at_paragraph_end_covers_earlier_uncited_sentences_after_checking():
    out = ("A1C measures your average blood sugar. Doctors may use it with other diabetes tests. "
           "This leads to many unrelated outcomes [1].\n\nNO_ANSWER")
    r = answer("q?", [A1C, KNEE], llm=lambda p: out)
    assert r["status"] == "answered"
    assert r["answer"].startswith("A1C measures your average blood sugar. [1] Doctors may use it with other "
                                  "diabetes tests. [1]")
    assert "unrelated" not in r["answer"] and r["checks"]["removed_sentences"] == 1


def test_paragraph_citation_does_not_reach_into_another_paragraph():
    out = "A1C measures your average blood sugar.\n\nCartilage wears away [2]."
    r = answer("q?", [A1C, KNEE], llm=lambda p: out)
    assert "A1C" not in r["answer"].split(DISCLAIMER)[0]
    assert [c["id"] for c in r["citations"]] == [41]


def test_sentence_supported_by_its_cited_sources_together():
    # Neither source alone has half of these key terms; together they have nearly all.
    out = "Average blood sugar and worn cartilage in osteoarthritis knee [1][2]."
    r = answer("q?", [A1C, KNEE], llm=lambda p: out)
    assert r["status"] == "answered" and [c["id"] for c in r["citations"]] == [40, 41]


def test_each_citation_carries_its_supporting_excerpt():
    r = answer("q?", [A1C, KNEE], llm=lambda p: "It measures average blood sugar over 3 months [1].")
    assert r["citations"][0]["excerpt"] == "It measures your average blood sugar level over the past 3 months."


def test_cited_answer_followed_by_stray_no_answer_is_kept():
    r = answer("q?", CHUNKS, llm=lambda p: "Fact two is true [2].\n\nNO_ANSWER")
    assert r["status"] == "answered" and "NO_ANSWER" not in r["answer"]
    assert [c["id"] for c in r["citations"]] == [1]


def test_no_answer_from_model_declines_with_closest_passages():
    r = answer("q?", CHUNKS, llm=lambda p: "NO_ANSWER")
    assert r["status"] == "declined" and r["answer"].startswith(DECLINE_MESSAGE)
    assert [c["id"] for c in r["citations"]] == [0, 1, 2]


def test_low_retrieval_score_declines_without_calling_model():
    low = [{**c, "score": 0.1} for c in CHUNKS]

    def boom(p):
        raise AssertionError("model should not be called")

    assert answer("q?", low, llm=boom, min_score=0.5)["status"] == "declined"


def test_chunks_without_scores_skip_threshold():
    plain = [{k: v for k, v in c.items() if k != "score"} for c in CHUNKS]
    r = answer("q?", plain, llm=lambda p: "Fact zero [1].", min_score=0.99)
    assert r["status"] == "answered" and r["citations"][0]["score"] == 0.0


def test_crisis_question_shows_988_even_when_declined():
    r = answer("I keep having thoughts of ending my life", CHUNKS, llm=lambda p: "NO_ANSWER")
    assert r["status"] == "declined"
    assert r["urgent"] == {"kind": "crisis", "message": CRISIS_MESSAGE}
    assert r["answer"].startswith(CRISIS_MESSAGE)


def test_emergency_question_shows_911_before_the_answer():
    r = answer("I have crushing chest pain", CHUNKS, llm=lambda p: "Fact one [1].")
    assert r["status"] == "answered"
    assert r["answer"].startswith(EMERGENCY_MESSAGE)
    assert r["urgent"]["kind"] == "emergency"
