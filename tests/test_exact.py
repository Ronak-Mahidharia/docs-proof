import json
import shutil
from pathlib import Path

from conftest import FILES, write

from docsproof.exact import as_code, find, ordinary, removed_names
from docsproof.plant import apply

ROOT = Path(__file__).resolve().parent.parent


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


def test_names_that_could_be_ordinary_words():
    assert all(ordinary(n) for n in ("records", "Server", "main", "words"))
    assert not any(ordinary(n) for n in ("fetch_items", "PluginSQL", "_helper", "ListOfItems"))


def test_the_answer_key_never_renames_an_ordinary_name():
    """So neither answer key can measure what the rule costs: a real mention of such a name in a plain sentence."""
    cases = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    renamed = [c["edit"]["old"] for c in cases if c["edit"]["kind"] == "rename_identifier"]
    assert renamed and not any(ordinary(n) for n in renamed)


def test_what_marks_a_name_as_code():
    for text in ("Call `records` first.", "Call ``records`` first.", "See :func:`records`.",
                 "Run records(vehicle) to get both.", "Use nhtsa.records to get both."):
        assert as_code(text, "records", in_block=False), text
    for text in ("NHTSA's own records say which records are the vehicle's.", "Keep the records.",
                 "(records) are kept", "`models_in_records` keeps the records", "Read records/2024.json",
                 "Files that end in .records are kept"):
        assert not as_code(text, "records", in_block=False), text
    assert as_code("records", "records", in_block=True)  # a line in a code block is code


def test_a_removed_function_named_with_an_ordinary_word(tmp_path):
    files = {**FILES, "tiny/store.py": "def records():\n    return []\n\n\ndef fetch_items():\n    return []\n",
             "docs/records.md": ("NHTSA's own records are public.\n"
                                 "Call `records()` to read them.\n"
                                 "\n"
                                 "```python\n"
                                 "for row in records:\n"
                                 "```\n")}
    before = write(tmp_path / "before", files)
    after = write(tmp_path / "after", {**files, "tiny/store.py": "def fetch_items():\n    return []\n"})
    assert [(f.file, f.line, f.name) for f in find(before, after)] == [("docs/records.md", 2, "records"),
                                                                      ("docs/records.md", 5, "records")]


def test_a_distinctive_name_counts_in_a_sentence_too(tmp_path):
    files = {**FILES, "docs/items.md": "Then fetch_items returns the list.\n"}
    before = write(tmp_path / "before", files)
    after = write(tmp_path / "after", files)
    path = after / "tiny" / "cli.py"
    path.write_text(path.read_text(encoding="utf-8").replace("def fetch_items():", "def fetch_rows():"), encoding="utf-8")
    assert ("docs/items.md", 1) in [(f.file, f.line) for f in find(before, after)]
