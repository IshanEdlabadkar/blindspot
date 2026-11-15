"""Local-model answer with citations and safe decline (docs/contracts.md section 6)."""
import re
import time

import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"
N_CONTEXT = 5
MAX_ANSWER_TOKENS = 256  # guard against runaway output; the longest eval answer used 145
MIN_SCORE = 0.55  # cosine estimate of the top chunk; tuned with eval/run_eval.py
DECLINE_MESSAGE = "I couldn't find a reliable source for this in the library. The closest passages are below."
DISCLAIMER = "This is general health information, not medical advice."

PROMPT = """You answer health questions using ONLY the numbered sources below.
Rules:
- Use only facts stated in the sources. Do not add outside knowledge.
- After each sentence, cite the source numbers it came from, like [1] or [2][3].
- If the sources do not answer the question, reply with exactly: NO_ANSWER
- Answer in plain language, in under 150 words.

Sources:
{sources}

Question: {question}
Answer:"""


def ollama_generate(prompt: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: float = 180) -> str:
    r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False,
                                 "keep_alive": "30m",  # avoid a cold reload between demo questions
                                 "options": {"temperature": 0, "num_predict": MAX_ANSWER_TOKENS}},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


GROUNDING_MIN = 0.6  # share of the answer's content words that must appear in one source


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 3}


def _grounding_source(text: str, ctx: list[dict]) -> int | None:
    """1-based index of the source covering most of an uncited answer's words, if enough."""
    answer_words = _words(text)
    if not answer_words:
        return None
    cover = [len(answer_words & _words(c["text"])) / len(answer_words) for c in ctx]
    best = max(range(len(ctx)), key=cover.__getitem__)
    return best + 1 if cover[best] >= GROUNDING_MIN else None


def _cite(c: dict) -> dict:
    return {**{k: c[k] for k in ("id", "title", "url", "updated", "text")}, "score": float(c.get("score", 0.0))}


def _result(status: str, text: str, citations: list[dict], t0: float) -> dict:
    return {"status": status, "answer": f"{text}\n\n{DISCLAIMER}", "citations": citations,
            "timings": {"answer_ms": (time.perf_counter() - t0) * 1000}}


def answer(question: str, chunks: list[dict], llm=ollama_generate,
           n_context: int = N_CONTEXT, min_score: float = MIN_SCORE) -> dict:
    t0 = time.perf_counter()
    ctx = chunks[:n_context]

    def decline():
        return _result("declined", DECLINE_MESSAGE, [_cite(c) for c in chunks[:3]], t0)

    if not ctx or ("score" in ctx[0] and ctx[0]["score"] < min_score):
        return decline()

    sources = "\n\n".join(f"[{i}] {c['title']}\n{c['text']}" for i, c in enumerate(ctx, 1))
    # Small models sometimes append NO_ANSWER after a real answer, so drop the token and
    # decline only if nothing usable is left.
    text = re.sub(r"\bNO_ANSWER\b", "", llm(PROMPT.format(sources=sources, question=question))).strip()
    if not text:
        return decline()

    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text) if 1 <= int(n) <= len(ctx)})
    if not used:
        best = _grounding_source(text, ctx)
        if best is None:
            return decline()
        text, used = f"{text} [{best}]", [best]
    renumber = {n: i for i, n in enumerate(used, 1)}

    def fix(m):
        n = int(m.group(1))
        return f"[{renumber[n]}]" if n in renumber else ""

    return _result("answered", re.sub(r"\[(\d+)\]", fix, text), [_cite(ctx[n - 1]) for n in used], t0)
