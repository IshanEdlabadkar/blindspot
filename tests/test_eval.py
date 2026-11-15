import json
from pathlib import Path
from eval.run_eval import first_rank, recall_table

ROOT = Path(__file__).resolve().parent.parent


def test_first_rank_and_recall():
    assert first_rank(["a", "b", "b"], "b") == 2
    assert first_rank(["a"], "z") is None
    assert recall_table([1, 3, None, 12], ks=(1, 5, 20)) == {1: 0.25, 5: 0.5, 20: 0.75}


def test_every_gold_url_is_in_the_corpus():
    urls = {json.loads(l)["url"] for l in (ROOT / "artifacts/chunks.jsonl").read_text().splitlines()}
    qs = [json.loads(l) for l in (ROOT / "eval/questions.jsonl").read_text().splitlines() if l.strip()]
    assert len(qs) >= 25
    missing = [q["source_url"] for q in qs if q["source_url"] and q["source_url"] not in urls]
    assert not missing
