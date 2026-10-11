"""Step 3: changed values (a new default, or a higher minimum Python version) and the doc lines that still state
the old value.

1. For each case, the changes to values are found by comparing the code before and after the planted change,
   and the doc lines that may state the old value are searched for (data/results/values-candidates.jsonl, with
   a few lines of context around each, so the model can read them without the repositories).
2. The baseline flags every candidate (data/results/values.jsonl).

    python scripts/run_values.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cases import clone, folder  # noqa: E402
from docsproof.docs import read_lines  # noqa: E402
from docsproof.names import Code  # noqa: E402
from docsproof.plant import apply  # noqa: E402
from docsproof.values import candidates, value_changes  # noqa: E402
from run_baseline import RESULTS, load_cases, pct, report  # noqa: E402

CONTEXT = 3  # lines shown before and after each candidate


def context(root: Path, file: str, line: int) -> list[str]:
    lines = read_lines(root / file)
    return lines[max(0, line - 1 - CONTEXT): line + CONTEXT]


def find_all(cases: list[dict]) -> list[dict]:
    """For each case: its changed values, and each one's candidate lines with their context."""
    codes: dict[str, Code] = {}
    rows = []
    for case in cases:
        original = folder(case["repo"])
        if case["repo"] not in codes:
            codes[case["repo"]] = Code(original)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            clone(original, copy)
            apply(copy, case["edit"])
            changes = value_changes(original, copy, codes[case["repo"]])
        rows.append({"id": case["id"], "changes": [
            {**asdict(change), "candidates": [{**asdict(c), "context": context(original, c.file, c.line),
                                               "context_starts": max(1, c.line - CONTEXT)}
                                              for c in candidates(original, change)]}
            for change in changes]})
    return rows


def baseline(rows: list[dict]) -> dict[str, list[dict]]:
    """The baseline flags every candidate."""
    return {row["id"]: sorted({(c["file"], c["line"]) for change in row["changes"] for c in change["candidates"]})
            for row in rows}


def main() -> None:
    cases = load_cases()
    rows = find_all(cases)
    with (RESULTS / "values-candidates.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    flagged = baseline(rows)
    with (RESULTS / "values.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps({"id": case["id"], "predicted": [{"file": f, "line": n} for f, n in flagged[case["id"]]]},
                                 ensure_ascii=False) + "\n")
    scores = report(cases, {k: [tuple(x) for x in v] for k, v in flagged.items()})
    (RESULTS / "values-scores.json").write_text(json.dumps({"baseline": scores}, indent=1) + "\n", encoding="utf-8")
    for split in ("dev", "test"):
        v, c = scores[split]["value"], scores[split]["control"]
        print(f"{split}: value group precision {pct(v['precision'])}, recall {pct(v['recall'])} "
              f"({v['tp']} of {v['tp'] + v['fn']} lines, {v['fp']} false alarms); controls with a false alarm "
              f"{c['false_alarm_cases']} of {c['cases']}")


if __name__ == "__main__":
    main()
