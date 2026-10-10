"""Score predicted doc lines against the answer key: precision, recall, and F1, for each kind of change."""
from __future__ import annotations

from collections import defaultdict


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def score(cases: list[dict], predicted: dict[str, list[tuple[str, int]]]) -> dict[str, dict]:
    """cases: the answer key's cases. predicted: case id -> [(file, line), ...]. Returns totals by kind,
    plus "all" for the cases whose change makes some doc line wrong."""
    totals: dict[str, dict] = defaultdict(lambda: {"cases": 0, "tp": 0, "fp": 0, "fn": 0, "all_found": 0,
                                                    "false_alarm_cases": 0})
    for case in cases:
        expected = {(e["file"], e["line"]) for e in case["expected"]}
        got = set(map(tuple, predicted.get(case["id"], [])))
        tp, fp, fn = len(expected & got), len(got - expected), len(expected - got)
        groups = [case["kind"]] + (["all"] if expected else [])
        for group in groups:
            t = totals[group]
            t["cases"] += 1
            t["tp"] += tp
            t["fp"] += fp
            t["fn"] += fn
            t["all_found"] += int(fn == 0)
            t["false_alarm_cases"] += int(fp > 0)
    for t in totals.values():
        t["precision"] = _ratio(t["tp"], t["tp"] + t["fp"])
        t["recall"] = _ratio(t["tp"], t["tp"] + t["fn"])
        p, r = t["precision"], t["recall"]
        t["f1"] = round(2 * p * r / (p + r), 3) if p and r else (0.0 if p is not None and r is not None else None)
    return dict(sorted(totals.items()))
