import pytest
from client.safety import CRISIS_MESSAGE, EMERGENCY_MESSAGE, urgent_notice


@pytest.mark.parametrize("q", [
    "I keep having thoughts of ending my life. Where can I get help?",
    "I want to kill myself",
    "Is it normal to think about suicide?",
    "I've been cutting myself again",
    "I don't want to be alive anymore",
])
def test_crisis_wording_gets_988(q):
    assert urgent_notice(q) == ("crisis", CRISIS_MESSAGE)
    assert "988" in CRISIS_MESSAGE


@pytest.mark.parametrize("q", [
    "I have crushing chest pain going down my left arm",
    "My dad's face is drooping and his speech is slurred",
    "My child can't breathe properly",
    "I think my friend took an overdose",
    "She passed out and is unconscious",
    "Was that a mini stroke?",
])
def test_emergency_signs_get_911(q):
    assert urgent_notice(q) == ("emergency", EMERGENCY_MESSAGE)
    assert "911" in EMERGENCY_MESSAGE


@pytest.mark.parametrize("q", [
    "What does an A1C test measure?",
    "I'm a smoker with a cough and shortness of breath that keep getting worse.",
    "How do I avoid food poisoning at a picnic?",
    "Why do I have so much bloating and burping?",
])
def test_ordinary_questions_get_no_notice(q):
    assert urgent_notice(q) is None


def test_crisis_takes_priority_over_emergency():
    assert urgent_notice("I took an overdose because I want to die")[0] == "crisis"
