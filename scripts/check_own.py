"""Step 6: docs-proof on my own public projects (data/own_repos.json). Every pull request merged into main is
checked the way the GitHub Action would have checked it: the tool's check (src/docsproof/check.py) reads the
project just before the merge and just after it, with no AI. The histories are fetched by commit hash into
data/history/ (scripts/fetch_history.py), and never committed here.

Every line it flags is read by hand (data/hand_check.json, "own_repositories"), and the scores aren't written
until each one has a verdict: a doc line the merge left wrong, or a false alarm. The verdicts on lines a later
rule stopped flagging are kept too ("before_the_rule"), so the page says what the rule changed.

    python scripts/check_own.py --run   # fetches the two histories and checks every merge (a few seconds)
    python scripts/check_own.py         # the scores and docs/results/own.md, from the kept results
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_history import fetch, git, place  # noqa: E402
from run_baseline import RESULTS  # noqa: E402

REPOS = ROOT / "data" / "own_repos.json"
PR = re.compile(r"\(#(\d+)\)$")
ALL = {"wrong": "left wrong by the merge", "false alarm": "false alarms"}


def merges(repo: Path, pinned: str) -> list[tuple[str, str]]:
    """(commit, subject) for every commit on main's first-parent line that has a parent, oldest first."""
    out = git(repo, "log", "--first-parent", "--reverse", "--format=%H%x00%s", pinned).stdout.splitlines()
    return [tuple(line.split("\0", 1)) for line in out][1:]  # the first commit has no parent


def run_repo(entry: dict) -> list[dict]:
    """The check on each merge of one repository."""
    from docsproof.check import check
    from docsproof.cli import export_ref
    repo = place(entry["repo"])
    rows = []
    for commit, subject in merges(repo, entry["commit"]):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "before", Path(tmp) / "after"
            export_ref(repo, f"{commit}^1", before)
            export_ref(repo, commit, after)
            found = check(before, after)
        pr = PR.search(subject)
        rows.append({"repo": entry["repo"], "commit": commit, "pr": int(pr.group(1)) if pr else None, "subject": subject,
                     "flagged": [{"file": x.file, "line": x.line, "text": x.text, "names": [n for _, n in x.names],
                                  "why": x.why, "fix": x.fix.new[0] if x.fix else None} for x in found]})
    return rows


def run_all(repos: list[dict]) -> None:
    for entry in repos:
        print(fetch(entry))
    with (RESULTS / "own.jsonl").open("w", encoding="utf-8") as out:
        for entry in repos:
            for row in run_repo(entry):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")


def verdicts(rows: list[dict], hand: list[dict], before: list[dict] = ()) -> dict[tuple[str, str, str, int], dict]:
    """Each flagged line's hand verdict. Stops if a flagged line hasn't been read, a verdict names a line that
    isn't flagged any more, or a line kept as flagged before a rule is flagged again."""
    flagged = {(r["repo"], r["commit"], x["file"], x["line"]) for r in rows for x in r["flagged"]}
    read = {(h["repo"], h["commit"], file, line): h for h in hand for file, line in h["lines"]}
    if flagged != set(read):
        raise SystemExit(f"Read these flagged lines by hand first: {sorted(flagged - set(read))}; "
                         f"no longer flagged: {sorted(set(read) - flagged)}")
    again = flagged & {(h["repo"], h["commit"], file, line) for h in before for file, line in h["lines"]}
    if again:
        raise SystemExit(f"Flagged again, though kept as flagged only before a rule: {sorted(again)}")
    return read


