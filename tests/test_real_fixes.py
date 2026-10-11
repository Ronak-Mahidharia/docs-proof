"""Checks on docs-proof's fixes on real history (step 6, scripts/real_fixes.py): the scores and
docs/results/real-fixes.md come from the kept results and hand verdicts, the stricter check does what it says, and
the README and plan quote the numbers. Reading the later fixes needs the fetched history, so the last test checks
the kept lines against it when it's there."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import real_fixes  # noqa: E402
from build_real_cases import History  # noqa: E402
from fetch_history import HISTORY, place  # noqa: E402

LINES = real_fixes.jsonl(ROOT / "data" / "results" / "real-fixes.jsonl")
SCORES = json.loads((ROOT / "data" / "results" / "real-fixes-scores.json").read_text(encoding="utf-8"))
HAND = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["real_fixes"]["fixes"]
KEY = real_fixes.jsonl(ROOT / "data" / "real_cases.jsonl")


def test_the_scores_and_the_page_come_from_the_kept_results():
    read = real_fixes.judged(LINES, HAND)
    s = real_fixes.scores(LINES, read)
    assert s == SCORES
    assert real_fixes.markdown(s, LINES, read) == (ROOT / "docs" / "results" / "real-fixes.md").read_text(encoding="utf-8")


def test_every_fix_has_a_hand_verdict():
    assert all(v["verdict"] in real_fixes.VERDICTS and v["why"] for v in HAND)
    with pytest.raises(SystemExit, match="Judge these fixes by hand first"):
        real_fixes.judged(LINES, HAND[1:])
    with pytest.raises(SystemExit, match="no fix any more"):
        real_fixes.judged(LINES, HAND + [{**HAND[0], "line": 1}])


def test_the_kept_lines_are_the_keys_lines():
    expected = [(c["id"], e["file"], e["line"]) for c in KEY for e in c["expected"]]
    assert [(x["id"], x["file"], x["line"]) for x in LINES] == expected


def test_the_stricter_check():
    only = real_fixes.only_where
    assert only("Use --old now.", "Use --new now.", ["--old"])
    assert not only("Use --old now.", "Use --new later.", ["--old"])
    assert only("a `x` and `x`", "a `y` and `z`", ["x"])  # each place the old name is may change
    assert not only("--old PATH   Location", "--olds PATH  Location", ["--old"])  # re-aligned columns change more
    assert only("ab", "cd", ["ab", "b"])  # overlapping places count as one
    assert only("Use --old now.", "Use  now.", ["--old"])  # removing the old name changes only where it was
    assert only("same", "same", []) and not only("same", "other", [])


def test_the_rules_fixes_keep_to_the_stricter_check():
    fixes = [x for x in LINES if x["ours"] is not None]
    assert fixes and all(real_fixes.only_where(x["old"], x["ours"], [x["name"]]) for x in fixes)
    lines = copy.deepcopy(LINES)
    first = next(x for x in lines if x["ours"] is not None)
    first["ours"] += " (and more)"
    with pytest.raises(SystemExit, match="A rule fix changes more than the old name"):
        real_fixes.scores(lines, real_fixes.judged(LINES, HAND))


def test_the_decision_waits_when_the_numbers_change():
    s = copy.deepcopy(SCORES)
    next(c for k, c in s["agent"].items() if k.startswith("dev "))["right_stopped"] = 1
    with pytest.raises(SystemExit, match="look again"):
        real_fixes.decision(s)


def test_readme_and_plan_numbers_for_the_fixes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    dev, test = SCORES["dev"], SCORES["test"]
    fixed = dev["fixed"] + test["fixed"]
    right, incomplete, wrong = (dev[v] + test[v] for v in ("right", "incomplete", "wrong"))
    edits = dev["later_edits"] + test["later_edits"]
    more = edits - dev["later_edits_only_the_name"] - test["later_edits_only_the_name"]
    assert dev["wrong"] == 0 and test["right"] == 0
    assert (f"a hand check of the {fixed} lines the rules would have fixed found {right} right, {incomplete} incomplete, "
            f"and {wrong} wrong. On dev, all {dev['fixed']} used the new name that replaced the old one, and "
            f"{dev['incomplete']} left something else the change made untrue") in readme
    assert f"On test, the {test['wrong']} wrong ones are coverage.py's" in readme
    assert all(not any(c[f"{v}_stopped"] for v in ("right", "wrong", "harm")) for k, c in SCORES["agent"].items() if k.startswith("dev "))
    assert (f"it stops none of the agent's dev fixes, and the later commits changed more than the old name in {more} of "
            f"the {edits} lines they edited, so it isn't added.") in readme
    assert (f"a hand check found {right} of the rules' {fixed} fixes right, {incomplete} incomplete, and {wrong} wrong, "
            f"all {wrong} from pairing coverage.py's replaced variables one to one") in plan


@pytest.mark.skipif(not HISTORY.is_dir(), reason="needs the fetched history (scripts/fetch_history.py)")
def test_the_kept_lines_match_the_history():
    cases = {c["id"]: c for c in KEY}
    for x in LINES:
        case = cases[x["id"]]
        e = next(e for e in case["expected"] if (e["file"], e["line"]) == (x["file"], x["line"]))
        h = History(place(case["repo"]))
        assert h.lines(case["commit"], x["file"])[x["line"] - 1] == x["old"]
        assert real_fixes.later_line(h, e["fixed_by"], x["file"], x["old"]) == x["later"]
