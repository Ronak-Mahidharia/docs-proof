"""Step 4: a suggested fix for each flagged doc line, checked before it's offered, and an agent for the lines the
rules can't fix.

1. The flagged lines: the exact check's (step 1, renamed names) and the changed-value search's (step 3), for every
   case. They include the false alarms, where any fix would make a right line wrong.
2. Rule fixes (src/docsproof/fix.py), worked out from the code before and after the change alone, never the key.
3. The sandbox: each fixed line that's part of a documented command is run again, after the change, as fixed. The
   program must take it the way it took the documented command before the change (data/results/runs/fixes.jsonl
   keeps every run).
4. The agent (src/docsproof/agent.py), for the flagged lines the rules decline, and for the 7 doc lines the step 2
   audit found out of date in 5 projects. Every setting is tried on dev, and test is run once with the setting
   chosen on dev (data/results/agent-answers.jsonl keeps every answer, with each tool call and its result).
5. The scores, against the answer key's fixed lines: the planted change made in the doc line, checked by hand
   (data/hand_check.json, "fixes"). The agent's fixes for the 7 real doc lines are judged by hand.

    python scripts/run_fixes.py --run           # the sandbox runs of the rules' fixed commands (needs Docker)
    python scripts/run_fixes.py --agent dev     # the agent on dev, every setting (needs Ollama and Docker)
    python scripts/run_fixes.py --agent test    # the agent on test, with the setting chosen on dev
    python scripts/run_fixes.py                 # the fixes, the scores, and docs/results/fixes.md, from what's kept
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cases import clone, folder  # noqa: E402
from build_sandbox import sandboxed  # noqa: E402
from docsproof import agent  # noqa: E402
from docsproof.commands import Command, code_block_lines, console_scripts, doc_commands, main_packages  # noqa: E402
from docsproof.docs import qualifiers, read_lines, token_pattern  # noqa: E402
from docsproof.exact import TOKEN_KIND  # noqa: E402
from docsproof.fix import (Fix, apply, changes_value, check_shape, renames, rule_fix, stale_name,  # noqa: E402
                           value_pattern)
from docsproof.model import describe  # noqa: E402
from docsproof.names import packages  # noqa: E402
from docsproof.plant import apply as plant  # noqa: E402
from docsproof.run import missing_input, refused, run_in_sandbox, runnable  # noqa: E402
from docsproof.values import ValueChange  # noqa: E402
from run_baseline import RESULTS, load_cases  # noqa: E402

RUNS = RESULTS / "runs"
ANSWERS = RESULTS / "agent-answers.jsonl"
MODELS = ["qwen3:8b", "granite4:3b"]
KIND = {"rename_option": "option", "rename_identifier": "identifier", "rename_env_var": "env", "rename_file": "path"}
PYTHON = {"python", "python3"}
WORKERS = 7


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def change_of(d: dict) -> ValueChange:
    return ValueChange(d["kind"], d["subject"], d["old"], d["new"], d["file"], d["line"], d["code"])


def hand() -> dict:
    return json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["fixes"]


# --- 1 and 2: the flagged lines, and the rules' fixes ---------------------------------------------------------

def rule(text: str, names: list[list[str]], values: list[dict], pairs: dict, own: set[str]) -> dict:
    """The rules' fix for one flagged line ({"new", "reason"}), or why they decline it ({"declined"}), from the
    line as kept in data/results/fixes.jsonl (fix.rule_fix does the work)."""
    new, why = rule_fix(text, [(kind, name) for kind, name in names], [change_of(d) for d in values],
                        {tuple(k.split(" ", 1)): v for k, v in pairs.items()}, own)
    return {"declined": why} if new is None else {"new": new, "reason": why}


def fixed_commands(rel: str, lines: list[str], fixes: list[Fix], scripts: set[str], mains: set[str],
                   changed_only: bool = True) -> list[tuple[Command | None, Command]]:
    """(the documented command, the fixed one) for each runnable command that shares a line with a fix. Only the
    ones whose words the fixes change, unless changed_only is False."""
    before = {c.line: c for c in doc_commands(rel, lines, scripts, mains) if runnable(c) is None}
    spans = [(f.line, f.line + len(f.new) - 1) for f in fixes]
    out = []
    for c in doc_commands(rel, apply(lines, fixes), scripts, mains):
        last = max([c.line] + [n for _, n in c.options])
        if runnable(c) is None and any(first <= last and c.line <= end for first, end in spans):
            old = before.get(c.line)
            if not changed_only or old is None or (old.argv, old.env) != (c.argv, c.env):
                out.append((old, c))
    return out


def find_all(cases: list[dict], runnable_repos: set[str]) -> list[dict]:
    """For each case: its flagged lines, each with the rules' fix and the commands that fix changes."""
    exact = {r["id"]: r["predicted"] for r in jsonl(RESULTS / "exact.jsonl")}
    values = {r["id"]: r["changes"] for r in jsonl(RESULTS / "values-candidates.jsonl")}
    pinned = {(r["repo"], tuple(r["argv"]), tuple(map(tuple, r["env"]))): r for r in jsonl(RUNS / "pinned.jsonl")}
    cache: dict = {}
    owns: dict[str, set[str]] = {}
    programs: dict[str, tuple[set[str], set[str]]] = {}
    rows = []
    for case in cases:
        original = folder(case["repo"])
        if case["repo"] not in owns:
            owns[case["repo"]] = packages(original)
            programs[case["repo"]] = (console_scripts(original), main_packages(original))
        flagged: dict[tuple[str, int], dict] = {}
        for p in exact[case["id"]]:
            flagged.setdefault((p["file"], p["line"]), {"names": [], "values": []})["names"].append([p["kind"], p["name"]])
        for change in values[case["id"]]:
            d = {k: change[k] for k in ("kind", "subject", "old", "new", "file", "line", "code")}
            for c in change["candidates"]:
                entry = flagged.setdefault((c["file"], c["line"]), {"names": [], "values": []})
                if d not in entry["values"]:
                    entry["values"].append(d)
        pairs: dict[str, str] = {}
        if any(entry["names"] for entry in flagged.values()):
            with tempfile.TemporaryDirectory() as tmp:
                copy = Path(tmp) / "repo"
                clone(original, copy)
                plant(copy, case["edit"])
                pairs = {f"{kind} {old}": new for (kind, old), new in sorted(renames(original, copy, cache).items())}
        own = sorted(owns[case["repo"]])
        lines_out, by_file = [], {}
        for (rel, n), entry in sorted(flagged.items()):
            text = read_lines(original / rel)[n - 1]
            result = rule(text, entry["names"], entry["values"], pairs, set(own))
            lines_out.append({"file": rel, "line": n, "text": text, **entry, "rule": result})
            if "new" in result:
                by_file.setdefault(rel, []).append(Fix(rel, n, (text,), (result["new"],), "rule", result["reason"]))
        checks = []
        if case["repo"] in runnable_repos:
            scripts, mains = programs[case["repo"]]
            for rel, fixes in sorted(by_file.items()):
                for old, new in fixed_commands(rel, read_lines(original / rel), fixes, scripts, mains):
                    before = pinned.get((case["repo"], old.argv, old.env)) if old else None
                    last = max([new.line] + [n for _, n in new.options])
                    checks.append({"file": rel, "line": new.line, "argv": list(new.argv), "env": [list(p) for p in new.env],
                                   "covers": sorted(f.line for f in fixes if new.line <= f.line <= last),
                                   "documented": list(old.argv) if old else None,
                                   "before": {k: before[k] for k in ("outcome", "exit", "unknown", "message")} if before else None})
        rows.append({"id": case["id"], "pairs": pairs, "own": own, "lines": lines_out, "commands": checks})
    return rows


