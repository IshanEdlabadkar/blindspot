"""B6: calibrate the score threshold in client.answer.MIN_SCORE on the tune split, report on test.

The threshold acts before the model: if the top search score is below it, answer() declines without
asking the model. So any threshold at or above the one used in the run can be simulated from one run:
a question is declined if its top score is below the threshold, otherwise it keeps the run's outcome.

  uv run python -m eval.calibrate            # needs eval/results/answers_plaintext.jsonl and retrieval.csv
"""
import csv
import json
from pathlib import Path

from client.answer import MIN_SCORE

RESULTS = Path(__file__).resolve().parent / "results"
QUESTIONS = Path(__file__).resolve().parent / "questions.jsonl"
WRONG_ANSWER_COST = 2  # an answer where the system should have declined is worse than a false decline


def sweep(rows: list[dict], thresholds: list[float], split: str) -> list[dict]:
    """rows: expect, status (from a run at a lower threshold), top1 score, split."""
    part = [r for r in rows if r["split"] == split]
    ans = [r for r in part if r["expect"] == "answer"]
    dec = [r for r in part if r["expect"] == "decline"]
    out = []
    for t in thresholds:
        answered = lambda r: r["status"] == "answered" and r["top1"] >= t
        out.append({"threshold": t, "split": split,
                    "false_declines": sum(not answered(r) for r in ans), "of_answerable": len(ans),
                    "wrong_answers": sum(answered(r) for r in dec), "of_unanswerable": len(dec)})
    return out


def choose_threshold(table: list[dict]) -> dict:
    return min(table, key=lambda r: (WRONG_ANSWER_COST * r["wrong_answers"] + r["false_declines"],
                                     r["wrong_answers"], r["threshold"]))


def load_rows() -> list[dict]:
    split = {q["id"]: q["split"] for q in map(json.loads, QUESTIONS.read_text().splitlines()) if q}
    top1 = {r["id"]: float(r["int8_top1"]) for r in csv.DictReader(open(RESULTS / "retrieval.csv"))}
    answers = [json.loads(l) for l in (RESULTS / "answers_plaintext.jsonl").read_text().splitlines() if l]
    return [{"expect": a["expect"], "status": a["status"], "top1": top1[a["id"]], "split": split[a["id"]]}
            for a in answers]


def main():
    rows = load_rows()
    thresholds = [round(MIN_SCORE + 0.01 * i, 2) for i in range(0, 21)]
    tune = sweep(rows, thresholds, "tune")
    best = choose_threshold(tune)
    test = {r["threshold"]: r for r in sweep(rows, thresholds, "test")}
    lines = ["threshold,split,false_declines,of_answerable,wrong_answers,of_unanswerable"]
    print(f"{'threshold':>9}  {'tune: false declines':>20}  {'tune: wrong answers':>19}")
    for r in tune:
        mark = "  <- chosen" if r is best else ""
        print(f"{r['threshold']:9.2f}  {r['false_declines']:>13}/{r['of_answerable']:<6}  "
              f"{r['wrong_answers']:>12}/{r['of_unanswerable']:<6}{mark}")
    for r in tune + list(test.values()):
        lines.append(",".join(str(r[k]) for k in ("threshold", "split", "false_declines", "of_answerable",
                                                   "wrong_answers", "of_unanswerable")))
    (RESULTS / "calibration.csv").write_text("\n".join(lines) + "\n")
    held = test[best["threshold"]]
    current = test[thresholds[0]]
    print(f"\nChosen on tune: {best['threshold']:.2f}. On the unseen test split:")
    print(f"  at {best['threshold']:.2f}: {held['false_declines']}/{held['of_answerable']} false declines, "
          f"{held['wrong_answers']}/{held['of_unanswerable']} wrong answers")
    print(f"  at {thresholds[0]:.2f} (current): {current['false_declines']}/{current['of_answerable']} false declines, "
          f"{current['wrong_answers']}/{current['of_unanswerable']} wrong answers")


if __name__ == "__main__":
    main()
