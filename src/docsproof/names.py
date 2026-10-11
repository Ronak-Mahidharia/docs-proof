"""Read the names a repository's code defines, the ones its docs can refer to.

Only the project's own code is read: tests, docs, examples, and helper scripts are skipped, because their
options and functions aren't the project's interface. Files that don't parse (templates, for example) are
skipped too.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .docs import skipped

TEST_DIRS = {"tests", "test", "testing"}  # skipped at any depth, when they hold test files
# Skipped only at the top level: a package's own scripts folder, such as piptools/scripts, is project code.
TOP_LEVEL_NOT_PROJECT = {"docs", "doc", "examples", "example", "benchmarks", "scripts", "tools", "ci", ".github",
                         "changelog.d"}
TEST_FILE = re.compile(r"^(?:test_.*|.*_test|conftest)\.py$")
# Calls that declare a command-line option: argparse, optparse, click, typer, and click's relatives.
OPTION_CALLS = {"add_argument", "add_option", "option", "Option", "make_option"}
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
LONG_OPTION = re.compile(r"--[A-Za-z0-9][\w-]*")


@dataclass(frozen=True)
class Where:
    file: str
    line: int


def _is_test_folder(folder: Path) -> bool:
    """A folder named tests, test, or testing that holds test files. A folder with that name and no test files,
    such as hatch's src/hatch/cli/test (the "hatch test" command), is project code."""
    return folder.name in TEST_DIRS and any(TEST_FILE.match(p.name) for p in folder.glob("*.py"))


