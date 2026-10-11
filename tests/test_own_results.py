"""Checks on docs-proof's run over my own public projects (step 6): the scores and docs/results/own.md come from
the kept results, every flagged line has a hand verdict, and the README and plan quote the numbers. Rerunning
needs the projects' history (scripts/check_own.py --run), so the last test checks the kept results against it
when it's there."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import check_own  # noqa: E402
from docsproof.commands import code_block_lines  # noqa: E402
from docsproof.exact import as_code, ordinary  # noqa: E402
from fetch_history import place  # noqa: E402

REPOS = json.loads((ROOT / "data" / "own_repos.json").read_text(encoding="utf-8"))["repos"]
ROWS = [json.loads(line) for line in (ROOT / "data" / "results" / "own.jsonl").read_text(encoding="utf-8").splitlines()]
SCORES = json.loads((ROOT / "data" / "results" / "own-scores.json").read_text(encoding="utf-8"))
OWN = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["own_repositories"]
HAND, BEFORE = OWN["lines"], OWN["before_the_rule"]


def test_the_scores_and_the_page_come_from_the_kept_results():
    read = check_own.verdicts(ROWS, HAND, BEFORE)
    s = check_own.scores(REPOS, ROWS, read, BEFORE)
    assert s == SCORES
    assert check_own.markdown(s, REPOS, ROWS, HAND, BEFORE) == (ROOT / "docs" / "results" / "own.md").read_text(encoding="utf-8")


def test_every_flagged_line_has_a_hand_verdict():
    assert all(h["verdict"] in check_own.ALL and h["why"] for h in HAND + BEFORE)
    group = {**BEFORE[0], "lines": BEFORE[0]["lines"][:1]}
    rows = copy.deepcopy(ROWS)
    row = next(r for r in rows if r["commit"] == group["commit"])
    row["flagged"].append({"file": group["lines"][0][0], "line": group["lines"][0][1]})
    with pytest.raises(SystemExit, match="Read these flagged lines by hand first"):
        check_own.verdicts(rows, HAND, [])
    with pytest.raises(SystemExit, match="no longer flagged"):
        check_own.verdicts(ROWS, HAND + [group], [])
    with pytest.raises(SystemExit, match="Flagged again"):
        check_own.verdicts(rows, HAND + [group], BEFORE)


def test_the_lines_flagged_before_the_ordinary_word_rule():
    """The 23 false alarms of Car Safety Checker's PR #8 aren't flagged since the rule, and the name is one it covers."""
    assert [(h["name"], len(h["lines"]), h["verdict"]) for h in BEFORE] == [("records", 23, "false alarm")]
    assert all(ordinary(h["name"]) for h in BEFORE)
    flagged = {(r["commit"], x["file"], x["line"]) for r in ROWS for x in r["flagged"]}
    assert not flagged & {(h["commit"], file, line) for h in BEFORE for file, line in h["lines"]}


def test_each_merge_is_a_pull_request_of_a_pinned_project():
    assert {r["repo"] for r in ROWS} == {e["repo"] for e in REPOS}
    for entry in REPOS:
        numbers = [r["pr"] for r in ROWS if r["repo"] == entry["repo"]]
        assert numbers == list(range(1, len(numbers) + 1))  # every pull request, in order
        assert next(r for r in reversed(ROWS) if r["repo"] == entry["repo"])["commit"] == entry["commit"]


def test_readme_and_plan_numbers_for_my_own_projects():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    csc, cf = SCORES["Ronak-Mahidharia/car-safety-checker"], SCORES["Ronak-Mahidharia/control-finder"]
    assert cf["lines"] == cf["flagged_before_a_rule"] == 0
    assert f"- **Control Finder** ({cf['merges']} merges): nothing flagged." in readme
    assert csc["lines"] == 0 and len(BEFORE) == 1 and BEFORE[0]["verdict"] == "false alarm"
    assert (f"- **Car Safety Checker** ({csc['merges']} merges): nothing flagged since the rule for ordinary words "
            f"(above). Before it, {csc['flagged_before_a_rule']} lines were flagged, all in one pull request and all "
            "false alarms: that pull request removed a function named `records`") in readme
    merges = sum(t["merges"] for t in SCORES.values())
    before = sum(t["flagged_before_a_rule"] for t in SCORES.values())
    assert (f"on {merges} merged pull requests in my two public projects, it flagged {before} lines, all false alarms "
            "from one removed function named with an ordinary word, `records`") in plan


@pytest.mark.skipif(not all(place(e["repo"]).is_dir() for e in REPOS), reason="needs the projects' history (scripts/check_own.py --run)")
def test_the_kept_merges_match_the_history():
    for entry in REPOS:
        repo = place(entry["repo"])
        kept = [(r["commit"], r["subject"]) for r in ROWS if r["repo"] == entry["repo"]]
        assert check_own.merges(repo, entry["commit"]) == kept

        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()
        # each merge's parent is the merge before it, and the first one's is the project's first commit
        parents = [git("rev-parse", f"{commit}^1") for commit, _ in kept]
        assert parents == [git("rev-list", "--max-parents=0", entry["commit"])] + [commit for commit, _ in kept[:-1]]
        # the lines flagged before the rule name it in a sentence, not as code
        for h in (h for h in BEFORE if h["repo"] == entry["repo"]):
            for file, line in h["lines"]:
                lines = git("show", f"{h['commit']}:{file}").splitlines()
                text = lines[line - 1]
                assert h["name"] in text and not as_code(text, h["name"], line in code_block_lines(file, lines))
