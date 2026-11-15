# Demo kit

Everything needed to give the 3-minute demo from a cold start, or from the backup recording.

| File | Use |
| --- | --- |
| [RUNBOOK.md](RUNBOOK.md) | Cold start, pre-flight check, what to do when something fails, how to record the backup |
| [SCRIPT.md](SCRIPT.md) | The 3-minute script: what to click and what to say |
| [PROMPTS.md](PROMPTS.md) | The questions to ask, and why those |
| `preflight.py` | Automated 8-step smoke test. Run `make preflight` before presenting |
| `screenshots/` | Development screenshots, and the list of real ones still to capture |

Status on Nov 14, 19:50: the smoke test passes on real crypto with the models switched off (Linux). It has **not** yet passed with the real embedding model and local LLM on the demo Mac. Do that first.
