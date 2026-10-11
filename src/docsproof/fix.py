"""Suggested fixes for the doc lines a change made wrong, each checked before it's offered.

Rules come first, as in the rest of docs-proof. A rename puts the new name where the old one was, and a changed
value puts the new value where the old one was. A rule fixes a line only when the fix is clear: the change
removed one name and added one like it (paired by kind and by how alike the names are), or the line shows the old
value once. A function or class name written under another package's name ("jinja2_time.TimeExtension") or inside
a file path is left alone. Lines the rules can't fix go to the agent (agent.py).

Every fix is checked: it changes at most a few lines, keeps most of each one, and no longer says what the change
removed or replaced. A fixed command is also run in the sandbox, after the change, where the program must take it
(scripts/run_fixes.py). Nothing is changed in a repository without approval (approve.py).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from .docs import qualifiers, token_pattern
from .exact import TOKEN_KIND, repo_files
from .names import Code
from .values import ValueChange

SIMILAR = 0.5  # how alike two names must be to be paired, and how much of a line a fix must keep
MAX_LINES = 3  # the most lines one fix may change


@dataclass(frozen=True)
class Fix:
    file: str
    line: int  # the first line it replaces
    old: tuple[str, ...]  # the lines it replaces
    new: tuple[str, ...]  # the same number of lines
    how: str  # "rule" or "agent"
    reason: str


def _names(code: Code, files: set[str]) -> dict[str, set[str]]:
    return {"option": set(code.options()), "identifier": set(code.defined_names()), "env": set(code.env_vars()),
            "path": files}


def renames(before: Path, after: Path, cache: dict | None = None,
            after_code: Code | None = None) -> dict[tuple[str, str], str]:
    """{(kind, old name): new name} for the names the change renamed: of one kind, a single removed and a single
    added name are a pair; with more, each old name is paired with the most alike new one, if alike enough. The
    names are read as exact.removed_names reads them, and a cache dict shares the parse of the "before" tree."""
    if cache is not None and str(before) in cache:
        old, old_files = cache[str(before)]
    else:
        old, old_files = Code(before), repo_files(before)
        if cache is not None:
            cache[str(before)] = (old, old_files)
    was, now = _names(old, old_files), _names(Code(after) if after_code is None else after_code, repo_files(after))
    pairs = {}
    for kind in was:
        old_names, new_names = sorted(was[kind] - now[kind]), sorted(now[kind] - was[kind])
        if len(old_names) == 1 and len(new_names) == 1:
            pairs[(kind, old_names[0])] = new_names[0]
            continue
        for name in old_names:
            scored = sorted(((difflib.SequenceMatcher(None, name, new).ratio(), new) for new in new_names), reverse=True)
            if scored and scored[0][0] >= SIMILAR and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                pairs[(kind, name)] = scored[0][1]
                new_names.remove(scored[0][1])
    return pairs


def _mentions(text: str, kind: str, old: str, own: set[str] | None = None) -> list[re.Match]:
    """The mentions of a name in a line that a fix changes. For a function or class, not one inside a file path
    (renaming it doesn't rename its file), and, given the names of the project's own packages, not one under
    another package's name."""
    found = list(token_pattern(old, TOKEN_KIND[kind]).finditer(text))
    if kind == "identifier":
        found = [m for m, q in zip(found, qualifiers(text, old))
                 if q != "<path>" and (own is None or q is None or q in own)]
    return found


def rename_fix(text: str, kind: str, old: str, new: str, own: set[str] | None = None) -> str | None:
    """The line with the new name where the old one was, or None if the line has no mention of it to change."""
    found = _mentions(text, kind, old, own)
    for m in reversed(found):
        text = text[: m.start()] + new + text[m.end():]
    return text if found else None


def value_pattern(change: ValueChange) -> re.Pattern:
    """The old value as the docs write it: "3.9" (not 3.90), or "10" (not 100 or 10.5)."""
    if change.kind == "python":
        return re.compile(rf"(?<![\d.]){re.escape(change.old)}(?!\d)")
    return re.compile(rf"(?<![\w.]){re.escape(change.old)}(?!\w|\.\d)")


def value_fix(text: str, change: ValueChange) -> str | None:
    """The line with the new value where the old one was, or None unless the old value is in it exactly once."""
    pattern = value_pattern(change)
    if len(pattern.findall(text)) != 1:
        return None
    return pattern.sub(lambda _: change.new, text)


def rule_fix(text: str, names: list[tuple[str, str]], changes: list[ValueChange], pairs: dict[tuple[str, str], str],
             own: set[str]) -> tuple[str | None, str]:
    """The rules' fix for a flagged line: (the fixed line, why), or (None, why the rules decline it). names are the
    (kind, name) pairs the line was flagged for, changes the values it may still state, and pairs what renames()
    found."""
    new, reasons = text, []
    for kind, name in names:
        target = pairs.get((kind, name))
        if target is None:
            return None, f"the change added no name to put in place of `{name}`"
        fixed = rename_fix(new, kind, name, target, own)
        if fixed is None:
            return None, f"`{name}` is there only under another package's name or in a file path"
        new = fixed
        reasons.append(f"`{name}` is now `{target}`")
    for change in changes:
        fixed = value_fix(new, change)
        if fixed is None:
            return None, f"{change.old} is in the line {len(value_pattern(change).findall(new))} times"
        new = fixed
        what = ("the oldest Python version the project supports" if change.kind == "python" else
                f"the default of the option {change.subject}")
        reasons.append(f"{what} is now {change.new}")
    return new, "; ".join(reasons)


def stale_name(text: str, kind: str, old: str, own: set[str] | None = None) -> bool:
    """Whether a line still mentions a name the change removed (as rename_fix counts mentions)."""
    return bool(_mentions(text, kind, old, own))


def changes_value(old_text: str, new_text: str, change: ValueChange) -> bool:
    """Whether a fix states the new value in place of the old one: the old value fewer times, the new one more."""
    old, new = value_pattern(change), value_pattern(ValueChange(change.kind, "", change.new, "", "", 0, ""))
    return len(old.findall(new_text)) < len(old.findall(old_text)) and \
        len(new.findall(new_text)) > len(new.findall(old_text))


def close(old_text: str, new_text: str) -> bool:
    """Whether a fixed line keeps most of the old one: a fix mends the line, it doesn't rewrite it."""
    return difflib.SequenceMatcher(None, old_text, new_text, autojunk=False).ratio() >= SIMILAR


def check_shape(fix: Fix, lines: list[str], flagged: int) -> str | None:
    """None if a fix has the shape of a fix for the flagged line (1-based), or what's wrong with it."""
    if not fix.new or len(fix.new) != len(fix.old):
        return "give the same number of lines as you replace"
    if len(fix.new) > MAX_LINES:
        return f"change at most {MAX_LINES} lines"
    if not fix.line <= flagged < fix.line + len(fix.new):
        return f"the lines you replace must include line {flagged}"
    if fix.line < 1 or fix.line + len(fix.old) - 1 > len(lines) or \
            tuple(lines[fix.line - 1: fix.line - 1 + len(fix.old)]) != fix.old:
        return "those aren't the doc's lines"
    if fix.new == fix.old:
        return "that changes nothing"
    if any("\n" in text or "\r" in text for text in fix.new):
        return "give one line in each string"
    for old_text, new_text in zip(fix.old, fix.new):
        if old_text != new_text and not close(old_text, new_text):
            return "that rewrites a line; change only what's wrong and keep the rest of it"
    return None


def apply(lines: list[str], fixes: list[Fix]) -> list[str]:
    """The doc's lines with the fixes made. Fixes may not overlap."""
    out = list(lines)
    taken: set[int] = set()
    for fix in sorted(fixes, key=lambda f: f.line):
        span = set(range(fix.line, fix.line + len(fix.old)))
        if span & taken:
            raise ValueError(f"overlapping fixes at {fix.file}:{fix.line}")
        taken |= span
        if tuple(out[fix.line - 1: fix.line - 1 + len(fix.old)]) != fix.old:
            raise ValueError(f"the fix at {fix.file}:{fix.line} doesn't match the doc")
        out[fix.line - 1: fix.line - 1 + len(fix.old)] = fix.new
    return out


def utf8(path: Path) -> bool:
    """Whether a doc is valid UTF-8. One that isn't is read, but never rewritten: writing it back would change
    bytes no fix meant to change."""
    try:
        path.read_bytes().decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _split_raw(text: str) -> list[str]:
    """A text's lines with their own endings ("\r\n" kept), split where read_lines splits them: at "\n" only."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _raw_lines(path: Path) -> list[str]:
    try:
        return _split_raw(path.read_bytes().decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} isn't valid UTF-8, so docs-proof won't rewrite it") from None


def _content(line: str) -> str:
    """A line without its ending, as read_lines gives it: no "\n", and no "\r" before it."""
    return line.removesuffix("\n").removesuffix("\r")


def fixed_text(path: Path, fixes: list[Fix]) -> str:
    """The file's text with the fixes made, each line keeping its own ending."""
    raw = _raw_lines(path)
    lines = apply([_content(line) for line in raw], fixes)
    return "".join(new + old[len(_content(old)):] for new, old in zip(lines, raw))


def patch(root: Path, fixes: list[Fix]) -> str:
    """The fixes as one unified diff, the way `git apply` and a pull request read them."""
    by_file: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_file.setdefault(fix.file, []).append(fix)
    out = []
    for rel in sorted(by_file):
        before = _raw_lines(root / rel)
        after = _split_raw(fixed_text(root / rel, by_file[rel]))
        out += difflib.unified_diff(before, after, f"a/{rel}", f"b/{rel}")
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in out)
