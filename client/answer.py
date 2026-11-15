"""Local-model answer with verified citations, safe decline and safety notices (docs/contracts.md section 6).

Every sentence shown to the user must cite a source the model was given, and that source must contain
most of the sentence's key terms. Sentences that fail are removed; if none survive, the answer declines.
No citation is ever added that the model did not write.

Distinctive terms (acronyms and letter-digit codes such as GLP-1, A1C, LDL, XR-417) are checked exactly:
the stemmed word-overlap check cannot see them. A question whose distinctive term appears in none of the
sources declines, and an answer sentence naming one its cited sources lack is removed.

The rules go to the model as a system message with three short examples (answered, partly covered,
not covered), through Ollama's chat endpoint with an explicit context window so a longer prompt is never
silently truncated from the front, where the rules are.
"""
import os
import re
import time
from functools import lru_cache

import requests

from client.safety import urgent_notice

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
NUM_CTX = 8192  # Ollama's default on laptops is 4096; a prompt is ~2,300 tokens. Set it so nothing is cut.
MODEL = "llama3.2:3b"
N_CONTEXT = 5
MAX_ANSWER_TOKENS = 256  # guard against runaway output; the longest eval answer used 145
MIN_SCORE = 0.55  # cosine estimate of the top chunk; see eval/run_eval.py for calibration
SUPPORT_MIN = 0.5  # share of a sentence's key terms that its cited source must contain
DECLINE_MESSAGE = "I couldn't find a reliable source for this in the library. The closest passages are below."
DISCLAIMER = "This is general information, not medical or legal advice."

SYSTEM = """You answer health questions using ONLY the numbered sources the user gives you.
Rules:
- Use only facts stated in the sources. Never add outside knowledge.
- Never name a drug, test, condition or number that is not in the sources.
- End every sentence with the numbers of the sources it came from, like [1] or [2][3].
- If the sources cover only part of the question, answer that part, then add one sentence saying the
  sources do not cover the rest.
- If the sources do not answer the question at all, reply with exactly: NO_ANSWER
- Write 3 to 5 plain-language sentences when the sources allow, at most 150 words."""

# Three tiny examples: answered, partly covered, not covered. Kept short so they cost ~200 tokens.
FEW_SHOT = [
    {"role": "user", "content": "Sources:\n[1] Flu\nThe flu is caused by influenza viruses. Symptoms include fever, "
                                "cough and body aches. Most people recover in one to two weeks.\n\n"
                                "Question: What causes the flu and how long does it last?"},
    {"role": "assistant", "content": "The flu is caused by influenza viruses [1]. It often brings fever, cough and "
                                     "body aches [1]. Most people recover in one to two weeks [1]."},
    {"role": "user", "content": "Sources:\n[1] Asthma\nAsthma inflames and narrows the airways. Inhalers can help "
                                "control symptoms.\n\nQuestion: Can a new pill called Breathex cure my asthma?"},
    {"role": "assistant", "content": "Inhalers can help control asthma symptoms [1]. The sources do not mention Breathex."},
    {"role": "user", "content": "Sources:\n[1] Sunburn\nSunburn is skin damage from ultraviolet rays.\n\n"
                                "Question: How much does a knee replacement cost?"},
    {"role": "assistant", "content": "NO_ANSWER"},
]

PROMPT = """Sources:
{sources}

Question: {question}"""

_STOP = {"about", "after", "also", "because", "been", "before", "being", "could", "does", "doesn",
         "each", "from", "have", "into", "many", "might", "more", "most", "only", "other", "should",
         "some", "such", "than", "that", "their", "them", "there", "these", "they", "this", "very",
         "were", "what", "when", "where", "which", "while", "will", "with", "would", "your", "you're"}
_CITE = re.compile(r"\[(\d+)\]")


RERANK_MARGIN = 5.0  # keep sources within this many reranker points of the best (eval: 67/79 vs 68/79 kept)
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


OLLAMA_OPTIONS = {"temperature": 0, "num_predict": MAX_ANSWER_TOKENS, "num_ctx": NUM_CTX}