def run_rule_commands(cases: list[dict], rows: list[dict]) -> None:
    """Run each case's fixed commands in a fresh sandbox, after its planted change (runs/fixes.jsonl)."""
    by_id = {c["id"]: c for c in cases}
    jobs = [(row["id"], sorted({(tuple(c["argv"]), tuple(map(tuple, c["env"]))) for c in row["commands"]}))
            for row in rows if row["commands"]]
    results = {}
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(run_in_sandbox, folder(by_id[i]["repo"]).name, keys, by_id[i]["edit"]): i for i, keys in jobs}
        for done, future in enumerate(as_completed(futures), 1):
            results[futures[future]] = future.result()
            if done % 10 == 0 or done == len(jobs):
                print(f"  {done} of {len(jobs)} sandbox runs", flush=True)
    with (RUNS / "fixes.jsonl").open("w", encoding="utf-8") as out:
        for case_id, keys in jobs:
            for key in keys:
                out.write(json.dumps({"id": case_id, "argv": list(key[0]), "env": [list(p) for p in key[1]],
                                      **results[case_id][key]}, ensure_ascii=False) + "\n")


def taken(before: dict | None, after: dict) -> bool:
    """Whether the program takes a fixed command: it accepts it (or runs it to the end), or it treats it as it
    treated the documented command before the change (such as refusing it the same way for a missing file). With
    nothing documented to compare with, a refusal counts only if it's for a missing input."""
    if after["outcome"] in ("accepted", "succeeded"):
        return True
    if before is None:
        return missing_input(after)
    return after["outcome"] == before["outcome"] and refused(before, after) is None


