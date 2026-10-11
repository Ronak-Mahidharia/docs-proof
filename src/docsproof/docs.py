"""Find a repository's docs, and the doc lines that mention a name.

Docs are the README and other Markdown, reStructuredText, and text files at the top level, plus everything
of those kinds under docs/ or doc/. History files (changelogs, release notes, news) are left out anywhere:
they record what used to be true, so a change doesn't make them wrong. So are the top-level legal and policy
files (license, code of conduct, security policy) and requirements lists, which aren't descriptions of the code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DOC_SUFFIXES = {".md", ".markdown", ".rst", ".txt"}
DOC_DIRS = ("docs", "doc")
# Folders that are never the project's own files: anywhere, or only at the top level ("build" and "dist" hold
# build output there, but a docs/build folder can be the docs' source).
SKIP_ANYWHERE = {".git", "node_modules", ".venv", "venv", "site-packages", "_build", ".tox", ".nox", "__pycache__"}
SKIP_AT_TOP = {"build", "dist"}
HISTORY = re.compile(r"(?:^|[/_.-])(?:changelog|changes|history|news|release[-_]?notes|releases)(?:[/_.-]|$)", re.I)
TOP_LEVEL_NOT_DOCS = {"license", "licence", "copying", "notice", "authors", "contributors", "code_of_conduct",
                      "code-of-conduct", "security"}
REQUIREMENTS = re.compile(r"requirements|constraints", re.I)


@dataclass(frozen=True)
class Mention:
    file: str  # relative to the repository root, with forward slashes
    line: int  # 1-based
    text: str


def skipped(parts: tuple[str, ...]) -> bool:
    """Whether a relative path's folders mark it as build output or tooling, not the project's own."""
    return bool(SKIP_ANYWHERE & set(parts)) or (len(parts) > 1 and parts[0] in SKIP_AT_TOP)


def is_doc(rel: str) -> bool:
    """Whether a relative path (forward slashes) is one of this project's doc files."""
    path = Path(rel)
    top = len(path.parts) == 1
    if top and not (path.suffix.lower() in DOC_SUFFIXES or path.name.upper().startswith("README")):
        return False
    if not top and (path.parts[0] not in DOC_DIRS or path.suffix.lower() not in DOC_SUFFIXES):
        return False
    if skipped(path.parts) or HISTORY.search(rel):
        return False
    if top and path.stem.lower() in TOP_LEVEL_NOT_DOCS:
        return False
    return not (path.suffix.lower() == ".txt" and REQUIREMENTS.search(path.name))


def inside(path: Path, root: Path) -> bool:
    """Whether a path, after following any links, is in the folder."""
    return path.resolve().is_relative_to(root.resolve())


def readable(rel: str) -> bool:
    """Whether a file's name is valid UTF-8. One that isn't can't be printed, or named in a patch."""
    try:
        rel.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def project_file(path: Path, root: Path) -> bool:
    """Whether a path is a file of the project's own: a readable name, and, after following any links, a file in
    the folder (a link to a file elsewhere isn't the project's, and one to nothing isn't a file)."""
    return readable(path.relative_to(root).as_posix()) and path.is_file() and inside(path, root)


def linked(path: Path, root: Path) -> bool:
    """Whether a path in the folder goes through a link: the file itself, or a folder on the way to it."""
    return path.resolve() != root.resolve() / path.relative_to(root)


def doc_files(root: Path) -> list[str]:
    """The repository's doc files, as sorted relative paths. Each is read once, where it really is: a doc reached
    through a link, such as a docs/index.md that links to README.md, is left out, since the file it leads to is
    read under its own name if it's a doc."""
    found = [p.name for p in root.iterdir()]
    for name in DOC_DIRS:
        if (root / name).is_dir():
            found += [p.relative_to(root).as_posix() for p in (root / name).rglob("*")]
    return sorted(rel for rel in found if is_doc(rel) and project_file(root / rel, root) and not linked(root / rel, root))


def split_lines(text: str) -> list[str]:
    """A text's lines as git and GitHub count them: split only at "\n", with a "\r" before it dropped.
    str.splitlines would also break at a form feed and other separators that can sit inside a line, and then
    the line numbers docs-proof reports, and the patch it makes, would drift from the file's."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def read_lines(path: Path) -> list[str]:
    return split_lines(path.read_bytes().decode("utf-8", errors="replace"))


def token_pattern(name: str, kind: str) -> re.Pattern[str]:
    """A whole-token match for a name. Options and paths count hyphens (and, for paths, dots) as word parts."""
    escaped = re.escape(name)
    if kind == "option":
        return re.compile(rf"(?<![\w-]){escaped}(?![\w-])")
    if kind == "path":
        return re.compile(rf"(?<![\w./-]){escaped}(?![\w/-])")
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


# A line about another tool's options, such as "pip install --upgrade", isn't about this project's options.
OTHER_TOOLS = re.compile(r"\b(?:pip3?\s+install|python3?\s+-m\s+pip|uv\s+pip|git\s+\w|docker\s+\w|npm\s+\w|"
                         r"brew\s+\w|conda\s+\w|apt(?:-get)?\s+\w)")


QUALIFIER = re.compile(r"((?:[A-Za-z_]\w*\.)+)$")


def qualifiers(text: str, name: str) -> list[str | None]:
    """For each whole-token occurrence of a name in a line, the first part of the dotted path in front of it:
    "jinja2_time" for "jinja2_time.TimeExtension", None when nothing names a module in front of it."""
    found = []
    for match in token_pattern(name, "identifier").finditer(text):
        if match.start() and text[match.start() - 1] in "/\\":
            found.append("<path>")  # part of a file path, such as docs/configuration/git_hook.md
            continue
        before = QUALIFIER.search(text[: match.start()])
        found.append(before.group(1).split(".")[0] if before else None)
    return found


def mentions(root: Path, name: str, kind: str, files: list[str] | None = None) -> list[Mention]:
    """Every doc line that mentions the name as a whole token."""
    pattern = token_pattern(name, kind)
    found = []
    for rel in files if files is not None else doc_files(root):
        for number, text in enumerate(read_lines(root / rel), 1):
            if pattern.search(text) and not (kind == "option" and OTHER_TOOLS.search(text)):
                found.append(Mention(rel, number, text))
    return found
