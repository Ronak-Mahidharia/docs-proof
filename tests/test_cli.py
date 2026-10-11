"""The docs-proof command, on a small git repository made fresh for each test."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import FILES, write

from docsproof import cli
from docsproof import model as models
from docsproof.check import check

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
SRC = Path(__file__).resolve().parent.parent / "src"
FIX = "Use `--cap` to cap the list (default: 10)."


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                           "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True).stdout


def repo(tmp_path: Path) -> Path:
    root = write(tmp_path / "tiny", FILES)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    return root


def rename_limit(root: Path) -> None:
    """The change: the --limit option becomes --cap, and no doc is touched."""
    path = root / "tiny" / "cli.py"
    path.write_text(path.read_text().replace('"--limit", type=int', '"--cap", dest="limit", type=int'))


def test_a_change_in_the_working_tree(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 1
    out = capsys.readouterr().out
    assert "1 doc line the change made wrong (HEAD to the working tree)" in out
    assert "README.md:6\n    Use `--limit` to cap the list (default: 10).\n" in out
    assert "  why: --limit was at tiny/cli.py:8 before the change and is gone\n" in out
    assert f"  fix: {FIX}\n" in out and "1 fix suggested." in out


def test_a_branch_against_where_it_started(tmp_path, capsys):
    root = repo(tmp_path)
    start = git(root, "rev-parse", "HEAD").strip()
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    git(root, "switch", "-q", "main")  # main moves on with a doc change of its own
    (root / "docs" / "usage.md").write_text("Use --max-results to limit output.\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "docs")
    git(root, "switch", "-q", "rename")
    (root / "README.md").write_text((root / "README.md").read_text() + "Uncommitted: --limit\n", encoding="utf-8")
    assert cli.main(["--repo", str(root), "--head", "HEAD"]) == 1  # what's committed, not the line just added
    out = capsys.readouterr().out
    assert f"(main at {start[:7]} to HEAD)" in out and "README.md:6" in out and "Uncommitted" not in out


def test_nothing_to_find(tmp_path, capsys):
    root = repo(tmp_path)
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0
    assert "no doc line found that the change made wrong" in capsys.readouterr().out


def test_json_and_a_patch_that_git_applies(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    patch_file = tmp_path / "fixes.patch"
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json", "--patch", str(patch_file)]) == 1
    found = json.loads(capsys.readouterr().out)
    assert found["base"] == "HEAD" and found["head"] == "the working tree"
    assert found["findings"] == [{"file": "README.md", "line": 6, "text": "Use `--limit` to cap the list (default: 10).",
                                  "why": ["--limit was at tiny/cli.py:8 before the change and is gone"],
                                  "fix": {"line": 6, "old": ["Use `--limit` to cap the list (default: 10)."],
                                          "new": [FIX], "reason": "`--limit` is now `--cap`"}, "left": ""}]
    git(root, "apply", str(patch_file))
    assert (root / "README.md").read_text().splitlines()[5] == FIX
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0


def test_apply_changes_nothing_without_a_yes(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    readme = (root / "README.md").read_text()
    for answer in ("n", "", "sure"):
        assert cli.main(["--repo", str(root), "--base", "HEAD", "--apply"], read=lambda q, a=answer: a) == 1
        assert (root / "README.md").read_text() == readme

    def no_one_there(question):
        raise EOFError
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--apply"], read=no_one_there) == 1
    assert (root / "README.md").read_text() == readme
    asked = []
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--apply"], read=lambda q: asked.append(q) or "y") == 1
    assert asked == [""]  # the question is on stderr, after the patch
    assert (root / "README.md").read_text() == readme.replace("Use `--limit` to cap", "Use `--cap` to cap")
    err = capsys.readouterr().err
    assert err.rindex("-Use `--limit`") < err.rindex("Make these fixes in the docs? [y/N] ")


def test_json_stays_json_when_apply_asks(tmp_path):
    root = repo(tmp_path)
    rename_limit(root)
    done = subprocess.run([sys.executable, "-m", "docsproof", "--repo", str(root), "--base", "HEAD", "--json", "--apply"],
                          input="n\n", capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(SRC)})
    assert done.returncode == 1 and json.loads(done.stdout)["findings"][0]["line"] == 6  # input() prompts on stdout
    assert "Make these fixes in the docs? [y/N] " in done.stderr and "did not make the 1 fix" in done.stderr


def test_a_patch_says_where_it_went(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    out = tmp_path / "fixes.patch"
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--patch", str(out)]) == 1
    printed = capsys.readouterr()
    assert f"wrote 1 fix to {out}; make it with `git apply {out}` in the project's top folder" in printed.err
    assert "1 fix suggested." in printed.out and "--patch FILE" not in printed.out  # no hint to do what it just did
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--patch", str(tmp_path / "missing" / "x.patch")]) == 2
    assert "couldn't write the patch to" in capsys.readouterr().err


def test_two_folders_without_git(tmp_path, capsys):
    before = write(tmp_path / "before", FILES)
    after = shutil.copytree(before, tmp_path / "after")
    rename_limit(after)
    assert cli.main(["--before", str(before), "--after", str(after)]) == 1
    assert f"fix: {FIX}" in capsys.readouterr().out


def test_what_the_working_tree_copy_takes(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    (root / ".gitignore").write_text("docs/ignored.md\n", encoding="utf-8")
    (root / "docs" / "ignored.md").write_text("Run with --limit.\n", encoding="utf-8")  # ignored by git
    (root / "docs" / "new.md").write_text("Try --limit 3.\n", encoding="utf-8")  # new, not yet added
    os.remove(root / "docs" / "usage.md")  # deleted, not yet staged
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json"]) == 1
    found = [(x["file"], x["line"]) for x in json.loads(capsys.readouterr().out)["findings"]]
    assert found == [("README.md", 6), ("docs/new.md", 1)]


def test_it_says_why_it_couldnt_run(tmp_path, capsys):
    plain = write(tmp_path / "plain", FILES)
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q", "-b", "main")
    apart = repo(tmp_path)
    git(apart, "switch", "-q", "--orphan", "other")
    git(apart, "commit", "-q", "--allow-empty", "-m", "a history of its own")
    cases = [(["--repo", str(plain)], f"{plain} isn't in a git repository"),
             (["--repo", str(tmp_path / "nowhere")], "nowhere isn't a folder"),
             (["--repo", str(empty)], "has no commit yet, so there's nothing to compare with"),
             (["--repo", str(apart)], "HEAD and main have no commit in common; give --base"),
             (["--repo", str(apart), "--base", "nope"], "no commit, branch, or tag called nope"),
             (["--repo", str(apart), "--head", "HEAD", "--apply"], "can't be used with --head"),
             (["--before", str(plain)], "give both --before and --after")]
    for argv, message in cases:
        assert cli.main(argv) == 2
        assert message in capsys.readouterr().err, message


def test_an_error_it_doesnt_expect_still_exits_2(tmp_path, capsys, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("boom")
    monkeypatch.setattr(cli, "check", broken)
    assert cli.main(["--before", str(write(tmp_path / "a", FILES)), "--after", str(write(tmp_path / "b", FILES))]) == 2
    assert "the check stopped on an error it doesn't expect (KeyError: 'boom')" in capsys.readouterr().err


def test_a_changed_default(tmp_path, capsys):
    root = repo(tmp_path)
    path = root / "tiny" / "cli.py"
    path.write_text(path.read_text().replace('"--limit", type=int, default=10', '"--limit", type=int, default=20'))
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 1
    out = capsys.readouterr().out
    assert "  why: The default of the option --limit changed from 10 to 20. The code after the change" in out
    assert "  fix: Use `--limit` to cap the list (default: 20)." in out


def test_with_a_model_a_value_line_is_kept_only_if_the_model_flags_it(tmp_path, monkeypatch):
    before = write(tmp_path / "before", FILES)
    after = shutil.copytree(before, tmp_path / "after")
    path = after / "tiny" / "cli.py"
    path.write_text(path.read_text().replace("default=10)", "default=20)"))
    answers = {"no": {"states_old_value": False, "doc_quote": "", "code_quote": "", "reason": "about another tool"},
               "yes": {"states_old_value": True, "doc_quote": "(default: 10)", "code_quote": "default=20",
                       "reason": "the line states the old default"}}
    for answer, expected in (("no", []), ("yes", [("README.md", 6)])):
        monkeypatch.setattr(models, "ask", lambda change, cand, name, version, a=answer: {"raw": json.dumps(answers[a])})
        assert [(x.file, x.line) for x in check(before, after, model="any")] == expected
    assert [(x.file, x.line) for x in check(before, after)] == [("README.md", 6)]  # with no model, the search alone


def test_the_command_itself(tmp_path):
    root = repo(tmp_path)
    rename_limit(root)
    done = subprocess.run([sys.executable, "-m", "docsproof", "--repo", str(root), "--base", "HEAD"],
                          capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(SRC)})
    assert done.returncode == 1 and f"fix: {FIX}" in done.stdout


def test_a_line_both_checks_flag_gets_both_proofs_and_one_fix(tmp_path, capsys):
    files = {**FILES, "pyproject.toml": FILES["pyproject.toml"] + '[project.scripts]\ntiny = "tiny.cli:main"\n',
             "docs/run.md": "```console\n$ tiny --limit 3\n```\nOr `tiny --limit 5`, or `tiny --limit 9`.\n"}
    root = write(tmp_path / "tiny", files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    rename_limit(root)
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json"]) == 1
    found = {(x["file"], x["line"]): x for x in json.loads(capsys.readouterr().out)["findings"]}
    both = ["--limit was at tiny/cli.py:8 before the change and is gone", "`tiny` declares no --limit option in the code"]
    assert found[("docs/run.md", 2)]["why"] == both and found[("docs/run.md", 2)]["fix"]["new"] == ["$ tiny --cap 3"]
    assert found[("docs/run.md", 4)]["why"] == both  # two commands on the line, one proof each
    assert found[("docs/run.md", 4)]["fix"]["new"] == ["Or `tiny --cap 5`, or `tiny --cap 9`."]


def test_a_link_out_of_the_repository_is_never_read(tmp_path, capsys):
    outside = tmp_path / "outside.md"
    outside.write_text("Use --limit.\n", encoding="utf-8")
    root = repo(tmp_path)
    (root / "docs" / "linked.md").symlink_to(outside)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "a link out of the repository")
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    for argv in (["--base", "main"], ["--base", "main", "--head", "HEAD"]):  # the working tree, then a commit
        assert cli.main(["--repo", str(root), *argv, "--json"]) == 1
        assert [x["file"] for x in json.loads(capsys.readouterr().out)["findings"]] == ["README.md"]
    cli.export_worktree(root, tmp_path / "worktree")
    cli.export_ref(root, "HEAD", tmp_path / "commit")
    for copy in (tmp_path / "worktree", tmp_path / "commit"):  # the link isn't even copied
        assert (copy / "docs" / "usage.md").is_file() and not os.path.lexists(copy / "docs" / "linked.md")


def test_doc_lines_the_change_already_updated_arent_flagged(tmp_path, capsys):
    root = repo(tmp_path)
    path, readme = root / "tiny" / "cli.py", root / "README.md"
    path.write_text(path.read_text().replace('"--limit", type=int, default=10', '"--limit", type=int, default=20'))
    readme.write_text(readme.read_text().replace("(default: 10)", "(default: 20)"), encoding="utf-8")  # a new default
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0
    git(root, "commit", "-q", "-am", "new default, and its doc line")
    rename_limit(root)
    readme.write_text(readme.read_text().replace("Use `--limit`", "Use `--cap`"), encoding="utf-8")  # a new name
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0
    assert capsys.readouterr().out.count("no doc line found") == 2


def test_a_command_that_only_moved_isnt_flagged(tmp_path, capsys):
    files = {**FILES, "pyproject.toml": FILES["pyproject.toml"] + '[project.scripts]\ntiny = "tiny.cli:main"\n',
             "docs/run.md": "```console\n$ tiny --undeclared 3\n$ tiny --limit 3\n```\n"}
    root = write(tmp_path / "tiny", files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start: --undeclared was already out of date")
    run = root / "docs" / "run.md"
    run.write_text("An intro.\n\n" + run.read_text(), encoding="utf-8")  # a doc edit moves both commands
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0
    rename_limit(root)  # now the change makes one of them wrong
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json"]) == 1
    found = json.loads(capsys.readouterr().out.split("\n", 1)[1])["findings"]
    assert [(x["file"], x["line"]) for x in found if x["file"] == "docs/run.md"] == [("docs/run.md", 5)]


def test_line_numbers_are_the_ones_git_shows(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "docs" / "usage.md").write_text("Intro.\x0c More of it, after a form feed.\nUse `--limit` to cap it.\n",
                                            encoding="utf-8")
    git(root, "commit", "-q", "-am", "a form feed in a doc")
    rename_limit(root)
    out = tmp_path / "fixes.patch"
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json", "--patch", str(out)]) == 1
    found = [(x["file"], x["line"]) for x in json.loads(capsys.readouterr().out)["findings"]]
    assert found == [("README.md", 6), ("docs/usage.md", 2)]  # line 2, as git and GitHub count, not 3
    git(root, "apply", "--check", str(out))  # the patch's line numbers match the file's


def test_attributes_dont_change_what_it_reads(tmp_path, capsys):
    files = {**FILES, ".gitattributes": "docs/ export-ignore\nversion.txt export-subst\n",
             "docs/usage.md": FILES["docs/usage.md"] + "Use --limit to cap it.\n", "version.txt": "$Format:%H$\n"}
    root = write(tmp_path / "tiny", files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    rename_limit(root)
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json"]) == 1  # the working tree, against a commit
    assert [x["file"] for x in json.loads(capsys.readouterr().out)["findings"]] == ["README.md", "docs/usage.md"]
    git(root, "commit", "-q", "-am", "rename --limit")
    assert cli.main(["--repo", str(root), "--base", "HEAD~1", "--head", "HEAD", "--json"]) == 1  # two commits
    assert [x["file"] for x in json.loads(capsys.readouterr().out)["findings"]] == ["README.md", "docs/usage.md"]
    cli.export_ref(root, "HEAD", tmp_path / "exported")
    assert (tmp_path / "exported" / "version.txt").read_text() == "$Format:%H$\n"  # as committed, not filled in


def test_a_sparse_checkout_is_read_from_the_index(tmp_path, capsys):
    root = repo(tmp_path)
    git(root, "sparse-checkout", "set", "--no-cone", "/docs/", "/README.md")
    assert not (root / "tiny" / "cli.py").exists()  # the code isn't in the folder
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 0  # but nothing changed
    assert "no doc line found" in capsys.readouterr().out


def test_odd_files_dont_stop_the_check(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "tiny" / "gone.py").symlink_to("nowhere.py")  # a link to nothing
    (root / "tiny" / "folder.py").mkdir()  # a folder with a Python file's name
    (root / "tiny" / "folder.py" / "notes.md").write_text("x\n", encoding="utf-8")
    try:
        (root / "tiny" / os.fsdecode(b"caf\xe9.py")).write_text("x = 1\n", encoding="utf-8")  # a name that isn't UTF-8
    except OSError:
        pass  # macOS doesn't allow one; Linux does
    rename_limit(root)
    for argv in (["--base", "HEAD"], ["--base", "HEAD~1", "--head", "HEAD"]):
        if "--head" in argv:
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "odd files, and the rename")
        assert cli.main(["--repo", str(root), *argv]) == 1
        assert f"fix: {FIX}" in capsys.readouterr().out


def test_apply_never_changes_bytes_it_doesnt_fix(tmp_path, capsys):
    root = repo(tmp_path)
    readme = root / "README.md"
    readme.write_bytes(b"# tiny Caf\xe9\n" + readme.read_bytes().split(b"\n", 1)[1])  # one byte that isn't UTF-8
    git(root, "commit", "-q", "-am", "a byte from another encoding")
    rename_limit(root)
    before = readme.read_bytes()
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--apply"], read=lambda q: "y") == 1
    assert readme.read_bytes() == before  # flagged, but not rewritten
    assert "fix: none (the file isn't valid UTF-8, so docs-proof won't rewrite it)" in capsys.readouterr().out


def test_apply_never_writes_outside_the_folder(tmp_path, capsys):
    notes = write(tmp_path / "someone else", {"notes.md": "Use --limit here too.\n"}) / "notes.md"
    before, after = write(tmp_path / "before", FILES), write(tmp_path / "after", FILES)
    for side in (before, after):
        (side / "docs" / "notes.md").symlink_to(notes)
    rename_limit(after)
    assert cli.main(["--before", str(before), "--after", str(after), "--apply", "--json"], read=lambda q: "y") == 1
    assert [x["file"] for x in json.loads(capsys.readouterr().out)["findings"]] == ["README.md"]
    assert notes.read_text() == "Use --limit here too.\n"


def test_control_characters_are_shown_as_escapes(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "docs" / "usage.md").write_text("Use `--limit` \x1b]0;a title\x07\x1b[2Jhere.\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "a doc line with escape sequences")
    rename_limit(root)
    assert cli.main(["--repo", str(root), "--base", "HEAD"]) == 1
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "    Use `--limit` \\x1b]0;a title\\x07\\x1b[2Jhere." in out


def test_the_readmes_sample_output_is_what_the_command_prints():
    """The README's example is the command's output for one planted case, rebuilt here from the kept results."""
    from docsproof.check import Finding
    from docsproof.fix import Fix
    results = Path(__file__).resolve().parent.parent / "data" / "results"
    case = "asottile/pyupgrade:rename_option:3"
    exact = next(r for r in map(json.loads, (results / "exact.jsonl").read_text(encoding="utf-8").splitlines()) if r["id"] == case)
    fixes = next(r for r in map(json.loads, (results / "fixes.jsonl").read_text(encoding="utf-8").splitlines()) if r["id"] == case)
    line = fixes["lines"][0]
    finding = Finding(line["file"], line["line"], line["text"], [p["proof"] for p in exact["predicted"]],
                      Fix(line["file"], line["line"], (line["text"],), (line["rule"]["new"],), "rule", line["rule"]["reason"]))
    readme = (SRC.parent / "README.md").read_text(encoding="utf-8")
    sample = readme.split("(one of the planted changes):\n\n```\n", 1)[1].split("\n```", 1)[0]
    assert sample.split("\n") == cli.text([finding], "base", "head").split("\n")[2:6]


def test_a_doc_that_links_another_is_flagged_once_and_the_patch_applies(tmp_path, capsys):
    root = repo(tmp_path)
    (root / "docs" / "index.md").symlink_to("../README.md")  # as python-dotenv's MkDocs home page does
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "docs/index.md links the README")
    rename_limit(root)
    out = tmp_path / "fixes.patch"
    assert cli.main(["--repo", str(root), "--base", "HEAD", "--json", "--patch", str(out)]) == 1
    assert [(x["file"], x["line"]) for x in json.loads(capsys.readouterr().out)["findings"]] == [("README.md", 6)]
    git(root, "apply", "--check", str(out))  # before, the same line came twice, and the patch didn't apply
