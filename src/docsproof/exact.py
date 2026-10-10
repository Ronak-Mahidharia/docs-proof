"""The baseline: exact checks, with no AI.

It compares the code before and after a change, collects the names that disappeared (long options,
top-level functions and classes, environment variables, and file paths), and flags every doc line that
still mentions one. Each finding carries its proof: where the name was defined before the change.
It can't see a change that keeps every name, such as a new default value.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .docs import doc_files, is_doc, mentions, skipped
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


def removed_names(before: Path, after: Path, cache: dict | None = None) -> list[tuple[str, str, str]]:
    """(kind, name, where it was) for every name the change removed from the code. A cache dict lets many
    changes to the same "before" tree share one parse of it."""
    if cache is not None and str(before) in cache:
        old, old_files = cache[str(before)]
    else:
        old, old_files = Code(before), repo_files(before)
        if cache is not None:
            cache[str(before)] = (old, old_files)
    new = Code(after)
    found = []
    for kind, read in (("option", Code.options), ("identifier", Code.defined_names), ("env", Code.env_vars)):
        was, now = read(old), read(new)
        for name in sorted(set(was) - set(now)):
            where = was[name][0]
            found.append((kind, name, f"{where.file}:{where.line}"))
    found += [("path", name, name) for name in sorted(old_files - repo_files(after))]
    return found


TOKEN_KIND = {"option": "option", "path": "path", "identifier": "identifier", "env": "identifier"}


def find(before: Path, after: Path, cache: dict | None = None) -> list[Finding]:
    """The doc lines that still mention a name the change removed."""
    docs = doc_files(after)
    findings = []
    for kind, name, where in removed_names(before, after, cache):
        proof = (f"{name} was at {where} before the change and is gone" if kind != "path"
                 else f"{name} existed before the change and is gone")
        for m in mentions(after, name, TOKEN_KIND[kind], docs):
            findings.append(Finding(m.file, m.line, name, kind, proof))
    return findings
