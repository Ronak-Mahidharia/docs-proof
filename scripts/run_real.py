"""Step 6: docs-proof on real history. For each case in the real-history key (data/real_cases.jsonl), the tool's
check (src/docsproof/check.py, the function the docs-proof command runs) reads the project just before the change
and just after it, from the fetched history (scripts/fetch_history.py), the way it would have on the day.

Measured: of the doc lines a later commit had to fix, how many it would have flagged then, by the kind of
reference, and how long those lines stayed wrong. Each expected line is also sorted by whether docs-proof's exact
check compares its name at all: the names it saw the change remove (src/docsproof/exact.py). Lines it flags that
the key doesn't list are counted and sorted, but not scored: the key lists only the lines its rules matched to a
later fix, so a line it doesn't list may be a false alarm, or a line that was fixed in a way the rules don't
match, or one that's still wrong.

    python scripts/run_real.py --run   # the checks (a few minutes); needs the fetched history
    python scripts/run_real.py         # the scores and docs/results/real.md, from the kept results
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_real_cases import KIND, references  # noqa: E402
from docsproof.docs import token_pattern  # noqa: E402
from fetch_history import SINCE, place  # noqa: E402
from run_baseline import RESULTS, pct  # noqa: E402

KEY = ROOT / "data" / "real_cases.jsonl"
KINDS = {"option": "long options (--name)", "path": "file paths",
         "env": "names in capitals (such as environment variables)",
         "identifier": "names in backticks (functions, classes, parameters, attributes, values)"}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace")


def changed_in(repo: Path, start: str, pinned: str, file: str, text: str) -> str | None:
    """The first first-parent commit after `start`, up to the pinned one, whose version of the file no longer has
    the line's text (or no longer has the file); None if every version keeps it."""
    for commit in git(repo, "log", "--first-parent", "--reverse", "--format=%H", f"{start}..{pinned}", "--",
                      file).stdout.split():
        shown = git(repo, "show", f"{commit}:{file}")
        if shown.returncode != 0 or text not in shown.stdout.splitlines():
            return commit
    return None


def run_case(case: dict) -> dict:
    """The tool's findings for one real change, read from the history, and which of the key's names its exact
    check saw removed. For each flagged line the key doesn't list: its text, and whether that's still in the file
    at the pinned commit; if not, the commit that first changed it, the names the exact check flagged it for,
    whether the key's rules read one of them in the line, and whether that commit's version of the file still
    names it."""
    from docsproof.check import check
    from docsproof.cli import export_ref
    from docsproof.exact import removed_names
    repo = place(case["repo"])
    pinned = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))
    pinned = next(r["commit"] for r in pinned["repos"] if r["repo"] == case["repo"])
    with tempfile.TemporaryDirectory() as tmp:
        before, after = Path(tmp) / "before", Path(tmp) / "after"
        export_ref(repo, case["parent"], before)
        export_ref(repo, case["commit"], after)
        found = check(before, after)
        gone = {name for _, name, _ in removed_names(before, after)}
    expected = {(e["file"], e["line"]) for e in case["expected"]}
    flagged = []
    for x in found:
        row = {"file": x.file, "line": x.line, "why": x.why, "fix": x.fix.new[0] if x.fix else None}
        if (x.file, x.line) not in expected:
            now = git(repo, "show", f"{pinned}:{x.file}")
            row["text"] = x.text
            row["still_there"] = now.returncode == 0 and x.text in now.stdout.splitlines()
            if not row["still_there"]:
                commit = changed_in(repo, case["commit"], pinned, x.file, x.text)
                seen = {name for _, name in references(x.text)}
                names = [(kind, name) for kind, name in x.names if name in seen]
                later = git(repo, "show", f"{commit}:{x.file}").stdout if commit else ""
                row.update(changed_in=commit, names=[name for _, name in x.names], key_rules_see=bool(names),
                           name_kept=any(token_pattern(name, KIND[kind]).search(later) for kind, name in names))
        flagged.append(row)
    return {"id": case["id"], "compared": sorted({e["name"] for e in case["expected"]} & gone), "flagged": flagged}


def run_all(cases: list[dict]) -> None:
    with ProcessPoolExecutor(8) as pool:
        rows = list(pool.map(run_case, cases))
    with (RESULTS / "real.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")


