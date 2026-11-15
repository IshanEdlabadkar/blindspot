from eval.calibrate import choose_threshold, sweep


def row(expect, status, top1, split="tune"):
    return {"expect": expect, "status": status, "top1": top1, "split": split}


ROWS = [
    row("answer", "answered", 0.80), row("answer", "answered", 0.62), row("answer", "declined", 0.70),
    row("decline", "answered", 0.60), row("decline", "declined", 0.66),
    row("answer", "answered", 0.61, "test"), row("decline", "answered", 0.59, "test"),
]


def test_sweep_simulates_the_threshold_on_one_split():
    table = {r["threshold"]: r for r in sweep(ROWS, [0.55, 0.61, 0.65], split="tune")}
    # 0.55: nothing blocked; one model decline on an answerable question, one wrong answer
    assert (table[0.55]["false_declines"], table[0.55]["wrong_answers"]) == (1, 1)
    # 0.61: blocks the 0.60 wrong answer
    assert (table[0.61]["false_declines"], table[0.61]["wrong_answers"]) == (1, 0)
    # 0.65: also blocks the 0.62 good answer
    assert (table[0.65]["false_declines"], table[0.65]["wrong_answers"]) == (2, 0)
    assert table[0.55]["of_answerable"] == 3 and table[0.55]["of_unanswerable"] == 2


def test_choose_threshold_counts_wrong_answers_double_and_prefers_lower_on_ties():
    rows = sweep(ROWS, [0.55, 0.61, 0.65], split="tune")
    assert choose_threshold(rows)["threshold"] == 0.61