def project_files(root: Path) -> list[str]:
    """The project's own Python files, as sorted relative paths."""
    files, test_folders = [], {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        folders = rel.parts[:-1]
        if skipped(rel.parts) or (folders and folders[0] in TOP_LEVEL_NOT_PROJECT) or TEST_FILE.match(path.name):
            continue
        tested = False
        for depth in range(1, len(folders) + 1):
            key = "/".join(folders[:depth])
            if key not in test_folders:
                test_folders[key] = _is_test_folder(root / key)
            tested = tested or test_folders[key]
        if not tested:
            files.append(rel.as_posix())
    return sorted(files)


def packages(root: Path) -> set[str]:
    """The names the project's code is imported under: top-level packages and modules, with or without src/."""
    names = set()
    for rel in project_files(root):
        parts = rel.split("/")
        if parts[0] == "src" and len(parts) > 1:
            parts = parts[1:]
        names.add(parts[0].removesuffix(".py"))
    return names


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _owner(node: ast.expr) -> str | None:
    """The last name in an expression such as os.environ (environ) or environ (environ)."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def long_options(node: ast.Call) -> list[str]:
    """The long options a call declares, such as "--limit", splitting click's "--color/--no-color" pairs.
    Declarations can be separate arguments or a list, as in click.Option(["-A", "--app"])."""
    values = []
    for arg in node.args:
        if isinstance(arg, (ast.List, ast.Tuple)):
            values += [e.value for e in arg.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            values.append(arg.value)
    found = []
    for value in values:
        for part in value.split("/"):
            if LONG_OPTION.fullmatch(part.strip()):
                found.append(part.strip())
    return found


class Code:
    """A repository's own Python code, parsed once. Each kind of name is also worked out once, the first time
    it's asked for, and every call returns a fresh copy, so a caller can't change what the next one gets."""

    def __init__(self, root: Path):
        self.root = root
        self.trees: dict[str, ast.Module] = {}
        for rel in project_files(root):
            try:
                self.trees[rel] = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue

    def option_calls(self) -> list[tuple[str, ast.Call]]:
        """(file, call) for every call that declares at least one long option."""
        return list(self._option_calls)

    @cached_property
    def _option_calls(self) -> list[tuple[str, ast.Call]]:
        calls = []
        for rel, tree in self.trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_name(node) in OPTION_CALLS and long_options(node):
                    calls.append((rel, node))
        return calls

    def options(self) -> dict[str, list[Where]]:
        return _copied(self._options)

    @cached_property
    def _options(self) -> dict[str, list[Where]]:
        out: dict[str, list[Where]] = {}
        for rel, node in self._option_calls:
            for option in long_options(node):
                out.setdefault(option, []).append(Where(rel, node.lineno))
        return out

    def declared_options(self) -> set[str]:
        """Every long option the command line can accept, as far as the code shows: declared options, any string
        that is exactly an option (alembic keeps its options in a table), and the ones libraries add themselves:
        --help always, --version from click's version_option, and shtab's --print-completion."""
        return set(self._declared_options)

    @cached_property
    def _declared_options(self) -> set[str]:
        found = set(self._options) | {"--help"}
        for tree in self.trees.values():
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and LONG_OPTION.fullmatch(node.value):
                    found.add(node.value)
                elif isinstance(node, ast.Call):
                    name = _call_name(node)
                    if name == "version_option":
                        found.add("--version")
                    elif name == "add_argument_to":
                        found.add("--print-completion")
        return found

    def option_defaults(self) -> list[tuple[str, Where, ast.Constant]]:
        """(option, where, default) for options whose default is a plain int or float written in the call."""
        return list(self._option_defaults)

    @cached_property
    def _option_defaults(self) -> list[tuple[str, Where, ast.Constant]]:
        found = []
        for rel, node in self._option_calls:
            for kw in node.keywords:
                value = kw.value
                if kw.arg == "default" and isinstance(value, ast.Constant) and type(value.value) in (int, float):
                    found += [(option, Where(rel, node.lineno), value) for option in long_options(node)]
        return found

    def defined_names(self) -> dict[str, list[Where]]:
        """Top-level functions and classes, public and private."""
        return _copied(self._defined_names)

    @cached_property
    def _defined_names(self) -> dict[str, list[Where]]:
        out: dict[str, list[Where]] = {}
        for rel, tree in self.trees.items():
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    out.setdefault(node.name, []).append(Where(rel, node.lineno))
        return out

    def public_names(self) -> dict[str, list[Where]]:
        """Top-level names defined in public modules: no part of the path starts with "_", except __init__.py
        and __main__.py. A name defined only in a private module, such as loguru/_filters.py, isn't part of the
        project's interface, so docs that use it usually mean something of their own."""
        def public(rel: str) -> bool:
            return not any(part.startswith("_") and part not in ("__init__.py", "__main__.py") for part in rel.split("/"))
        return {name: [w for w in where if public(w.file)] for name, where in self._defined_names.items()
                if any(public(w.file) for w in where)}

    def env_vars(self) -> dict[str, list[Where]]:
        """Environment variables the code reads: os.getenv("X"), os.environ.get("X"), os.environ["X"], ..."""
        return _copied(self._env_vars)

    @cached_property
    def _env_vars(self) -> dict[str, list[Where]]:
        out: dict[str, list[Where]] = {}
        for rel, tree in self.trees.items():
            for node in ast.walk(tree):
                value = line = None
                if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                    name = _call_name(node)
                    owner = _owner(node.func.value) if isinstance(node.func, ast.Attribute) else None
                    if name == "getenv" or (owner == "environ" and name in {"get", "setdefault", "pop"}):
                        value, line = node.args[0].value, node.lineno
                elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                    if _owner(node.value) == "environ":
                        value, line = node.slice.value, node.lineno
                if isinstance(value, str) and ENV_NAME.match(value):
                    out.setdefault(value, []).append(Where(rel, line))
        return out


def _copied(found: dict[str, list]) -> dict[str, list]:
    return {key: list(value) for key, value in found.items()}


REQUIRES = re.compile(r"""(?m)^\s*(?:requires-python|python_requires)\s*[=:]\s*["']?\s*>=\s*3\.(\d+)""")
SETUP_PY_REQUIRES = re.compile(r"""python_requires\s*=\s*["']\s*>=\s*3\.(\d+)""")


def min_python(root: Path) -> tuple[str, int] | None:
    """(file, minor) for the minimum Python 3 version the project declares, such as ("pyproject.toml", 9)."""
    for rel, pattern in (("pyproject.toml", REQUIRES), ("setup.cfg", REQUIRES), ("setup.py", SETUP_PY_REQUIRES)):
        path = root / rel
        if path.is_file():
            match = pattern.search(path.read_text(encoding="utf-8", errors="replace"))
            if match:
                return rel, int(match.group(1))
    return None
