import ast
import importlib.util
import shutil

import pytest

from docsproof.plant import PlantError, apply


def load(path):
    spec = importlib.util.spec_from_file_location(f"copy_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy(tiny, tmp_path):
    return shutil.copytree(tiny, tmp_path / "copy")


def test_a_renamed_option_still_works_and_the_docs_stay_as_they_were(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    readme = (root / "README.md").read_text()
    changed = apply(root, {"kind": "rename_option", "old": "--max-results", "new": "--max-results2"})
    assert changed == ["tiny/cli.py"]
    text = (root / "tiny/cli.py").read_text()
    assert '"--max-results2"' in text and "(see --max-results2)" in text and 'dest="max_results"' in text
    assert load(root / "tiny/cli.py").main(["--max-results2", "3"])[0] == 3  # the code reads the same name
    assert (root / "README.md").read_text() == readme  # docs are never touched


def test_a_comment_before_the_closing_parenthesis(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    apply(root, {"kind": "rename_option", "old": "--upgrade", "new": "--upgrade2"})
    assert load(root / "tiny/cli.py").main(["--upgrade2"])[3] is True


def test_click_options_keep_their_parameter_name(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    apply(root, {"kind": "rename_option", "old": "--color", "new": "--color2"})
    text = (root / "tiny/hello.py").read_text()
    assert '@click.option("--color2/--no-color", "color", default=True)' in text
    ast.parse(text)


def test_identifier_env_var_file_default_and_python_changes(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    assert apply(root, {"kind": "rename_identifier", "old": "fetch_items", "new": "fetch_items2"}) == ["tiny/cli.py"]
    assert "def fetch_items2():" in (root / "tiny/cli.py").read_text()
    apply(root, {"kind": "rename_env_var", "old": "TINY_TOKEN", "new": "TINY_TOKEN2"})
    assert 'os.environ.get("TINY_TOKEN2")' in (root / "tiny/cli.py").read_text()
    apply(root, {"kind": "rename_file", "old": "examples/basic.py", "new": "examples/basic2.py"})
    assert (root / "examples/basic2.py").is_file() and not (root / "examples/basic.py").exists()
    assert (root / "tiny/data.py").read_text() == 'EXAMPLE = "examples/basic2.py"\n'
    apply(root, {"kind": "change_default", "file": "tiny/cli.py", "line": 8, "option": "--limit", "new": "11"})
    assert 'parser.add_argument("--limit", type=int, default=11)' in (root / "tiny/cli.py").read_text()
    apply(root, {"kind": "raise_python", "file": "pyproject.toml", "old": 9, "new": 11})
    assert 'requires-python = ">=3.11"' in (root / "pyproject.toml").read_text()


def test_a_change_that_changes_nothing_is_refused(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    with pytest.raises(PlantError):
        apply(root, {"kind": "rename_identifier", "old": "no_such_name", "new": "no_such_name2"})


def test_f_string_braces_survive_a_rename(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"pkg/cli.py": (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        'p.add_argument("--max-results", type=int)\n'
        "n = 3\n"
        'MESSAGE = f"use --max-results {{literal braces}} with {n}"\n')})
    apply(root, {"kind": "rename_option", "old": "--max-results", "new": "--max-results2"})
    text = (root / "pkg/cli.py").read_text()
    assert 'f"use --max-results2 {{literal braces}} with {n}"' in text
    ast.parse(text)


def test_a_file_that_was_already_broken_doesnt_block_a_change(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"pkg/core.py": "def fetch_items():\n    return []\n",
                                   "pkg/template.py": "fetch_items = = 1\n",  # tokenizes, but never parsed
                                   "pkg/garbled.py": "def fetch_items(:\n"})  # doesn't even tokenize: left alone
    assert sorted(apply(root, {"kind": "rename_identifier", "old": "fetch_items", "new": "fetch_items2"})) == [
        "pkg/core.py", "pkg/template.py"]
    assert (root / "pkg/garbled.py").read_text() == "def fetch_items(:\n"


def test_a_change_that_breaks_working_code_is_refused(tiny, tmp_path):
    root = copy(tiny, tmp_path)
    with pytest.raises(PlantError, match="no longer parses"):
        apply(root, {"kind": "rename_identifier", "old": "fetch_items", "new": "1fetch"})  # not a valid name


def test_a_form_feed_inside_a_string_doesnt_shift_later_changes(tmp_path):
    # str.splitlines counts a form feed as a line break, but Python doesn't (autopep8's tests have one).
    from conftest import write
    root = write(tmp_path / "r", {"pkg/core.py": (
        'PAGE = "one\x0ctwo"\n'  # a real form feed inside the string
        "\n"
        "\n"
        "def fetch_items():\n"
        "    return []\n"
        "\n"
        "\n"
        "ITEMS = fetch_items()\n")})
    apply(root, {"kind": "rename_identifier", "old": "fetch_items", "new": "fetch_items2"})
    text = (root / "pkg/core.py").read_text()
    assert "def fetch_items2():" in text and "ITEMS = fetch_items2()" in text and 'PAGE = "one\x0ctwo"' in text


def test_non_ascii_text_before_a_change_keeps_it_in_place(tmp_path):
    # ast reports columns in UTF-8 bytes; "é" is two bytes.
    from conftest import write
    root = write(tmp_path / "r", {"pkg/cli.py": (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        'p.add_argument("--limit", type=int, default=10, help="résumé café")\n')})
    apply(root, {"kind": "rename_option", "old": "--limit", "new": "--limit2"})
    assert 'help="résumé café", dest="limit")' in (root / "pkg/cli.py").read_text()
    apply(root, {"kind": "change_default", "file": "pkg/cli.py", "line": 3, "option": "--limit2", "new": "20"})
    assert 'default=20, help="résumé café"' in (root / "pkg/cli.py").read_text()
