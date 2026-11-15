"""Deterministic safety rules. They look only at the question and run whatever the model writes."""
import re

CRISIS_MESSAGE = ("If you are thinking about suicide or harming yourself, call or text 988 "
                  "(Suicide & Crisis Lifeline, US) now. If you are in immediate danger, call 911.")
EMERGENCY_MESSAGE = ("If this is happening now, it may be an emergency: call 911 "
                     "(or your local emergency number) or go to the nearest emergency room.")

_CRISIS = re.compile(
    r"\b(suicid\w*|kill(ing)? myself|end(ing)? (my|her|his) (own )?life|take my (own )?life|"
    r"self[- ]?harm\w*|hurt(ing)? myself|cut(ting)? myself|"
    r"(don'?t|do not) want to (live|be alive)|want to die)\b", re.I)
_EMERGENCY = re.compile(
    r"\b(chest (pain|pressure|tightness)|crushing (pain|chest)|"
    r"(can'?t|cannot|can not|struggling to|trouble) breath\w*|not breathing|"
    r"face (is )?droop\w*|slurred speech|stroke|heart attack|"
    r"overdos\w*|unconscious|passed out|unresponsive|seizure|"
    r"(severe|heavy|uncontrolled) bleeding|bleeding (heavily|a lot|won'?t stop)|"
    r"anaphyla\w*|throat (is )?(closing|swelling))\b", re.I)


def urgent_notice(question: str) -> tuple[str, str] | None:
    """("crisis", message), ("emergency", message), or None. Crisis wins when both match."""
    if _CRISIS.search(question):
        return "crisis", CRISIS_MESSAGE
    if _EMERGENCY.search(question):
        return "emergency", EMERGENCY_MESSAGE
    return None
