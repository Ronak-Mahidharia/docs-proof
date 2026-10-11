import shutil

from conftest import write

from docsproof.commands import (_options, _program, _simple_commands, _tokens, commands, console_scripts,
                                main_packages, new_problems, problems)
from docsproof.plant import apply

FILES = {
    "pyproject.toml": '[project]\nname = "tiny"\nrequires-python = ">=3.9"\n\n[project.scripts]\ntiny = "tiny.cli:main"\n',
    "tiny/__init__.py": "",
    "tiny/__main__.py": "from .cli import main\nmain()\n",
    "tiny/cli.py": (
        "import argparse\n"
        "p = argparse.ArgumentParser()\n"
        'p.add_argument("--max-results", type=int)\n'
        'p.add_argument("--limit", type=int)\n'
        'p.add_argument("--pip-args")\n'),
    "README.md": (
        "```bash\n"
        "$ tiny --max-results 5 | head -3\n"
        "$ tiny --gone\n"
        "$ pip install --upgrade waitress\n"
        "$ waitress-serve --host 127.0.0.1 app\n"
        "$ python -m tiny --limit 3 \\\n"
        "    --also-gone\n"
        "tiny run: error: no such option --not-a-command\n"  # output: the block shows prompts
        "```\n"
        "Use `tiny --limit 2` for two. The --max-results option is described here.\n"),
    "docs/more.md": (
        "```\n"
        "cat notes.txt | tiny --limit 1\n"
        "cd demo && VAR=1 uvx tiny --gone-too\n"
        "poetry run tiny --max-results 2 > out.txt\n"
        "gunicorn --workers 2 \\\n"
        "    --bind 0.0.0.0 app\n"
        "```\n"
        "\n"
        "```ini\n"
        "commands = tiny --limit 3\n"
        "addopts = --strict\n"
        "```\n"),
    "docs/usage.rst": (
        "Example::\n"
        "\n"
        '    $ tiny --max-results 1 --pip-args "--no-deps"\n'
        "\n"
        ".. code-block:: console\n"
        "\n"
        "   $ tiny --help\n"),
}


def test_words_follow_the_shell():
    assert _tokens('tiny --max-results 5 | head -3') == ["tiny", "--max-results", "5"]
    assert _tokens('tiny --pip-args "--no-deps --pre"') == ["tiny", "--pip-args", '"--no-deps --pre"']
    assert _tokens("tiny > out.txt --x") == ["tiny", "--x"]  # a redirect skips only its file
    assert _simple_commands([("cat x | tiny --a 2>&1 --b && other -c # note --d", 1)]) == [
        [("cat", 1), ("x", 1)], [("tiny", 1), ("--a", 1), ("2", 1), ("--b", 1)], [("other", 1), ("-c", 1)]]
    assert _options(_simple_commands([('tiny --pip-args "--no-deps"', 4)])[0]) == (("--pip-args", 4),)  # a quoted value isn't an option
    assert _options([("--host=0.0.0.0", 1), ("--", 1), ("--not-an-option", 2)]) == (("--host", 1),)
    assert _tokens('tiny --a "unclosed # note --d') == ["tiny", "--a", '"unclosed']  # a comment, without shlex's help


def test_a_program_started_through_another():
    assert _program(["uvx", "tiny", "--x"], {"tiny"}, set()) == ("tiny", 2)
    assert _program(["VAR=1", "poetry", "run", "tiny"], {"tiny"}, set()) == ("tiny", 4)
    assert _program(["python3.12", "-m", "tiny"], set(), {"tiny"}) == ("python -m tiny", 3)
    assert _program(["pip", "install", "tiny"], {"tiny"}, {"tiny"}) is None  # installs it, doesn't run it


def test_a_package_under_src_runs_with_python_m(tmp_path):
    root = write(tmp_path / "r", {"src/tool/__init__.py": "", "src/tool/__main__.py": "", "src/lib/__init__.py": ""})
    assert main_packages(root) == {"tool"}


def test_console_scripts_from_each_kind_of_config(tmp_path):
    assert console_scripts(write(tmp_path / "a", FILES)) == {"tiny"}
    cfg = write(tmp_path / "b", {"setup.cfg": "[options.entry_points]\nconsole_scripts =\n    tool-a = pkg.cli:main\n"})
    assert console_scripts(cfg) == {"tool-a"}
    py = write(tmp_path / "c", {"setup.py": "setup(entry_points={'console_scripts': ['tool-b = pkg.cli:main']})\n"})
    assert console_scripts(py) == {"tool-b"}
    pbr = write(tmp_path / "d", {"setup.cfg": "[entry_points]\nconsole_scripts =\n    tool-d = pkg.cli:main\n"})
    assert console_scripts(pbr) == {"tool-d"}


