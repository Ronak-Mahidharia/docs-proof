"""The real-history miner (scripts/build_real_cases.py), on a small git history made fresh for each test: a change
renames an option without touching the docs, and a later commit fixes the docs."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FILES, write

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_real_cases as mine  # noqa: E402
from fetch_history import REF  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
LINE = "Use `--limit` to cap the list (default: 10)."


def git(root: Path, *args: str, day: str = "2021-01-04") -> str:
    when = f"{day}T12:00:00+00:00"
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True,
                          env=env).stdout


def commit(root: Path, day: str, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message, day=day)
    return git(root, "rev-parse", "HEAD").strip()


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.fixture
def history(tmp_path):
    """a: the start. c: --limit becomes --cap in the code, which keeps the old name only in a comment and a longer
    string, and a new doc line still says --limit. e: a doc line naming the project and a literal goes, so does one
    naming an option the code still has, another --limit line changes, and the code's comment about --limit goes.
    d: the docs drop --limit."""
    files = {**FILES, "README.md": FILES["README.md"] + "Import `tiny` and set `true` to start.\n",
             "docs/usage.md": "Pass --limit 5 for five.\nUse --max-results to limit output.\nThe --verbose flag prints more.\n"}
    root = write(tmp_path / "tiny", files)
    git(root, "init", "-q", "-b", "main")
    a = commit(root, "2021-01-04", "start")
    edit(root, "tiny/cli.py", '"--limit", type=int', '"--cap", dest="limit", type=int, help="was --limit"')
    edit(root, "tiny/cli.py", "def main(argv=None):\n", "def main(argv=None):\n    # --limit is now --cap\n")
    edit(root, "docs/usage.md", "prints more.\n", "prints more.\nOld scripts may still pass --limit.\n")
    c = commit(root, "2021-02-01", "rename --limit to --cap")
    edit(root, "README.md", "Import `tiny` and set `true` to start.\n", "Start here.\n")
    edit(root, "README.md", "Run `tiny --max-results 5` to see five results.\n", "")
    edit(root, "docs/usage.md", "Pass --limit 5 for five.", "Pass --limit 3 for three.")
    edit(root, "tiny/cli.py", "    # --limit is now --cap\n", "")  # the name's count changes, but it was already gone
    e = commit(root, "2021-02-15", "tidy")
    edit(root, "README.md", LINE, "Use `--cap` to cap the list (default: 10).")
    edit(root, "docs/usage.md", "Pass --limit 3 for three.\n", "")
    edit(root, "docs/usage.md", "Old scripts may still pass --limit.\n", "")
    d = commit(root, "2021-03-01", "docs: --cap")
    git(root, "update-ref", REF, d)
    return root, {"a": a, "c": c, "e": e, "d": d}


def test_a_doc_fix_leads_back_to_the_change_that_left_the_line_wrong(history):
    root, at = history
    cases, funnel = mine.build({"repo": "test/tiny", "split": "dev", "commit": at["d"]}, mine.History(root))
    assert cases == [{"repo": "test/tiny", "split": "dev", "commit": at["c"], "parent": at["a"], "date": "2021-02-01",
                      "id": f"test/tiny@{at['c'][:10]}",
                      "expected": [{"file": "README.md", "line": 6, "sha256": mine.line_hash(LINE), "kind": "option",
                                    "name": "--limit", "fixed_by": at["d"], "fixed_on": "2021-03-01", "days": 28}]}]
    # The fix drops --limit from 3 doc lines. Earlier, `tiny` (the project), `true` (a literal), and --max-results
    # (still in the code) left the docs, and none of them counts. One --limit line changed after the change, so it
    # can't be matched, and another was written by the change.
    assert funnel == {"commits_touching_docs": 3, "references_removed": 6, "already_gone": 3,
                      "with_a_removal_commit": 3, "lines_changed_before_the_fix": 1, "lines_new_in_the_change": 1,
                      "expected_lines": 1}


def test_the_code_has_a_reference_only_where_python_sees_it(history):
    root, at = history
    h = mine.History(root)
    assert h.in_code(at["a"], "option", "--limit")
    assert not h.in_code(at["c"], "option", "--limit")  # only in a comment and a longer string now
    assert h.in_code(at["c"], "option", "--cap")
    assert h.in_code(at["c"], "identifier", "fetch_items")
    assert h.in_code(at["c"], "path", "examples/basic.py") and not h.in_code(at["c"], "path", "examples/gone.py")
    assert h.removal(at["e"], "option", "--limit") == at["c"]  # not e, which only dropped a comment
    assert h.removal(at["e"], "option", "--cap") is None  # it never left the code
    assert h.own(at["c"]) == {"tiny", "examples"}  # tests/ isn't the project's code
    assert h.parent(at["a"]) is None


def test_the_projects_own_names_include_a_src_layout(tmp_path):
    root = write(tmp_path / "proj", {"src/pkg/__init__.py": "", "src/tool.py": "", "setup.py": "", "docs/conf.py": "",
                                     "pkg2/tests/test_x.py": "", "README.md": "x\n"})
    git(root, "init", "-q", "-b", "main")
    assert mine.History(root).own(commit(root, "2021-01-04", "start")) == {"pkg", "tool", "setup"}


def test_occurs_counts_names_and_exact_strings():
    assert mine.occurs('p.add_argument("--limit")', "option", "--limit")
    assert not mine.occurs("x = 1  # --limit", "option", "--limit")
    assert not mine.occurs('help = "was --limit"', "option", "--limit")
    assert not mine.occurs("limit = 1", "option", "limit")  # an option counts only as a string
    for source in ("def fetch_items(): pass", "class fetch_items: pass", "obj.fetch_items()", "f(fetch_items=1)",
                   "def f(fetch_items): pass", "from x import fetch_items", "import a.fetch_items",
                   "import x as fetch_items", "fetch_items = 1", "y = 'fetch_items'"):
        assert mine.occurs(source, "identifier", "fetch_items"), source
    assert not mine.occurs("y = 'fetch_items is gone'", "identifier", "fetch_items")
    assert not mine.occurs("def (", "identifier", "x")  # a file that doesn't parse has nothing


def test_references_reads_the_four_kinds():
    text = "Run `tiny --max-results 5`, set TINY_TOKEN, call `pkg.fetch_items()`, or see examples/basic.py."
    assert mine.references(text) == {("option", "--max-results"), ("env", "TINY_TOKEN"),
                                     ("identifier", "fetch_items"), ("path", "examples/basic.py")}
    assert mine.references("Call `run()` or $HOME_DIR.") == set()  # a short name, and a shell variable


def test_hunks_skip_a_deleted_file(tmp_path):
    root = write(tmp_path / "docs", {"README.md": "one\ntwo\n", "CHANGELOG.md": "- old\n"})
    git(root, "init", "-q", "-b", "main")
    first = commit(root, "2021-01-04", "start")
    (root / "CHANGELOG.md").unlink()
    edit(root, "README.md", "two\n", "2\n")
    second = commit(root, "2021-01-05", "edit")
    assert mine.hunks(mine.History(root), first, second, ["CHANGELOG.md", "README.md"]) == [
        {"file": "README.md", "removed": ["two"], "added": ["2"]}]


def test_hunks_keep_doc_lines_that_look_like_file_headers(tmp_path):
    """A removed "-- x" shows as "--- x" in a diff, and an added "++ x" as "+++ x"; only a file's header has them."""
    root = write(tmp_path / "docs", {"README.md": "a\n-- an SQL comment\nb\n", "docs/usage.md": "c\n"})
    git(root, "init", "-q", "-b", "main")
    first = commit(root, "2021-01-04", "start")
    edit(root, "README.md", "-- an SQL comment\n", "++ added\n")
    edit(root, "docs/usage.md", "c\n", "d\n")
    second = commit(root, "2021-01-05", "edit")
    assert mine.hunks(mine.History(root), first, second, ["README.md", "docs/usage.md"]) == [
        {"file": "README.md", "removed": ["-- an SQL comment"], "added": ["++ added"]},
        {"file": "docs/usage.md", "removed": ["c"], "added": ["d"]}]


