"""Checks on the real-history key and docs-proof's run on it (step 6): the key is the mined cases the hand check
found real, the scores and docs/results/real.md come from the kept results, and the README and plan quote them.
Mining and running need the fetched history (scripts/fetch_history.py), so they run on my Mac; the last test
checks the key against the history when it's there."""
import copy
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import build_real_cases  # noqa: E402
import run_real  # noqa: E402
from fetch_history import HISTORY, place  # noqa: E402
from run_baseline import pct  # noqa: E402

KEY = run_real.jsonl(ROOT / "data" / "real_cases.jsonl")
MINED = run_real.jsonl(ROOT / "data" / "real_mined.jsonl")
ROWS = {r["id"]: r for r in run_real.jsonl(ROOT / "data" / "results" / "real.jsonl")}
SCORES = json.loads((ROOT / "data" / "results" / "real-scores.json").read_text(encoding="utf-8"))
MINING = json.loads((ROOT / "data" / "results" / "real-mining.json").read_text(encoding="utf-8"))
HAND = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["real_history"]


def test_the_key_is_the_mined_cases_the_hand_check_found_real():
    key, counts = build_real_cases.checked(MINED)
    assert key == KEY
    assert counts == MINING["hand_check"]
    assert [c["id"] for c in KEY] == [c["case"] for c in HAND["cases"] if c["verdict"] == "real"]
    assert sorted(c["case"] for c in HAND["cases"]) == sorted(c["id"] for c in MINED)
    assert all(c["verdict"] in ("real", "not real") and c["why"] for c in HAND["cases"])


def test_the_key_waits_for_the_hand_check():
    with pytest.raises(SystemExit, match="Check these real-history cases by hand first"):
        build_real_cases.checked(MINED + [{**MINED[0], "id": "someone/else@0123456789"}])
    with pytest.raises(SystemExit, match="no longer mined"):
        build_real_cases.checked(MINED[1:])
    case, file, line = HAND["drop_lines"][0]
    mined = copy.deepcopy(MINED)
    for c in mined:
        if c["id"] == case:
            c["expected"] = [e for e in c["expected"] if (e["file"], e["line"]) != (file, line)]
    with pytest.raises(SystemExit, match="Dropped lines that aren't mined any more"):
        build_real_cases.checked(mined)


def test_the_cases_keep_the_split_by_repository():
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    splits = {r["repo"]: r["split"] for r in repos}
    assert set(MINING["funnel"]) == set(splits)
    for case in MINED:
        assert case["split"] == splits[case["repo"]]
        assert case["id"] == f"{case['repo']}@{case['commit'][:10]}"
        assert case["expected"]
        for e in case["expected"]:
            assert e["days"] == (date.fromisoformat(e["fixed_on"]) - date.fromisoformat(case["date"])).days >= 0
            assert e["kind"] in run_real.KINDS


def test_the_scores_and_the_page_come_from_the_kept_results():
    run_real.gate(ROWS, HAND["other_still_there"])
    s = run_real.scores(KEY, ROWS)
    assert s == SCORES
    assert run_real.markdown(s, KEY, ROWS) == (ROOT / "docs" / "results" / "real.md").read_text(encoding="utf-8")


def test_scores_and_page_for_a_case_flagged_in_part():
    """In the kept results every case is flagged in full or not at all, so a case flagged in part is made up here."""
    def case(split: str, n: int) -> dict:
        return {"id": f"x/{split}@0123456789", "split": split, "expected": [
            {"file": "a.md", "line": line, "kind": "option", "name": f"--name{line}", "days": line, "fixed_by": "f"}
            for line in range(1, n + 1)]}
    cases = [case("dev", 1), case("test", 2)]
    rows = {"x/dev@0123456789": {"compared": ["--name1"], "flagged": [{"file": "a.md", "line": 1}]},
            "x/test@0123456789": {"compared": ["--name1", "--name2"], "flagged": [{"file": "a.md", "line": 2}]}}
    s = run_real.scores(cases, rows)
    assert {k: s["test"][k] for k in ("found", "cases_all_found", "compared_lines", "compared_found")} == {
        "found": 1, "cases_all_found": 0, "compared_lines": 2, "compared_found": 1}
    assert s["dev"]["cases_all_found"] == 1
    page = run_real.markdown(s, cases, rows)
    assert "| test | x/test@0123456789 | `--name1` | a.md:1 | 1 | yes | no |" in page
    assert "| test | x/test@0123456789 | `--name2` | a.md:2 | 2 | yes | yes |" in page


def test_the_scores_wait_for_the_hand_reads():
    with pytest.raises(SystemExit, match="Read these flagged lines by hand first"):
        run_real.gate(ROWS, HAND["other_still_there"][1:])
    with pytest.raises(SystemExit, match="no longer flagged"):
        run_real.gate(ROWS, HAND["other_still_there"] + [{**HAND["other_still_there"][0], "line": 1}])
    rows = copy.deepcopy(ROWS)
    changed = next(x for r in rows.values() for x in r["flagged"] if x.get("still_there") is False)
    changed["names"] = []  # flagged by another check, so the page's account by name doesn't fit it
    with pytest.raises(SystemExit, match="Read these changed lines by hand first"):
        run_real.gate(rows, HAND["other_still_there"])
    rows = copy.deepcopy(ROWS)
    changed = next(x for r in rows.values() for x in r["flagged"] if x.get("still_there") is False and x["key_rules_see"])
    changed["name_kept"] = False
    with pytest.raises(SystemExit, match="Read these changed lines by hand first"):
        run_real.gate(rows, HAND["other_still_there"])


