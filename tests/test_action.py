"""The GitHub Action's script, on a small repository whose HEAD is a merge commit, the way GitHub checks out a
pull request, with GitHub's files and API replaced by local ones."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
from test_cli import FIX, git, rename_limit, repo

from docsproof import action

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
ROOT = Path(__file__).resolve().parent.parent


def pull_request(tmp_path: Path) -> Path:
    root = repo(tmp_path)
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "Merge the pull request", "rename")
    return root


def run(env: dict, request=None) -> tuple[int, str]:
    out = io.StringIO()
    code = action.main(env, request=request or (lambda *a: pytest.fail("no API call expected")), out=out)
    return code, out.getvalue()


def github(tmp_path: Path, root: Path, **more) -> dict:
    return {"DOCSPROOF_PATH": str(root), "GITHUB_WORKSPACE": str(root), "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"), "GITHUB_OUTPUT": str(tmp_path / "output.txt"), **more}


def test_a_pull_request_gets_a_summary_annotations_and_outputs(tmp_path):
    root = pull_request(tmp_path)
    code, log = run(github(tmp_path, root))
    assert code == 1  # a flagged line fails the step
    assert "docs-proof: 1 doc line the change made wrong" in log
    assert (f"::warning file=README.md,line=6,title=docs-proof::--limit was at tiny/cli.py:8 before the change and is "
            f"gone Suggested fix: {FIX}") in log
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith(action.MARKER) and "### docs-proof: 1 doc line this change made wrong" in summary
    assert "```text\n" in summary and "+Use `--cap` to cap the list" in summary
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output.txt").read_text(encoding="utf-8").splitlines())
    assert outputs["findings"] == "1" and outputs["fixes"] == "1"
    git(root, "apply", "--check", outputs["patch"])  # the patch fits the pull request's docs


def test_fail_on_findings_false_and_a_clean_change(tmp_path):
    root = pull_request(tmp_path)
    assert run(github(tmp_path, root, DOCSPROOF_FAIL="false"))[0] == 0
    clean = repo(tmp_path / "clean")
    (clean / "notes.txt").write_text("nothing about the code\n", encoding="utf-8")
    git(clean, "add", "-A")
    git(clean, "commit", "-q", "-m", "a note")
    code, log = run(github(tmp_path, clean, DOCSPROOF_BASE="HEAD~1", GITHUB_STEP_SUMMARY=str(tmp_path / "clean.md")))
    assert code == 0 and "::warning" not in log
    assert "No doc line found that this change made wrong." in (tmp_path / "clean.md").read_text(encoding="utf-8")


def test_without_a_merge_commit_it_needs_a_base(tmp_path):
    root = repo(tmp_path)
    code, log = run(github(tmp_path, root))  # the first commit, with no parent
    assert code == 2 and log.startswith("::error title=docs-proof::no base commit")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "an ordinary commit, with one parent")
    code, log = run(github(tmp_path, root))
    assert code == 2 and log.startswith("::error title=docs-proof::no base commit")


def test_a_repository_in_a_subfolder_of_the_workspace_or_outside_it(tmp_path):
    root = pull_request(tmp_path / "workspace")
    code, log = run(github(tmp_path, root, GITHUB_WORKSPACE=str(tmp_path / "workspace")))
    assert "::warning file=tiny/README.md,line=6," in log
    code, log = run(github(tmp_path, root, GITHUB_WORKSPACE=str(tmp_path / "elsewhere")))
    assert "::warning title=docs-proof::README.md:6: --limit was at" in log and "file=" not in log  # on no wrong file


def test_doc_text_cant_break_out_of_its_code_block():
    assert action.fence("plain") == "```\nplain\n```"
    assert action.fence("a ``` b", "text") == "````text\na ``` b\n````"
    assert action.fence("`````") == "``````\n`````\n``````"
    assert action.escape("a:b,c%.md", prop=True) == "a%3Ab%2Cc%25.md"
    assert action.annotation("d.md", 3, "line one\nline two") == "::warning file=d.md,line=3,title=docs-proof::line one%0Aline two"


def test_a_backtick_fence_in_a_doc_line(tmp_path):
    root = pull_request(tmp_path)
    readme = root / "README.md"
    git(root, "switch", "-q", "-c", "fence", "HEAD~1")  # back before the merge, on a new branch
    readme.write_text(readme.read_text() + "Try ```--limit 3``` and [a link](http://example.com).\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "a doc line with a fence in it")
    git(root, "merge", "-q", "--no-ff", "-m", "merge", "rename")
    run(github(tmp_path, root, DOCSPROOF_FAIL="false"))
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    block = re.search(r"^(`{4,})text\n(.*?)\n\1$", summary, re.S | re.M)
    assert block and "Try ```--limit 3```" in block.group(2)  # inside a fence of four backticks


def calls_to(existing: list[dict], fail: int | None = None):
    calls = []

    def request(method, url, token, data=None):
        calls.append((method, url.rsplit("/repos/", 1)[1], data))
        if fail:
            raise urllib.error.HTTPError(url, fail, "Forbidden", {}, None)
        return 200, existing if method == "GET" else {}
    request.calls = calls
    return request


def commenting(tmp_path: Path, root: Path, **more) -> dict:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7}}), encoding="utf-8")
    return {**github(tmp_path, root, DOCSPROOF_COMMENT="true", DOCSPROOF_TOKEN="t", GITHUB_EVENT_PATH=str(event),
                     GITHUB_REPOSITORY="me/project", GITHUB_API_URL="https://api.example"), **more}


def test_one_comment_made_then_updated(tmp_path):
    root = pull_request(tmp_path)
    first = calls_to([{"id": 1, "user": {"type": "User"}, "body": f"{action.MARKER} copied by a person"}])
    code, log = run(commenting(tmp_path, root), first)
    assert code == 1 and "docs-proof: comment created" in log
    assert [(m, u) for m, u, _ in first.calls] == [("GET", "me/project/issues/7/comments?per_page=100&page=1"),
                                                   ("POST", "me/project/issues/7/comments")]
    assert first.calls[1][2]["body"].startswith(action.MARKER)
    again = calls_to([{"id": 9, "user": {"type": "Bot"}, "body": f"{action.MARKER}\nan earlier report"}])
    run(commenting(tmp_path, root), again)
    assert again.calls[1][:2] == ("PATCH", "me/project/issues/comments/9")


def test_no_comment_when_there_is_nothing_new_to_say(tmp_path):
    clean = repo(tmp_path)
    (clean / "notes.txt").write_text("a note\n", encoding="utf-8")
    git(clean, "add", "-A")
    git(clean, "commit", "-q", "-m", "a note")
    quiet = calls_to([])
    assert run(commenting(tmp_path, clean, DOCSPROOF_BASE="HEAD~1"), quiet)[1].count("comment skipped: nothing to report") == 1
    assert [m for m, _, _ in quiet.calls] == ["GET"]
    fixed = calls_to([{"id": 3, "user": {"type": "Bot"}, "body": f"{action.MARKER}\n1 doc line"}])
    run(commenting(tmp_path, clean, DOCSPROOF_BASE="HEAD~1"), fixed)  # an earlier report, now out of date
    assert fixed.calls[1][0] == "PATCH" and fixed.calls[1][2]["body"].startswith(action.MARKER)
    assert "No doc line found" in fixed.calls[1][2]["body"]  # and the marker lets a later run find it again


def test_a_token_that_cant_comment_is_a_note_not_a_failure(tmp_path):
    root = pull_request(tmp_path)
    code, log = run(commenting(tmp_path, root, DOCSPROOF_FAIL="false"), calls_to([], fail=403))
    assert code == 0 and "::notice title=docs-proof::No comment (403)" in log
    event = tmp_path / "push.json"
    event.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
    code, log = run(commenting(tmp_path, root, GITHUB_EVENT_PATH=str(event)))
    assert "comment skipped: this isn't a pull request" in log


def test_a_long_report_is_cut_for_the_comment_only():
    from docsproof.check import Finding
    found, log, diff = [Finding("README.md", 6, "Use --limit.")], "x" * 50, "y" * 50
    assert action.report(found, log, diff, part=10).count("(cut short: all of it is in the job summary)") == 2
    assert "(cut short" not in action.report(found, log, diff)


def test_inputs_never_reach_the_script_as_code():
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    script = text.split("      run: |\n", 1)[1]
    assert "${{" not in script  # inputs come in through the environment only
    for name in ("path", "base", "head", "fail-on-findings", "comment", "token"):
        assert f"${{{{ inputs.{name} }}}}" in text.split("      run: |\n", 1)[0]


def test_a_line_flagged_without_a_fix(tmp_path):
    root = repo(tmp_path)
    readme, code_file = root / "README.md", root / "tiny" / "cli.py"
    readme.write_text(readme.read_text().replace("(default: 10).", "(default: 10, and 10 at most)."), encoding="utf-8")
    git(root, "commit", "-q", "-am", "the default, said twice")
    code_file.write_text(code_file.read_text().replace("type=int, default=10", "type=int, default=20"))
    git(root, "commit", "-q", "-am", "a new default")
    code, log = run(github(tmp_path, root, DOCSPROOF_BASE="HEAD~1", DOCSPROOF_FAIL="false"))
    outputs = dict(line.split("=", 1) for line in (tmp_path / "output.txt").read_text(encoding="utf-8").splitlines())
    assert (outputs["findings"], outputs["fixes"]) == ("1", "0") and "fix: none (10 is in the line 2 times)" in log
    assert Path(outputs["patch"]).read_text(encoding="utf-8") == ""
    assert "suggested fixes, as one patch" not in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_doc_text_cant_become_a_workflow_command(tmp_path):
    root = repo(tmp_path)
    usage = root / "docs" / "usage.md"
    usage.write_text("::stop-commands::hush --limit\n   ::error::a fake error --limit\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "doc lines that look like workflow commands")
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "Merge the pull request", "rename")
    tokens = set()
    for _ in range(2):
        code, log = run(github(tmp_path, root))
        lines = log.split("\n")
        stop = next(i for i, line in enumerate(lines) if line.startswith("::stop-commands::"))
        token = lines[stop].removeprefix("::stop-commands::")
        resume = lines.index(f"::{token}::")
        tokens.add(token)
        assert stop < lines.index("    ::stop-commands::hush --limit") < resume  # the doc lines, inside
        assert stop < lines.index("    ::error::a fake error --limit") < resume
        # every other line GitHub would read as a command (it reads one even after spaces) is one of the action's own
        outside = [line for i, line in enumerate(lines) if line.lstrip().startswith("::") and not stop <= i <= resume]
        assert outside and all(line.startswith("::warning file=") for line in outside)
    assert len(tokens) == 2 and all(len(t) == 32 and t not in usage.read_text() for t in tokens)  # new each run


def test_an_earlier_comment_on_a_later_page_is_updated(tmp_path):
    root = pull_request(tmp_path)
    pages = {1: [{"id": n, "user": {"type": "User"}, "body": "a comment"} for n in range(100)],
             2: [{"id": 500, "user": {"type": "Bot"}, "body": f"{action.MARKER}\nan earlier report"}]}
    calls = []

    def request(method, url, token, data=None):
        calls.append((method, url.rsplit("/repos/", 1)[1]))
        return 200, pages[int(url.rsplit("page=", 1)[1])] if method == "GET" else {}
    run(commenting(tmp_path, root), request)
    assert calls == [("GET", "me/project/issues/7/comments?per_page=100&page=1"),
                     ("GET", "me/project/issues/7/comments?per_page=100&page=2"),
                     ("PATCH", "me/project/issues/comments/500")]


def test_a_pull_request_cant_run_its_own_docsproof(tmp_path):
    """The step as action.yml runs it, in a pull request's checkout that has a docsproof folder of its own."""
    root = pull_request(tmp_path)
    own = root / "docsproof"
    own.mkdir()
    for name in ("__init__.py", "action.py"):
        (own / name).write_text("print('the pull request ran its own code')\n", encoding="utf-8")
    step = (ROOT / "action.yml").read_text(encoding="utf-8").split("      run: |\n", 1)[1]
    script = "\n".join(line.removeprefix("        ") for line in step.splitlines())
    assert script.endswith('PYTHONPATH="$DOCSPROOF_SRC" python3 -P -m docsproof.action')
    done = subprocess.run(["bash", "-c", script], cwd=root, capture_output=True, text=True,
                          env={**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                               "DOCSPROOF_SRC": str(ROOT / "src"), **github(tmp_path, root, DOCSPROOF_PATH=".")})
    assert "ran its own code" not in done.stdout + done.stderr
    assert done.returncode == 1 and "docs-proof: 1 doc line the change made wrong" in done.stdout


def test_more_flagged_lines_than_github_shows_warnings_for(tmp_path):
    root = repo(tmp_path)
    (root / "docs" / "many.md").write_text("".join(f"Line {n}: use --limit.\n" for n in range(1, 12)), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "a doc that names --limit eleven times")
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    git(root, "switch", "-q", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "Merge the pull request", "rename")
    code, log = run(github(tmp_path, root))
    assert log.count("::warning file=") == 12  # 11 in docs/many.md and the README's
    assert ("::notice title=docs-proof::GitHub shows 10 warnings for a step, so the other 2 flagged lines are only in "
            "the job summary and the log.") in log
    assert "docs/many.md:11" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert f"(GitHub shows {action.WARNINGS} for a step, and a note says when there are more)" in \
        (ROOT / "README.md").read_text(encoding="utf-8")
