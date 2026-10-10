"""Planted changes: one realistic code change at a time, made on a copy of a repository.

Like mutation testing, the changes are mechanical (a renamed option gets a "2" at the end), and they keep
the code working: when an option is renamed, the variable name the code reads is pinned, so the program
still runs. The docs are never touched; finding the doc lines a change made wrong is the job being measured.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from .docs import skipped, token_pattern
from .names import long_options

CONFIG_FILES = ("pyproject.toml", "setup.cfg", "MANIFEST.in")


def python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py*") if p.suffix in (".py", ".pyi")
                  and not skipped(p.relative_to(root).parts))


def _offsets(text: str) -> list[int]:
    """Where each line starts, counting lines the way Python's tokenizer and parser do: only at "\n".
    str.splitlines would also break at a form feed or other separators, which can sit inside a string,
    and then every later position would be wrong."""
    starts = [0]
    at = text.find("\n")
    while at != -1:
        starts.append(at + 1)
        at = text.find("\n", at + 1)
    starts.append(len(text))
    return starts


def _at(text: str, starts: list[int], line: int, byte_col: int) -> int:
    """The character offset for an ast position: ast columns count UTF-8 bytes, not characters."""
    begin = starts[line - 1]
    return begin + len(text[begin:].encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _apply(text: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _token_edits(text: str, change) -> list[tuple[int, int, str]]:
    """Edits from a function that maps (token, its exact source text) to new text, or None to leave it.
    Working on the exact source text means only the changed part of a token is ever rewritten."""
    starts = _offsets(text)
    edits = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            start = starts[tok.start[0] - 1] + tok.start[1]
            end = starts[tok.end[0] - 1] + tok.end[1]
            raw = text[start:end]
            new = change(tok, raw)
            if new is not None and new != raw:
                edits.append((start, end, new))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    return edits


STRING_TOKENS = {tokenize.STRING} | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())


def _replace_in_strings(root: Path, pattern: re.Pattern[str], new: str) -> list[str]:
    changed = []
    for path in python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not pattern.search(text):
            continue
        edits = _token_edits(text, lambda tok, raw: pattern.sub(lambda _: new, raw)
                             if tok.type in STRING_TOKENS else None)
        if edits:
            _write(path, text, _apply(text, edits))
            changed.append(path.relative_to(root).as_posix())
    return changed


_WRITES: list[tuple[Path, bool]] = []  # (file, whether it parsed before the change), for apply's check


def _parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


def _write(path: Path, old: str, new: str) -> None:
    if path.suffix in (".py", ".pyi"):
        _WRITES.append((path, _parses(old)))
    path.write_text(new, encoding="utf-8")


def _dest(option: str) -> str:
    return option.lstrip("-").replace("-", "_")


def _pin_names(root: Path, files: list[str], new: str, old: str) -> None:
    """Keep the variable name the code reads when an option is renamed: argparse and optparse get dest=,
    click gets its parameter name. typer's names come from the function, so they need nothing."""
    for rel in files:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        starts, edits = _offsets(text), []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not long_options(node) or long_options(node)[0] != new:
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            keywords = {kw.arg for kw in node.keywords}
            if name in {"add_argument", "add_option", "make_option"} and "dest" not in keywords:
                last = max([*node.args, *(kw.value for kw in node.keywords)], key=lambda n: (n.end_lineno, n.end_col_offset))
                at = _at(text, starts, last.end_lineno, last.end_col_offset)
                closing = _at(text, starts, node.end_lineno, node.end_col_offset) - 1
                between = text[at:closing]
                comma = re.match(r"\s*,", between)  # a trailing comma comes before any comment
                if comma:
                    at += comma.end()
                    edits.append((at, at, f' dest="{_dest(old)}",'))
                else:
                    edits.append((at, at, f', dest="{_dest(old)}"'))
            elif name == "option" and not any(isinstance(a, ast.Constant) and isinstance(a.value, str)
                                              and not a.value.startswith("-") for a in node.args):
                first = node.args[0]
                at = _at(text, starts, first.end_lineno, first.end_col_offset)
                edits.append((at, at, f', "{_dest(old)}"'))
        if edits:
            _write(path, text, _apply(text, edits))


