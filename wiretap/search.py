"""Search recorded traffic for the words of a question.

  uv run python -m wiretap.search "my secret question"            # everything recorded
  uv run python -m wiretap.search "my secret question" --since 2026-11-15T09:00:00Z

Looks in every request body and URL, as raw bytes and after undoing URL and JSON escaping,
case-insensitively. Words shorter than 4 letters are skipped: in random-looking (encrypted) bytes a
3-letter match can happen by chance, a 4-letter one practically never (see chance_of_random_match).
"""
import argparse
import base64
import json
import re
from urllib.parse import unquote_plus

from wiretap.proxy import DEFAULT_LOG, read_records

MIN_LEN = 4


def question_words(question: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9]+", question.lower()):
        if len(w) >= MIN_LEN and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def chance_of_random_match(n_bytes: int, word_len: int) -> float:
    """Expected chance that a given word appears in n random bytes, ignoring case."""
    return n_bytes * (2 / 256) ** word_len


def _views(rec: dict) -> list[str]:
    """The request as text, several ways: raw, URL-decoded, JSON-decoded."""
    body = base64.b64decode(rec["body_b64"])
    raw = rec["path"] + "\n" + body.decode("latin-1")
    views = [raw, unquote_plus(raw)]
    try:
        views.append(json.dumps(json.loads(body), ensure_ascii=False))
    except (ValueError, UnicodeDecodeError):
        pass
    return [v.lower() for v in views]


def search_traffic(records: list[dict], question: str, since: str | None = None) -> list[dict]:
    """Per route: requests and bytes sent since `since`, and which question words appear in them."""
    words = question_words(question)
    routes: dict[str, dict] = {}
    for rec in records:
        if since and rec["ts"] < since:
            continue
        r = routes.setdefault(rec["route"], {"route": rec["route"], "upstream": rec["upstream"], "requests": 0,
                                             "bytes": 0, "words": len(words), "found": [], "matches": [],
                                             "sample_hex": ""})
        r["requests"] += 1
        r["bytes"] += rec["request_bytes"]
        if not r["sample_hex"] and rec["request_bytes"]:
            r["sample_hex"] = base64.b64decode(rec["body_b64"])[:48].hex()
        views = _views(rec)
        for w in words:
            if w in r["found"]:
                continue
            for v in views:
                i = v.find(w)
                if i >= 0:
                    r["found"].append(w)
                    ctx = v[max(0, i - 30): i + len(w) + 30].replace("\n", " ")
                    r["matches"].append({"word": w, "path": rec["path"], "context": ctx})
                    break
    for r in routes.values():
        r["found"].sort(key=words.index)
        r["chance_by_luck"] = sum(chance_of_random_match(r["bytes"], len(w)) for w in words)
    return list(routes.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--since", help="only traffic at or after this UTC time (ISO 8601)")
    ap.add_argument("--log", default=DEFAULT_LOG)
    args = ap.parse_args()
    words = question_words(args.question)
    print(f"Searching for {len(words)} words: {', '.join(words)}")
    for r in search_traffic(read_records(args.log), args.question, args.since):
        print(f"  {r['route']:12} {r['requests']:3} requests, {r['bytes']:>9,} bytes sent  ->  "
              f"{len(r['found'])} of {r['words']} words found {r['found'] or ''}")


if __name__ == "__main__":
    main()
