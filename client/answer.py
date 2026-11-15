"""Local-model answer with verified citations, safe decline and safety notices (docs/contracts.md section 6).

Every sentence shown to the user must cite a source the model was given, and that source must contain
most of the sentence's key terms. Sentences that fail are removed; if none survive, the answer declines.
No citation is ever added that the model did not write.
"""
import re
import time
from functools import lru_cache

import requests

from client.safety import urgent_notice

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"
N_CONTEXT = 5
MAX_ANSWER_TOKENS = 256  # guard against runaway output; the longest eval answer used 145
MIN_SCORE = 0.55  # cosine estimate of the top chunk; see eval/run_eval.py for calibration
SUPPORT_MIN = 0.5  # share of a sentence's key terms that its cited source must contain
DECLINE_MESSAGE = "I couldn't find a reliable source for this in the library. The closest passages are below."
DISCLAIMER = "This is general information, not medical or legal advice."

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

_STOP = {"about", "after", "also", "because", "been", "before", "being", "could", "does", "doesn",
         "each", "from", "have", "into", "many", "might", "more", "most", "only", "other", "should",
         "some", "such", "than", "that", "their", "them", "there", "these", "they", "this", "very",
         "were", "what", "when", "where", "which", "while", "will", "with", "would", "your", "you're"}
_CITE = re.compile(r"\[(\d+)\]")


RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
RERANK_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANK_MODEL, revision=RERANK_REVISION, device="cpu")


def rerank_chunks(question: str, chunks: list[dict]) -> list[dict]:
    """Reorder retrieved chunks by a local cross-encoder; each gets "rerank_score". Runs on the device."""
    if not chunks:
        return []
    scores = _cross_encoder().predict([(question, f"{c['title']}\n{c['text']}") for c in chunks])
    ranked = sorted(zip(scores, range(len(chunks))), key=lambda p: -p[0])
    return [{**chunks[i], "rerank_score": float(s)} for s, i in ranked]


def _default_rerank(question: str, chunks: list[dict]) -> list[dict]:
    return rerank_chunks(question, chunks)


def ollama_generate(prompt: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: float = 180) -> str:
    r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False,
                                 "keep_alive": "30m",  # avoid a cold reload between demo questions
                                 "options": {"temperature": 0, "num_predict": MAX_ANSWER_TOKENS}},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


def _terms(text: str) -> set[str]:
    """Key terms: words over 3 letters, minus common words, cut to 5 letters as a crude stem."""
    return {w[:5] for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 3 and w not in _STOP}


def _sentences(text: str) -> list[str]:
    """Split into sentences; a citation written after the full stop stays with its sentence."""
    out: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+|\n+", text):
        part = part.strip()
        lead = re.match(r"^((?:\[\d+\]\s*)+)(.*)$", part, re.S)
        if lead and out:
            out[-1] += " " + lead.group(1).strip()
            part = lead.group(2).strip()
        if part:
            out.append(part)
    return out


def _claims(text: str, n_sources: int) -> list[tuple[str, list[int], bool]]:
    """(sentence, cited sources, inherited?) for each sentence.

    A citation at the end of a paragraph also covers that paragraph's earlier uncited sentences, which is
    how models often cite. It never crosses into another paragraph, and each sentence is still checked.
    """
    out = []
    for para in re.split(r"\n\s*\n", text):
        rows = []
        for s in _sentences(para):
            rows.append([s, sorted({int(n) for n in _CITE.findall(s) if 1 <= int(n) <= n_sources}), False])
        carry: list[int] = []
        for row in reversed(rows):
            if row[1]:
                carry = row[1]
            elif carry:
                row[1], row[2] = carry, True
        out += [tuple(r) for r in rows]
    return out


def _supported(sentence: str, cited: list[int], ctx: list[dict]) -> list[int]:
    """The cited sources backing the sentence: together they must hold SUPPORT_MIN of its key terms."""
    claim = _terms(_CITE.sub("", sentence))
    if not cited:
        return []
    if not claim:  # nothing checkable, e.g. "Yes [1]."
        return cited
    covered = {n: claim & _terms(ctx[n - 1]["text"]) for n in cited}
    if len(set().union(*covered.values())) / len(claim) < SUPPORT_MIN:
        return []
    return [n for n in cited if covered[n]]


def _excerpt(chunk: dict, sentences: list[str]) -> str:
    """The source sentence that best matches the answer sentences citing this chunk."""
    want = _terms(" ".join(sentences))
    return max(_sentences(chunk["text"]), key=lambda s: len(_terms(s) & want))


def _cite(c: dict, excerpt: str | None = None) -> dict:
    out = {**{k: c[k] for k in ("id", "title", "url", "updated", "text")}, "score": float(c.get("score", 0.0))}
    for k in ("source", "source_name"):  # set when the chunk came from a multi-server fan-out
        if k in c:
            out[k] = c[k]
    if excerpt is not None:
        out["excerpt"] = excerpt
    return out


def answer(question: str, chunks: list[dict], llm=ollama_generate,
           n_context: int = N_CONTEXT, min_score: float = MIN_SCORE, rerank=None) -> dict:
    """chunks: the k fetched records in search order. They are reranked locally, then the best
    n_context become the model's sources. The score threshold uses the search score of the top hit."""
    t0 = time.perf_counter()
    urgent = urgent_notice(question)
    top_score = chunks[0].get("score") if chunks else None
    chunks = (rerank or _default_rerank)(question, chunks)
    t_rerank = (time.perf_counter() - t0) * 1000
    ctx = chunks[:n_context]

    def result(status, text, citations, removed=0):
        body = f"{urgent[1]}\n\n{text}" if urgent else text
        return {"status": status, "answer": f"{body}\n\n{DISCLAIMER}", "citations": citations,
                "urgent": {"kind": urgent[0], "message": urgent[1]} if urgent else None,
                "checks": {"removed_sentences": removed},
                "timings": {"rerank_ms": t_rerank, "answer_ms": (time.perf_counter() - t0) * 1000 - t_rerank}}

    def decline(removed=0):
        return result("declined", DECLINE_MESSAGE, [_cite(c) for c in chunks[:3]], removed)

    if not ctx or (top_score is not None and top_score < min_score):
        return decline()

    sources = "\n\n".join(f"[{i}] {c['title']}\n{c['text']}" for i, c in enumerate(ctx, 1))
    # Small models sometimes append NO_ANSWER after a real answer; drop the token and check what is left.
    text = re.sub(r"\bNO_ANSWER\b", "", llm(PROMPT.format(sources=sources, question=question))).strip()

    kept: list[tuple[str, list[int]]] = []
    removed = 0
    for s, cited, inherited in _claims(text, len(ctx)):
        ok = _supported(s, cited, ctx)
        if not ok:
            removed += 1
        elif inherited:
            kept.append((s + " " + "".join(f"[{n}]" for n in ok), ok))
        else:
            kept.append((_CITE.sub(lambda m: m.group(0) if int(m.group(1)) in ok else "", s), ok))
    if not kept:
        return decline(removed)

    used = sorted({n for _, ok in kept for n in ok})
    renumber = {n: i for i, n in enumerate(used, 1)}
    body = " ".join(_CITE.sub(lambda m: f"[{renumber[int(m.group(1))]}]", s) for s, _ in kept)
    body = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", body)).strip()
    body = re.sub(r"(\[\d+\])(\s*\1)+", r"\1", body)  # "[1] [1]" -> "[1]"
    citations = [_cite(ctx[n - 1], _excerpt(ctx[n - 1], [s for s, ok in kept if n in ok])) for n in used]
    return result("answered", body, citations, removed)
