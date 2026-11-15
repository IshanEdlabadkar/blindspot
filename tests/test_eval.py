import json
from pathlib import Path

import pytest

from eval.run_eval import first_rank, load_pipeline, recall_table, run_answers, summarize

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = [json.loads(l) for l in (ROOT / "eval/questions.jsonl").read_text().splitlines() if l.strip()]


def test_first_rank_and_recall():
    assert first_rank(["a", "b", "b"], "b") == 2
    assert first_rank(["a"], "z") is None
    assert recall_table([1, 3, None, 12], ks=(1, 5, 20)) == {1: 0.25, 5: 0.5, 20: 0.75}


def test_questions_are_well_formed_and_gold_urls_exist():
    urls = {json.loads(l)["url"] for l in (ROOT / "artifacts/chunks.jsonl").read_text().splitlines()}
    assert len(QUESTIONS) >= 25
    assert len({q["id"] for q in QUESTIONS}) == len(QUESTIONS)
    for q in QUESTIONS:
        assert q["expect"] in ("answer", "decline") and q["urgent"] in (None, "crisis", "emergency")
        assert (q["source_url"] is None) == (q["expect"] == "decline"), q["id"]
        assert q["source_url"] is None or q["source_url"] in urls, q["id"]


def fake_answer(question):
    return {"status": "answered", "answer": "a", "urgent": None, "checks": {"removed_sentences": 0},
            "citations": [{"id": 3, "title": "T", "url": "u3", "updated": "d", "text": "t", "score": 0.7}],
            "timings": {"answer_ms": 1000.0}}


class FakePipeline:
    def ask_traced(self, question):
        return fake_answer(question), {"top_ids": [3, 4, 5], "upload_bytes": 100, "download_bytes": 2000,
                                       "total_seconds": 2.5, "mode": {"crypto": "real"}}


def test_load_pipeline_accepts_a_function_or_a_class(monkeypatch):
    import eval.run_eval as mod
    monkeypatch.setattr(mod, "_resolve", lambda spec: {"m:f": fake_answer, "m:C": FakePipeline}[spec])
    result, trace = load_pipeline("m:f")("q")
    assert result["status"] == "answered" and trace is None
    result, trace = load_pipeline("m:C")("q")
    assert trace["top_ids"] == [3, 4, 5]


def test_load_pipeline_resolves_module_paths():
    fn = load_pipeline("baseline.ask_plain:ask_plain")
    assert callable(fn)
    with pytest.raises(ValueError):
        load_pipeline("no-colon")


def test_run_answers_keeps_ids_and_records_agreement_and_bytes():
    qs = [{"id": "q1", "question": "x", "source_url": "u3", "category": "basic", "expect": "answer", "urgent": None},
          {"id": "q2", "question": "y", "source_url": None, "category": "out_of_scope", "expect": "decline",
           "urgent": None}]
    rows = run_answers(qs, lambda q: FakePipeline().ask_traced(q), reference_ids={"q1": [3, 4, 5], "q2": [9, 8, 7]})
    assert [r["id"] for r in rows] == ["q1", "q2"]
    assert rows[0]["gold_cited"] is True and rows[0]["behaved"] is True
    assert rows[1]["behaved"] is False  # expected a decline, got an answer
    assert rows[0]["agrees_with_plaintext"] is True and rows[1]["agrees_with_plaintext"] is False
    assert rows[0]["upload_bytes"] == 100 and rows[0]["seconds"] == 2.5


def test_summarize_counts_with_denominators():
    rows = [{"expect": "answer", "status": "answered", "gold_cited": True, "behaved": True, "seconds": 2.0,
             "urgent_expected": None, "urgent": None, "agrees_with_plaintext": True, "removed_sentences": 1},
            {"expect": "answer", "status": "declined", "gold_cited": False, "behaved": False, "seconds": 4.0,
             "urgent_expected": "crisis", "urgent": "crisis", "agrees_with_plaintext": None, "removed_sentences": 0},
            {"expect": "decline", "status": "declined", "gold_cited": None, "behaved": True, "seconds": 6.0,
             "urgent_expected": None, "urgent": None, "agrees_with_plaintext": True, "removed_sentences": 0}]
    s = summarize(rows)
    assert s["answered"] == "1/2" and s["right_page_cited"] == "1/2" and s["declined_out_of_scope"] == "1/1"
    assert s["urgent_notice_correct"] == "3/3" and s["agreement_with_plaintext"] == "2/2"
    assert s["median_seconds"] == 4.0 and s["sentences_removed"] == 1
