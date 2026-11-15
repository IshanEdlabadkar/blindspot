from client import answer as answer_mod
from client.answer import DECLINE_MESSAGE, DISCLAIMER, answer


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

CHUNKS = [{"id": i, "title": f"T{i}", "url": f"u{i}", "updated": "d", "text": f"fact {i}",
           "score": 0.8 - i * 0.01} for i in range(10)]


def test_answer_cites_and_renumbers():
    seen = {}

    def llm(prompt):
        seen["prompt"] = prompt
        return "Fact three [3]. Fact one [1][3]. Bogus [9]."

    r = answer("q?", CHUNKS, llm=llm)
    assert r["status"] == "answered"
    assert [c["id"] for c in r["citations"]] == [0, 2]
    assert r["answer"].startswith("Fact three [2]. Fact one [1][2]. Bogus .")
    assert r["answer"].endswith(DISCLAIMER)
    assert "[5] T4" in seen["prompt"] and "[6]" not in seen["prompt"]
    assert "answer_ms" in r["timings"]


def test_no_answer_from_model_declines_with_closest_passages():
    r = answer("q?", CHUNKS, llm=lambda p: "NO_ANSWER")
    assert r["status"] == "declined" and r["answer"].startswith(DECLINE_MESSAGE)
    assert [c["id"] for c in r["citations"]] == [0, 1, 2]


def test_uncited_unsupported_answer_declines():
    assert answer("q?", CHUNKS, llm=lambda p: "Some unsupported text.")["status"] == "declined"


def test_cited_answer_followed_by_stray_no_answer_is_kept():
    r = answer("q?", CHUNKS, llm=lambda p: "Fact two is true [2].\n\nNO_ANSWER")
    assert r["status"] == "answered" and "NO_ANSWER" not in r["answer"]
    assert [c["id"] for c in r["citations"]] == [1]


def test_uncited_answer_grounded_in_one_source_cites_it():
    chunks = [{**CHUNKS[0], "text": "Unrelated passage about taxes."},
              {**CHUNKS[1], "text": "Call or text the 988 Suicide and Crisis Lifeline for help right away."}]
    r = answer("q?", chunks, llm=lambda p: "Call or text the 988 Suicide and Crisis Lifeline right away.")
    assert r["status"] == "answered"
    assert [c["id"] for c in r["citations"]] == [1]
    assert r["answer"].startswith("Call or text the 988 Suicide and Crisis Lifeline right away. [1]")


def test_low_retrieval_score_declines_without_calling_model():
    low = [{**c, "score": 0.1} for c in CHUNKS]

    def boom(p):
        raise AssertionError("model should not be called")

    assert answer("q?", low, llm=boom, min_score=0.5)["status"] == "declined"


def test_chunks_without_scores_skip_threshold():
    plain = [{k: v for k, v in c.items() if k != "score"} for c in CHUNKS]
    r = answer("q?", plain, llm=lambda p: "Yes [1].", min_score=0.99)
    assert r["status"] == "answered" and r["citations"][0]["score"] == 0.0
