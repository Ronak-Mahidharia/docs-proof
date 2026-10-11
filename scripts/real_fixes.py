"""Step 6: docs-proof's suggested fixes on real history, against the fixes the later commits made.

For each line in the real-history key (data/real_cases.jsonl), the later commit that fixed it shows what the line
became. Where that commit edited the line rather than rewrote it (the new line is at least ALIKE as similar to the
old one), the new line is kept. Measured:
- the rules' fixes for the lines docs-proof flagged (data/results/real.jsonl), each judged by hand against the
  code after the change and the later fix (data/hand_check.json, "real_fixes");
- the stricter check step 4 left for a new answer key: a fix may change a line only where the old name is. It's
  measured on the later commits' own edits (how often a right fix changes more), on the rules' fixes (which keep
  to it by construction), and on the agent's kept fixes for the planted key (data/results/agent-answers.jsonl).

    python scripts/real_fixes.py --run   # reads each later fix from the fetched history (scripts/fetch_history.py)
    python scripts/real_fixes.py         # the scores and docs/results/real-fixes.md, from the kept results
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_real_cases import History, hunks  # noqa: E402
from failures import explained  # noqa: E402
from fetch_history import place  # noqa: E402
from run_baseline import RESULTS  # noqa: E402
from run_fixes import short  # noqa: E402

ALIKE = 0.8  # how similar the later line must be to count as an edit of the old one, not a rewrite
VERDICTS = ("right", "incomplete", "wrong")


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def only_where(old: str, new: str, olds: list[str]) -> bool:
    """The stricter check: whether new is old with nothing changed outside the places where one of olds is."""
    spans = sorted(m.span() for o in olds if o for m in re.finditer(re.escape(o), old))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    if not merged:
        return new == old
    parts, last = [], 0
    for start, end in merged:
        parts.append(old[last:start])
        last = end
    parts.append(old[last:])
    return re.fullmatch(re.escape(parts[0]) + "".join("(.*?)" + re.escape(p) for p in parts[1:]), new, re.S) is not None


def later_line(h: History, fix: str, file: str, old: str) -> str | None:
    """What the later commit made of the line: the most similar line it added in the same place, if it's at
    least ALIKE as similar; None if the line was rewritten or removed."""
    for hunk in hunks(h, h.parent(fix), fix, [file]):
        if old in hunk["removed"]:
            scored = sorted(((difflib.SequenceMatcher(None, old, new).ratio(), new) for new in hunk["added"]), reverse=True)
            return scored[0][1] if scored and scored[0][0] >= ALIKE else None
    return None


def run_all(cases: list[dict], rows: dict[str, dict]) -> None:
    with (RESULTS / "real-fixes.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            h = History(place(case["repo"]))
            ours = {(x["file"], x["line"]): x["fix"] for x in rows[case["id"]]["flagged"]}
            for e in case["expected"]:
                old = h.lines(case["commit"], e["file"])[e["line"] - 1]
                out.write(json.dumps({"id": case["id"], "split": case["split"], "file": e["file"], "line": e["line"],
                                      "name": e["name"], "old": old, "later": later_line(h, e["fixed_by"], e["file"], old),
                                      "flagged": (e["file"], e["line"]) in ours, "ours": ours.get((e["file"], e["line"]))},
                                     ensure_ascii=False) + "\n")


def judged(lines: list[dict], hand: list[dict]) -> dict[tuple[str, str, int], dict]:
    """Each fix's hand verdict. Stops if a fix hasn't been judged, or a verdict names a line with no fix."""
    fixed = {(x["id"], x["file"], x["line"]) for x in lines if x["ours"] is not None}
    read = {(v["case"], v["file"], v["line"]): v for v in hand}
    if fixed != set(read):
        raise SystemExit(f"Judge these fixes by hand first: {sorted(fixed - set(read))}; no fix any more: {sorted(set(read) - fixed)}")
    return read


def agent_fixes() -> dict:
    """The stricter check on the agent's kept fixes for the planted key: per split and setting, how many of its
    right, wrong, and harmful fixes (fixes of false alarms) the check would stop."""
    import run_fixes as rf
    from docsproof import agent
    from run_baseline import load_cases
    cases = load_cases()
    rows = rf.jsonl(RESULTS / "fixes.jsonl")
    verdicts = rf.rule_verdicts(rows)
    answers = rf.load_answers()
    by_line = {(r["id"], x["file"], x["line"]): x for r in rows for x in r["lines"]}
    chosen = json.loads((RESULTS / "fixes-scores.json").read_text(encoding="utf-8"))["chosen"]
    out = {}
    for split in ("dev", "test"):
        settings = [(m, v) for m in rf.MODELS for v in agent.SYSTEMS] if split == "dev" else [(chosen["model"], chosen["version"])]
        for setting in settings:
            counts = {f"{v}_{k}": 0 for v in ("right", "wrong", "harm") for k in ("kept", "stopped")}
            for x in rf.line_outcomes(cases, rows, verdicts, answers, setting):
                if x["split"] != split or x["how"] != "agent" or x["text"] is None or x["verdict"] not in ("right", "wrong", "harm"):
                    continue
                line = by_line[(x["id"], x["file"], x["line"])]
                olds = [n for _, n in line["names"]] + [str(v.get("old")) for v in line["values"]]
                counts[f"{x['verdict']}_{'kept' if only_where(line['text'], x['text'], olds) else 'stopped'}"] += 1
            out[f"{split} {setting[0]} {setting[1]}"] = counts
    return out


def scores(lines: list[dict], read: dict) -> dict:
    for x in lines:  # the rules only swap the old name, so they keep to the stricter check
        if x["ours"] is not None and not only_where(x["old"], x["ours"], [x["name"]]):
            raise SystemExit(f"A rule fix changes more than the old name: {x['id']} {x['file']}:{x['line']}")
    out = {}
    for split in ("dev", "test"):
        part = [x for x in lines if x["split"] == split]
        fixed = [read[(x["id"], x["file"], x["line"])]["verdict"] for x in part if x["ours"] is not None]
        edited = [x for x in part if x["later"] is not None]
        out[split] = {"lines": len(part), "flagged": sum(x["flagged"] for x in part), "fixed": len(fixed),
                      **{v: fixed.count(v) for v in VERDICTS},
                      "later_edits": len(edited),
                      "later_edits_only_the_name": sum(only_where(x["old"], x["later"], [x["name"]]) for x in edited)}
    out["agent"] = agent_fixes()
    return out


def cell(text: str | None) -> str:
    """A doc line as inline code in a table cell, fenced with more backticks than any run inside it, so a line with
    reStructuredText's ``double backticks`` stays whole."""
    if text is None:
        return "-"
    text = short(text, 80).replace("|", "\\|")
    ticks = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    return f"{ticks} {text} {ticks}" if "`" in text else f"`{text}`"