def ollama_generate(prompt: str, model: str = MODEL, url: str = OLLAMA_URL, timeout: float = 180) -> str:
    """Plain completion (used by the plaintext demo server's warm-up)."""
    r = requests.post(url, json={"model": model, "prompt": prompt, "stream": False,
                                 "keep_alive": "30m",  # avoid a cold reload between demo questions
                                 "options": OLLAMA_OPTIONS},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["response"].strip()


def ollama_chat(prompt: str, model: str = MODEL, url: str = OLLAMA_CHAT_URL, timeout: float = 180) -> str:
    """The answer call: rules as a system message, the examples, then the sources and question."""
    messages = [{"role": "system", "content": SYSTEM}, *FEW_SHOT, {"role": "user", "content": prompt}]
    r = requests.post(url, json={"model": model, "messages": messages, "stream": False,
                                 "keep_alive": "30m", "options": OLLAMA_OPTIONS},
                      timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def _terms(text: str) -> set[str]:
    """Key terms: words over 3 letters, minus common words, cut to 5 letters as a crude stem."""
    return {w[:5] for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 3 and w not in _STOP}


def distinctive_terms(text: str) -> set[str]:
    """Acronyms and letter-digit codes, normalized: GLP-1s -> glp1, A1C -> a1c, LDL -> ldl, XR-417 -> xr417."""
    out = set()
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9]", text):
        mixed = any(ch.isdigit() for ch in tok) and any(ch.isalpha() for ch in tok)
        acronym = tok.isalpha() and tok.isupper() and len(tok) >= 2
        if not (mixed or acronym):
            continue
        t = tok.lower().replace("-", "")
        if t.endswith("s") and len(t) > 3:  # plural: GLP-1s, LDLs
            t = t[:-1]
        out.add(t)
    return out


def _has_term(term: str, text: str) -> bool:
    return term in text.lower().replace("-", "")


def _missing_terms(text: str, sources: list[str]) -> set[str]:
    """Distinctive terms in text that appear in none of the sources."""
    return {t for t in distinctive_terms(text) if not any(_has_term(t, s) for s in sources)}


# A sentence that only says what the sources do not cover is kept without a citation.
_COVERAGE_NOTE = re.compile(r"^\s*(the )?(sources?|library|passages?) (do|does|did) not (mention|cover|say|discuss|"
                            r"address|include)\b[^\[\]]*$", re.I)


def _sentences(text: str) -> list[str]:
    """Split into sentences; a citation written after the full stop stays with its sentence."""
    out: list[str] = []
    # Never split after a single capital letter ("C. diff") or a common title ("Dr.").
    boundary = r"(?<![\s(][A-Z]\.)(?<!\b(?:Dr|Mr|Ms|St|vs)\.)(?<!\bMrs\.)(?<=[.!?])\s+|\n+"
    for part in re.split(boundary, text):
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
    for k in ("source", "source_name", "server"):  # set when the chunk came from a multi-server fan-out
        if k in c:
            out[k] = c[k]
    if excerpt is not None:
        out["excerpt"] = excerpt
    return out


def _env_num(name: str, default):
    v = os.environ.get(name)
    try:
        return type(default)(v) if v not in (None, "") else default
    except ValueError:
        return default


def select_sources(chunks: list[dict], n_context: int = N_CONTEXT) -> list[dict]:
    """Which reranked passages become the model's sources.

    Default: one slot per page (the best-ranked piece of each page), then the best n_context, minus any
    more than RERANK_MARGIN reranker points below the best one (a passage about another condition that
    shares common words, C. diff for a chlamydia question, otherwise ends up quoted in the answer).
    One slot per page frees slots that two pieces of the same page used to take, so answers can draw on
    more pages without loosening the relevance cutoff (and the same page is no longer cited twice).

    Variants, for measuring (eval.bench --sources ...):
      BLIND_RAG_N_CONTEXT=8        more slots
      BLIND_RAG_RERANK_MARGIN=7    a looser margin
      BLIND_RAG_MIN_SOURCES=2      always keep at least this many, margin or not
      BLIND_RAG_ONE_PER_PAGE=0     back to several pieces of one page in separate slots
    """
    n_context = _env_num("BLIND_RAG_N_CONTEXT", n_context)
    margin = _env_num("BLIND_RAG_RERANK_MARGIN", RERANK_MARGIN)
    min_keep = _env_num("BLIND_RAG_MIN_SOURCES", 1)
    one_per_page = os.environ.get("BLIND_RAG_ONE_PER_PAGE", "1") != "0"
    pool = chunks
    if one_per_page:
        seen, pool = set(), []
        for c in chunks:
            page = c.get("url") or c.get("title")
            if page not in seen:
                seen.add(page)
                pool.append(c)
    ctx = pool[:n_context]
    if ctx and "rerank_score" in ctx[0]:
        best = ctx[0]["rerank_score"]
        ctx = [c for i, c in enumerate(ctx) if i < min_keep or c["rerank_score"] >= best - margin]
    return ctx


def answer(question: str, chunks: list[dict], llm=ollama_chat,
           n_context: int = N_CONTEXT, min_score: float = MIN_SCORE, rerank=None) -> dict:
    """chunks: the k fetched records in search order. They are reranked locally, then the best
    n_context become the model's sources. The score threshold uses the search score of the top hit."""
    t0 = time.perf_counter()
    urgent = urgent_notice(question)
    top_score = chunks[0].get("score") if chunks else None
    chunks = (rerank or _default_rerank)(question, chunks)
    t_rerank = (time.perf_counter() - t0) * 1000
    ctx = select_sources(chunks, n_context)

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
    # The question names something specific (GLP-1, XR-417) that none of the sources mention: decline
    # rather than let the model fill the gap from memory.
    if _missing_terms(question, [c["title"] + " " + c["text"] for c in ctx]):
        return decline()

    sources = "\n\n".join(f"[{i}] {c['title']}\n{c['text']}" for i, c in enumerate(ctx, 1))
    # Small models sometimes append NO_ANSWER after a real answer; drop the token and check what is left.
    text = re.sub(r"\bNO_ANSWER\b", "", llm(PROMPT.format(sources=sources, question=question))).strip()

    kept: list[tuple[str, list[int]]] = []
    removed = 0
    notes: list[str] = []
    for s, cited, inherited in _claims(text, len(ctx)):
        if not cited and _COVERAGE_NOTE.match(s):  # "The sources do not mention X." Honest, keep it.
            notes.append(s)
            continue
        ok = _supported(s, cited, ctx)
        if ok and _missing_terms(s, [ctx[n - 1]["title"] + " " + ctx[n - 1]["text"] for n in ok]):
            ok = []  # names a specific drug/test/code its cited sources do not contain
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
    body = " ".join([_CITE.sub(lambda m: f"[{renumber[int(m.group(1))]}]", s) for s, _ in kept] + notes)
    body = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", body)).strip()
    body = re.sub(r"(\[\d+\])(\s*\1)+", r"\1", body)  # "[1] [1]" -> "[1]"
    citations = [_cite(ctx[n - 1], _excerpt(ctx[n - 1], [s for s, ok in kept if n in ok])) for n in used]
    return result("answered", body, citations, removed)
