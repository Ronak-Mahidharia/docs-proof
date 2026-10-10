"""Checks on the committed answer key, the hand checks, and the published scores."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_cases  # noqa: E402
import run_baseline  # noqa: E402

REPOS = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
CASES = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
HAND = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_repositories_are_pinned_permissive_and_split_evenly():
    assert len(REPOS) == 30 and len({r["repo"] for r in REPOS}) == 30
    assert all(re.fullmatch(r"[0-9a-f]{40}", r["commit"]) for r in REPOS)
    assert {r["license"] for r in REPOS} <= {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "Unlicense"}
    assert sum(r["split"] == "dev" for r in REPOS) == sum(r["split"] == "test" for r in REPOS) == 15


def test_every_case_follows_its_repositorys_split_and_kind():
    split = {r["repo"]: r["split"] for r in REPOS}
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert c["split"] == split[c["repo"]], c["id"]
        assert c["group"] == build_cases.GROUP[c["kind"]], c["id"]
        lines = [(e["file"], e["line"]) for e in c["expected"]]
        assert len(lines) == len(set(lines)), c["id"]
        assert (c["group"] == "control") == (not lines), c["id"]  # controls have nothing to find; the rest do


def test_value_cases_are_all_checked_by_hand_and_hand_checks_name_real_cases():
    ids = {c["id"] for c in CASES}
    assert all(c["checked"] == "hand" for c in CASES if c["group"] == "value")
    for case_id, *_ in HAND["drop_lines"] + HAND["add_lines"]:
        assert case_id in ids or case_id in HAND["drop_cases"], case_id
    held_out = [s for s in HAND["name_group_samples"] if s["used_to"].startswith("estimate")]
    assert [(s["right"], s["lines"]) for s in held_out] == [(59, 60)]


def test_published_scores_come_from_the_committed_predictions():
    published = json.loads((ROOT / "data" / "results" / "exact-scores.json").read_text(encoding="utf-8"))
    assert run_baseline.report(CASES, run_baseline.load_predictions()) == published


def test_readme_numbers_match_the_key_and_the_scores():
    scores = json.loads((ROOT / "data" / "results" / "exact-scores.json").read_text(encoding="utf-8"))
    test, dev = scores["test"], scores["dev"]
    name, value = test["name"], test["value"]
    expected = [
        f"**{len(CASES)} planted changes in {len(REPOS)} real repositories.**",
        f"{sum(len(c['expected']) for c in CASES)} lines in all",
        f"{dev['cases']} dev cases in {dev['repos']} repositories, and {test['cases']} test cases in the other {test['repos']}",
        f"{dev['control']['cases'] + test['control']['cases']} cases change something no doc mentions",
        f"the {sum(c['group'] == 'value' for c in CASES)} cases that change a value",
        f"On the test split ({test['repos']} repositories, {test['cases']} cases)",
        f"**Renames** ({name['cases']} cases, {name['tp'] + name['fn']} lines): found all {name['tp']}, "
        f"with {name['fp']} false alarms (precision {100 * name['precision']:.1f}%).",
        f"**Changed values** ({value['cases']} cases, {value['tp'] + value['fn']} lines): found {value['tp']} of "
        f"{value['tp'] + value['fn']}.",
        f"**Controls** ({test['control']['cases']} cases): no false alarms.",
        f"the {name['fp']} are lines that name something else",
    ]
    assert name["fn"] == 0 and test["control"]["false_alarm_cases"] == 0
    for sentence in expected:
        assert sentence in README, sentence
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    done = (f"**Done:** {len(CASES)} cases in {len(REPOS)} repositories. On test, the baseline found all {name['tp']} rename "
            f"lines with {name['fp']} false alarms, and {value['tp']} of {value['tp'] + value['fn']} changed-value lines")
    assert done in plan


REPO_DIR = ROOT / "data" / "repos"


@pytest.mark.skipif(not REPO_DIR.is_dir(), reason="the pinned repositories aren't fetched (scripts/fetch_repos.py)")
def test_expected_lines_match_the_pinned_docs():
    for c in CASES:
        root = REPO_DIR / c["repo"].replace("/", "__")
        for e in c["expected"]:
            text = (root / e["file"]).read_text(encoding="utf-8", errors="replace").splitlines()[e["line"] - 1]
            assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == e["sha256"], (c["id"], e["file"], e["line"])
