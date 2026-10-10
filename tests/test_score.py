from docsproof.score import score

CASES = [
    {"id": "a", "kind": "rename_option", "expected": [{"file": "R.md", "line": 1}, {"file": "R.md", "line": 2}]},
    {"id": "b", "kind": "rename_option", "expected": [{"file": "R.md", "line": 5}]},
    {"id": "c", "kind": "rename_private", "expected": []},
]


def test_precision_recall_and_f1_by_kind():
    totals = score(CASES, {"a": [("R.md", 1), ("R.md", 9)], "b": [("R.md", 5)], "c": [("R.md", 3)]})
    opt = totals["rename_option"]
    assert (opt["tp"], opt["fp"], opt["fn"]) == (2, 1, 1)
    assert opt["precision"] == 0.667 and opt["recall"] == 0.667 and opt["f1"] == 0.667
    assert opt["all_found"] == 1 and opt["false_alarm_cases"] == 1
    assert totals["rename_private"]["false_alarm_cases"] == 1 and totals["rename_private"]["recall"] is None


def test_all_counts_only_cases_with_something_to_find():
    totals = score(CASES, {})
    assert totals["all"]["cases"] == 2 and totals["all"]["recall"] == 0.0 and totals["all"]["precision"] is None
