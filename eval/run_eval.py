"""Evaluate retrieval and answers over eval/questions.jsonl, for any pipeline.

  uv run python -m eval.run_eval                                   # retrieval only (plaintext tables)
  uv run python -m eval.run_eval --answers                         # + answers through plaintext ask_plain
  uv run python -m eval.run_eval --pipeline client.pipeline:Pipeline   # + answers through C's encrypted path

--pipeline takes module:function (returns the answer shape, or (answer, trace)) or module:Class (its
ask_traced method is used). Every pipeline writes the same row format, keyed by question id, to
eval/results/answers_<name>.jsonl and summary_<name>.json, so runs can be compared row by row.
"""
import argparse
import csv
import importlib
import json
import statistics
import time
from pathlib import Path

from baseline.ask_plain import ask_plain, default_index
from client.answer import N_CONTEXT, rerank_chunks
from common.embedding import embed_query_float

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
KS = (1, 5, 10, 20)
PLAINTEXT = "baseline.ask_plain:ask_plain"


def first_rank(urls: list[str], gold: str) -> int | None:
    return next((i for i, u in enumerate(urls, 1) if u == gold), None)


def recall_table(ranks: list[int | None], ks=KS) -> dict[int, float]:
    return {k: sum(r is not None and r <= k for r in ranks) / len(ranks) for k in ks}


def load_questions(path: Path | None = None) -> list[dict]:
    lines = (path or ROOT / "eval" / "questions.jsonl").read_text().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


# ---------------------------------------------------------------- retrieval (plaintext tables)

def run_retrieval(questions: list[dict]) -> list[dict]:
    """Per question: rank of the right page (float, int8), the int8 top-10 ids (the ranking the encrypted
    path must reproduce exactly), and whether the right page reaches the model's sources."""
    idx = default_index()
    # The float comparison (quantization cost) needs B's local data/embeddings_f32.npy, which is not in
    # git. Without it, report int8 only; the answer evaluation uses the int8 ranking either way.
    modes = ("float", "int8") if idx.float_vecs is not None else ("int8",)
    if idx.float_vecs is None:
        print("note: data/embeddings_f32.npy not found (made by ingest/build.py); skipping the float comparison")
    rows = []
    for q in questions:
        qvec = embed_query_float(q["question"])
        gold = q["source_url"]
        row = {"id": q["id"], "question": q["question"], "gold": gold}
        row["float_rank"] = row["float_top1"] = None
        for mode in modes:
            hits = idx.search_vec(qvec, max(KS), mode)
            urls = [c["url"] for c in idx.chunks(hits)]
            row[f"{mode}_rank"] = first_rank(urls, gold) if gold else None
            row[f"{mode}_top1"] = round(hits[0][1], 4)
        hits10 = idx.search_vec(qvec, 10, "int8")
        row["int8_top10_ids"] = [i for i, _ in hits10]
        fetched = idx.chunks(hits10)
        reranked = rerank_chunks(q["question"], fetched)
        row["evidence_top5"] = any(c["url"] == gold for c in fetched[:N_CONTEXT]) if gold else None
        row["evidence_rerank5"] = any(c["url"] == gold for c in reranked[:N_CONTEXT]) if gold else None
        rows.append(row)
    return rows


# ---------------------------------------------------------------- answers (any pipeline)

def _resolve(spec: str):
    module, _, attr = spec.partition(":")
    obj = importlib.import_module(module)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def load_pipeline(spec: str):
    """module:function or module:Class -> callable(question) -> (answer, trace or None)."""
    if ":" not in spec:
        raise ValueError(f"--pipeline must look like module:function or module:Class, got {spec!r}")
    target = _resolve(spec)
    if isinstance(target, type):
        instance = target()
        return lambda q: instance.ask_traced(q)

    def call(q):
        out = target(q)
        return out if isinstance(out, tuple) else (out, None)
    return call


def run_answers(questions: list[dict], ask, reference_ids: dict[str, list[int]] | None = None,
                on_row=None) -> list[dict]:
    """on_row(row) is called as each question finishes, so a crash mid-run keeps what was done."""
    rows = []
    for q in questions:
        t0 = time.perf_counter()
        result, trace = ask(q["question"])
        wall = time.perf_counter() - t0
        trace = trace or {}
        answered = result["status"] == "answered"
        cited = [c["url"] for c in result["citations"]] if answered else []
        top_ids = trace.get("top_ids")
        ref = (reference_ids or {}).get(q["id"])
        rows.append({
            "id": q["id"], "question": q["question"], "category": q.get("category"),
            "expect": q["expect"], "source_url": q["source_url"], "status": result["status"],
            "behaved": answered == (q["expect"] == "answer"),
            "gold_cited": (q["source_url"] in cited) if q["source_url"] else None,
            "urgent_expected": q.get("urgent"), "urgent": (result.get("urgent") or {}).get("kind"),
            "removed_sentences": (result.get("checks") or {}).get("removed_sentences", 0),
            "cited": cited, "answer": result["answer"],
            "top_ids": top_ids,
            "agrees_with_plaintext": (top_ids == ref) if top_ids is not None and ref is not None else None,
            "upload_bytes": trace.get("upload_bytes"), "download_bytes": trace.get("download_bytes"),
            "mode": trace.get("mode"),
            "seconds": round(trace.get("total_seconds", wall), 3),
            "timings": result.get("timings", {}),
            "grade": "",
        })
        if on_row:
            on_row(rows[-1])
    return rows