def test_the_history_must_be_at_the_pinned_commit(history):
    root, at = history
    with pytest.raises(SystemExit, match="isn't at the pinned commit"):
        mine.build({"repo": "test/tiny", "split": "dev", "commit": at["c"]}, mine.History(root))


def test_the_window_starts_at_midnight_utc_at_any_hour_and_in_any_time_zone(tmp_path, monkeypatch):
    """Git reads a bare date such as 2020-01-01 at the current time of day, so the miner's window used to move with
    the clock (alembic's count of commits touching docs was 401 at 15:36 EDT and 400 at 17:10). Written with its time
    and zone, it starts at the same moment wherever and whenever the miner runs."""
    from fetch_history import SINCE, SINCE_GIT
    root = write(tmp_path / "tiny", FILES)
    git(root, "init", "-q", "-b", "main")

    def commit_at(when: str, message: str) -> str:
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        for args in (("add", "-A"), ("commit", "-q", "-m", message)):
            subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=env)
        return git(root, "rev-parse", "HEAD").strip()
    commit_at("2019-12-30T12:00:00+00:00", "start")
    for when in ("2019-12-31T23:30:00+00:00", "2020-01-01T00:30:00+00:00", "2020-01-01T23:30:00+00:00"):
        (root / "docs" / "usage.md").write_text(f"Edited at {when}.\n", encoding="utf-8")
        last = commit_at(when, f"a doc edit at {when}")
    git(root, "update-ref", REF, last)
    counts, bare = set(), set()
    for now in ("1791760000", "1791780000"):  # two times of day on Oct 11, 2026
        for tz in ("UTC", "Asia/Kolkata", "America/New_York"):
            monkeypatch.setenv("GIT_TEST_DATE_NOW", now)
            monkeypatch.setenv("TZ", tz)
            _, funnel = mine.build({"repo": "test/tiny", "split": "dev", "commit": last}, mine.History(root))
            counts.add(funnel["commits_touching_docs"])
            bare.add(len(git(root, "rev-list", "--first-parent", f"--since={SINCE}", last).split()))
    assert counts == {2}  # the two edits after midnight UTC, at any hour, in any zone
    assert len(bare) > 1  # a bare date gives a different window depending on the hour and the zone
    assert SINCE_GIT == f"{SINCE} 00:00:00 +0000"
