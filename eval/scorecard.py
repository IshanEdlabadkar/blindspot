"""B7: build eval/results/scorecard.csv and scorecard.md from the latest eval results.

  uv run python -m eval.scorecard            # after eval.run_eval --answers and eval.calibrate

Every number carries its denominator. Encrypted-path rows stay "pending" until summary_pipeline.json
exists (eval.run_eval --pipeline client.pipeline:Pipeline).
"""
import csv
import json
import subprocess
from collections import defaultdict
from pathlib import Path

from client.answer import MIN_SCORE, MODEL, N_CONTEXT, RERANK_MODEL
from client.safety import urgent_notice
from common.embedding import MODEL_NAME

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"


def _frac(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def build(retrieval: list[dict], answers: list[dict], questions: list[dict], encrypted: dict | None) -> list[tuple]:
    pos = [r for r in retrieval if r["gold"]]
    rank = lambda r: int(r["int8_rank"]) if r["int8_rank"] else None
    frank = lambda r: int(r["float_rank"]) if r["float_rank"] else None
    ans = [a for a in answers if a["expect"] == "answer"]
    dec = [a for a in answers if a["expect"] == "decline"]
    urgent_now = sum(q["urgent"] == (urgent_notice(q["question"]) or [None])[0] for q in questions)
    secs = sorted(a["seconds"] for a in answers)
    p95 = secs[min(len(secs) - 1, int(0.95 * len(secs)))]
    enc = lambda key: encrypted.get(key) if encrypted else "pending (needs A's server + C's pipeline)"
    rows = [
        ("Retrieval", "Right page in top 5 (int8)", _frac(sum(rank(r) is not None and rank(r) <= 5 for r in pos), len(pos))),
        ("Retrieval", "Right page in top 10 (int8, what Blindspot fetches)",
         _frac(sum(rank(r) is not None and rank(r) <= 10 for r in pos), len(pos))),
        ("Retrieval", "Right page in top 10 (float, no quantization)",
         _frac(sum(frank(r) is not None and frank(r) <= 10 for r in pos), len(pos))),
        ("Evidence", f"Right page among the model's {N_CONTEXT} sources, search order",
         _frac(sum(r["evidence_top5"] == "True" for r in pos), len(pos))),
        ("Evidence", f"Right page among the model's {N_CONTEXT} sources, after local rerank",
         _frac(sum(r["evidence_rerank5"] == "True" for r in pos), len(pos))),
        ("Answers", "Answerable questions answered", _frac(sum(a["status"] == "answered" for a in ans), len(ans))),
        ("Answers", "Answerable questions citing the right page", _frac(sum(bool(a["gold_cited"]) for a in ans), len(ans))),
        ("Answers", "Unsupported sentences removed by the citation checker", str(sum(a["removed_sentences"] for a in answers))),
        ("Safety", "Should-decline questions declined (out of scope, missing info, adversarial)",
         _frac(sum(a["status"] == "declined" for a in dec), len(dec))),
        ("Safety", "Wrong answers (answered when it should decline)", _frac(sum(a["status"] == "answered" for a in dec), len(dec))),
        ("Safety", "Urgent 988/911 notice correct (rule rechecked on all questions)", _frac(urgent_now, len(questions))),
        ("Cost", "Median seconds per question, plaintext path", f"{secs[len(secs) // 2]:.1f}"),
        ("Cost", "p95 seconds per question, plaintext path", f"{p95:.1f}"),
        ("Encrypted", "Encrypted path: top-10 agreement with plaintext int8 (score parity)", enc("agreement_with_plaintext")),
        ("Encrypted", "Encrypted path: answerable questions answered", enc("answered")),
        ("Encrypted", "Encrypted path: median seconds per question", enc("median_seconds")),
        ("Encrypted", "Encrypted path: median bytes up / down per question",
         f"{encrypted['median_upload_bytes']} / {encrypted['median_download_bytes']}" if encrypted
         else "pending (needs A's server + C's pipeline)"),
    ]
    return rows


def by_category(answers: list[dict]) -> dict[str, str]:
    c = defaultdict(lambda: [0, 0])
    for a in answers:
        c[a["category"]][0] += a["behaved"]
        c[a["category"]][1] += 1
    return {k: _frac(*v) for k, v in c.items()}


def main():
    retrieval = list(csv.DictReader(open(RESULTS / "retrieval.csv")))
    answers = [json.loads(l) for l in (RESULTS / "answers_plaintext.jsonl").read_text().splitlines() if l]
    questions = [json.loads(l) for l in (ROOT / "eval/questions.jsonl").read_text().splitlines() if l]
    enc_path = RESULTS / "summary_pipeline.json"
    encrypted = json.loads(enc_path.read_text()) if enc_path.exists() else None
    manifest = json.loads((ROOT / "artifacts/manifest.json").read_text())
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()

    rows = build(retrieval, answers, questions, encrypted)
    with open(RESULTS / "scorecard.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["area", "metric", "value"])
        w.writerows(rows)

    cats = by_category(answers)
    md = [
        "# Blindspot quality scorecard (part B)", "",
        f"Commit `{commit}` · corpus `{manifest['corpus_version']}` ({manifest['num_chunks']} MedlinePlus chunks) · "
        f"{len(questions)} questions ({sum(q['expect'] == 'answer' for q in questions)} answerable) · "
        f"embedding `{MODEL_NAME}` · reranker `{RERANK_MODEL}` · answers `{MODEL}` on-device",
        "", "| Area | Metric | Value |", "|---|---|---|",
        *[f"| {a} | {m} | {v} |" for a, m, v in rows],
        "", "## Behaved as expected, by question type", "", "| Type | Result |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in cats.items()],
        "", "## Decline threshold", "",
        f"`MIN_SCORE = {MIN_SCORE}`, chosen on the tune split and checked on the held-out test split "
        "(`eval/results/calibration.csv`). Raising it never reduced wrong answers (already zero); it only "
        "added false declines, so the model's own decline and the citation checker do the safety work.",
        "", "## Caveats", "",
        "- Questions and expected answers were written by the team, not clinicians; small sample, so one question is "
        "1.6 points on answerable metrics.",
        "- \"Right page\" means the MedlinePlus topic we labelled; another relevant page can also be a good answer "
        "(for example COPD questions answered from the emphysema page).",
        "- The 988/911 rule was extended after this eval exposed two gaps; its row is a recheck of the "
        "deterministic rule, not a rerun of the model.",
        "- Latency is from an 8 GB M2 Mac under memory pressure with other apps open; a clean machine is faster. "
        "Restart Ollama before demos (its memory grows over long sessions).",
        "- Not medically validated. The system gives general information with citations, not medical advice.",
    ]
    (RESULTS / "scorecard.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
