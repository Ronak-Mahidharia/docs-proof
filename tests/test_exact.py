import shutil

from docsproof.exact import find, removed_names
from docsproof.plant import apply


def changed(tiny, tmp_path, edit):
    after = shutil.copytree(tiny, tmp_path / "after")
    apply(after, edit)
    return after


def test_a_renamed_option_flags_every_doc_line_that_still_names_it(tiny, tmp_path):
    after = changed(tiny, tmp_path, {"kind": "rename_option", "old": "--max-results", "new": "--max-results2"})
    findings = find(tiny, after)
    assert [(f.file, f.line) for f in findings] == [("README.md", 2), ("docs/usage.md", 1)]
    assert findings[0].proof == "--max-results was at tiny/cli.py:7 before the change and is gone"


def test_renamed_names_and_files(tiny, tmp_path):
    after = changed(tiny, tmp_path, {"kind": "rename_identifier", "old": "fetch_items", "new": "fetch_items2"})
    assert [(f.file, f.line, f.kind) for f in find(tiny, after)] == [("README.md", 5, "identifier")]
    after = changed(tiny, tmp_path / "2", {"kind": "rename_file", "old": "examples/basic.py", "new": "examples/x.py"})
    assert [(f.file, f.line, f.kind) for f in find(tiny, after)] == [("README.md", 4, "path")]
    after = changed(tiny, tmp_path / "3", {"kind": "rename_env_var", "old": "TINY_TOKEN", "new": "TINY_TOKEN2"})
    assert [(f.file, f.line, f.kind) for f in find(tiny, after)] == [("README.md", 3, "env")]


def test_what_exact_checks_cant_see(tiny, tmp_path):
    after = changed(tiny, tmp_path, {"kind": "change_default", "file": "tiny/cli.py", "line": 8,
                                      "option": "--limit", "new": "11"})
    assert removed_names(tiny, after) == [] and find(tiny, after) == []  # README line 6 is now wrong, unseen


def test_a_private_rename_flags_nothing(tiny, tmp_path):
    after = changed(tiny, tmp_path, {"kind": "rename_private", "old": "_helper", "new": "_helper2"})
    assert removed_names(tiny, after) == [("identifier", "_helper", "tiny/cli.py:27")]
    assert find(tiny, after) == []