def decision(s: dict) -> list[str]:
    """Why the stricter check isn't added, from the numbers. Stops if they no longer say so."""
    dev = [c for k, c in s["agent"].items() if k.startswith("dev ")]
    test = [c for k, c in s["agent"].items() if k.startswith("test ")][0]
    edits = s["dev"]["later_edits"] + s["test"]["later_edits"]
    more = edits - s["dev"]["later_edits_only_the_name"] - s["test"]["later_edits_only_the_name"]
    if any(c["right_stopped"] or c["wrong_stopped"] or c["harm_stopped"] for c in dev) or test["right_stopped"]:
        raise SystemExit("The stricter check now stops a dev fix or a right test fix: look again before writing the page.")
    return [f"**Not added.** On dev it stops none of the agent's fixes, in any of the {len(dev)} settings, so dev can't "
            "show that it helps. And a right fix often has to change more than the old name: the later commits did in "
            f"{more} of the {edits} lines they edited, and the {s['dev']['incomplete']} incomplete dev fixes above are "
            "incomplete for that reason, such as a help line that keeps the old option's description. On test it would "
            f"have stopped the agent's {test['wrong_stopped']} wrong fix and {test['harm_stopped']} fix of a false alarm, "
            f"and kept all {test['right_kept']} of its right fixes. That's known only from test, so it stays a limit."]