def rule_verdicts(rows: list[dict]) -> dict[str, dict[tuple[str, int], bool]]:
    """For each case and each fixed line that's part of a fixed command: whether the program takes every fixed
    command the line is part of."""
    kept = {(r["id"], tuple(r["argv"]), tuple(map(tuple, r["env"]))): r for r in jsonl(RUNS / "fixes.jsonl")}
    out: dict[str, dict[tuple[str, int], bool]] = {}
    for row in rows:
        for c in row["commands"]:
            key = (row["id"], tuple(c["argv"]), tuple(map(tuple, c["env"])))
            if key not in kept:
                raise SystemExit(f"No sandbox run for {key}: run the sandbox again (--run).")
            spot = out.setdefault(row["id"], {})
            for n in c["covers"]:
                spot[(c["file"], n)] = spot.get((c["file"], n), True) and taken(c["before"], kept[key])
    return out


# --- 4: the agent --------------------------------------------------------------------------------------------

def tasks(cases: list[dict], rows: list[dict], verdicts: dict) -> list[dict]:
    """The agent's work: each flagged line the rules decline, or whose fix the program refuses, and each line the
    step 2 audit found out of date."""
    by_id = {c["id"]: c for c in cases}
    out = []
    for row in rows:
        case = by_id[row["id"]]
        for line in row["lines"]:
            at = (line["file"], line["line"])
            refused_fix = verdicts.get(row["id"], {}).get(at) is False
            if "declined" in line["rule"] or refused_fix:
                out.append({"id": f"{row['id']}|{line['file']}:{line['line']}", "split": case["split"], "kind": "planted",
                            "case": row["id"], "repo": case["repo"], "file": line["file"], "line": line["line"],
                            "why_rules": line["rule"].get("declined") or "the program refused the rules' fix"})
    split = {c["repo"]: c["split"] for c in cases}
    findings = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["run_audit"]["findings"]
    for f in findings:
        if f["verdict"] != "out of date":
            continue
        for where in f["lines"]:
            rel, n = where.rsplit(":", 1)
            out.append({"id": f"audit|{f['repo']}|{where}", "split": split[f["repo"]], "kind": "real", "case": None,
                        "repo": f["repo"], "file": rel, "line": int(n), "command": f["command"], "message": f["message"]})
    return sorted(out, key=lambda t: (t["split"], t["kind"], t["id"]))


def describe_names(names: list[list[str]], pairs: dict) -> str:
    return "; ".join(f"`{name}` is gone from the code" + (f", and `{pairs[f'{kind} {name}']}` was added"
                                                          if f"{kind} {name}" in pairs else "") for kind, name in names)


class Sandbox:
    """Runs one command at a time in a fresh sandbox, for the agent's tool and its fixes' checks. Each run is kept
    with what it was for: try_command, or the check of the agent's nth proposed fix."""

    def __init__(self, repo: str, edit: dict | None):
        self.repo, self.edit, self.runs, self.checks = repo, edit, [], 0

    def __call__(self, argv: tuple[str, ...], env: tuple = (), check: bool = False, capture: bool = False) -> dict:
        key = (tuple(argv), tuple(env))
        result = run_in_sandbox(folder(self.repo).name, [key], self.edit, capture=capture)[key]
        why = f"check {self.checks}" if check else ("show_help" if capture else "try_command")
        self.runs.append({"for": why, "argv": list(argv), "env": [list(p) for p in env], **result})
        return result


