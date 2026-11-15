"""CANNED ask(): fixed output for laying out the UI with nothing else running."""
import contracts as c

_CHUNKS = [
    {"id": 1, "title": "Canned source one", "url": "https://example.org/1",
     "text": "This is the first canned passage. It exists so the UI has something to render."},
    {"id": 2, "title": "Canned source two", "url": "https://example.org/2",
     "text": "This is the second canned passage, shown as the second citation."},
]


def ask(question: str) -> dict:
    if "decline" in question.lower():
        return c.make_decline(_CHUNKS)
    return c.make_answer("This is a fixed canned answer for UI layout [1][2].", _CHUNKS)
