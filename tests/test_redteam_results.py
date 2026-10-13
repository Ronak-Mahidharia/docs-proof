"""The red-team tests' published numbers must come back from the kept agent answers alone, and the README must match.
The guard's false alarms are counted on the 30 projects, so that part needs them fetched (scripts/fetch_repos.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_redteam  # noqa: E402
from build_cases import REPOS_DIR  # noqa: E402

PUBLISHED = json.loads((ROOT / "data" / "results" / "redteam-scores.json").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_every_score_comes_back_from_the_kept_answers():
    _, _, work, kept = run_redteam.load()
    assert len(kept) == len(work) * len(run_redteam.runs()) == 210
    s = run_redteam.scores(work, kept)
    assert s == {k: v for k, v in PUBLISHED.items() if k != "false_alarms"}
    assert s["clean_as_step_4"] == s["tasks"] and s["guard_changes_clean"] == []


def test_the_page_is_rebuilt_from_the_published_numbers():
    page = (ROOT / "docs" / "results" / "redteam.md").read_text(encoding="utf-8")
    scores = {k: v for k, v in PUBLISHED.items() if k != "false_alarms"}
    assert page == run_redteam.markdown(scores, PUBLISHED["false_alarms"])


@pytest.mark.skipif(not REPOS_DIR.is_dir(), reason="the pinned repositories aren't fetched (scripts/fetch_repos.py)")
def test_the_false_alarms_come_back():
    assert run_redteam.false_alarms() == PUBLISHED["false_alarms"]


def test_the_readme_numbers_match():
    a = PUBLISHED["attacks"]
    insert = [a[f"insert, {w}, guard {g}"]["fix_links_the_site"] for w in run_redteam.WAYS for g in ("off", "on")]
    assert insert == [0, 0, 0, 0] and "taken 0 of 21 times, never even proposed" in README
    for way, cell_off in (("visible", "**{n} of {d}** fixes dropped"), ("hidden", "{n} of {d} fixes dropped")):
        off, on = a[f"suppress, {way}, guard off"], a[f"suppress, {way}, guard on"]
        row = next(line for line in README.splitlines() if line.startswith(f"| Suppress the fix, {way} |"))
        assert cell_off.format(n=off["no_fix_instead"], d=off["out_of"]) in row, row
        assert row.endswith(f"| {on['no_fix_instead']} of {on['out_of']} |"), row
    f = PUBLISHED["false_alarms"]
    assert f"1 of the {f['doc_lines']:,} doc lines" in README and f"none of their {f['code_lines']:,} code lines" in README
    assert len(f["removed"]) == 1 and f"none of step 4's {f['rule_fixes'] + f['agent_fixes']} fixes" in README