def build(task: dict, row: dict | None, case: dict | None, runnable_repos: set[str], pinned: dict,
          code: Path) -> tuple[agent.Task, Sandbox]:
    """The agent's task for a flagged line, with its checks and its sandbox. code is the project after the change."""
    original = folder(task["repo"])
    rel, n = task["file"], task["line"]
    lines = read_lines(original / rel)
    scripts, mains = console_scripts(original), main_packages(original)
    sandbox = Sandbox(task["repo"], case["edit"] if case else None)
    runs = task["repo"] in runnable_repos

    def own(words: list[str]) -> str | None:
        if words[0] in scripts or (words[0] in PYTHON and words[1:2] == ["-m"] and words[2:3] and words[2] in mains):
            return None
        allowed = sorted(scripts) + [f"python -m {m}" for m in sorted(mains)]
        return f"The sandbox runs only this project's programs: {', '.join(allowed)}."

    def run_command(words: list[str]) -> dict | str:
        return own(words) or sandbox(tuple(words))

    def show_help(words: list[str]) -> str:
        if own(words):
            return own(words)
        result = sandbox((*words, "--help"), capture=True)
        text = result.get("output", "").strip()
        return text[:agent.KEEP] if text else f"It printed nothing. {agent.said(result)}"

    if task["kind"] == "real":
        problem = (f"Run in a sandbox, the program refuses this documented command: `{task['command']}`. "
                   f"It says: {task['message']}")
        change = ""
        in_block = n in code_block_lines(rel, lines)

        def check(fix: Fix) -> str | None:
            sandbox.checks += 1
            problem = check_shape(fix, lines, n)
            if problem or not runs or not in_block:
                return problem
            for _, new in fixed_commands(rel, lines, [fix], scripts, mains, changed_only=False):
                after = sandbox(new.argv, new.env, check=True)
                if not taken(None, after):
                    return f"the program refuses `{' '.join(new.argv)}`: {after['message'] or after['outcome']}"
            return None
    else:
        line = next(x for x in row["lines"] if (x["file"], x["line"]) == (rel, n))
        names, values = line["names"], line["values"]
        if names:
            problem = "The exact check found a name here that the change removed: " + describe_names(names, row["pairs"]) + "."
            change = describe_names(names, row["pairs"]) + "."
        else:
            problem = "The changed-value search found the old value on this line, so it may still state it."
            change = " ".join(describe(d) + f" ({d['file']}, line {d['line']}: `{d['code'].strip()}`)" for d in values)

        def check(fix: Fix) -> str | None:
            sandbox.checks += 1
            problem = check_shape(fix, lines, n)
            if problem:
                return problem
            if any(o != x for i, (o, x) in enumerate(zip(fix.old, fix.new)) if fix.line + i != n):
                return f"change only line {n}"
            old_text, new_text = lines[n - 1], fix.new[n - fix.line]
            for kind, name in names:
                if stale_name(new_text, kind, name):
                    return f"line {n} still mentions `{name}`, which the change removed"
            for d in values:
                if not changes_value(old_text, new_text, change_of(d)):
                    return f"line {n} should state {d['new']} where it stated {d['old']}"
            if runs:
                for old, new in fixed_commands(rel, lines, [fix], scripts, mains):
                    before = pinned.get((task["repo"], old.argv, old.env)) if old else None
                    after = sandbox(new.argv, new.env, check=True)
                    if not taken(before, after):
                        return (f"after the change, the program refuses the fixed command `{' '.join(new.argv)}`: "
                                f"{after['message'] or after['outcome']}")
            return None

    return agent.Task(rel, n, lines, problem, change, code, check, run_command if runs else None,
                      task.get("why_rules", ""), show_help if runs else None), sandbox


def ask(cases: list[dict], rows: list[dict], work: list[dict], settings: list[tuple[str, str]], runnable_repos: set[str]) -> None:
    """Run the agent on each task with each setting, keeping each answer as soon as it's made."""
    by_id = {c["id"]: c for c in cases}
    rows_by_id = {r["id"]: r for r in rows}
    pinned = {(r["repo"], tuple(r["argv"]), tuple(map(tuple, r["env"]))): r for r in jsonl(RUNS / "pinned.jsonl")}
    kept = {(a["model"], a["version"], a["task"]) for a in jsonl(ANSWERS)} if ANSWERS.exists() else set()
    todo = [(t, m, v) for t in work for m, v in settings if (m, v, t["id"]) not in kept]
    print(f"  {len(todo)} agent runs to do", flush=True)
    with ANSWERS.open("a", encoding="utf-8") as out:
        for i, (t, model, version) in enumerate(todo, 1):
            case = by_id.get(t["case"]) if t["case"] else None
            with tempfile.TemporaryDirectory() as tmp:
                code = Path(tmp) / "repo"  # the code after the change, for search_code
                clone(folder(t["repo"]), code)
                if case:
                    plant(code, case["edit"])
                task, sandbox = build(t, rows_by_id.get(t["case"]), case, runnable_repos, pinned, code)
                answer = agent.solve(task, model, version)
            out.write(json.dumps({"model": model, "version": version, "task": t["id"], **answer,
                                  "sandbox_runs": sandbox.runs}, ensure_ascii=False) + "\n")
            out.flush()
            print(f"  {i} of {len(todo)}: {model} {version} {t['id']} -> {answer['outcome']} "
                  f"({answer['turns']} turns, {answer['seconds']} s)", flush=True)


# --- 5: the scores -------------------------------------------------------------------------------------------

def key_change(case: dict) -> ValueChange:
    edit = case["edit"]
    if case["kind"] == "raise_python":
        return ValueChange("python", "Python", f"3.{edit['old']}", f"3.{edit['new']}", edit["file"], 0, "")
    return ValueChange("default", edit["option"], str(edit["old"]), str(edit["new"]), edit["file"], edit["line"], "")