def _frac(n: int, d: int) -> str:
    return f"{n}/{d}"


def summarize(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["expect"] == "answer"]
    dec = [r for r in rows if r["expect"] == "decline"]
    agree = [r for r in rows if r["agrees_with_plaintext"] is not None]
    secs = sorted(r["seconds"] for r in rows)
    up = [r["upload_bytes"] for r in rows if r.get("upload_bytes") is not None]
    down = [r["download_bytes"] for r in rows if r.get("download_bytes") is not None]
    return {
        "questions": len(rows),
        "answered": _frac(sum(r["status"] == "answered" for r in ans), len(ans)),
        "right_page_cited": _frac(sum(bool(r["gold_cited"]) for r in ans), len(ans)),
        "declined_out_of_scope": _frac(sum(r["status"] == "declined" for r in dec), len(dec)),
        "behaved_as_expected": _frac(sum(r["behaved"] for r in rows), len(rows)),
        "urgent_notice_correct": _frac(sum(r["urgent"] == r["urgent_expected"] for r in rows), len(rows)),
        "agreement_with_plaintext": _frac(sum(r["agrees_with_plaintext"] for r in agree), len(agree)) if agree else None,
        "sentences_removed": sum(r["removed_sentences"] for r in rows),
        "median_seconds": round(statistics.median(secs), 2) if secs else None,
        "p95_seconds": round(secs[min(len(secs) - 1, int(0.95 * len(secs)))], 2) if secs else None,
        "median_upload_bytes": statistics.median(up) if up else None,
        "median_download_bytes": statistics.median(down) if down else None,
    }


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", action="store_true", help="run answers through the plaintext pipeline")
    ap.add_argument("--pipeline", help="module:function or module:Class to evaluate (implies answers)")
    ap.add_argument("--name", help="label for result files (default: derived from the pipeline)")
    ap.add_argument("--questions", type=Path, help="questions file (default eval/questions.jsonl)")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    questions = load_questions(args.questions)

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
        if mode == "float" and all(r["float_top1"] is None for r in rows):
            print("float  (skipped: no data/embeddings_f32.npy)")
            continue
        rec = recall_table([r[f"{mode}_rank"] for r in pos])
        print(f"{mode:6} " + "  ".join(f"{rec[k]:.2f} " for k in KS))
    for key, label in (("evidence_top5", "search order"), ("evidence_rerank5", "after rerank")):
        print(f"Right page among the model's {N_CONTEXT} sources ({label}): {sum(r[key] for r in pos)}/{len(pos)}")
    if neg:
        print(f"int8 top-1 score: answerable min {min(r['int8_top1'] for r in pos):.3f}, "
              f"unanswerable max {max(r['int8_top1'] for r in neg):.3f}")

    spec = args.pipeline or (PLAINTEXT if args.answers else None)
    if not spec:
        return
    name = args.name or ("plaintext" if spec == PLAINTEXT else spec.replace(":", ".").split(".")[-2])
    reference = {r["id"]: r["int8_top10_ids"] for r in rows}
    if spec == PLAINTEXT:  # the plaintext path ranks with the same int8 tables, so record its top-10 too
        ask = lambda q: (ask_plain(q), {"top_ids": reference_for(q)})
        by_question = {r["question"]: r["int8_top10_ids"] for r in rows}
        reference_for = by_question.get
    else:
        ask = load_pipeline(spec)
    with open(RESULTS / f"answers_{name}.jsonl", "w") as f:
        def save(r):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  {r['id']} {r['seconds']:6.1f}s {r['status']:9} {'ok ' if r['behaved'] else 'MISS'} "
                  f"{r['question'][:60]}", flush=True)
        out = run_answers(questions, ask, reference, on_row=save)
    summary = {"pipeline": spec, **summarize(out)}
    (RESULTS / f"summary_{name}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nAnswers via {spec}")
    for k, v in summary.items():
        if k != "pipeline" and v is not None:
            print(f"  {k:26} {v}")


if __name__ == "__main__":
    main()
