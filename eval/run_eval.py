"""Retrieval recall (float vs int8) and answer outcomes over eval/questions.jsonl."""
import argparse
import csv
import json
from pathlib import Path

from baseline.ask_plain import ask_plain, default_index
from common.embedding import embed_query_float

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
KS = (1, 5, 10, 20)


def first_rank(urls: list[str], gold: str) -> int | None:
    return next((i for i, u in enumerate(urls, 1) if u == gold), None)


def recall_table(ranks: list[int | None], ks=KS) -> dict[int, float]:
    return {k: sum(r is not None and r <= k for r in ranks) / len(ranks) for k in ks}


def load_questions() -> list[dict]:
    lines = (ROOT / "eval" / "questions.jsonl").read_text().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def run_retrieval(questions: list[dict]) -> list[dict]:
    idx = default_index()
    rows = []
    for q in questions:
        qvec = embed_query_float(q["question"])
        row = {"question": q["question"], "gold": q["source_url"]}
        for mode in ("float", "int8"):
            hits = idx.search_vec(qvec, max(KS), mode)
            urls = [c["url"] for c in idx.chunks(hits)]
            row[f"{mode}_rank"] = first_rank(urls, q["source_url"]) if q["source_url"] else None
            row[f"{mode}_top1"] = round(hits[0][1], 4)
        rows.append(row)
    return rows


def run_answers(questions: list[dict]) -> list[dict]:
    out = []
    for q in questions:
        r = ask_plain(q["question"])
        cited = [c["url"] for c in r["citations"]] if r["status"] == "answered" else []
        out.append({**q, "status": r["status"],
                    "gold_cited": q["source_url"] in cited if q["source_url"] else None,
                    "answer": r["answer"], "cited": cited, "timings": r["timings"], "grade": ""})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--answers", action="store_true", help="also run ask_plain with the local model")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    questions = load_questions()

    rows = run_retrieval(questions)
    with open(RESULTS / "retrieval.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    pos = [r for r in rows if r["gold"]]
    neg = [r for r in rows if not r["gold"]]
    print(f"Recall over {len(pos)} answerable questions")
    print("mode   " + "  ".join(f"@{k:<4}" for k in KS))
    for mode in ("float", "int8"):
        rec = recall_table([r[f"{mode}_rank"] for r in pos])
        print(f"{mode:6} " + "  ".join(f"{rec[k]:.2f} " for k in KS))
    print(f"int8 top-1 score: answerable min {min(r['int8_top1'] for r in pos):.3f}, "
          f"unanswerable max {max(r['int8_top1'] for r in neg):.3f}")

    if args.answers:
        out = run_answers(questions)
        with open(RESULTS / "answers.jsonl", "w") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        ans = [r for r in out if r["source_url"]]
        un = [r for r in out if not r["source_url"]]
        print(f"Answerable: {sum(r['status'] == 'answered' for r in ans)}/{len(ans)} answered, "
              f"{sum(bool(r['gold_cited']) for r in ans)} cite the right page")
        print(f"Unanswerable: {sum(r['status'] == 'declined' for r in un)}/{len(un)} declined")
        ms = sorted(sum(r["timings"].values()) for r in out)
        print(f"Median latency {ms[len(ms) // 2] / 1000:.1f} s")


if __name__ == "__main__":
    main()
