"""Checks on the docs-proof tool's run over the answer key (scripts/check_tool.py): its counts agree with the
measured steps' kept results, and the README and plan quote them. The run itself needs the repositories, so
CI's reproduce job reruns it."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import check_tool  # noqa: E402
from run_baseline import load_cases  # noqa: E402

TOOL = json.loads((ROOT / "data" / "results" / "tool.json").read_text(encoding="utf-8"))


def test_the_tools_counts_are_the_measured_steps_counts():
    cases = load_cases()
    lines, fixes = check_tool.published(cases)
    for split in ("dev", "test"):
        part = [c["id"] for c in cases if c["split"] == split]
        assert TOOL[split]["cases"] == len(part)
        assert TOOL[split]["flagged_lines"] == sum(len(lines[i]) for i in part)
        assert TOOL[split]["fixes"] == sum(1 for i in part for new in fixes[i].values() if new is not None)
        assert TOOL[split]["lines_step_4_didnt_take"] == 0


def test_readme_and_plan_numbers_for_the_tool():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    cases = sum(TOOL[s]["cases"] for s in TOOL)
    flagged = sum(TOOL[s]["flagged_lines"] for s in TOOL)
    fixes = sum(TOOL[s]["fixes"] for s in TOOL)
    assert (f"on all {cases} cases, it flags exactly the {flagged} lines that the exact checks, the commands read, and "
            f"the changed-value search flag, and offers exactly step 4's {fixes} rule fixes") in readme
    assert f"On all {cases} cases it flags exactly the {flagged} lines the measured steps flag, and offers exactly step 4's {fixes} rule fixes" in plan
