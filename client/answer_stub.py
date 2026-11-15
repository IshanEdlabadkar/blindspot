"""STUB for B's client/answer.py. Same signature and answer shape."""
import contracts as c


def answer(question: str, chunks: list) -> dict:
    if not chunks:
        return c.make_decline([])
    return c.make_answer(chunks[0]["text"][:300], chunks[:3])
