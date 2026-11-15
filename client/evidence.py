"""Point the reader at the part of a source that an answer leans on."""
import re

_WORD = re.compile(r"[a-z0-9]+")


def _words(s: str) -> set:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 3}


def sentences(t: str) -> list:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", t or "") if x.strip()]


def supporting_excerpt(answer: str, n: int, source_text: str) -> str:
    """The sentence of the source sharing most words with the answer sentences that cite [n].

    Returned verbatim from the source, or "" if nothing overlaps. This is a word-overlap
    pointer for the reader, not proof that the source supports the claim.
    """
    cited = [s for s in sentences(answer) if f"[{n}]" in s] or sentences(answer)
    aw = _words(" ".join(cited))
    best, score = "", 0.0
    for s in sentences(source_text):
        sw = _words(s)
        sc = len(sw & aw) / ((len(sw) ** 0.5) + 1) if sw else 0
        if sc > score:
            best, score = s, sc
    return best
