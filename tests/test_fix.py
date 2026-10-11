import shutil
import subprocess

import pytest
from conftest import FILES, write

from docsproof.fix import (Fix, apply, changes_value, check_shape, close, fixed_text, patch, rename_fix, renames,
                           stale_name, value_fix)
from docsproof.plant import apply as plant
from docsproof.values import ValueChange

DEFAULT = ValueChange("default", "--limit", "10", "20", "tiny/cli.py", 8, "default=20")
PYTHON = ValueChange("python", "Python", "3.9", "3.11", "pyproject.toml", 3, 'requires-python = ">=3.11"')


def changed(tmp_path, edit):
    before = write(tmp_path / "before", FILES)
    after = shutil.copytree(before, tmp_path / "after")
    plant(after, edit)
    return before, after


def test_a_rename_is_paired_from_the_change_alone(tmp_path):
    before, after = changed(tmp_path, {"kind": "rename_option", "old": "--limit", "new": "--renamed-limit"})
    assert renames(before, after) == {("option", "--limit"): "--renamed-limit"}
    before, after = changed(tmp_path / "2", {"kind": "rename_identifier", "old": "fetch_items", "new": "fetch_items2"})
    assert renames(before, after) == {("identifier", "fetch_items"): "fetch_items2"}
    before, after = changed(tmp_path / "3", {"kind": "rename_file", "old": "examples/basic.py", "new": "examples/basic2.py"})
    assert renames(before, after) == {("path", "examples/basic.py"): "examples/basic2.py"}
    before, after = changed(tmp_path / "4", {"kind": "rename_option", "old": "--limit", "new": "--cap"})
    assert renames(before, after) == {("option", "--limit"): "--cap"}  # one out and one in: a pair, alike or not


def test_two_equally_alike_new_names_make_no_pair(tmp_path):
    before = write(tmp_path / "before", FILES)
    after = write(tmp_path / "after", {**FILES, "tiny/cli.py": FILES["tiny/cli.py"].replace(
        '"--limit", type=int, default=10)', '"--limit-a", type=int, default=10)\n    parser.add_argument("--limit-b")')})
    assert ("option", "--limit") not in renames(before, after)


def test_a_rename_fix_changes_whole_names_only():
    assert rename_fix("Use `--limit` or --limit=3.", "option", "--limit", "--cap") == "Use `--cap` or --cap=3."
    assert rename_fix("Use --limit-max here.", "option", "--limit", "--cap") is None  # another option
    assert rename_fix("Call `fetch_items()`.", "identifier", "fetch_items", "list_items") == "Call `list_items()`."


def test_a_rename_fix_leaves_other_packages_and_file_paths_alone():
    line = "See [`tiny/Fetcher.py`](tiny/Fetcher.py) or `help(tiny.Fetcher)`; not `other.Fetcher`."
    assert rename_fix(line, "identifier", "Fetcher", "Fetcher2", own={"tiny"}) == \
        "See [`tiny/Fetcher.py`](tiny/Fetcher.py) or `help(tiny.Fetcher2)`; not `other.Fetcher`."
    assert rename_fix('"_extensions": ["jinja2_time.TimeExtension"]', "identifier", "TimeExtension", "T2",
                      own={"cookiecutter"}) is None
    assert stale_name(line, "identifier", "Fetcher", own={"tiny"})
    assert not stale_name("`tiny/Fetcher.py` and `other.Fetcher`", "identifier", "Fetcher", own={"tiny"})
    assert stale_name("`other.Fetcher`", "identifier", "Fetcher")  # with no package names, every mention counts
    assert not stale_name("[`tiny/Fetcher.py`](tiny/Fetcher.py)", "identifier", "Fetcher")  # but never a file path


def test_a_value_fix_needs_the_old_value_once():
    assert value_fix("Use `--limit` to cap the list (default: 10).", DEFAULT) == "Use `--limit` to cap the list (default: 20)."
    assert value_fix("Default: 10. Range 1 to 10.", DEFAULT) is None  # twice: which one is the default?
    assert value_fix("Requires Python 3.9 or later; 3.90 isn't real.", PYTHON) == "Requires Python 3.11 or later; 3.90 isn't real."


def test_a_fix_must_state_the_new_value_in_place_of_the_old():
    old = "Jitter in `[0, jitter]`. **Default:** 0."
    assert changes_value(old, "Jitter in `[0, jitter]`. **Default:** 1.", ValueChange("default", "--j", "0", "1", "", 0, ""))
    assert not changes_value(old, old.replace("Jitter", "Spread"), ValueChange("default", "--j", "0", "1", "", 0, ""))
    assert not changes_value("Requires Python 3.9+", "Requires a recent Python", PYTHON)  # the new value is missing
    assert not changes_value("Requires Python 3.9+", "Requires Python 3.9+ (3.11+ soon)", PYTHON)  # the old one stays