def rename_option(root: Path, old: str, new: str) -> list[str]:
    changed = _replace_in_strings(root, token_pattern(old, "option"), new)
    _pin_names(root, changed, new, old)
    return changed


def rename_identifier(root: Path, old: str, new: str) -> list[str]:
    changed = []
    quoted = {f'"{old}"': f'"{new}"', f"'{old}'": f"'{new}'"}
    for path in python_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            continue

        def change(tok, raw):
            if tok.type == tokenize.NAME and raw == old:
                return new
            if tok.type == tokenize.STRING:
                return quoted.get(raw)
            return None

        edits = _token_edits(text, change)
        if edits:
            _write(path, text, _apply(text, edits))
            changed.append(path.relative_to(root).as_posix())
    return changed


def rename_env_var(root: Path, old: str, new: str) -> list[str]:
    return _replace_in_strings(root, re.compile(rf"(?<!\w){re.escape(old)}(?!\w)"), new)


def rename_file(root: Path, old: str, new: str) -> list[str]:
    (root / new).parent.mkdir(parents=True, exist_ok=True)
    (root / old).rename(root / new)
    pattern = token_pattern(old, "path")
    changed = _replace_in_strings(root, pattern, new) + [old, new]
    for rel in CONFIG_FILES:
        path = root / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                path.write_text(pattern.sub(lambda _: new, text), encoding="utf-8")
                changed.append(rel)
    return changed


def change_default(root: Path, file: str, line: int, option: str, new: str) -> list[str]:
    path = root / file
    text = path.read_text(encoding="utf-8")
    starts = _offsets(text)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and node.lineno == line and option in long_options(node):
            for kw in node.keywords:
                if kw.arg == "default":
                    v = kw.value
                    start = _at(text, starts, v.lineno, v.col_offset)
                    end = _at(text, starts, v.end_lineno, v.end_col_offset)
                    _write(path, text, text[:start] + new + text[end:])
                    return [file]
    raise ValueError(f"no default for {option} at {file}:{line}")


def raise_python(root: Path, file: str, old_minor: int, new_minor: int) -> list[str]:
    path = root / file
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?m)((?:requires-python|python_requires)\s*[=:]\s*[\"']?\s*>=\s*3\.){old_minor}\b")
    new_text, count = pattern.subn(rf"\g<1>{new_minor}", text, count=1)
    if not count:
        raise ValueError(f"no requires-python >=3.{old_minor} in {file}")
    path.write_text(new_text, encoding="utf-8")
    return [file]


class PlantError(Exception):
    """A planted change that couldn't be made cleanly. The case is left out of the answer key."""


def apply(root: Path, edit: dict) -> list[str]:
    """Make one planted change on the copy at root. Returns the files it changed."""
    _WRITES.clear()
    changed = _apply_edit(root, edit)
    if not changed:
        raise PlantError(f"nothing changed for {edit}")
    for path, parsed_before in _WRITES:
        if parsed_before and not _parses(path.read_text(encoding="utf-8")):
            raise PlantError(f"{path.relative_to(root).as_posix()} no longer parses after {edit['kind']}")
    return changed


def _apply_edit(root: Path, edit: dict) -> list[str]:
    kind = edit["kind"]
    if kind in ("rename_option", "rename_unmentioned_option"):
        return rename_option(root, edit["old"], edit["new"])
    if kind in ("rename_identifier", "rename_private"):
        return rename_identifier(root, edit["old"], edit["new"])
    if kind == "rename_env_var":
        return rename_env_var(root, edit["old"], edit["new"])
    if kind == "rename_file":
        return rename_file(root, edit["old"], edit["new"])
    if kind == "change_default":
        return change_default(root, edit["file"], edit["line"], edit["option"], edit["new"])
    if kind == "raise_python":
        return raise_python(root, edit["file"], edit["old"], edit["new"])
    raise ValueError(f"unknown kind: {kind}")