def test_the_pages_example_is_one_of_the_lines_it_explains():
    unread = [x["text"].strip() for r in ROWS.values() for x in r["flagged"]
              if x.get("still_there") is False and not x["key_rules_see"]]
    assert "return PluginSQL(" in unread
    assert build_real_cases.references("return PluginSQL(") == set()
    assert build_real_cases.references("Return a `PluginSQL` or `utils.PluginSQL()`.") == {("identifier", "PluginSQL")}


def test_readme_and_plan_numbers_for_real_history():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    dev, test = SCORES["dev"], SCORES["test"]
    mined = sum(MINING["hand_check"][s]["mined_cases"] for s in ("dev", "test"))
    real = sum(MINING["hand_check"][s]["cases"] for s in ("dev", "test"))
    assert f"and {real} of the {mined} were real" in readme
    assert (f"**Test** ({test['cases']} cases, {test['lines']} lines): reading the code just before and just after each "
            f"change, with no AI, docs-proof would have flagged {test['found']} of the {test['lines']} lines "
            f"({pct(test['recall'])}), and every line in {test['cases_all_found']} of the {test['cases']} cases. On dev, "
            f"it would have flagged {dev['found']} of {dev['lines']} ({pct(dev['recall'])}).") in readme
    # every line whose name it compares is flagged, and no other line is
    for t in (dev, test):
        assert t["compared_found"] == t["compared_lines"] == t["found"]
    assert (f"it flagged every line whose name its exact check compares, {test['compared_found']} of "
            f"{test['compared_lines']} on test ({dev['compared_found']} of {dev['compared_lines']} on dev). The other "
            f"{test['lines'] - test['compared_lines']} test lines name what it doesn't compare") in readme
    missed = {e["name"]: c["repo"] for c in KEY if c["split"] == "test" for e in c["expected"]
              if e["name"] not in ROWS[c["id"]]["compared"]}
    for name, repo in (("compare_against_backend", "sqlalchemy/alembic"), ("Server", "mkdocs/mkdocs"),
                       ("sphinx_rtd_theme", "simonw/datasette"), ("W690", "hhatto/autopep8")):
        assert missed[name] == repo
    longest = max((e for c in KEY if c["split"] == "test" for e in c["expected"]), key=lambda e: e["days"])
    assert (longest["name"], longest["days"]) == ("SafeConfigParser", test["days_max"])
    assert 3.5 < test["days_max"] / 365.25 < 4
    assert (f"on test, a median of {test['days_median']:g} days over the {test['lines']} lines, and up to "
            f"{test['days_max']:,} days (alembic's `SafeConfigParser`, almost 4 years). On dev, a median of "
            f"{dev['days_median']:g} days, with {dev['fixed_same_day']} of the {dev['lines']} lines fixed the same day.") in readme
    other = {k: dev["other"][k] + test["other"][k] for k in dev["other"]}
    verdicts = Counter(x["verdict"] for x in HAND["other_still_there"])
    assert sum(verdicts.values()) == other["still_there"]
    assert (f"it also flagged {other['flagged']} lines the key doesn't list, since the key lists only the lines its "
            f"rules matched to a later fix. By the pinned commit, {other['changed']} of them had changed, {other['changed_in_a_fix']} in "
            f"a commit that fixed one of the case's key lines. A hand check of the {other['still_there']} still there "
            f"found {verdicts['false alarm']} false alarms and {verdicts['unclear']} unclear.") in readme
    assert (f"**Done:** the key: {real} real cases, of {mined} mined, in the 30 repositories' history since 2020. On "
            f"test, docs-proof would have flagged {test['found']} of the {test['lines']} lines a later commit fixed "
            f"({pct(test['recall'])}), including every line whose name it compares") in plan
    assert run_real.SINCE.startswith("2020-")


@pytest.mark.skipif(not HISTORY.is_dir(), reason="needs the fetched history (scripts/fetch_history.py)")
def test_the_key_matches_the_history():
    for case in MINED:
        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(place(case["repo"])), *args], capture_output=True, text=True,
                                  errors="replace", check=True).stdout
        assert git("rev-parse", f"{case['commit']}^1").strip() == case["parent"]
        assert git("log", "-1", "--format=%cs", case["commit"]).strip() == case["date"]
        for e in case["expected"]:
            line = git("show", f"{case['commit']}:{e['file']}").splitlines()[e["line"] - 1]
            assert build_real_cases.line_hash(line) == e["sha256"] and e["name"] in line
            assert line in git("show", f"{case['parent']}:{e['file']}").splitlines()  # the change left it as it was
            assert line in git("show", f"{e['fixed_by']}^1:{e['file']}").splitlines()  # still there until the fix
            assert git("log", "-1", "--format=%cs", e["fixed_by"]).strip() == e["fixed_on"]
