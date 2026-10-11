"""Step 7: the write-up, docs/write-up.md. Its text is below, and every number in it is filled in from the results
files and the hand checks, so the write-up can't drift from what was measured. A test checks the page is exactly
what this script writes.

    python scripts/write_up.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from run_baseline import RESULTS, pct  # noqa: E402

TEXT = """# Building docs-proof: what I measured, and what I learned

docs-proof finds the lines in a project's docs that a code change made wrong, and proves each one: it runs the documented command, or it points to the code line that contradicts the doc. It suggests a fix for each line and changes nothing without a person's yes. It runs as a command, as a GitHub Action, and as an MCP server for AI assistants, and it uses no AI unless you ask it to.

I set myself one rule: no claim without a number behind it. This write-up follows the project in order, with the numbers that shaped each decision. The details are in the [README](../README.md) and the results pages it links.

## The problem
Docs drift is common, even in well-run projects. In GitHub's 2017 Open Source Survey, 93% of respondents called incomplete or outdated documentation a pervasive problem. More than a quarter of the 1,000 most popular GitHub projects had at least one outdated reference to code in their docs (Tan, Wagner, and Treude, ICSME 2023). And in a 2026 study of pull requests from 714 repositories, only 0.8% changed the README (Gao et al.).

## An answer key from planted changes
To measure a checker, I needed changes whose wrong doc lines were known in advance.
- **The key:** {cases} changes planted one at a time in {repos} popular Python projects with permissive licenses, each pinned to a commit: a renamed option, function, environment variable, or file, a changed default, or a raised minimum Python version. Each case records the doc lines it makes wrong, {lines} in all. The projects are split by repository: {dev_cases} cases for choosing settings (dev) and {test_cases} for the final score (test).
- **Exact checks first, with no AI:** a search for names the change removed. On test it found all {rename_lines} rename lines, with {rename_fp} false alarms (precision {rename_precision}), and none of the {value_lines} changed-value lines.
- **That 100% is by design.** A rename case's expected lines are the doc lines that still name the old name, so a search for removed names finds all of them. Those cases really test false alarms.
- **Reading the "false alarms" one by one paid off.** Several turned out to name the project's own class through a short module name. The key had missed them, so I fixed the key and corrected the numbers I'd published.

## Commands in the docs, read and then run
- **Read the way a shell reads them:** documented commands' options were compared with the options the code declares. On test it flagged {read_flagged} of the {option_lines} renamed-option lines, with no false alarms. An audit of the projects as they are found {audit_commands:,} documented commands, and its {audit_findings} findings were all false alarms on a closer look.
- **Then run in a sandbox:** each command ran in Docker with no network, and the program stopped right after reading its command line, so nothing it would do was done. On test it flagged {run_flagged} of the {option_lines} lines, with no false alarms, and its proof is the program's own error message.
- **Running finds fewer lines than reading, for a real reason.** argparse and optparse accept a unique prefix of an option's name, so after `--x` became `--x2`, a command with `--x` still works. Reading finds every stale name; running proves which commands break.
- **The audit found real errors:** of {run_commands:,} distinct command lines, {out_of_date} doc lines in {projects} projects were out of date, each confirmed on the project's main branch.

## Changed values, and a local model
A changed default keeps every name, so exact checks can't see it.
- **A wide search** for doc lines that show the old value found all {value_lines} test lines, with {search_fp} false alarms (precision {search_precision}).
- **A local model** (qwen3:8b through Ollama, chosen on dev from {models} models and {prompts} prompts) then read each line in context. It kept {model_tp} of the {value_lines}, with {model_fp} false alarms (precision {model_precision}). F1 went from {search_f1} to {model_f1}: an 8B local model barely helped here, and I report it that way.

## Suggested fixes, and why each one needs a yes
- **Rules first:** a rename puts the new name where the old one was, and a changed value puts the new value where the old one was. On test they fixed {rules_right} of the {fix_lines} lines the change made wrong, all of them right, and declined {rules_declined}. Every fixed line in a documented command was run again in the sandbox, and the program took all {command_lines} of them.
- **An agent for the rest:** qwen3:8b, working only through read-only tools, with a turn limit and loop detection. Of the {rules_declined} lines, it fixed {agent_right} right and {agent_wrong} wrong, and left {agent_left} for a person.
- **Every false alarm got a fix too** ({harm} of {alarms}). A fix is only as right as the flag behind it, so the fixes become one patch, and nothing changes until a person says yes to that exact patch.

## Three ways to use it
- **A command:** on all {cases} cases, it flags exactly the {tool_lines} lines the measured steps flag, and offers exactly their {tool_fixes} rule fixes.
- **A GitHub Action:** it reports in the job summary and with a warning on each flagged line, needs no write permission, and comments on a pull request only when asked.
- **An MCP server:** two read-only tools that give assistants such as Claude Code the command's findings.

