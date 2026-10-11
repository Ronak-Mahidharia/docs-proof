"""Changed values: a new default for an option, or a higher minimum Python version, found by comparing the code
before and after a change, and the doc lines that may still state the old value.

The search is wide on purpose. For a default, every doc line about the option that shows the old number is a
candidate: the line that names the option, and the two after it, where its description often goes on. For
Python, every line that mentions Python and the old minimum version, such as "3.9". The baseline flags all of
them; a model reads each candidate in context and keeps the ones that state the old value as current.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .docs import doc_files, mentions, read_lines
from .names import Code, min_python

PYTHON = re.compile(r"(?<![\w-])(?:c?python|pypy)", re.I)
REQUIRES_LINE = re.compile(r"requires-python|python_requires", re.I)
AFTER_MENTION = 2  # lines after an option's mention that its description can run on to


@dataclass(frozen=True)
class ValueChange:
    kind: str  # "default" or "python"
    subject: str  # the option, or "Python"
    old: str  # as docs write it: "10", "0.5", "3.9"
    new: str
    file: str  # where the code sets it, after the change
    line: int
    code: str  # that line of code, after the change


@dataclass(frozen=True)
class Candidate:
    file: str
    line: int
    text: str


def _number(value: int | float) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def code_line(path: Path, number: int) -> str:
    """A line of code, numbered as ast numbers it: Python counts lines at "\n" and "\r", not at a form feed."""
    return path.read_text(encoding="utf-8", errors="replace").split("\n")[number - 1].strip()


def _defaults(code: Code) -> dict[tuple[str, str, int], ast.Constant]:
    return {(option, where.file, where.line): const for option, where, const in code.option_defaults()}


def value_changes(before: Path, after: Path, before_code: Code | None = None,
                  after_code: Code | None = None) -> list[ValueChange]:
    """The values the change set differently: option defaults, and the minimum Python version."""
    found = []
    old = _defaults(Code(before) if before_code is None else before_code)
    new = _defaults(Code(after) if after_code is None else after_code)
    # a default whose line moved (a line added above it, say) is the same one when its file declares the
    # option once, before and after the change
    declared = Counter((o, f) for o, f, _ in old), Counter((o, f) for o, f, _ in new)
    moved = {(o, f): const for (o, f, _), const in old.items() if declared[0][(o, f)] == declared[1][(o, f)] == 1}
    for (option, file, line), const in sorted(new.items()):
        previous = old.get((option, file, line))
        if previous is None:
            previous = moved.get((option, file))
        if previous is not None and previous.value != const.value:
            code = code_line(after / file, const.lineno)
            found.append(ValueChange("default", option, _number(previous.value), _number(const.value), file,
                                     const.lineno, code))
    was, now = min_python(before), min_python(after)
    if was and now and was[1] != now[1]:
        lines = read_lines(after / now[0])
        at = next((i for i, text in enumerate(lines, 1) if REQUIRES_LINE.search(text) and f"3.{now[1]}" in text), 0)
        found.append(ValueChange("python", "Python", f"3.{was[1]}", f"3.{now[1]}", now[0], at,
                                 lines[at - 1].strip() if at else ""))
    return found


def candidates(root: Path, change: ValueChange) -> list[Candidate]:
    """Doc lines that may state the old value: the wide search the baseline flags, and the model reads."""
    docs = doc_files(root)
    found: dict[tuple[str, int], str] = {}
    if change.kind == "python":
        version = re.compile(rf"(?<![\d.]){re.escape(change.old)}(?!\d)")
        for rel in docs:
            for n, text in enumerate(read_lines(root / rel), 1):
                if version.search(text) and PYTHON.search(text):
                    found[(rel, n)] = text
    else:
        number = re.compile(rf"(?<![\w.]){re.escape(change.old)}(?!\w|\.\d)")  # "10." ends a sentence; "10.5" doesn't
        for m in mentions(root, change.subject, "option", docs):
            lines = read_lines(root / m.file)
            for n in range(m.line, min(m.line + AFTER_MENTION, len(lines)) + 1):
                if number.search(lines[n - 1]):
                    found[(m.file, n)] = lines[n - 1]
    return [Candidate(f, n, text) for (f, n), text in sorted(found.items())]
