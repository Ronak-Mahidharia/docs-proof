import shutil

from conftest import FILES, write

from docsproof.plant import apply
from docsproof.values import Candidate, ValueChange, candidates, value_changes


def changed(tmp_path, edit, files=FILES):
    before = write(tmp_path / "before", files)
    after = shutil.copytree(before, tmp_path / "after")
    apply(after, edit)
    return before, after


def test_a_changed_default(tmp_path):
    before, after = changed(tmp_path, {"kind": "change_default", "option": "--limit", "file": "tiny/cli.py", "line": 8,
                                       "old": "10", "new": "20"})
    assert value_changes(before, after) == [ValueChange("default", "--limit", "10", "20", "tiny/cli.py", 8,
                                                        'parser.add_argument("--limit", type=int, default=20)')]
    assert candidates(before, value_changes(before, after)[0]) == \
        [Candidate("README.md", 6, "Use `--limit` to cap the list (default: 10).")]


def test_a_raised_minimum_python(tmp_path):
    before, after = changed(tmp_path, {"kind": "raise_python", "file": "pyproject.toml", "old": 9, "new": 11})
    change = value_changes(before, after)
    assert change == [ValueChange("python", "Python", "3.9", "3.11", "pyproject.toml", 3, 'requires-python = ">=3.11"')]
    assert candidates(before, change[0]) == [Candidate("README.md", 7, "Requires Python 3.9 or later.")]


def test_the_search_for_an_old_python_version(tmp_path):
    files = {**FILES, "docs/install.md": ("Works on python3.9 and newer.\n"   # yes
                                          "Python 3.90 isn't a release.\n"   # no: another number
                                          "Build 13.9 is out.\n"             # no: not 3.9, and not about Python
                                          "Supported: 3.9, 3.10.\n"          # no Python word on the line
                                          "CPython 3.9.1 or PyPy.\n")}       # yes
    before, after = changed(tmp_path, {"kind": "raise_python", "file": "pyproject.toml", "old": 9, "new": 11}, files)
    found = [(c.file, c.line) for c in candidates(before, value_changes(before, after)[0])]
    assert found == [("README.md", 7), ("docs/install.md", 1), ("docs/install.md", 5)]


def test_a_default_described_on_the_lines_after_the_option(tmp_path):
    files = {**FILES, "docs/options.md": "--limit N\n    How many to show.\n    Default: 10.\n\n\n    Not 10 here.\n"}
    before, after = changed(tmp_path, {"kind": "change_default", "option": "--limit", "file": "tiny/cli.py", "line": 8,
                                       "old": "10", "new": "20"}, files)
    found = [(c.file, c.line) for c in candidates(before, value_changes(before, after)[0])]
    assert found == [("README.md", 6), ("docs/options.md", 3)]  # line 6 is too far from the option


def test_a_rename_changes_no_value(tmp_path):
    before, after = changed(tmp_path, {"kind": "rename_option", "old": "--limit", "new": "--limit2"})
    assert value_changes(before, after) == []


def test_a_default_whose_line_moved(tmp_path):
    before = write(tmp_path / "before", FILES)
    after = shutil.copytree(before, tmp_path / "after")
    cli = after / "tiny" / "cli.py"
    cli.write_text("import sys\n" + cli.read_text().replace("default=10", "default=20"), encoding="utf-8")
    assert value_changes(before, after) == [ValueChange("default", "--limit", "10", "20", "tiny/cli.py", 9,
                                                        'parser.add_argument("--limit", type=int, default=20)')]


def test_a_moved_default_is_paired_only_when_the_file_declares_the_option_once(tmp_path):
    two = {**FILES, "tiny/cli.py": FILES["tiny/cli.py"].replace(
        '    return parser\n', '    parser.add_argument("--limit", type=int, default=5)\n    return parser\n', 1)}
    before = write(tmp_path / "before", two)
    after = shutil.copytree(before, tmp_path / "after")
    cli = after / "tiny" / "cli.py"
    cli.write_text("import sys\n" + cli.read_text().replace("default=10", "default=20"), encoding="utf-8")
    assert value_changes(before, after) == []  # which one is which can't be told from the code alone


def test_the_code_line_is_numbered_as_python_numbers_it(tmp_path):
    # Python ends a line at "\r" too (git doesn't), and not at a form feed (str.splitlines does)
    code = "# an old Mac line ending\r" + FILES["tiny/cli.py"].replace("import os", "import os  # \x0c")
    before = write(tmp_path / "before", {**FILES, "tiny/cli.py": code})
    after = shutil.copytree(before, tmp_path / "after")
    cli = after / "tiny" / "cli.py"
    cli.write_bytes(cli.read_bytes().replace(b"default=10", b"default=20"))  # the bytes as they were, "\r" kept
    assert b"ending\rimport" in cli.read_bytes()
    assert [(c.line, c.code) for c in value_changes(before, after)] == \
        [(9, 'parser.add_argument("--limit", type=int, default=20)')]