## Real history: what it would have caught
Planted changes measure what the tool was built to find. Real history measures what it would have caught in practice.
- **A second key, nobody planted it:** commits in the same projects' history since {since} that removed a name from the code while doc lines still mentioned it, with the lines a later commit had to fix. I mined {mined} cases with rules worked out on dev and read every one by hand before running docs-proof on any of them; {real} were real.
- **On test, it would have flagged {real_found} of the {real_lines} lines ({real_recall}).** On dev, {dev_found} of {dev_lines} ({dev_recall}).
- **The misses come from what it compares, not how it matches.** It flagged every line whose name its exact check compares, {compared_test} of {compared_test} on test and {compared_dev} of {compared_dev} on dev. The rest name methods, parameters, other libraries' names, dependencies, or values.
- **The lines stayed wrong a long time:** on test, a median of {days_median} days, and up to {days_max:,}.

## My own projects found what both keys missed
I ran it on every pull request merged into my two public projects, {merges} in all. Control Finder had nothing flagged. Car Safety Checker had {before_rule} false alarms in one pull request: it removed a function named `records`, and every sentence that uses the word "records" was flagged.
- **The answer key could never show this.** It renames only names that can't be ordinary words, such as `fetch_items`, and the real-history key reads code names only in backticks.
- **The rule it led to:** a removed function or class whose name could be an ordinary word counts only where the doc marks it as code, in backticks, in a code block, as a call, or after a dot. It changed no result on either key and removed all {before_rule} false alarms. For the same reason the keys never had such a name, neither can measure what the rule costs.

## The fixes, against the real ones
Each real-history line was later fixed by a person, so their fix shows what the line became. I judged each of docs-proof's {rf_fixed} fixes against the code after the change.
- **{rf_right} right, {rf_incomplete} incomplete, {rf_wrong} wrong.** On dev, all {rf_dev} used the right new name; the incomplete ones left something else stale, such as a help line's old description.
- **The wrong ones taught the most.** coverage.py replaced three tracer variables with a different scheme, and the rules paired them one to one because the names looked alike. Pairing can't tell a rename from a replacement.
- **A stricter check I'd deferred was measured and not added.** It would allow a fix to change a line only where the old name is. On dev it stopped none of the agent's fixes, and the people who fixed these lines changed more than the old name in {more} of the {edits} lines they edited. Its only benefit showed on test, where it would have stopped {stopped_test} bad agent fixes, so it stays a known limit.

## What I'd do next
- **Compare more kinds of names:** methods, parameters, and attributes, which most real misses named.
- **Pair with care:** when a change removes several names and adds several, say the pairing is a guess instead of offering a confident fix.
- **Fix the rest of a line:** a help line needs its new description, not only the new option.
- **Bring the sandbox and the agent into the command,** so its users get the run proofs and the harder fixes.

