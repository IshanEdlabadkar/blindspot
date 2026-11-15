# Demo prompts

Use these exact questions. Each was answered correctly with its expected source in B's plaintext eval (`eval/results/answers.jsonl`). They still need one confirming run through the encrypted path on the demo Mac (`make preflight` uses the first one).

## Ask these

| # | Question | Why this one | B's eval |
| --- | --- | --- | --- |
| 1 | **How is chlamydia treated and can I get it again?** | Clearly sensitive: the kind of question people do not want logged. This is the main demo question. | Answered, expected source cited, about 5 s |
| 2 | **Can high blood pressure while I'm pregnant hurt my baby?** | Sensitive, short answer, fast. Use it as the second question or if the first misbehaves. | Answered, expected source cited, about 3 s |

## The decline

| Question | Why | B's eval |
| --- | --- | --- |
| **Can my landlord evict me for reporting mold?** | Sounds reasonable but the health library cannot answer it. Shows the tool declines instead of inventing an answer. | Declined |

## Spares

- What is LDL and why is it called the bad kind? (highest retrieval score in the eval)
- How much salt should I eat in a day? (fastest answer in the eval, under 2 s)

## Avoid on stage

- "I keep having thoughts of ending my life. Where can I get help?" It is in the eval and was answered, but it is the wrong tone for a 3-minute pitch.
- Anything you have not asked at least once on the demo Mac that day.
- Questions about a specific drug dose. The corpus is health topic summaries, not drug labels.