def scores(cases: list[dict], rows: dict[str, dict]) -> dict:
    out = {}
    for split in ("dev", "test"):
        part = [c for c in cases if c["split"] == split]
        found, kinds, days, compared = [], {}, [], [0, 0]
        other = {"flagged": 0, "still_there": 0, "changed": 0, "changed_in_a_fix": 0, "unseen_by_key_rules": 0,
                 "name_kept": 0}
        for case in part:
            row = rows[case["id"]]
            flagged = {(x["file"], x["line"]) for x in row["flagged"]}
            expected = {(e["file"], e["line"]) for e in case["expected"]}
            fixes = {e["fixed_by"] for e in case["expected"]}
            for x in row["flagged"]:
                if (x["file"], x["line"]) in expected:
                    continue
                other["flagged"] += 1
                if x["still_there"]:
                    other["still_there"] += 1
                    continue
                other["changed"] += 1
                other["changed_in_a_fix"] += x["changed_in"] in fixes
                other["unseen_by_key_rules"] += not x["key_rules_see"]
                other["name_kept"] += x["key_rules_see"] and x["name_kept"]
            for e in case["expected"]:
                hit = (e["file"], e["line"]) in flagged
                found.append(hit)
                k = kinds.setdefault(e["kind"], {"lines": 0, "found": 0})
                k["lines"] += 1
                k["found"] += hit
                if e["name"] in row["compared"]:
                    compared[0] += 1
                    compared[1] += hit
                days.append(e["days"])
        out[split] = {"cases": len(part), "lines": len(found), "found": sum(found),
                      "recall": round(sum(found) / len(found), 3) if found else None,
                      "cases_all_found": sum(1 for c in part if all((e["file"], e["line"]) in
                                             {(x["file"], x["line"]) for x in rows[c["id"]]["flagged"]} for e in c["expected"])),
                      "kinds": {kind: kinds[kind] for kind in KINDS if kind in kinds},
                      "compared_lines": compared[0], "compared_found": compared[1],
                      "other": other,
                      "days_median": statistics.median(days) if days else None, "days_max": max(days) if days else None,
                      "fixed_same_day": sum(1 for d in days if d == 0)}
    return out


