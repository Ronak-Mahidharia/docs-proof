"""Step 2, second half: the documented commands, run in the sandbox (scripts/build_sandbox.py builds it).

1. Audit: every runnable documented command in the repositories whose programs run in the sandbox, as pinned
   (data/results/runs/pinned.jsonl). Commands the program refuses for a word it doesn't know are checked by
   hand in data/hand_check.json ("run_audit").
2. The answer key: each case in those repositories, with its planted change applied in a fresh sandbox. The
   commands are run again, and the ones the change made the program refuse are flagged (data/results/run.jsonl).
   Only the runs whose result changed are kept (data/results/runs/cases.jsonl), so the flags and scores can be
   worked out again without Docker.

    python scripts/run_sandbox.py --run   # the runs (about half an hour), then the scores
    python scripts/run_sandbox.py         # the scores and docs/results/run.md, from the kept runs
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cases import folder  # noqa: E402
from build_sandbox import sandboxed  # noqa: E402
from build_sandbox import SKIP  # noqa: E402
from docsproof.commands import commands  # noqa: E402
from docsproof.run import MISSING_INPUT, documented, flagged_lines, proof, refused, run_in_sandbox, runnable  # noqa: E402
from run_baseline import RESULTS, load_cases, pct, report  # noqa: E402

RUNS = RESULTS / "runs"
WORKERS = 7
KIND = {"unknown_option": "an option it doesn't know", "unknown_command": "a command it doesn't know"}


def key_of(row: dict) -> tuple:
    return tuple(row["argv"]), tuple(tuple(pair) for pair in row["env"])


def run_all(repos: list[dict], cases: list[dict]) -> None:
    """Run every job in the sandbox and keep the results (pinned.jsonl and cases.jsonl)."""
    plan = {entry["repo"]: documented(folder(entry["repo"])) for entry in repos}
    jobs = [(entry["repo"], None) for entry in repos] + [(c["repo"], c) for c in cases if c["repo"] in plan]
    results: dict[tuple, dict] = {}
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(run_in_sandbox, folder(repo).name, list(plan[repo]), case["edit"] if case else None):
                   (repo, case["id"] if case else None) for repo, case in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]] = future.result()
            if done % 20 == 0 or done == len(jobs):
                print(f"  {done} of {len(jobs)} sandbox runs", flush=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    not_run = {entry["repo"]: [{"file": c.file, "line": c.line, "reason": runnable(c)}
                               for c in commands(folder(entry["repo"])) if runnable(c)] for entry in repos}
    (RUNS / "not-run.json").write_text(json.dumps(not_run, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with (RUNS / "pinned.jsonl").open("w", encoding="utf-8") as out:
        for entry in repos:
            before = results[(entry["repo"], None)]
            for key, occurrences in plan[entry["repo"]].items():
                where = [{"file": c.file, "line": c.line, "options": [list(o) for o in c.options]} for c in occurrences]
                out.write(json.dumps({"repo": entry["repo"], "argv": list(key[0]), "env": [list(p) for p in key[1]],
                                      **before[key], "documented": where}, ensure_ascii=False) + "\n")
    with (RUNS / "cases.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            if case["repo"] not in plan:
                out.write(json.dumps({"id": case["id"], "ran": 0, "changed": []}) + "\n")
                continue
            before, after = results[(case["repo"], None)], results[(case["repo"], case["id"])]
            changed = [{"argv": list(k[0]), "env": [list(p) for p in k[1]], **after[k]} for k in plan[case["repo"]]
                       if after[k] != before[k]]
            out.write(json.dumps({"id": case["id"], "ran": len(plan[case["repo"]]), "changed": changed},
                                 ensure_ascii=False) + "\n")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (RUNS / name).read_text(encoding="utf-8").splitlines()]


def predictions(cases: list[dict], audit: list[dict], runs: list[dict]) -> dict[str, list[dict]]:
    """Doc lines flagged for each case, worked out from the kept runs alone."""
    from docsproof.commands import Command
    before = {(row["repo"], key_of(row)): row for row in audit}
    by_case = {row["id"]: row for row in runs}
    out = {}
    for case in cases:
        flagged: dict[tuple[str, int], dict] = {}
        for after in by_case[case["id"]]["changed"]:
            key = key_of(after)
            original = before[(case["repo"], key)]
            words = refused(original, after)
            if words is None:
                continue
            where = [Command(d["file"], d["line"], "", "", tuple(tuple(o) for o in d["options"]))
                     for d in original["documented"]]
            for line in sorted(flagged_lines(where, words)):
                flagged.setdefault(line, {"file": line[0], "line": line[1], "argv": after["argv"],
                                          "proof": proof(key[0], after)})
        out[case["id"]] = [flagged[k] for k in sorted(flagged)]
    return out


def audit_findings(audit: list[dict]) -> list[dict]:
    """Commands the program refuses, as pinned, for a word it doesn't know or any reason other than a missing
    input. Each is checked by hand."""
    return [row for row in audit if row["unknown"]
            or (row["outcome"] == "rejected" and not MISSING_INPUT.search(row["message"]))]


def hand_verdicts(findings: list[dict]) -> dict:
    """The hand check of the audit's findings. Stops if one hasn't been checked, or a check names a finding
    that's no longer there."""
    checks = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8")).get("run_audit", {})
    checks = checks.get("findings", [])
    found = {(row["repo"], " ".join(row["argv"])) for row in findings}
    checked = {(c["repo"], c["command"]) for c in checks}
    if found != checked:
        raise SystemExit(f"Check these sandbox findings by hand first: {sorted(found - checked)}; "
                         f"no longer found: {sorted(checked - found)}")
    reasons: dict[str, int] = {}
    for c in checks:
        if c["verdict"] == "false alarm":
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
    return {"out_of_date": sum(c["verdict"] == "out of date" for c in checks),
            "false_alarms": sum(reasons.values()), "reasons": dict(sorted(reasons.items(), key=lambda r: -r[1]))}