def key_text(case: dict, file: str, line: int, text: str, labels: dict) -> str:
    """The answer key's fixed line: the planted change made in the doc line, unless a hand label says otherwise.
    For a rename, every mention of the old name becomes the new name, except inside a file path; for a value, the
    old value becomes the new one where the line states it once (a line that states it more is labeled by hand)."""
    if (case["id"], file, line) in labels:
        return labels[(case["id"], file, line)]
    edit = case["edit"]
    if case["group"] == "name":
        kind = KIND[case["kind"]]
        found = list(token_pattern(edit["old"], TOKEN_KIND[kind]).finditer(text))
        if kind == "identifier":
            found = [m for m, q in zip(found, qualifiers(text, edit["old"])) if q != "<path>"]
        for m in reversed(found):
            text = text[: m.start()] + edit["new"] + text[m.end():]
        return text
    change = key_change(case)
    pattern = value_pattern(change)
    if len(pattern.findall(text)) != 1:
        raise SystemExit(f"Label by hand the fixed text of {case['id']} {file}:{line} (data/hand_check.json, fixes)")
    return pattern.sub(lambda _: change.new, text)


def task_id(case_id: str, file: str, line: int) -> str:
    return f"{case_id}|{file}:{line}"


def verdict(expected: bool, text: str | None, key: str | None) -> str:
    """For a line the change made wrong: right, wrong, or left (no fix offered). For a false alarm: harm (a fix
    offered for a right line) or left alone."""
    if not expected:
        return "harm" if text is not None else "left alone"
    if text is None:
        return "left"
    return "right" if text == key else "wrong"


def line_outcomes(cases: list[dict], rows: list[dict], verdicts: dict, answers: dict,
                  setting: tuple[str, str] | None) -> list[dict]:
    """One row for each flagged line: who fixed it (the rules, or the agent with this setting for the lines the
    rules don't fix), and the verdict against the answer key."""
    labels = {(x["case"], x["file"], x["line"]): x["fix"] for x in hand()["labels"]}
    by_id = {c["id"]: c for c in cases}
    out = []
    for row in rows:
        case = by_id[row["id"]]
        expected = {(e["file"], e["line"]) for e in case["expected"]}
        for line in row["lines"]:
            at = (line["file"], line["line"])
            ok = verdicts.get(row["id"], {}).get(at)
            if "new" in line["rule"] and ok is not False:
                how, outcome, text = "rule", "fixed", line["rule"]["new"]
            else:
                answer = answers.get((*setting, task_id(row["id"], *at))) if setting else None
                fix = answer["fix"] if answer else None
                how, outcome = "agent", answer["outcome"] if answer else None
                text = fix["new"][at[1] - fix["line"]] if fix else None
            key = key_text(case, *at, line["text"], labels) if at in expected else None
            out.append({"id": row["id"], "split": case["split"], "group": case["group"], "file": at[0], "line": at[1],
                        "expected": at in expected, "how": how, "outcome": outcome, "text": text, "key": key,
                        "in_command": ok is not None, "verdict": verdict(at in expected, text, key)})
    return out


VERDICTS = ("right", "wrong", "left", "harm", "left alone")


def tally(lines: list[dict]) -> dict:
    return {v: sum(1 for x in lines if x["verdict"] == v) for v in VERDICTS}


def rule_scores(lines: list[dict], verdicts: dict, cases: list[dict]) -> dict:
    """What the rules alone do, by split and group, and how the sandbox treated their fixed commands."""
    split_of = {c["id"]: c["split"] for c in cases}
    out = {}
    for split in ("dev", "test"):
        part = [x for x in lines if x["split"] == split]
        groups = {}
        for group in ("name", "value"):
            g = [x for x in part if x["group"] == group]
            groups[group] = {"expected": sum(x["expected"] for x in g), "false_alarms": sum(not x["expected"] for x in g),
                             **{v: sum(1 for x in g if x["how"] == "rule" and x["verdict"] == v) for v in ("right", "wrong", "harm")},
                             "declined": sum(1 for x in g if x["how"] == "agent" and x["expected"]),
                             "declined_false_alarms": sum(1 for x in g if x["how"] == "agent" and not x["expected"])}
        spots = [ok for case_id, found in verdicts.items() if split_of[case_id] == split for ok in found.values()]
        out[split] = {"groups": groups, "command_lines": len(spots), "command_lines_taken": sum(spots)}
    return out


def proof(answer: dict) -> list[dict]:
    """The sandbox runs of the check that took the agent's fix."""
    if answer["outcome"] != "fixed":
        return []
    last = max((int(r["for"].split()[1]) for r in answer["sandbox_runs"] if r["for"].startswith("check")), default=None)
    return [r for r in answer["sandbox_runs"] if r["for"] == f"check {last}"]


