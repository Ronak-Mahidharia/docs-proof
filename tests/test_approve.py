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


def test_local_fixes_are_made_only_after_a_yes(tmp_path):
    from docsproof.approve import apply_locally
    root = repo(tmp_path)
    assert not apply_locally(root, [FIX], lambda diff: False)
    assert (root / "README.md").read_text(encoding="utf-8") == "# tiny\nUse --limit here.\n"
    assert apply_locally(root, [FIX], lambda diff: True)
    assert (root / "README.md").read_text(encoding="utf-8") == "# tiny\nUse --cap here.\n"


def test_local_fixes_stop_if_the_docs_changed_after_the_patch(tmp_path):
    from docsproof.approve import apply_locally
    root = repo(tmp_path)

    def approve_while_someone_edits(diff):
        (root / "README.md").write_text("# tiny, edited\nUse --limit here.\n", encoding="utf-8")
        return True

    with pytest.raises(RuntimeError, match="changed after the patch was made"):
        apply_locally(root, [FIX], approve_while_someone_edits)
    assert (root / "README.md").read_text(encoding="utf-8") == "# tiny, edited\nUse --limit here.\n"


def test_the_pull_request_commits_only_the_fixes(tmp_path):
    import subprocess
    root = repo(tmp_path)
    git = ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "start"], check=True)
    (root / "notes.txt").write_text("someone's work in progress\n", encoding="utf-8")
    subprocess.run([*git, "add", "notes.txt"], check=True)  # staged before docs-proof runs

    def run(cmd, **kwargs):  # git for real, with the test's name; never push or gh
        if cmd[0] == "git" and cmd[3] != "push":
            subprocess.run([*git, *cmd[3:]], check=True, capture_output=True)
    assert open_pull_request(root, [FIX], lambda diff: True, "main", run=run)
    shown = subprocess.run([*git, "show", "--name-only", "--format=", "HEAD"], capture_output=True, text=True).stdout
    assert shown.split() == ["README.md"]
    staged = subprocess.run([*git, "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout
    assert staged.split() == ["notes.txt"]  # still staged, as it was, and not in the fix


def test_fixes_are_never_written_through_a_link_out_of_the_folder(tmp_path):
    from docsproof.approve import apply_locally
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("# tiny\nUse --limit here.\n", encoding="utf-8")
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").symlink_to(elsewhere)
    with pytest.raises(ValueError, match="leads out of"):
        apply_locally(root, [FIX], lambda diff: True)
    assert elsewhere.read_text(encoding="utf-8") == "# tiny\nUse --limit here.\n"
