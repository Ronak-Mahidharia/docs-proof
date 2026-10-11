import pytest

from docsproof.approve import ask, open_pull_request
from docsproof.fix import Fix

FIX = Fix("README.md", 2, ("Use --limit here.",), ("Use --cap here.",), "rule", "`--limit` is now `--cap`")


def repo(tmp_path):
    (tmp_path / "README.md").write_text("# tiny\nUse --limit here.\n", encoding="utf-8")
    return tmp_path


def test_nothing_happens_without_a_yes(tmp_path):
    ran, shown = [], []
    opened = open_pull_request(repo(tmp_path), [FIX], lambda diff: shown.append(diff) or False, "main",
                               run=lambda *a, **k: ran.append(a))
    assert not opened and ran == []
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# tiny\nUse --limit here.\n"
    assert shown and "-Use --limit here.\n+Use --cap here.\n" in shown[0]  # the exact patch was shown


def test_a_yes_opens_one_pull_request_with_the_approved_fixes(tmp_path):
    ran = []
    opened = open_pull_request(repo(tmp_path), [FIX], lambda diff: True, "main", run=lambda cmd, **k: ran.append(cmd))
    assert opened
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# tiny\nUse --cap here.\n"
    assert [cmd[3] if cmd[0] == "git" else cmd[1] for cmd in ran] == ["switch", "add", "commit", "push", "pr"]
    assert ran[-1][:4] == ["gh", "pr", "create", "--base"] and "`--limit` is now `--cap`" in ran[-1][-1]


def test_docs_changed_after_the_patch_was_made_stop_everything(tmp_path):
    ran = []

    def approve_while_someone_edits(diff):  # another line changes, so the fix itself still fits
        (tmp_path / "README.md").write_text("# tiny, edited\nUse --limit here.\n", encoding="utf-8")
        return True

    with pytest.raises(RuntimeError, match="changed after the patch was made"):
        open_pull_request(repo(tmp_path), [FIX], approve_while_someone_edits, "main", run=lambda *a, **k: ran.append(a))
    assert ran == [] and (tmp_path / "README.md").read_text(encoding="utf-8") == "# tiny, edited\nUse --limit here.\n"


def test_only_yes_is_a_yes():
    for answer, expected in (("y", True), ("YES", True), ("", False), ("n", False), ("sure", False)):
        assert ask("diff", read=lambda prompt: answer, show=lambda text: None) is expected