def setting_scores(work: list[dict], cases: list[dict], rows: list[dict], verdicts: dict, answers: dict,
                   setting: tuple[str, str], split: str) -> dict | None:
    """How one setting did on a split's agent tasks, or None if it wasn't run on all of them."""
    part = [t for t in work if t["split"] == split]
    if not part or not all((*setting, t["id"]) in answers for t in part):
        return None
    lines = {task_id(x["id"], x["file"], x["line"]): x for x in line_outcomes(cases, rows, verdicts, answers, setting)}
    planted = [lines[t["id"]] for t in part if t["kind"] == "planted"]
    real = [(t, answers[(*setting, t["id"])]) for t in part if t["kind"] == "real"]
    mine = [answers[(*setting, t["id"])] for t in part]
    return {"model": setting[0], "version": setting[1], **tally(planted),
            "real_fixed": sum(a["outcome"] == "fixed" for _, a in real), "real": len(real),
            "real_right": sum(judgment(t, a, setting) == "right" for t, a in real),
            "outcomes": {o: sum(a["outcome"] == o for a in mine) for o in ("fixed", "no fix", "turn limit", "loop")},
            "seconds": statistics.median(a["seconds"] for a in mine),
            "turns": statistics.median(a["turns"] for a in mine)}


def judgment(task: dict, answer: dict, setting: tuple[str, str]) -> str | None:
    """The hand verdict on the agent's fix for an out-of-date doc line, or None when it offered no fix. Stops if a
    fix hasn't been judged, or if the fix that was judged isn't the one kept."""
    if answer["outcome"] != "fixed":
        return None
    found = [x for x in hand()["real"] if (x["task"], x["model"], x["version"]) == (task["id"], *setting)]
    if not found or found[0]["fix"] != list(answer["fix"]["new"]):
        raise SystemExit(f"Judge this fix by hand (data/hand_check.json, fixes, real): {task['id']} {setting} "
                         f"{answer['fix']['new']}")
    return found[0]["verdict"]


def choose(rows_by_setting: list[dict]) -> tuple[str, str]:
    """The rule: the most right fixes on dev's planted lines, then the fewest fixes for false alarms, then the most
    out-of-date lines fixed right (judged by hand), then the faster setting. Fixed before the dev runs, except the
    third step, which first counted the out-of-date lines whose fix the program takes: on dev, that counted fixes
    that drop part of a command, so it was changed before the test run."""
    best = min(rows_by_setting, key=lambda r: (-r["right"], r["harm"], -r["real_right"], r["seconds"],
                                                MODELS.index(r["model"]), r["version"]))
    return best["model"], best["version"]


def real_rows(work: list[dict], answers: dict, setting: tuple[str, str]) -> list[dict]:
    """The agent's answers for the out-of-date doc lines, with each fix's proof and its hand verdict."""
    why = {(x["task"], x["model"], x["version"]): x["why"] for x in hand()["real"]}
    out = []
    for t in work:
        if t["kind"] != "real" or (*setting, t["id"]) not in answers:
            continue
        answer = answers[(*setting, t["id"])]
        out.append({"task": t["id"], "split": t["split"], "repo": t["repo"], "file": t["file"], "line": t["line"],
                    "command": t["command"], "message": t["message"], "outcome": answer["outcome"],
                    "fix": answer["fix"], "proof": [{k: r[k] for k in ("argv", "outcome", "message")} for r in proof(answer)],
                    "verdict": judgment(t, answer, setting), "why": why.get((t["id"], *setting))})
    return out


def load_answers() -> dict:
    return {(a["model"], a["version"], a["task"]): a for a in jsonl(ANSWERS)} if ANSWERS.exists() else {}


def report(cases: list[dict], rows: list[dict]) -> dict | None:
    """Every score, from the kept fixes, runs, and answers; None while the agent hasn't been run on test."""
    verdicts = rule_verdicts(rows)
    work = tasks(cases, rows, verdicts)
    answers = load_answers()
    settings = [(m, v) for m in MODELS for v in agent.SYSTEMS]
    dev = [r for r in (setting_scores(work, cases, rows, verdicts, answers, s, "dev") for s in settings) if r]
    if len(dev) != len(settings):
        return None
    chosen = choose(dev)
    test = setting_scores(work, cases, rows, verdicts, answers, chosen, "test")
    if test is None:
        return {"dev_settings": dev, "chosen": {"model": chosen[0], "version": chosen[1]}}
    alone = line_outcomes(cases, rows, verdicts, {}, None)
    together = line_outcomes(cases, rows, verdicts, answers, chosen)
    return {"rules": rule_scores(alone, verdicts, cases),
            "together": {split: {group: tally([x for x in together if x["split"] == split and x["group"] == group])
                                 for group in ("name", "value")} for split in ("dev", "test")},
            "dev_settings": dev, "chosen": {"model": chosen[0], "version": chosen[1]}, "test_agent": test,
            "agent_lines": [{k: x[k] for k in ("id", "split", "file", "line", "expected", "outcome", "text", "key", "verdict")}
                            for x in together if x["how"] == "agent"],
            "real": real_rows(work, answers, chosen)}


