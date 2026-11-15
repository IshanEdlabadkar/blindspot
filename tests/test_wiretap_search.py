import base64
import json
import random

from wiretap.search import chance_of_random_match, question_words, search_traffic


def rec(route, body: bytes, path="/v1/score", ts="2026-11-15T09:00:00.000Z"):
    return {"ts": ts, "route": route, "upstream": "u", "method": "POST", "path": path,
            "request_bytes": len(body), "body_b64": base64.b64encode(body).decode(), "status": 200,
            "response_bytes": 10}


Q = "Can I take FMLA leave for my pregnancy complication?"


def test_question_words_keeps_words_of_four_letters_or_more():
    assert question_words(Q) == ["take", "fmla", "leave", "pregnancy", "complication"]
    assert question_words("Is my A1C ok?") == []


def test_plaintext_request_reveals_every_word_encrypted_one_reveals_none():
    cipher = random.Random(7).randbytes(3080)
    plain = json.dumps({"question": Q}).encode()
    result = {r["route"]: r for r in search_traffic([rec("health", cipher), rec("plain", plain)], Q)}
    assert result["health"]["found"] == [] and result["health"]["bytes"] == 3080
    assert result["plain"]["found"] == ["take", "fmla", "leave", "pregnancy", "complication"]
    assert result["plain"]["words"] == 5 and result["plain"]["requests"] == 1
    m = result["plain"]["matches"][0]
    assert m["word"] == "take" and "take" in m["context"].lower()


def test_finds_words_hidden_by_url_or_json_escaping_and_in_paths():
    url = rec("a", b"", path="/search?q=pregnancy%20leave")
    esc = rec("b", b'{"q": "FMLA complicati\\u006fn"}')  # JSON escape on the wire: complication
    assert b"complication" not in esc["body_b64"].encode() and b"\\u006f" in base64.b64decode(esc["body_b64"])
    upper = rec("c", b"TAKE")
    got = {r["route"]: r["found"] for r in search_traffic([url, esc, upper], Q)}
    assert got == {"a": ["leave", "pregnancy"], "b": ["fmla", "complication"], "c": ["take"]}


def test_only_traffic_since_the_question_counts():
    old = rec("plain", json.dumps({"question": Q}).encode(), ts="2026-11-15T08:00:00.000Z")
    new = rec("plain", b"{}", ts="2026-11-15T09:00:00.000Z")
    r = search_traffic([old, new], Q, since="2026-11-15T08:30:00.000Z")[0]
    assert r["found"] == [] and r["requests"] == 1


def test_chance_of_a_random_match_is_tiny_for_four_letter_words():
    assert chance_of_random_match(3080, 4) < 1e-4
    assert chance_of_random_match(3080, 3) > chance_of_random_match(3080, 4)