def markdown(s: dict, lines: list[dict], read: dict) -> str:
    out = ["# Fixes on real history", "", "Generated by `scripts/real_fixes.py`. Don't edit by hand.", "",
           "Each line in the real-history key was later fixed by a commit in the project, so that fix shows what the "
           "line became. Where the later commit edited the line rather than rewrote it (a new line at least "
           f"{ALIKE:.0%} as similar), its new line is shown. docs-proof's fixes are the rules' fixes (step 4) for the "
           "lines it flagged, each judged by hand against the code after the change and the later fix "
           "([data/hand_check.json](../../data/hand_check.json), \"real_fixes\"): right, incomplete (the right new "
           "name, but the line still says something the change made untrue), or wrong.", "",
           "| Split | Lines | Flagged | Fixed by the rules | Right | Incomplete | Wrong |", "|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        t = s[split]
        out.append(f"| {split} | {t['lines']} | {t['flagged']} | {t['fixed']} | {t['right']} | {t['incomplete']} | {t['wrong']} |")
    out += ["", "## The stricter check", "",
            "Step 4 found on test that its check that a fix keeps most of a line let two bad agent fixes through, and "
            "a stricter check (a fix may change a line only where the old name or value is) would have stopped both. "
            "Because it was found on test, it waited for new data:", ""]
    for split in ("dev", "test"):
        t = s[split]
        out.append(f"- **The later commits' own edits ({split}):** {t['later_edits_only_the_name']} of the "
                   f"{t['later_edits']} that edited a line changed only the old name; the rest also changed something "
                   "else in the line.")
    out += ["- **The rules' fixes** only ever swap the old name, so they keep to it (the script checks every one).", "",
            "| The agent's kept fixes (planted key) | Right, kept | Right, stopped | Wrong, kept | Wrong, stopped | "
            "Of a false alarm, kept | Of a false alarm, stopped |", "|---|---|---|---|---|---|---|"]
    for setting, c in s["agent"].items():
        out.append(f"| {setting} | {c['right_kept']} | {c['right_stopped']} | {c['wrong_kept']} | {c['wrong_stopped']} | "
                   f"{c['harm_kept']} | {c['harm_stopped']} |")
    out += [""] + decision(s)
    out += ["", "## What the fixes showed", "",
            f"- **On dev,** all {s['dev']['fixed']} fixes use the new name that replaced the old one. The "
            f"{s['dev']['incomplete']} incomplete ones leave something else the change made untrue: a help line's "
            "description, an option's type, an example's ID, and a sentence that says one file where several are allowed.",
            f"- **On test,** the {s['test']['wrong']} wrong fixes are coverage.py's: the change replaced three tracer "
            "variables with a different scheme, and the rules paired them one to one by how alike the names are. Pairing "
            "can't tell a rename from a replacement. It was found on test, so it isn't changed now.",
            f"- **The {s['test']['incomplete']} incomplete test fixes** keep a class's old module path: the change moved "
            "datasette's class as it renamed it.", "",
            "## Every fix", "", "| Split | Case | Doc line | docs-proof's fix | The later line | Verdict |",
            "|---|---|---|---|---|---|"]
    for x in lines:
        if x["ours"] is not None:
            v = read[(x["id"], x["file"], x["line"])]
            out.append(f"| {x['split']} | {x['id']} | {x['file']}:{x['line']} | {cell(x['ours'])} | {cell(x['later'])} | "
                       f"{v['verdict']}: {v['why']} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="read each later fix from the fetched history first")
    args = parser.parse_args()
    cases = jsonl(ROOT / "data" / "real_cases.jsonl")
    rows = {r["id"]: r for r in jsonl(RESULTS / "real.jsonl")}
    if args.run:
        run_all(cases, rows)
    lines = jsonl(RESULTS / "real-fixes.jsonl")
    hand = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8")).get("real_fixes", {}).get("fixes", [])
    read = judged(lines, hand)
    s = scores(lines, read)
    (RESULTS / "real-fixes-scores.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    (ROOT / "docs" / "results" / "real-fixes.md").write_text(markdown(s, lines, read), encoding="utf-8")
    for split in ("dev", "test"):
        t = s[split]
        print(f"{split}: {t['fixed']} fixes: {t['right']} right, {t['incomplete']} incomplete, {t['wrong']} wrong; "
              f"the later commits changed only the old name in {t['later_edits_only_the_name']} of {t['later_edits']} edited lines")


if __name__ == "__main__":
    explained(main)