def test_close():
    assert close("Requires Python 3.9 or later.", "Requires Python 3.11 or later.")
    assert not close("Requires Python 3.9 or later.", "This project needs a recent interpreter to work well.")


LINES = ["one", "$ tool --old \\", "    --other", "four", "five"]


@pytest.mark.parametrize("fix, problem", [
    (Fix("d.md", 2, ("$ tool --old \\",), ("$ tool --new \\",), "agent", ""), None),
    (Fix("d.md", 2, ("$ tool --old \\", "    --other"), ("$ tool --new \\",), "agent", ""), "same number"),
    (Fix("d.md", 1, tuple(LINES[:4]), ("one", "$ tool --new \\", "    --other", "4"), "agent", ""), "at most 3"),
    (Fix("d.md", 3, ("    --other",), ("    --others",), "agent", ""), "must include line 2"),
    (Fix("d.md", 2, ("$ tool --x \\",), ("$ tool --new \\",), "agent", ""), "aren't the doc's lines"),
    (Fix("d.md", 2, ("$ tool --old \\",), ("$ tool --old \\",), "agent", ""), "changes nothing"),
    (Fix("d.md", 2, ("$ tool --old \\",), ("$ tool\n--new",), "agent", ""), "one line in each"),
    (Fix("d.md", 2, ("$ tool --old \\",), ("Run the program with the new switch, then check what it printed.",),
         "agent", ""), "rewrites a line"),
])
def test_the_shape_of_a_fix_is_checked(fix, problem):
    found = check_shape(fix, LINES, 2)
    assert (found is None) if problem is None else (problem in found)


def test_fixes_are_made_in_place_and_never_overlap():
    assert apply(LINES, [Fix("d.md", 2, (LINES[1],), ("$ tool --new \\",), "rule", "")])[1] == "$ tool --new \\"
    with pytest.raises(ValueError, match="overlapping"):
        apply(LINES, [Fix("d.md", 2, tuple(LINES[1:3]), ("a", "b"), "agent", ""),
                      Fix("d.md", 3, (LINES[2],), ("c",), "rule", "")])
    with pytest.raises(ValueError, match="doesn't match"):
        apply(LINES, [Fix("d.md", 1, ("not one",), ("1",), "rule", "")])


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_patch_keeps_line_endings_and_git_applies_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.md").write_bytes(b"first\r\nUse --limit here.\r\nlast\r\n")
    (repo / "b.rst").write_bytes(b"Requires Python 3.9+")  # no newline at the end
    fixes = [Fix("a.md", 2, ("Use --limit here.",), ("Use --cap here.",), "rule", ""),
             Fix("b.rst", 1, ("Requires Python 3.9+",), ("Requires Python 3.11+",), "rule", "")]
    assert fixed_text(repo / "a.md", fixes[:1]) == "first\r\nUse --cap here.\r\nlast\r\n"
    diff = patch(repo, fixes)
    assert "\\ No newline at end of file" in diff and "+Use --cap here.\r\n" in diff
    git = ["git", "-c", "core.autocrlf=false", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    (tmp_path / "fix.patch").write_text(diff, encoding="utf-8", newline="")
    subprocess.run([*git, "apply", str(tmp_path / "fix.patch")], check=True)
    assert (repo / "a.md").read_bytes() == b"first\r\nUse --cap here.\r\nlast\r\n"
    assert (repo / "b.rst").read_bytes() == b"Requires Python 3.11+"


def test_a_line_with_a_form_feed_in_it_can_still_be_fixed(tmp_path):
    lines = ["Use `--limit`\x0c to cap it.", "next"]  # one line for git, two for str.splitlines
    fix = Fix("a.md", 1, (lines[0],), ("Use `--cap`\x0c to cap it.",), "rule", "`--limit` is now `--cap`")
    assert check_shape(fix, lines, 1) is None
    assert check_shape(Fix("a.md", 1, (lines[0],), ("Use `--cap`\n to cap it.",), "rule", ""), lines, 1) == \
        "give one line in each string"
    (tmp_path / "a.md").write_bytes(b"Use `--limit`\x0c to cap it.\r\nnext\n")
    assert fixed_text(tmp_path / "a.md", [fix]) == "Use `--cap`\x0c to cap it.\r\nnext\n"  # its own ending kept