OUTCOMES = {"accepted": "the parser took the command line", "rejected": "the parser refused it",
            "failed": "stopped for another reason (such as reading a missing input)",
            "succeeded": "ran to the end", "timeout": "took longer than the time limit", "missing": "program not installed"}


def pinned_summary(pinned: list[dict]) -> dict:
    """What running the documented commands, as pinned, showed."""
    not_run = json.loads((RUNS / "not-run.json").read_text(encoding="utf-8"))
    outcomes: dict[str, int] = {}
    for row in pinned:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    return {"repos": len({row["repo"] for row in pinned}), "commands": len(pinned),
            "documented": sum(len(row["documented"]) for row in pinned),
            "not_run": sum(len(v) for v in not_run.values()),
            "outcomes": dict(sorted(outcomes.items(), key=lambda o: -o[1])),
            "missing_input": sum(1 for row in pinned if row["outcome"] == "rejected" and not row["unknown"]
                                 and MISSING_INPUT.search(row["message"])),
            "findings": len(audit_findings(pinned))}


def comparison(cases: list[dict], runs: list[dict], pinned: list[dict]) -> dict:
    """For renamed options: the expected lines that reading the commands flags (step 2a) and running doesn't, by
    what the program did after the change; and the lines only running flags."""
    static = {r["id"]: {(p["file"], p["line"]) for p in r["predicted"]}
              for r in map(json.loads, (RESULTS / "commands.jsonl").read_text(encoding="utf-8").splitlines())}
    ran = {r["id"]: {(p["file"], p["line"]): p for p in r["predicted"]}
           for r in map(json.loads, (RESULTS / "run.jsonl").read_text(encoding="utf-8").splitlines())}
    before = {(row["repo"], key_of(row)): row for row in pinned}
    by_case = {r["id"]: r for r in runs}
    out = {}
    for split in ("dev", "test"):
        still_accepted, other, only_run = 0, 0, []
        for case in cases:
            if case["split"] != split:
                continue
            expected = {(e["file"], e["line"]) for e in case["expected"]}
            if case["kind"] == "rename_option":
                for line in (static[case["id"]] & expected) - set(ran[case["id"]]):
                    rows = [r for (repo, _), r in before.items() if repo == case["repo"]
                            and any((d["file"], d["line"]) == line or (d["file"] == line[0] and any(l == line[1] for _, l in d["options"]))
                                    for d in r["documented"])]
                    changed = {key_of(c) for c in by_case[case["id"]]["changed"]}
                    if rows and all(r["outcome"] == "accepted" and key_of(r) not in changed for r in rows):
                        still_accepted += 1
                    else:
                        other += 1
            for line, p in sorted(ran[case["id"]].items()):
                if line not in static[case["id"]] and line in expected:
                    only_run.append({"case": case["id"], "file": line[0], "line": line[1], "proof": p["proof"]})
        out[split] = {"still_accepted": still_accepted, "other": other, "only_run": only_run}
    return out