def markdown(s: dict, cases: list[dict], rows: dict[str, dict]) -> str:
    mining = json.loads((RESULTS / "real-mining.json").read_text(encoding="utf-8"))["hand_check"]
    lines = ["# Real history", "", "Generated by `scripts/run_real.py`. Don't edit by hand.", "",
             f"The second answer key comes from the 30 repositories' own history since {SINCE}. A case is a commit that "
             "removed a reference from the code (an option, a name, an environment variable, or a file) while doc lines "
             "still mentioned it, and its expected lines are the ones a later commit had to fix. The cases were mined "
             "with rules worked out on dev, and every one was checked by hand "
             "([data/hand_check.json](../../data/hand_check.json), \"real_history\").", "",
             "For each case, docs-proof's check read the project just before the change and just after it, the way it "
             "would have on the day, with no AI.", "",
             "| Split | Cases mined | Real, after the hand check | Lines a later commit fixed | Flagged by docs-proof "
             "at the time | Recall | Cases with every line flagged |", "|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        t, m = s[split], mining[split]
        lines.append(f"| {split} | {m['mined_cases']} | {t['cases']} | {t['lines']} | {t['found']} | {pct(t['recall'])} | "
                     f"{t['cases_all_found']} of {t['cases']} |")
    lines += ["", "## What it compares", "",
              "docs-proof's exact check compares four kinds of names before and after a change: long options, top-level "
              "functions and classes, environment variables the code reads, and files. A line whose name it compares "
              "is one whose name it saw the change remove.", "",
              "| Split | Lines whose name it compares | Flagged | Other lines | Flagged |", "|---|---|---|---|---|"]
    for split in ("dev", "test"):
        t = s[split]
        lines.append(f"| {split} | {t['compared_lines']} | {t['compared_found']} | {t['lines'] - t['compared_lines']} | "
                     f"{t['found'] - t['compared_found']} |")
    lines += ["", "The other lines name what it doesn't compare: a method, a parameter or attribute, another library's "
              "name, a dependency or tool, or a value. The table of every case, below, marks each line.", "",
              "## By the kind of reference", "", "| Split | Kind | Lines | Flagged |", "|---|---|---|---|"]
    for split in ("dev", "test"):
        for kind, k in s[split]["kinds"].items():
            lines.append(f"| {split} | {KINDS[kind]} | {k['lines']} | {k['found']} |")
    lines += ["", "## How long the lines stayed wrong", ""]
    for split in ("dev", "test"):
        t = s[split]
        lines.append(f"- **{split}:** a median of {t['days_median']:g} days from the change to the fix, and up to "
                     f"{t['days_max']:,} days; fixed the same day: {t['fixed_same_day']} of {t['lines']} lines.")
    lines += ["", "## Every case", "", "| Split | Case | Reference | Doc line | Days wrong | Name compared | Flagged |",
              "|---|---|---|---|---|---|---|"]
    for case in cases:
        row = rows[case["id"]]
        flagged = {(x["file"], x["line"]) for x in row["flagged"]}
        for e in case["expected"]:
            lines.append(f"| {case['split']} | {case['id']} | `{e['name']}` | {e['file']}:{e['line']} | {e['days']:,} | "
                         f"{'yes' if e['name'] in row['compared'] else 'no'} | "
                         f"{'yes' if (e['file'], e['line']) in flagged else 'no'} |")
    hand = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["real_history"]["other_still_there"]
    other = {k: s["dev"]["other"][k] + s["test"]["other"][k] for k in s["dev"]["other"]}
    lines += ["", "## Not scored", "",
              f"docs-proof also flagged {s['dev']['other']['flagged']} other lines in dev's cases and "
              f"{s['test']['other']['flagged']} in test's. The key lists only the lines its rules matched to a later "
              f"fix, so these aren't scored. By the pinned commit, {other['changed']} of them had changed, {other['changed_in_a_fix']} "
              "of those in a commit that fixed one of the case's key lines. In "
              f"{other['unseen_by_key_rules']} of the {other['changed']}, the key's rules don't read the removed name: they read a function's or "
              "class's name only in backticks, alone or at the end of a dotted name, so `return PluginSQL(` in an "
              "example doesn't count. For the other "
              f"{other['name_kept']}, the commit that changed the line still names it in that file. "
              f"{other['still_there']} were still there, and were read by hand:", ""]
    lines += [f"- {x['case']}: {x['file']}:{x['line']}: {x['verdict']}. {x['why']}" for x in hand]
    lines.append("")
    return "\n".join(lines)


def gate(rows: dict[str, dict], hand: list[dict]) -> None:
    """Stops before the scores are written unless every flagged line the key doesn't list that's still there has
    been read by hand, and every one that changed fits the page's account of it: flagged for a removed name, which
    the key's rules either don't read in the line or still find in the file after the change."""
    still = {(i, x["file"], x["line"]) for i, r in rows.items() for x in r["flagged"] if x.get("still_there")}
    read = {(x["case"], x["file"], x["line"]) for x in hand}
    if still != read:
        raise SystemExit(f"Read these flagged lines by hand first: {sorted(still - read)}; no longer flagged: {sorted(read - still)}")
    odd = [(i, x["file"], x["line"]) for i, r in rows.items() for x in r["flagged"]
           if x.get("still_there") is False and (not x["names"] or (x["key_rules_see"] and not x["name_kept"]))]
    if odd:
        raise SystemExit(f"Read these changed lines by hand first: {sorted(odd)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the checks on the history first")
    args = parser.parse_args()
    cases = jsonl(KEY)
    if args.run:
        run_all(cases)
    rows = {r["id"]: r for r in jsonl(RESULTS / "real.jsonl")}
    if set(rows) != {c["id"] for c in cases}:
        raise SystemExit("The kept results don't match the key; run with --run.")
    gate(rows, json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["real_history"]["other_still_there"])
    s = scores(cases, rows)
    (RESULTS / "real-scores.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    (ROOT / "docs" / "results" / "real.md").write_text(markdown(s, cases, rows), encoding="utf-8")
    for split in ("dev", "test"):
        t = s[split]
        print(f"{split}: {t['found']} of {t['lines']} lines flagged at the time ({pct(t['recall'])}), "
              f"{t['cases_all_found']} of {t['cases']} cases complete; {t['compared_found']} of the "
              f"{t['compared_lines']} lines whose name it compares; {t['other']['flagged']} other lines flagged")


if __name__ == "__main__":
    main()
