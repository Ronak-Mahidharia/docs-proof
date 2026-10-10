"""Checks on the sandbox's kept runs, and on the flags and scores worked out from them (scripts/run_sandbox.py)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_baseline  # noqa: E402
import run_sandbox  # noqa: E402
from build_cases import folder  # noqa: E402
from build_sandbox import sandboxed  # noqa: E402
from docsproof.run import documented  # noqa: E402

REPOS = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
CASES = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
RESULTS = ROOT / "data" / "results"
PINNED, RUNS = run_sandbox.load("pinned.jsonl"), run_sandbox.load("cases.jsonl")


def test_every_case_has_its_kept_run_in_order():
    assert [r["id"] for r in RUNS] == [c["id"] for c in CASES]


def test_flags_and_scores_come_from_the_kept_runs():
    predicted = run_sandbox.predictions(CASES, PINNED, RUNS)
    committed = [json.loads(line) for line in (RESULTS / "run.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["id"]: r["predicted"] for r in committed} == predicted
    scores = json.loads((RESULTS / "run-scores.json").read_text(encoding="utf-8"))
    assert scores["runner"] == run_baseline.report(CASES, {k: [(p["file"], p["line"]) for p in v]
                                                           for k, v in predicted.items()})
    assert scores["pinned"] == run_sandbox.pinned_summary(PINNED)
    assert scores["comparison"] == run_sandbox.comparison(CASES, RUNS, PINNED)


def test_every_audit_finding_is_checked_by_hand():
    findings = run_sandbox.audit_findings(PINNED)
    scores = json.loads((RESULTS / "run-scores.json").read_text(encoding="utf-8"))
    assert run_sandbox.hand_verdicts(findings) == scores["audit"]
    assert scores["audit"]["out_of_date"] + scores["audit"]["false_alarms"] == len(findings)
    extra = dict(findings[0], argv=["tiny", "--not-checked"])
    with pytest.raises(SystemExit):
        run_sandbox.hand_verdicts(findings + [extra])  # a new finding has to be checked first


def test_the_results_page_is_built_from_the_scores():
    scores = json.loads((RESULTS / "run-scores.json").read_text(encoding="utf-8"))
    page = (ROOT / "docs" / "results" / "run.md").read_text(encoding="utf-8")
    assert page == run_sandbox.markdown(scores)


REPO_DIR = ROOT / "data" / "repos"


@pytest.mark.skipif(not REPO_DIR.is_dir(), reason="the pinned repositories aren't fetched (scripts/fetch_repos.py)")
def test_kept_runs_are_the_commands_in_todays_docs():
    """If the docs reader changes, the kept runs are stale and the sandbox has to run again."""
    sizes = {}
    for entry in sandboxed(REPOS):
        plan = documented(folder(entry["repo"]))
        sizes[entry["repo"]] = len(plan)
        kept = [row for row in PINNED if row["repo"] == entry["repo"]]
        assert [run_sandbox.key_of(row) for row in kept] == list(plan), entry["repo"]
        for row, occurrences in zip(kept, plan.values()):
            assert row["documented"] == [{"file": c.file, "line": c.line, "options": [list(o) for o in c.options]}
                                         for c in occurrences], (entry["repo"], row["argv"])
    for run, case in zip(RUNS, CASES):
        assert run["ran"] == sizes.get(case["repo"], 0), case["id"]


def test_readme_and_plan_numbers_for_running():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    scores = json.loads((RESULTS / "run-scores.json").read_text(encoding="utf-8"))
    static = json.loads((RESULTS / "commands-scores.json").read_text(encoding="utf-8"))["commands"]["test"]
    t, pinned, audit, cmp = scores["runner"]["test"]["kinds"]["rename_option"], scores["pinned"], scores["audit"], \
        scores["comparison"]["test"]
    checks = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["run_audit"]["findings"]
    projects = {c["repo"] for c in checks if c["verdict"] == "out of date"}
    reasons = audit["reasons"]
    added = reasons["a command the user's own app defines"] + reasons["a command a plugin adds, and the plugin isn't installed"]
    read_flagged = static["kinds"]["rename_option"]["tp"] + static["kinds"]["rename_option"]["fp"]
    expected = [
        f"**Renamed options** ({t['cases']} cases, {t['tp'] + t['fn']} lines): flagged {t['tp'] + t['fp']} lines, with no "
        "false alarms.",
        f"the other {read_flagged - t['tp'] - t['fp']} lines that reading flags are in commands the program still accepts "
        "after the change",
        f"**An audit of the {pinned['repos']} repositories whose programs run:** {pinned['commands']:,} distinct command lines. "
        f"{pinned['findings']} are refused for a reason other than a missing input",
        f"Checked by hand, {audit['out_of_date']} doc lines in {len(projects)} projects are out of date",
        f"The other {audit['false_alarms']} are commands that the reader's own app or a plugin adds ({added}), quoted "
        f"arguments that span several lines ({reasons[next(r for r in reasons if r.startswith('a quoted'))]}), and a "
        f"placeholder ({reasons['a placeholder the reader took for words']}).",
    ]
    for sentence in expected:
        assert sentence in readme, sentence
    assert t["fp"] == 0 and cmp["still_accepted"] == read_flagged - t["tp"] - t["fp"] and cmp["other"] == 0
    assert [(o["case"], o["line"]) for o in cmp["only_run"]] == [("pypa/pipx:rename_env_var:1", 69)]
    flask = [p for r in map(json.loads, (RESULTS / "run.jsonl").read_text(encoding="utf-8").splitlines())
             if r["id"] == "pallets/flask:rename_option:3" for p in r["predicted"]]
    assert flask and flask[0]["proof"].endswith("No such option '--host'. (Did you mean one of: '--host2', '--port'?)")
    assert "flask's \"No such option '--host'. (Did you mean one of: '--host2', '--port'?)\"" in readme
    done = (f"**Done:** on test, it flagged {t['tp'] + t['fp']} of the {t['tp'] + t['fn']} renamed-option lines with no false "
            f"alarms, and an audit of {pinned['commands']:,} command lines found {audit['out_of_date']} doc lines in "
            f"{len(projects)} projects that their programs refuse")
    assert done in plan


@pytest.mark.skipif(not REPO_DIR.is_dir(), reason="the pinned repositories aren't fetched (scripts/fetch_repos.py)")
def test_the_committed_dockerfile_and_pins_are_current():
    from build_sandbox import PINS, SANDBOX, dockerfile
    repos = sandboxed(REPOS)
    assert (SANDBOX / "Dockerfile").read_text(encoding="utf-8") == dockerfile(repos, resolve=False)
    assert sorted(p.stem for p in PINS.glob("*.txt")) == sorted(folder(r["repo"]).name for r in repos)