def test_commands_in_blocks_continued_lines_and_inline_code(tmp_path):
    root = write(tmp_path / "r", FILES)
    assert main_packages(root) == {"tiny"}
    found = [(c.file, c.line, c.program, c.options) for c in commands(root)]
    assert found == [
        ("README.md", 2, "tiny", (("--max-results", 2),)),
        ("README.md", 3, "tiny", (("--gone", 3),)),
        ("README.md", 6, "python -m tiny", (("--limit", 6), ("--also-gone", 7))),  # continued on line 7
        ("README.md", 10, "tiny", (("--limit", 10),)),  # inline; the prose mention isn't a command
        ("docs/more.md", 2, "tiny", (("--limit", 2),)),  # after a pipe
        ("docs/more.md", 3, "tiny", (("--gone-too", 3),)),  # after cd, an assignment, and uvx
        ("docs/more.md", 4, "tiny", (("--max-results", 4),)),
        ("docs/usage.rst", 3, "tiny", (("--max-results", 3), ("--pip-args", 3))),  # not pip's --no-deps
        ("docs/usage.rst", 7, "tiny", (("--help", 7),)),
    ]  # pip's, waitress-serve's, and gunicorn's commands aren't this project's, and line 8 is output


def test_problems_are_options_the_code_doesnt_declare(tmp_path):
    root = write(tmp_path / "r", FILES)
    found = [(p.file, p.line, p.option) for p in problems(root)]
    assert found == [("README.md", 3, "--gone"), ("README.md", 7, "--also-gone"), ("docs/more.md", 3, "--gone-too")]
    assert problems(root)[0].proof == "`tiny` declares no --gone option in the code"  # and --help is built in


def test_new_problems_after_a_change(tmp_path):
    before = write(tmp_path / "before", FILES)
    after = shutil.copytree(before, tmp_path / "after")
    apply(after, {"kind": "rename_option", "old": "--limit", "new": "--limit2"})
    found = [(p.file, p.line, p.option) for p in new_problems(before, after)]
    assert found == [("README.md", 6, "--limit"), ("README.md", 10, "--limit"), ("docs/more.md", 2, "--limit")]
    assert new_problems(before, after, problems(before)) == new_problems(before, after)


def test_a_command_line_not_declared_in_python_isnt_checked(tmp_path):
    files = dict(FILES)
    files["tiny/cli.py"] = "def main():\n    pass\n"  # the options live elsewhere (another language)
    assert problems(write(tmp_path / "r", files)) == []


def test_a_heading_underline_in_restructuredtext_isnt_a_fence(tmp_path):
    files = {**FILES, "docs/guide.rst": "Usage\n~~~~~\n\ntiny --prose-not-code reads a file.\n\nMore\n~~~~\n"}
    assert [c.line for c in commands(write(tmp_path / "r", files)) if c.file == "docs/guide.rst"] == []


def test_a_quote_inside_a_word_keeps_the_word_whole():
    words = _simple_commands([('pipx install x --pip-args="--index-url https://i/simple/ --trusted-host i" --force', 1)])
    assert [w for w, _ in words[0]] == ["pipx", "install", "x", '--pip-args="--index-url https://i/simple/ --trusted-host i"',
                                        "--force"]
    assert [o for o, _ in _options(words[0])] == ["--pip-args", "--force"]  # not pip's --index-url or --trusted-host


def test_a_note_in_restructuredtext_is_prose(tmp_path):
    guide = (".. note::\n\n    tiny reads --not-an-option from prose here.\n\n"
             ".. warning::\n\n    Run this::\n\n        tiny --max-results 2\n")
    root = write(tmp_path / "r", {**FILES, "docs/guide.rst": guide})
    assert [(c.line, c.argv) for c in commands(root) if c.file == "docs/guide.rst"] == [(9, ("tiny", "--max-results", "2"))]


def test_a_pyproject_with_odd_tables_doesnt_stop_the_check(tmp_path):
    root = write(tmp_path / "odd", {"pyproject.toml": 'project = "not a table"\n[tool]\npoetry = 3\n'})
    assert console_scripts(root) == set()
    (root / "pyproject.toml").write_bytes(b'[project.scripts]\ntiny = "tiny.cli:main" # caf\xe9\n')
    assert console_scripts(root) == {"tiny"}