def markdown(scores: dict) -> str:
    p, hand, runner, cmp = scores["pinned"], scores["audit"], scores["runner"], scores["comparison"]
    static = json.loads((RESULTS / "commands-scores.json").read_text(encoding="utf-8"))["commands"]
    checks = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["run_audit"]["findings"]
    reasons = "; ".join(f"{reason} ({n})" for reason, n in hand["reasons"].items())
    not_run = (f"{p['not_run']} documented command wasn't" if p["not_run"] == 1 else
               f"{p['not_run']} documented commands weren't")
    lines = ["# Commands in the docs, run in a sandbox", "",
             "Generated by `scripts/run_sandbox.py`. Don't edit by hand.", "",
             "Each documented command that runs one of the project's own programs is run in a Docker container "
             "with no network, no Linux capabilities, and limits on processes, memory, and time. There's no shell: "
             "the program gets the documented words directly, so pipes and other programs in a line never run. "
             "Hooks loaded with Python stop the program right after its parser has read the command line, so "
             "nothing the command would do is done. The proof is the parser's own message.", "",
             "## What ran", "",
             f"- **{p['commands']:,} distinct command lines** from {p['documented']:,} documented commands in "
             f"{p['repos']} repositories. {not_run} run, because its words need the shell (such as `$(...)`)."
             if p["not_run"] == 1 else
             f"- **{p['commands']:,} distinct command lines** from {p['documented']:,} documented commands in "
             f"{p['repos']} repositories. {not_run} run, because their words need the shell (such as `$(...)`).",
             "- **Not run:** " + "; ".join(f"{repo} ({why})" for repo, why in SKIP.items()) +
             "; and the two repositories with no command line.",
             "- **As pinned:** " + "; ".join(f"{OUTCOMES[k]}: {n:,}" for k, n in p["outcomes"].items()) + ". "
             f"Of the refusals, {p['missing_input']} are for an input the sandbox doesn't have or the docs leave out: "
             "a file, a required argument or value, a subcommand, or the network.", "",
             "## Audit: the repositories as pinned", "",
             f"- **Findings:** {p['findings']} command lines the program refuses for a word it doesn't know, or for "
             "any other reason. Checked by hand ([data/hand_check.json](../../data/hand_check.json)): "
             f"{hand['out_of_date']} out of date, and {hand['false_alarms']} false alarms: {reasons}.", "",
             "| Repository | Doc line | What's wrong | The program says |", "|---|---|---|---|"]
    for c in sorted(checks, key=lambda c: (c["repo"].lower(), c["lines"])):
        if c["verdict"] == "out of date":
            lines.append(f"| {c['repo']} | {', '.join(c['lines'])} | {c['reason']} | {c['message'].splitlines()[0][:80]} |")
    lines += ["", "## The answer key", "",
              "A command line is flagged when, after the planted change, the parser names a word it doesn't know "
              "that it didn't name before, or refuses a command line it took before.", "",
              "| Split | Renamed option: cases | Lines | Flagged | False alarms | Precision | Recall | "
              "Read, not run: flagged |", "|---|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        t, s2 = runner[split]["kinds"]["rename_option"], static[split]["kinds"]["rename_option"]
        lines.append(f"| {split} | {t['cases']} | {t['tp'] + t['fn']} | {t['tp'] + t['fp']} | {t['fp']} | "
                     f"{pct(t['precision'])} | {pct(t['recall'])} | {s2['tp'] + s2['fp']} |")
    lines += ["", "**Read, then run.** Of the renamed-option lines that reading the commands flags and running "
              f"doesn't, {cmp['dev']['still_accepted']} in dev and {cmp['test']['still_accepted']} in test are in "
              "commands the program still accepts after the change: argparse and optparse take a unique prefix of "
              "an option's name, so after a rename from `--x` to `--x2`, `--x` still works. "
              f"{cmp['dev']['other']} in dev and {cmp['test']['other']} in test are in commands that weren't run "
              "(their repository's program doesn't run in the sandbox) or were refused for another reason.", ""]
    only = cmp["dev"]["only_run"] + cmp["test"]["only_run"]
    if only:
        lines += ["**Found only by running:**", ""]
        lines += [f"- {o['case']}: {o['file']}:{o['line']}. {o['proof'].split(' (choose from')[0]}" for o in only]
        lines.append("")
    other = {split: sum(v["tp"] + v["fp"] for k, v in runner[split]["kinds"].items() if k != "rename_option")
             for split in ("dev", "test")}
    lines += [f"Other kinds of change: {other['dev']} lines flagged in dev and {other['test']} in test. "
              f"Controls with a false alarm: {runner['dev']['control']['false_alarm_cases']} of "
              f"{runner['dev']['control']['cases']} in dev, {runner['test']['control']['false_alarm_cases']} of "
              f"{runner['test']['control']['cases']} in test.", "",
              "## Limits", "",
              "- A quoted argument that spans several lines isn't joined, so its command is read in pieces "
              "(3 of the audit's false alarms).",
              "- A program that reads an internal command line with argparse before its own would be stopped early, "
              "and its command counted as accepted: that can hide a problem, but not make one up.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the commands in the sandbox first (needs Docker)")
    args = parser.parse_args()
    repos = sandboxed(json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"])
    cases = load_cases()
    if args.run:
        run_all(repos, cases)
    audit, runs = load("pinned.jsonl"), load("cases.jsonl")
    predicted = predictions(cases, audit, runs)
    with (RESULTS / "run.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps({"id": case["id"], "predicted": predicted[case["id"]]}, ensure_ascii=False) + "\n")
    scores = report(cases, {k: [(p["file"], p["line"]) for p in v] for k, v in predicted.items()})
    findings = audit_findings(audit)
    summary = {"pinned": pinned_summary(audit), "audit": hand_verdicts(findings), "runner": scores,
               "comparison": comparison(cases, runs, audit)}
    (RESULTS / "run-scores.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    (ROOT / "docs" / "results" / "run.md").write_text(markdown(summary), encoding="utf-8")
    print(f"audit: {len(audit)} distinct commands run in {len(repos)} repositories; {len(findings)} findings")
    for split in ("dev", "test"):
        t = scores[split]["kinds"]["rename_option"]
        print(f"{split}: renamed options: flagged {t['tp'] + t['fp']}, false alarms {t['fp']}, "
              f"precision {pct(t['precision'])}, recall {pct(t['recall'])}; name group precision "
              f"{pct(scores[split]['name']['precision'])}, controls with a false alarm "
              f"{scores[split]['control']['false_alarm_cases']}")


if __name__ == "__main__":
    main()