GROUP = {"name": "renamed names", "value": "changed values"}


def short(text: str, width: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def code(text: str) -> str:
    """Text as inline code in a table cell; double backticks when the text has a backtick of its own."""
    text = cell(text)
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def markdown(s: dict) -> str:
    rules, together, chosen = s["rules"], s["together"], s["chosen"]
    lines = ["# Suggested fixes", "", "Generated by `scripts/run_fixes.py`. Don't edit by hand.", "",
             "For each doc line the earlier steps flag, docs-proof suggests a fix and checks it before offering it. The "
             "rules fix what they can, working from the code before and after the change alone, and an agent takes the "
             "rest: a local model that works only by calling tools (read the doc, search the code, run a command in the "
             "sandbox), with a turn limit and loop detection. A fix may change at most 3 lines and must keep most of "
             "each one, and the flagged line must no longer say what the change removed or replaced. A fixed line in a "
             "documented command is run again in the sandbox, after the change, and the program must take it.", "",
             "The flagged lines include the earlier steps' false alarms, and a fix offered for one of them would make a "
             "right line wrong. So nothing is changed without approval: the fixes become one patch to read, and a pull "
             "request is opened only after a person says yes to that patch.", "",
             "The answer key's fix is the planted change made in the doc line: every mention of a renamed name becomes "
             "the new name (except inside a file path), and the old value becomes the new one. It was checked by hand, "
             "and 5 value lines needed a fix of their own ([data/hand_check.json](../../data/hand_check.json), "
             "\"fixes\").", "",
             "## The rules", "",
             "| Split | Lines | Made wrong | Fixed right | Fixed wrong | Declined | False alarms | Given a fix |",
             "|---|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        for group in ("name", "value"):
            g = rules[split]["groups"][group]
            lines.append(f"| {split} | {GROUP[group]} | {g['expected']} | {g['right']} | {g['wrong']} | {g['declined']} | "
                         f"{g['false_alarms']} | {g['harm']} |")
    lines += ["", f"**In the sandbox:** of the lines the rules fixed, {rules['dev']['command_lines']} in dev and "
              f"{rules['test']['command_lines']} in test are part of a documented command. Each fixed command was run "
              f"after the change, and the program took {rules['dev']['command_lines_taken']} and "
              f"{rules['test']['command_lines_taken']} of them: it accepted the fixed command, or refused it just as it "
              "refused the documented one before the change (for a file the sandbox doesn't have).", "",
              "## The agent", "",
              "It gets the lines the rules decline, and the doc lines that step 2 found out of date in 5 projects. Every "
              "setting was tried on dev, and one was chosen by a rule: the most right fixes on dev's planted lines, then "
              "the fewest fixes for false alarms, then the most out-of-date lines fixed right (judged by hand), then the "
              "faster setting. The rule was fixed before the dev runs, except its third step, which first counted the "
              "out-of-date lines whose fix the program takes. On dev, that counted fixes that drop part of a command, so "
              "it was changed before the test run.", "",
              "| Model | Prompt | Right | Wrong | Left | Fixes for false alarms | False alarms left alone | "
              "Out-of-date lines: a fix the program takes | Fixed right | Median seconds |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in s["dev_settings"]:
        mark = " (chosen)" if (r["model"], r["version"]) == (chosen["model"], chosen["version"]) else ""
        lines.append(f"| {r['model']}{mark} | {r['version']} | {r['right']} | {r['wrong']} | {r['left']} | {r['harm']} | "
                     f"{r['left alone']} | {r['real_fixed']} of {r['real']} | {r['real_right']} | {r['seconds']:.1f} |")
    t = s["test_agent"]
    lines += ["", f"**On test,** with {chosen['model']} and prompt {chosen['version']}: {t['right']} right, {t['wrong']} "
              f"wrong, and {t['left']} left for a person, of the lines the change made wrong; {t['harm']} fixes for "
              f"false alarms, and {t['left alone']} left alone.", "",
              "| Doc line | Made wrong? | The agent's fix | The key's fix | Verdict |", "|---|---|---|---|---|"]
    for x in s["agent_lines"]:
        if x["split"] == "test":
            did = code(short(x["text"])) if x["text"] is not None else x["outcome"]
            key = code(short(x["key"])) if x["key"] is not None else "none: leave it"
            lines.append(f"| {x['id'].split(':')[0]}: {x['file']}:{x['line']} | {'yes' if x['expected'] else 'no'} | "
                         f"{did} | {key} | {x['verdict']} |")
    lines += ["", "## Doc lines step 2 found out of date", "",
              "The agent's fixes for the doc lines that the sandbox found out of date in the repositories as pinned. "
              "Each fix the program took was judged by hand: right only if the command also does what the doc around "
              "it shows, such as the output printed under it.", "",
              "| Split | Project | Doc line | The program said | The agent | Judged by hand |", "|---|---|---|---|---|---|"]
    for r in s["real"]:
        did = "; ".join(code(short(text, 60)) for text in r["fix"]["new"]) if r["fix"] else r["outcome"]
        judged = f"{r['verdict']}: {r['why']}" if r["verdict"] else "nothing to judge"
        lines.append(f"| {r['split']} | {r['repo']} | {r['file']}:{r['line']} | {cell(short(r['message'], 50))} | {did} | "
                     f"{cell(judged)} |")
    lines += ["", "## Rules and agent together", "",
              "| Split | Lines | Made wrong | Fixed right | Fixed wrong | Left for a person | False alarms | Given a fix |",
              "|---|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        for group in ("name", "value"):
            g = together[split][group]
            made = g["right"] + g["wrong"] + g["left"]
            lines.append(f"| {split} | {GROUP[group]} | {made} | {g['right']} | {g['wrong']} | {g['left']} | "
                         f"{g['harm'] + g['left alone']} | {g['harm']} |")
    lines += ["", "## Limits", "",
              "- **Rename fixes are right by design** wherever the rules make them: the key's fix is the same change, "
              "checked by hand. What's measured there is how often the rules can make one, and whether the program "
              "takes the fixed command.",
              "- **A fix the program takes can still be wrong.** An agent made a command run by dropping the option "
              "that the doc's example was about, so the out-of-date lines' fixes are judged by hand.",
              "- **The rules change only the old value.** They don't know that a minimum stated for PyPy is a Python "
              "version too, so after a rise from 3.10 to 3.12 they leave yt-dlp's \"PyPy >=3.11\".",
              "- **Every false alarm got a fix,** from the rules or the agent. A fix is only as right as the flag it "
              "fixes, so each one needs a person's yes. Running step 3's model on the value search's flags first "
              "would remove some of them (3 of 10 on test).",
              "- **The agent renames whatever it's given.** With every qwen3 prompt, it renamed another package's class "
              "(cookiecutter's `jinja2_time.TimeExtension`, 4 of 4 lines on dev), although the prompt from v2 on says the "
              "checker can be wrong.",
              "- **The check that a fix keeps most of a line is loose.** On test, it let through a fix that cuts a line "
              "short (pipx's comparisons.rst:227) and one that drops a Markdown quote marker (mkdocs's plugins.md:117). "
              "A stricter check, that a fix changes the line only where the old name or value is, would have stopped "
              "both. It was found on test, so it waited for new data. Measured in step 6, it stops none of the agent's "
              "dev fixes, and right fixes often change more than the old name, so it isn't added "
              "([fixes on real history](real-fixes.md)).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the rules' fixed commands in the sandbox (needs Docker)")
    parser.add_argument("--agent", choices=["dev", "test"], help="run the agent (needs Ollama and Docker)")
    args = parser.parse_args()
    cases = load_cases()
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    runnable_repos = {entry["repo"] for entry in sandboxed(repos)}
    rows = find_all(cases, runnable_repos)
    with (RESULTS / "fixes.jsonl").open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    if args.run:
        run_rule_commands(cases, rows)
    work = tasks(cases, rows, rule_verdicts(rows))
    if args.agent:
        settings = [(m, v) for m in MODELS for v in agent.SYSTEMS]
        if args.agent == "test":
            scores = report(cases, rows)
            if not scores:
                raise SystemExit("Run the agent on dev first (--agent dev).")
            settings = [(scores["chosen"]["model"], scores["chosen"]["version"])]
        ask(cases, rows, [t for t in work if t["split"] == args.agent], settings, runnable_repos)
    scores = report(cases, rows)
    if scores is None or "rules" not in scores:
        print("The agent hasn't been run on everything yet: " + ("dev" if scores is None else "test"))
        return
    (RESULTS / "fixes-scores.json").write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (ROOT / "docs" / "results" / "fixes.md").write_text(markdown(scores), encoding="utf-8")
    for split in ("dev", "test"):
        print(split, scores["together"][split])


if __name__ == "__main__":
    main()