## How it's checked
- Every change runs the whole test suite in GitHub Actions, pinned to exact commits, with read-only permissions. Another CI job runs the Action itself, and a third rebuilds the answer key and its results from the pinned projects, recomputes the rest from the kept runs, and checks that nothing changed.
- Every step planted bugs on purpose to test its tests, and every one was caught; when one wasn't at first, a test was added for it.
- The key and every result rebuild byte for byte the same on macOS and on Linux, and every number in the README and this write-up is checked by a test.
- Every model answer and sandbox run is kept, so CI recomputes every score without running a model or Docker.
- It costs $0 to run: local models through Ollama, and public projects with permissive licenses.
"""


def load(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def numbers() -> dict:
    """Every number the write-up uses, from the results files and the hand checks."""
    exact, commands, run, values, model = (load(n) for n in ("exact-scores", "commands-scores", "run-scores",
                                                                   "values-scores", "model-scores"))
    fixes, tool, real, mining, own, rf = (load(n) for n in ("fixes-scores", "tool", "real-scores", "real-mining",
                                                            "own-scores", "real-fixes-scores"))
    hand = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    name, value = exact["test"]["name"], exact["test"]["value"]
    read = commands["commands"]["test"]["kinds"]["rename_option"]
    ran = run["runner"]["test"]["kinds"]["rename_option"]
    search, chosen = values["baseline"]["test"]["value"], model["model"]["test"]["value"]
    rules, together, agent = fixes["rules"]["test"]["groups"], fixes["together"]["test"], fixes["test_agent"]
    real_dev, real_test = real["dev"], real["test"]
    rf_dev, rf_test = rf["dev"], rf["test"]
    stopped = next(c for k, c in rf["agent"].items() if k.startswith("test "))
    edits = rf_dev["later_edits"] + rf_test["later_edits"]
    return {
        "cases": exact["dev"]["cases"] + exact["test"]["cases"], "repos": len(repos),
        "lines": exact["dev"]["expected_lines"] + exact["test"]["expected_lines"],
        "dev_cases": exact["dev"]["cases"], "test_cases": exact["test"]["cases"],
        "rename_lines": name["tp"] + name["fn"], "rename_fp": name["fp"], "rename_precision": pct(name["precision"]),
        "value_lines": value["tp"] + value["fn"],
        "read_flagged": read["tp"] + read["fp"], "option_lines": read["tp"] + read["fn"],
        "audit_commands": commands["audit"]["commands"], "audit_findings": commands["audit"]["findings"],
        "run_flagged": ran["tp"] + ran["fp"], "run_commands": run["pinned"]["commands"],
        "out_of_date": run["audit"]["out_of_date"],
        "projects": len({c["repo"] for c in hand["run_audit"]["findings"] if c["verdict"] == "out of date"}),
        "search_fp": search["fp"], "search_precision": pct(search["precision"]), "search_f1": f"{search['f1']:.3f}",
        "models": len({s["model"] for s in model["dev_settings"]}), "prompts": len({s["version"] for s in model["dev_settings"]}),
        "model_tp": chosen["tp"], "model_fp": chosen["fp"], "model_precision": pct(chosen["precision"]),
        "model_f1": f"{chosen['f1']:.3f}",
        "rules_right": sum(g["right"] for g in rules.values()), "fix_lines": sum(g["expected"] for g in rules.values()),
        "rules_declined": sum(g["declined"] for g in rules.values()),
        "command_lines": fixes["rules"]["test"]["command_lines_taken"],
        "agent_right": agent["right"], "agent_wrong": agent["wrong"], "agent_left": agent["left"],
        "harm": sum(g["harm"] for g in together.values()), "alarms": sum(g["false_alarms"] for g in rules.values()),
        "tool_lines": tool["dev"]["flagged_lines"] + tool["test"]["flagged_lines"],
        "tool_fixes": tool["dev"]["fixes"] + tool["test"]["fixes"],
        "since": mining["since"][:4],
        "mined": sum(m["mined_cases"] for m in mining["hand_check"].values()),
        "real": sum(m["cases"] for m in mining["hand_check"].values()),
        "real_found": real_test["found"], "real_lines": real_test["lines"], "real_recall": pct(real_test["recall"]),
        "dev_found": real_dev["found"], "dev_lines": real_dev["lines"], "dev_recall": pct(real_dev["recall"]),
        "compared_test": real_test["compared_found"], "compared_dev": real_dev["compared_found"],
        "days_median": f"{real_test['days_median']:g}", "days_max": real_test["days_max"],
        "merges": sum(t["merges"] for t in own.values()),
        "before_rule": sum(t["flagged_before_a_rule"] for t in own.values()),
        "rf_fixed": rf_dev["fixed"] + rf_test["fixed"], "rf_dev": rf_dev["fixed"],
        "rf_right": rf_dev["right"] + rf_test["right"], "rf_incomplete": rf_dev["incomplete"] + rf_test["incomplete"],
        "rf_wrong": rf_dev["wrong"] + rf_test["wrong"],
        "edits": edits, "more": edits - rf_dev["later_edits_only_the_name"] - rf_test["later_edits_only_the_name"],
        "stopped_test": stopped["wrong_stopped"] + stopped["harm_stopped"],
    }


def check() -> None:
    """The claims in the text that aren't numbers. Stops if a result changed so that one of them no longer holds."""
    exact, commands, run, values = (load(n) for n in ("exact-scores", "commands-scores", "run-scores", "values-scores"))
    fixes, tool, real, own, rf = (load(n) for n in ("fixes-scores", "tool", "real-scores", "own-scores", "real-fixes-scores"))
    rules = fixes["rules"]["test"]
    claims = {
        "the exact checks found all rename lines": exact["test"]["name"]["fn"] == 0,
        "the exact checks found none of the changed values": exact["test"]["value"]["tp"] == 0,
        "reading and running commands had no false alarms": (
            commands["commands"]["test"]["kinds"]["rename_option"]["fp"] == 0
            and run["runner"]["test"]["kinds"]["rename_option"]["fp"] == 0),
        "the audit's findings were all false alarms": commands["audit"]["out_of_date"] == 0,
        "the search found every changed-value line": values["baseline"]["test"]["value"]["fn"] == 0,
        "the rules' fixes were all right": all(g["wrong"] == 0 for g in rules["groups"].values()),
        "the program took every fixed command": rules["command_lines_taken"] == rules["command_lines"],
        "every false alarm got a fix": sum(g["harm"] for g in fixes["together"]["test"].values())
        == sum(g["false_alarms"] for g in rules["groups"].values()),
        "the command matches the measured steps": all(t["lines_step_4_didnt_take"] == 0 for t in tool.values()),
        "every compared real line was flagged": all(real[s]["compared_found"] == real[s]["compared_lines"] for s in ("dev", "test")),
        "nothing flagged on my projects since the rule": all(t["lines"] == 0 for t in own.values()),
        "on dev, no rule fix was wrong": rf["dev"]["wrong"] == 0,
        "on dev, the stricter check stopped none of the agent's fixes": not any(
            c[f"{v}_stopped"] for k, c in rf["agent"].items() if k.startswith("dev ") for v in ("right", "wrong", "harm")),
    }
    broken = [claim for claim, holds in claims.items() if not holds]
    if broken:
        raise SystemExit(f"The write-up says something the results no longer support: {broken}")


def render() -> str:
    check()
    return TEXT.format(**numbers())


def main() -> None:
    (ROOT / "docs" / "write-up.md").write_text(render(), encoding="utf-8")
    print(f"wrote docs/write-up.md ({len(render().split()):,} words)")


if __name__ == "__main__":
    main()