def scores(repos: list[dict], rows: list[dict], read: dict, before: list[dict] = ()) -> dict:
    out = {}
    for entry in repos:
        part = [r for r in rows if r["repo"] == entry["repo"]]
        lines = [(r["repo"], r["commit"], x["file"], x["line"]) for r in part for x in r["flagged"]]
        out[entry["repo"]] = {"merges": len(part), "merges_flagged": sum(1 for r in part if r["flagged"]),
                              "lines": len(lines),
                              "wrong": sum(1 for k in lines if read[k]["verdict"] == "wrong"),
                              "false_alarms": sum(1 for k in lines if read[k]["verdict"] == "false alarm"),
                              "flagged_before_a_rule": sum(len(h["lines"]) for h in before if h["repo"] == entry["repo"])}
    return out


def groups(rows: list[dict], hand: list[dict]) -> list[str]:
    out = []
    for h in hand:
        row = next(r for r in rows if r["repo"] == h["repo"] and r["commit"] == h["commit"])
        out.append(f"- **{h['repo']}, pull request #{row['pr']}** (`{h['commit'][:7]}`, \"{PR.sub('', row['subject']).strip()}\"): "
                   f"{len(h['lines'])} lines flagged for `{h['name']}`, all {ALL[h['verdict']]}. {h['why']}")
    return out


def markdown(s: dict, repos: list[dict], rows: list[dict], hand: list[dict], before: list[dict] = ()) -> str:
    lines = ["# On my own projects", "", "Generated by `scripts/check_own.py`. Don't edit by hand.", "",
             "docs-proof checked every pull request merged into main in my two public projects, each just before and "
             "just after the merge, the way its GitHub Action would have, with no AI. Every flagged line was read by "
             "hand ([data/hand_check.json](../../data/hand_check.json), \"own_repositories\").", "",
             "| Project | Merges checked | Merges with a flagged line | Lines flagged | Left wrong by the merge | False alarms |",
             "|---|---|---|---|---|---|"]
    for entry in repos:
        t = s[entry["repo"]]
        lines.append(f"| [{entry['repo']}](https://github.com/{entry['repo']}) at `{entry['commit'][:7]}` | {t['merges']} | "
                     f"{t['merges_flagged']} | {t['lines']} | {t['wrong']} | {t['false_alarms']} |")
    lines += ["", "## What it flagged", ""] + (groups(rows, hand) or ["Nothing."])
    if before:
        lines += ["", "## Before the rule for ordinary words", "",
                  "A removed function or class whose name could be an ordinary word, such as `records`, now counts only "
                  "where the doc marks it as code: in a code block, in backticks, as a call, or after a dot "
                  "(`ordinary()` and `as_code()` in [src/docsproof/exact.py](../../src/docsproof/exact.py)). Before "
                  "that rule, docs-proof flagged these lines, and none of them marks the name as code:", ""]
        lines += groups(rows, before)
    lines += ["", "## Every merge", "", "| Project | Pull request | Commit | Lines flagged |", "|---|---|---|---|"]
    for r in rows:
        title = PR.sub("", r["subject"]).strip()
        number = f"#{r['pr']} " if r["pr"] else ""
        lines.append(f"| {r['repo'].split('/')[1]} | {number}{title} | `{r['commit'][:7]}` | {len(r['flagged'])} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="fetch the histories and check every merge first")
    args = parser.parse_args()
    repos = json.loads(REPOS.read_text(encoding="utf-8"))["repos"]
    if args.run:
        run_all(repos)
    rows = [json.loads(line) for line in (RESULTS / "own.jsonl").read_text(encoding="utf-8").splitlines()]
    own = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8")).get("own_repositories", {})
    hand, before = own.get("lines", []), own.get("before_the_rule", [])
    read = verdicts(rows, hand, before)
    s = scores(repos, rows, read, before)
    (RESULTS / "own-scores.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    (ROOT / "docs" / "results" / "own.md").write_text(markdown(s, repos, rows, hand, before), encoding="utf-8")
    for repo, t in s.items():
        print(f"{repo}: {t['merges']} merges, {t['lines']} lines flagged in {t['merges_flagged']}; "
              f"{t['wrong']} left wrong, {t['false_alarms']} false alarms")


if __name__ == "__main__":
    main()
