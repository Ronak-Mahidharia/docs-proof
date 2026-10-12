"""Checks on the committed answer key, the hand checks, and the published scores."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import build_cases  # noqa: E402
import run_baseline  # noqa: E402
import run_commands  # noqa: E402
from docsproof.commands import Problem  # noqa: E402

REPOS = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
CASES = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
HAND = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))
RESULTS = ROOT / "data" / "results"
README = (ROOT / "README.md").read_text(encoding="utf-8")
COMMANDS = json.loads((ROOT / "data" / "results" / "commands-scores.json").read_text(encoding="utf-8"))


def test_repositories_are_pinned_permissive_and_split_evenly():
    assert len(REPOS) == 30 and len({r["repo"] for r in REPOS}) == 30
    assert all(re.fullmatch(r"[0-9a-f]{40}", r["commit"]) for r in REPOS)
    assert {r["license"] for r in REPOS} <= {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "Unlicense"}
    assert sum(r["split"] == "dev" for r in REPOS) == sum(r["split"] == "test" for r in REPOS) == 15


def test_the_readme_names_the_licenses_and_what_is_quoted():
    section = README.split("\n## License\n", 1)[1]
    assert f"The {len(REPOS)} repositories used for measurement" in section
    assert "[data/repos.json](data/repos.json)" in section and "short excerpts" in section
    for license in {r["license"] for r in REPOS}:  # BSD-2-Clause and BSD-3-Clause both as "BSD"
        assert re.search(rf"\b{re.escape(license.split('-')[0])}\b", section), license


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
    assert run_baseline.report(CASES, run_commands.load_rows("commands.jsonl")) == COMMANDS["commands"]


def test_results_pages_are_built_from_the_published_scores():
    exact = json.loads((RESULTS / "exact-scores.json").read_text(encoding="utf-8"))
    assert run_baseline.markdown(exact) == (ROOT / "docs" / "results" / "exact.md").read_text(encoding="utf-8")
    page = run_commands.markdown(COMMANDS["audit"]["repos"], COMMANDS["audit"], COMMANDS["commands"], exact)
    assert page == (ROOT / "docs" / "results" / "commands.md").read_text(encoding="utf-8")


def test_every_line_the_exact_checks_flag_outside_the_key_was_checked_by_hand():
    left_out = [c for c in HAND["full_checks"] if c["what"].startswith("every doc line the exact check flags")]
    assert len(left_out) == 1
    scores = json.loads((ROOT / "data" / "results" / "exact-scores.json").read_text(encoding="utf-8"))
    false_alarms = sum(t["fp"] for split in ("dev", "test") for t in scores[split]["kinds"].values())
    assert false_alarms == left_out[0]["right"]  # the rest were the key's mistakes, and were added


def test_every_audit_finding_is_checked_by_hand():
    rows = [json.loads(line) for line in (RESULTS / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    checks = HAND["audit"]["findings"]
    assert {(r["repo"], r["file"], r["line"], r["option"]) for r in rows} == \
        {(c["repo"], c["file"], c["line"], c["option"]) for c in checks}
    assert len(rows) == COMMANDS["audit"]["findings"] == sum(r["findings"] for r in COMMANDS["audit"]["repos"])
    assert {c["verdict"] for c in checks} <= {"out of date", "false alarm"}
    findings: dict[str, list[Problem]] = {}
    for r in rows:
        findings.setdefault(r["repo"], []).append(Problem(r["file"], r["line"], r["program"], r["option"], r["proof"]))
    hand = run_commands.hand_verdicts(findings)
    assert hand == {k: COMMANDS["audit"][k] for k in hand}
    findings["pypa/pipx"].append(Problem("README.md", 1, "pipx", "--unchecked", ""))
    with pytest.raises(SystemExit):
        run_commands.hand_verdicts(findings)  # a new finding has to be checked by hand before the results are published


def test_commands_not_read_are_expected_lines_the_check_missed():
    flagged = run_commands.load_rows("commands.jsonl")
    by_id = {c["id"]: c for c in CASES}
    for case_id, file, line, _ in HAND["commands_not_read"]["lines"]:
        assert (file, line) in {(e["file"], e["line"]) for e in by_id[case_id]["expected"]}, (case_id, file, line)
        assert (file, line) not in flagged[case_id], (case_id, file, line)


def test_readme_numbers_match_the_key_and_the_scores():
    scores = json.loads((ROOT / "data" / "results" / "exact-scores.json").read_text(encoding="utf-8"))
    test, dev = scores["test"], scores["dev"]
    name, value = test["name"], test["value"]
    expected = [
        f"**{len(CASES)} planted changes in {len(REPOS)} real repositories.**",
        f"**Two answer keys:** changes planted in {len(REPOS)} real repositories, and the same repositories' own history",
        f"{sum(len(c['expected']) for c in CASES)} lines in all",
        f"{dev['cases']} dev cases in {dev['repos']} repositories, and {test['cases']} test cases in the other {test['repos']}",
        f"{dev['control']['cases'] + test['control']['cases']} cases change something no doc mentions",
        f"the {sum(c['group'] == 'value' for c in CASES)} cases that change a value",
        f"All on the test split ({test['repos']} repositories, {test['cases']} cases)",
        f"**Renames** ({name['cases']} cases, {name['tp'] + name['fn']} lines): found all {name['tp']}, "
        f"with {name['fp']} false alarms (precision {100 * name['precision']:.1f}%).",
        f"**Changed values** ({value['cases']} cases, {value['tp'] + value['fn']} lines): found {value['tp']} of "
        f"{value['tp'] + value['fn']}.",
        f"**Controls** ({test['control']['cases']} cases): no false alarms.",
        f"the {name['fp']} are lines the change doesn't make wrong",
    ]
    changed, left_out = HAND["full_checks"]
    expected += [
        f"{changed['right']} of {changed['lines']} were right, and the other {changed['lines'] - changed['right']} were removed",
        f"{left_out['lines'] - left_out['right']} of {left_out['lines']} named the project's own class or function",
    ]
    audit, renamed = COMMANDS["audit"], COMMANDS["commands"]["test"]["kinds"]["rename_option"]
    not_read = [x for x in HAND["commands_not_read"]["lines"] if x[0].split(":")[0] in {r["repo"] for r in REPOS if r["split"] == "test"}]
    reasons = audit["reasons"]
    plugins, other, on_purpose = (reasons[r] for r in ("an option a plugin adds", "another program's option",
                                                      "a command the docs show failing on purpose"))
    expected += [
        f"**Renamed options** ({renamed['cases']} cases, {renamed['tp'] + renamed['fn']} lines): flagged "
        f"{renamed['tp'] + renamed['fp']} lines in commands, with no false alarms",
        f"**The other {renamed['fn']} lines:** {renamed['fn'] - len(not_read)} mention the option outside a command",
        f"{len(not_read)} are commands it doesn't read yet",
        f"{audit['commands']:,} documented commands, {audit['commands_with_options']} with long options. "
        f"{audit['findings']} use an option the code doesn't declare, and a hand check found none of them out of date: "
        f"{plugins} are options that plugins add, {other} is another program's option, and {on_purpose} is an error "
        "the docs show on purpose.",
    ]
    assert name["fn"] == 0 and test["control"]["false_alarm_cases"] == 0
    assert renamed["fp"] == 0 and audit["out_of_date"] == 0 and sum(reasons.values()) == audit["findings"]
    for sentence in expected:
        assert sentence in README, sentence
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    done = (f"**Done:** {len(CASES)} cases in {len(REPOS)} repositories. On test, the baseline found all {name['tp']} rename "
            f"lines with {name['fp']} false alarms, and {value['tp']} of {value['tp'] + value['fn']} changed-value lines")
    assert done in plan
    done = (f"**Done:** on test, it flagged {renamed['tp'] + renamed['fp']} of the {renamed['tp'] + renamed['fn']} "
            f"renamed-option lines with no false alarms, and an audit of {audit['commands']:,} documented commands "
            "found none out of date")
    assert done in plan


REPO_DIR = ROOT / "data" / "repos"


@pytest.mark.skipif(not REPO_DIR.is_dir(), reason="the pinned repositories aren't fetched (scripts/fetch_repos.py)")
def test_expected_lines_match_the_pinned_docs():
    for c in CASES:
        root = REPO_DIR / c["repo"].replace("/", "__")
        for e in c["expected"]:
            text = (root / e["file"]).read_text(encoding="utf-8", errors="replace").splitlines()[e["line"] - 1]
            assert hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] == e["sha256"], (c["id"], e["file"], e["line"])


def test_a_planted_copy_keeps_links_as_links(tmp_path):
    """The copy each planted change is made in: a link to a doc stays a link, on macOS (cp -R) and on Linux
    (shutil.copytree), so the copy's docs are the original's."""
    src = tmp_path / "repo"
    (src / "docs").mkdir(parents=True)
    (src / ".git").mkdir()
    (src / "README.md").write_text("Use --limit.\n", encoding="utf-8")
    (src / "docs" / "index.md").symlink_to("../README.md")
    build_cases.clone(src, tmp_path / "copy")
    copy = tmp_path / "copy"
    assert (copy / "docs" / "index.md").is_symlink() and not (copy / ".git").exists()
    assert build_cases.doc_files(copy) == build_cases.doc_files(src) == ["README.md"]
