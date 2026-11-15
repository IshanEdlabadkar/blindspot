"""Page -> chunks of at most max_words words that fit a 2,048-byte record."""
from common.records import MAX_JSON_BYTES, encode_chunk


def _pieces(lines: list[str], limit: int) -> list[str]:
    out = []
    for line in lines:
        w = line.split()
        if len(w) <= limit:
            out.append(line)
        else:
            out += [" ".join(w[i:i + limit]) for i in range(0, len(w), limit)]
    return out


def _windows(lines: list[str], max_words: int, overlap: int) -> list[str]:
    chunks, cur, n = [], [], 0
    for piece in _pieces(lines, max_words - overlap):
        k = len(piece.split())
        if cur and n + k > max_words:
            chunks.append(cur)
            tail = " ".join(" ".join(cur).split()[-overlap:]) if overlap else ""
            cur, n = ([tail], len(tail.split())) if tail else ([], 0)
        cur.append(piece)
        n += k
    if cur:
        chunks.append(cur)
    return ["\n".join(c) for c in chunks]


def _make(page: dict, text: str) -> dict:
    head = page["title"]
    if page["also_called"]:
        head += f" (also called: {', '.join(page['also_called'])})"
    return {"title": page["title"], "url": page["url"], "updated": page["updated"],
            "text": text, "embed_text": f"{head}\n{text}"}


def _fit(page: dict, text: str) -> list[dict]:
    chunk = _make(page, text)
    if len(encode_chunk({**chunk, "id": 999999})) <= MAX_JSON_BYTES:
        return [chunk]
    w = text.split()
    if len(w) < 2:
        raise ValueError(f"cannot fit a single word into a record: {page['url']}")
    half = len(w) // 2
    return _fit(page, " ".join(w[:half])) + _fit(page, " ".join(w[half:]))


def chunk_page(page: dict, max_words: int = 250, overlap: int = 40) -> list[dict]:
    lines = []
    for heading, paras in page["sections"]:
        if heading:
            lines.append(heading)
        lines += paras
    return [c for body in _windows(lines, max_words, overlap) for c in _fit(page, body)]
