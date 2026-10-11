"""Checks on step 4's kept results: the rules' fixes, the sandbox runs of the fixed commands, the agent's answers,
and the scores and page worked out from them (scripts/run_fixes.py). None of them needs the repositories, Docker, or
Ollama."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_fixes  # noqa: E402
from build_cases import line_hash  # noqa: E402
from docsproof import agent  # noqa: E402

CASES = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
RESULTS = ROOT / "data" / "results"
ROWS = run_fixes.jsonl(RESULTS / "fixes.jsonl")
SCORES = json.loads((RESULTS / "fixes-scores.json").read_text(encoding="utf-8"))
HAND = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["fixes"]


def test_the_rules_fixes_come_from_the_kept_lines():
    by_id = {c["id"]: c for c in CASES}
    assert [r["id"] for r in ROWS] == [c["id"] for c in CASES]
    for row in ROWS:
        expected = {(e["file"], e["line"]): e["sha256"] for e in by_id[row["id"]]["expected"]}
        for line in row["lines"]:
            assert run_fixes.rule(line["text"], line["names"], line["values"], row["pairs"], set(row["own"])) == line["rule"]
            if (line["file"], line["line"]) in expected:  # the kept line is the line the key has a hash of
                assert line_hash(line["text"]) == expected[(line["file"], line["line"])]
        assert expected.keys() <= {(x["file"], x["line"]) for x in row["lines"]}  # every line the change made wrong is flagged


def test_every_fixed_command_was_run_and_taken():
    verdicts = run_fixes.rule_verdicts(ROWS)  # stops if a fixed command has no kept run
    kept = run_fixes.jsonl(RESULTS / "runs" / "fixes.jsonl")
    assert len(kept) == len({(r["id"], tuple(c["argv"]), tuple(map(tuple, c["env"]))) for r in ROWS for c in r["commands"]})
    rules = SCORES["rules"]
    assert sum(len(v) for v in verdicts.values()) == rules["dev"]["command_lines"] + rules["test"]["command_lines"]


def test_every_agent_task_has_its_answers():
    work = run_fixes.tasks(CASES, ROWS, run_fixes.rule_verdicts(ROWS))
    answers = run_fixes.load_answers()
    settings = [(m, v) for m in run_fixes.MODELS for v in agent.SYSTEMS]
    chosen = (SCORES["chosen"]["model"], SCORES["chosen"]["version"])
    for t in work:
        for setting in settings:
            asked = (*setting, t["id"]) in answers
            assert asked if t["split"] == "dev" or setting == chosen else not asked  # test was run once, chosen on dev
    assert len(answers) == sum(len(settings) if t["split"] == "dev" else 1 for t in work)
    for answer in answers.values():
        assert answer["turns"] <= agent.MAX_TURNS and answer["runs"] <= agent.MAX_RUNS
        assert answer["outcome"] in ("fixed", "no fix", "turn limit", "loop")


def test_the_scores_and_page_come_from_the_kept_runs_and_answers():
    assert run_fixes.report(CASES, ROWS) == SCORES
    assert (ROOT / "docs" / "results" / "fixes.md").read_text(encoding="utf-8") == run_fixes.markdown(SCORES)


def test_the_hand_checks_of_the_key_fixes():
    by_id = {c["id"]: c for c in CASES}
    for label in HAND["labels"]:
        case = by_id[label["case"]]
        assert case["group"] == "value" and (label["file"], label["line"]) in {(e["file"], e["line"]) for e in case["expected"]}
    sample = HAND["name_sample"]
    assert len(sample) == len({tuple(x) for x in sample}) == 40
    assert sum(by_id[cid]["split"] == "dev" for cid, _, _ in sample) == 20
    for cid, rel, n in sample:
        assert by_id[cid]["group"] == "name" and (rel, n) in {(e["file"], e["line"]) for e in by_id[cid]["expected"]}
    judged = {(x["task"], x["model"], x["version"]) for x in HAND["real"]}
    assert len(judged) == len(HAND["real"]) and {x["verdict"] for x in HAND["real"]} <= {"right", "wrong"}


def test_readme_and_plan_numbers_for_fixes():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    rules, together, test = SCORES["rules"]["test"], SCORES["together"]["test"], SCORES["test_agent"]
    g = rules["groups"]
    made = g["name"]["expected"] + g["value"]["expected"]
    alarms = g["name"]["false_alarms"] + g["value"]["false_alarms"]
    fixed = sum(g[k]["right"] + g[k]["wrong"] for k in g)
    declined = sum(g[k]["declined"] for k in g)
    right = sum(together[k]["right"] for k in together)
    harm = sum(together[k]["harm"] for k in together)
    real = [x for x in SCORES["real"] if x["split"] == "test"]
    assert fixed == sum(g[k]["right"] for k in g)  # "all of them right"
    assert rules["command_lines_taken"] == rules["command_lines"] and test["right"] + test["wrong"] + test["left"] == declined
    assert [x["outcome"] for x in real].count("no fix") == 2 and [x["verdict"] for x in real].count("wrong") == 1
    expected = [
        f"**The rules, with no AI** (on the {made + alarms} lines the exact checks and the value search flag): fixed {fixed} of the {made} lines "
        f"the change made wrong, all of them right, and declined {declined}. The program took every one of the "
        f"{rules['command_lines']} fixed lines that are part of a documented command, run again after the change.",
        f"**An agent for the rest** ({SCORES['chosen']['model']} through Ollama, working only through tools, with a turn "
        f"limit and loop detection; chosen on dev from {len(run_fixes.MODELS)} models and {len(agent.SYSTEMS)} prompts): "
        f"of the {declined} lines, it fixed {test['right']} right and {test['wrong']} wrong, and left {test['left']} for "
        "a person.",
        f"**Together:** {right} of the {made} lines fixed right.",
        f"**Every false alarm got a fix too** ({harm} of {alarms}), so each fix needs a person's yes.",
        f"on test's {len(real)}, the agent left 2 for a person and fixed 1 wrong",
    ]
    for sentence in expected:
        assert sentence in readme, sentence
    done = (f"**Done:** on test, the rules fix {fixed} of the {made} lines the change made wrong, all right, and the agent "
            f"fixes {test['right']} of the other {declined} right; but every false alarm gets a fix too ({harm} of "
            f"{alarms}), so a fix waits for a person's yes")
    assert done in plan


def test_when_the_program_takes_a_fixed_command():
    accepted = {"outcome": "accepted", "exit": 0, "unknown": [], "message": ""}
    missing = {"outcome": "rejected", "exit": 2, "unknown": [], "message": "Error: Path 'mydb.db' does not exist."}
    unknown = {"outcome": "rejected", "exit": 2, "unknown": ["--cap"], "message": "No such option '--cap'."}
    assert run_fixes.taken(accepted, accepted) and run_fixes.taken(None, accepted)
    assert run_fixes.taken(missing, missing) and run_fixes.taken(None, missing)  # refused as before: a missing file
    assert not run_fixes.taken(accepted, unknown) and not run_fixes.taken(None, unknown) and not run_fixes.taken(accepted, missing)
    ran, fails = {"outcome": "succeeded", "exit": 0, "unknown": [], "message": ""}, {"outcome": "failed", "exit": 2, "unknown": [], "message": ""}
    assert not run_fixes.taken(ran, fails)  # a script that ran before the change and fails after it


def test_the_commands_a_fix_changes():
    from docsproof.fix import Fix
    lines = ["# tiny", "```console", "$ tiny --limit 3 \\", "    --verbose", "$ tiny --verbose", "```", "Use --limit."]
    fix = Fix("README.md", 3, (lines[2],), ("$ tiny --cap 3 \\",), "rule", "")
    found = run_fixes.fixed_commands("README.md", lines, [fix], {"tiny"}, set())
    assert [(old.argv, new.argv) for old, new in found] == [(("tiny", "--limit", "3", "--verbose"), ("tiny", "--cap", "3", "--verbose"))]
    on_option_line = Fix("README.md", 4, (lines[3],), ("    --quiet",), "rule", "")  # the command starts a line above
    assert [new.argv for _, new in run_fixes.fixed_commands("README.md", lines, [on_option_line], {"tiny"}, set())] == \
        [("tiny", "--limit", "3", "--quiet")]
    spacing = Fix("README.md", 5, (lines[4],), ("$  tiny --verbose",), "agent", "")  # the same words
    assert run_fixes.fixed_commands("README.md", lines, [spacing], {"tiny"}, set()) == []
    assert len(run_fixes.fixed_commands("README.md", lines, [spacing], {"tiny"}, set(), changed_only=False)) == 1
    prose = Fix("README.md", 7, (lines[6],), ("Use --cap.",), "rule", "")
    assert run_fixes.fixed_commands("README.md", lines, [prose], {"tiny"}, set()) == []
    assert [n.argv for _, n in run_fixes.fixed_commands("README.md", lines, [fix], {"tiny"}, set(), changed_only=False)] == \
        [("tiny", "--cap", "3", "--verbose")]


def test_a_fix_is_judged_only_as_it_was_judged(monkeypatch):
    import pytest
    first = HAND["real"][0]
    monkeypatch.setattr(run_fixes, "hand", lambda: {**HAND, "real": [{**first, "fix": ["another fix"]}]})
    answer = {"outcome": "fixed", "fix": {"new": first["fix"]}}
    with pytest.raises(SystemExit, match="Judge this fix by hand"):
        run_fixes.judgment({"id": first["task"]}, answer, (first["model"], first["version"]))


def test_a_rule_fix_the_program_refuses_goes_to_the_agent():
    case = {"id": "x/y:rename_option:1", "repo": "x/y", "split": "dev", "group": "name", "kind": "rename_option",
            "edit": {"kind": "rename_option", "old": "--a", "new": "--a2"}, "expected": [{"file": "README.md", "line": 1}]}
    row = {"id": case["id"], "pairs": {"option --a": "--a2"}, "own": [], "commands": [],
           "lines": [{"file": "README.md", "line": 1, "text": "tool --a", "names": [["option", "--a"]], "values": [],
                      "rule": {"new": "tool --a2", "reason": "`--a` is now `--a2`"}}]}
    refused = {case["id"]: {("README.md", 1): False}}
    assert [(x["how"], x["verdict"]) for x in run_fixes.line_outcomes([case], [row], refused, {}, None)] == [("agent", "left")]
    taken = {case["id"]: {("README.md", 1): True}}
    assert [(x["how"], x["verdict"]) for x in run_fixes.line_outcomes([case], [row], taken, {}, None)] == [("rule", "right")]
    planted = [t["id"] for t in run_fixes.tasks(CASES + [case], [row], refused) if t["kind"] == "planted"]
    assert planted == ["x/y:rename_option:1|README.md:1"] and run_fixes.tasks(CASES + [case], [row], taken)[0]["kind"] == "real"
