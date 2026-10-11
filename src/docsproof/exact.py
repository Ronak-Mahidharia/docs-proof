"""The baseline: exact checks, with no AI.

It compares the code before and after a change, collects the names that disappeared (long options,
top-level functions and classes, environment variables, and file paths), and flags every doc line that
still mentions one. Each finding carries its proof: where the name was defined before the change.
It can't see a change that keeps every name, such as a new default value.

A function or class whose name could also be an ordinary word, such as records, counts only where the doc marks
it as code: in a code block, inside backticks, as a call, or after a dot. Otherwise every sentence that uses the
word would be flagged (23 false alarms on one pull request of Car Safety Checker; docs/results/own.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .commands import INLINE, code_block_lines
from .docs import doc_files, is_doc, mentions, read_lines, skipped, token_pattern
from .names import Code


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    name: str
    kind: str  # option, identifier, env, or path
    proof: str


def repo_files(root: Path) -> set[str]:
    """Every file in the repository except docs, build output, and tooling folders."""
    out = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not skipped(rel.parts) and not is_doc(rel.as_posix()):
            out.add(rel.as_posix())
    return out


def removed_names(before: Path, after: Path, cache: dict | None = None,
                  after_code: Code | None = None) -> list[tuple[str, str, str]]:
    """(kind, name, where it was) for every name the change removed from the code. A cache dict lets many
    changes to the same "before" tree share one parse of it, and after_code is the "after" tree, if it's
    already parsed."""
    if cache is not None and str(before) in cache:
        old, old_files = cache[str(before)]
    else:
        old, old_files = Code(before), repo_files(before)
        if cache is not None:
            cache[str(before)] = (old, old_files)
    new = Code(after) if after_code is None else after_code
    found = []
    for kind, read in (("option", Code.options), ("identifier", Code.defined_names), ("env", Code.env_vars)):
        was, now = read(old), read(new)
        for name in sorted(set(was) - set(now)):
            where = was[name][0]
            found.append((kind, name, f"{where.file}:{where.line}"))
    found += [("path", name, name) for name in sorted(old_files - repo_files(after))]
    return found


TOKEN_KIND = {"option": "option", "path": "path", "identifier": "identifier", "env": "identifier"}


def ordinary(name: str) -> bool:
    """Whether a function's or class's name could also be an ordinary word: no underscore and fewer than two
    capitals, such as records or Server. A name like fetch_items or PluginSQL can't be. The answer key renames
    only names like those (distinctive() in scripts/build_cases.py), so it never has an ordinary one."""
    return "_" not in name and sum(c.isupper() for c in name) < 2


def as_code(text: str, name: str, in_block: bool) -> bool:
    """Whether a doc line marks the name as code: the line is in a code block, or the name is inside backticks
    (`records`, ``records``, :func:`records`), called (records()), or after a dot (nhtsa.records)."""
    if in_block:
        return True
    spans = [m.span() for m in INLINE.finditer(text)]
    for match in token_pattern(name, "identifier").finditer(text):
        start, end = match.span()
        if any(a <= start and end <= b for a, b in spans) or text[end:end + 1] == "(" \
                or (start >= 2 and text[start - 1] == "." and (text[start - 2].isalnum() or text[start - 2] == "_")):
            return True
    return False


def find(before: Path, after: Path, cache: dict | None = None, after_code: Code | None = None) -> list[Finding]:
    """The doc lines that still mention a name the change removed."""
    docs = doc_files(after)
    blocks: dict[str, set[int]] = {}

    def in_block(file: str, line: int) -> bool:
        if file not in blocks:
            blocks[file] = code_block_lines(file, read_lines(after / file))
        return line in blocks[file]

    findings = []
    for kind, name, where in removed_names(before, after, cache, after_code):
        proof = (f"{name} was at {where} before the change and is gone" if kind != "path"
                 else f"{name} existed before the change and is gone")
        for m in mentions(after, name, TOKEN_KIND[kind], docs):
            if kind == "identifier" and ordinary(name) and not as_code(m.text, name, in_block(m.file, m.line)):
                continue  # the word in a sentence, not the removed function or class
            findings.append(Finding(m.file, m.line, name, kind, proof))
    return findings
