"""Step 5: the docs-proof tool, checked against the measured steps on every case in the answer key.

For each case, the tool's check (src/docsproof/check.py, the function the docs-proof command runs) reads the
pinned repository and a copy with the planted change, the way it reads the two sides of a real change. It must
flag exactly the doc lines the measured steps flag (the exact checks, the documented commands read, and the
changed-value search, with no model), and offer exactly the rules' fixes from step 4. Any difference stops the
script. The counts are in data/results/tool.json.

    python scripts/check_tool.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cases import clone, folder  # noqa: E402
from docsproof.check import check  # noqa: E402
from docsproof.plant import apply  # noqa: E402
from run_baseline import RESULTS, load_cases  # noqa: E402


def jsonl(name: str) -> list[dict]:
    return [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines()]


def run_repo(repo: str, cases: list[dict]) -> list[tuple[str, list[list], dict]]:
    """For each of a repository's cases: the lines the tool flags, and its fix for each (None for none)."""
    original = folder(repo)
    cache: dict = {}
    out = []
    for case in cases:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            clone(original, copy)
            apply(copy, case["edit"])
            found = check(original, copy, cache=cache)
        out.append((case["id"], [[x.file, x.line] for x in found],
                    {f"{x.file}:{x.line}": x.fix.new[0] if x.fix else None for x in found}))
    return out


def published(cases: list[dict]) -> tuple[dict, dict]:
    """For each case: the lines the measured steps flag, and the rules' fix for each line step 4 fixed."""
    lines = {c["id"]: set() for c in cases}
    for name in ("exact.jsonl", "commands.jsonl", "values.jsonl"):
        for row in jsonl(name):
            lines[row["id"]] |= {(p["file"], p["line"]) for p in row["predicted"]}
    fixes = {row["id"]: {f"{x['file']}:{x['line']}": x["rule"].get("new") for x in row["lines"]}
             for row in jsonl("fixes.jsonl")}
    return {k: sorted(v) for k, v in lines.items()}, fixes


def compare(cases: list[dict], results: dict) -> dict:
    """The counts, by split. Stops at the first case where the tool and the measured steps differ."""
    lines, fixes = published(cases)
    out = {}
    for split in ("dev", "test"):
        part = [c for c in cases if c["split"] == split]
        flagged = fixed = extra = 0
        for case in part:
            got_lines, got_fixes = results[case["id"]]
            if [tuple(x) for x in got_lines] != lines[case["id"]]:
                raise SystemExit(f"{case['id']}: the tool flags {got_lines}, the measured steps {lines[case['id']]}")
            for where, new in got_fixes.items():
                if where in fixes[case["id"]]:
                    if new != fixes[case["id"]][where]:
                        raise SystemExit(f"{case['id']} {where}: the tool's fix {new!r}, step 4's {fixes[case['id']][where]!r}")
                else:
                    extra += 1  # flagged only by the commands check, which step 4 didn't take as input
            flagged += len(got_lines)
            fixed += sum(1 for new in got_fixes.values() if new is not None)
        out[split] = {"cases": len(part), "flagged_lines": flagged, "fixes": fixed, "lines_step_4_didnt_take": extra}
    return out


def main() -> None:
    cases = load_cases()
    by_repo: dict[str, list[dict]] = {}
    for case in cases:
        by_repo.setdefault(case["repo"], []).append(case)
    results = {}
    with ProcessPoolExecutor(min(8, os.cpu_count() or 1)) as pool:
        for rows in pool.map(run_repo, list(by_repo), list(by_repo.values())):
            for case_id, got_lines, got_fixes in rows:
                results[case_id] = (got_lines, got_fixes)
    counts = compare(cases, results)
    (RESULTS / "tool.json").write_text(json.dumps(counts, indent=1) + "\n", encoding="utf-8")
    for split, c in counts.items():
        print(f"{split}: {c['cases']} cases, the same {c['flagged_lines']} flagged lines and {c['fixes']} fixes as the "
              f"measured steps")


if __name__ == "__main__":
    main()
