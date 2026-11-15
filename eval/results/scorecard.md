# Blind RAG quality scorecard (part B)

Commit `0ce3528` · corpus `2026-11-14.2` (2101 MedlinePlus chunks) · 82 questions (64 answerable) · embedding `BAAI/bge-small-en-v1.5` · reranker `cross-encoder/ms-marco-MiniLM-L6-v2` · answers `llama3.2:3b` on-device

| Area | Metric | Value |
|---|---|---|
| Retrieval | Right page in top 5 (int8) | 56/64 (88%) |
| Retrieval | Right page in top 10 (int8, what Blind RAG fetches) | 61/64 (95%) |
| Retrieval | Right page in top 10 (float, no quantization) | 62/64 (97%) |
| Evidence | Right page among the model's 5 sources, search order | 56/64 (88%) |
| Evidence | Right page among the model's 5 sources, after local rerank | 58/64 (91%) |
| Answers | Answerable questions answered | 54/64 (84%) |
| Answers | Answerable questions citing the right page | 48/64 (75%) |
| Answers | Unsupported sentences removed by the citation checker | 76 |
| Safety | Should-decline questions declined (out of scope, missing info, adversarial) | 18/18 (100%) |
| Safety | Wrong answers (answered when it should decline) | 0/18 (0%) |
| Safety | Urgent 988/911 notice correct (rule rechecked on all questions) | 82/82 (100%) |
| Cost | Median seconds per question, plaintext path | 22.1 |
| Cost | p95 seconds per question, plaintext path | 38.2 |
| Encrypted | Encrypted path: top-10 agreement with plaintext int8 (score parity) | pending (needs A's server + C's pipeline) |
| Encrypted | Encrypted path: answerable questions answered | pending (needs A's server + C's pipeline) |
| Encrypted | Encrypted path: median seconds per question | pending (needs A's server + C's pipeline) |
| Encrypted | Encrypted path: median bytes up / down per question | pending (needs A's server + C's pipeline) |

## Behaved as expected, by question type

| Type | Result |
|---|---|
| basic | 18/20 (90%) |
| out_of_scope | 5/5 (100%) |
| paraphrase | 25/28 (89%) |
| close_diagnosis | 7/8 (88%) |
| missing_info | 7/7 (100%) |
| urgent | 4/8 (50%) |
| adversarial | 6/6 (100%) |

## Decline threshold

`MIN_SCORE = 0.55`, chosen on the tune split and checked on the held-out test split (`eval/results/calibration.csv`). Raising it never reduced wrong answers (already zero); it only added false declines, so the model's own decline and the citation checker do the safety work.

## Caveats

- Questions and expected answers were written by the team, not clinicians; small sample, so one question is 1.6 points on answerable metrics.
- "Right page" means the MedlinePlus topic we labelled; another relevant page can also be a good answer (for example COPD questions answered from the emphysema page).
- The 988/911 rule was extended after this eval exposed two gaps; its row is a recheck of the deterministic rule, not a rerun of the model.
- Latency is from an 8 GB M2 Mac under memory pressure with other apps open; a clean machine is faster. Restart Ollama before demos (its memory grows over long sessions).
- Not medically validated. The system gives general information with citations, not medical advice.
