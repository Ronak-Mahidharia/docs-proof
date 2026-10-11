from docsproof.names import Code, min_python, packages, project_files


def test_project_files_skip_tests_and_examples(tiny):
    assert project_files(tiny) == ["tiny/__init__.py", "tiny/cli.py", "tiny/data.py", "tiny/hello.py"]


def test_options_from_argparse_and_click(tiny):
    options = Code(tiny).options()
    assert sorted(options) == ["--color", "--limit", "--max-results", "--name", "--no-color", "--upgrade", "--verbose"]
    assert options["--max-results"][0].file == "tiny/cli.py" and options["--max-results"][0].line == 7


def test_only_numeric_defaults(tiny):
    found = sorted((option, d.value) for option, _, d in Code(tiny).option_defaults())
    assert found == [("--limit", 10), ("--max-results", 20)]


def test_defined_names_and_env_vars(tiny):
    code = Code(tiny)
    assert sorted(code.defined_names()) == ["_helper", "build_parser", "fetch_items", "hello", "main"]
    assert list(code.env_vars()) == ["TINY_TOKEN"]


def test_min_python(tiny):
    assert min_python(tiny) == ("pyproject.toml", 9)


def test_a_packages_own_scripts_folder_is_project_code(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"pkg/scripts/cli.py": "", "scripts/release.py": "", "pkg/tests/test_x.py": "",
                                   "pkg/tests/helpers.py": "", "build/lib/pkg/x.py": "", "pkg/core.py": ""})
    assert project_files(root) == ["pkg/core.py", "pkg/scripts/cli.py"]


def test_packages_with_and_without_src(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"src/pkg/__init__.py": "", "tool.py": "", "tests/test_x.py": ""})
    assert packages(root) == {"pkg", "tool"}


def test_public_names_leave_out_private_modules(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"pkg/__init__.py": "def load_all():\n    pass\n",
                                   "pkg/_filters.py": "def filter_by_level(r):\n    pass\n\n\ndef only_private(r):\n    pass\n",
                                   "pkg/api.py": "def filter_by_level(r):\n    pass\n\n\ndef only_public():\n    pass\n"})
    public = Code(root).public_names()
    assert sorted(public) == ["filter_by_level", "load_all", "only_public"]
    assert [w.file for w in public["filter_by_level"]] == ["pkg/api.py"]  # the private copy isn't listed


def test_a_command_folder_named_test_is_project_code(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"src/hatch/cli/test/__init__.py": "", "src/hatch/cli/test/core.py": "",
                                   "src/pkg/tests/test_core.py": "", "src/pkg/tests/helpers.py": "", "src/pkg/a.py": ""})
    assert project_files(root) == ["src/hatch/cli/test/__init__.py", "src/hatch/cli/test/core.py", "src/pkg/a.py"]


def test_declared_options_include_lists_tables_and_built_ins(tmp_path):
    from conftest import write
    root = write(tmp_path / "r", {"pkg/cli.py": (
        "import click, shtab\n"
        'app_option = click.Option(["-A", "--app"])\n'
        'TABLE = {"autogenerate": ("--autogenerate", dict(action="store_true"))}\n'
        "@click.version_option()\n"
        "def main():\n"
        '    "Use --not-an-option in help text."\n'
        "shtab.add_argument_to(parser)\n")})
    assert "--app" in Code(root).options()  # declared in a list, as flask does
    declared = Code(root).declared_options()
    assert {"--app", "--autogenerate", "--help", "--version", "--print-completion"} <= declared
    assert "--not-an-option" not in declared  # a mention inside text isn't a declaration


def test_each_call_gets_its_own_copy(tiny):
    code = Code(tiny)
    code.options()["--made-up"] = []
    code.options()["--limit"].clear()
    code.defined_names().pop("fetch_items")
    code.env_vars()["TINY_TOKEN"].append(None)
    code.option_calls().clear()
    code.declared_options().clear()
    assert "--made-up" not in code.options() and code.options()["--limit"]
    assert "fetch_items" in code.defined_names() and None not in code.env_vars()["TINY_TOKEN"]
    assert code.option_calls() and "--limit" in code.declared_options()
