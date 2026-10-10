"""Commands in the docs, and a check of their options against the code.

A documented command is a command in a code block, or an inline code span, that runs one of the project's own
programs: a console script, or python -m with one of its packages. It's read the way a shell reads it:
- a quoted value stays whole ("--pip-args '--no-deps'" passes --no-deps to pip, not to this program)
- a line can hold several commands ("cat notes.txt | llm --system ..."), and a redirect's file isn't an argument
- a program can be started through another one ("uvx cookiecutter", "poetry run tiny", "VAR=1 tiny")
- in a block that shows prompts ("$ tiny --limit 3"), the lines without one are output, not commands

The check finds options a documented command uses that the code doesn't declare. With no change, that's a
command that is already out of date (audit). Comparing before and after a change, it's a command the change
made wrong.
"""
from __future__ import annotations

import configparser
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .docs import doc_files, read_lines
from .names import LONG_OPTION, Code, packages

PROMPT = re.compile(r"^(?:\(\S+\)\s*)?(?:\$|%|>>>?|PS\S*>)\s+")
FENCE = re.compile(r"^\s*(```+|~~~+)")
# A code directive, or a paragraph ending in "::". Other directives, such as ".. note::", hold prose.
RST_BLOCK = re.compile(r"^\s*(?:\.\.\s+(?:code-block|code|sourcecode|parsed-literal|prompt)::.*|(?!\s|\.\.\s).*::)\s*$")
QUOTED_VALUE = re.compile(r"""[^'"\s]+=["']""")
INLINE = re.compile(r"``([^`]+)``|`([^`]+)`")
SEPARATORS = {"|", "||", "&&", ";", "&", "|&", "(", ")"}  # one command ends and the next begins
REDIRECTS = {">", ">>", "<", "<<", ">&", "<&", ">|", "&>", "&>>"}  # skip the file named next, then go on
WRAPPERS = [("sudo",), ("env",), ("time",), ("nohup",), ("exec",), ("uvx",), ("pipx", "run"), ("uv", "run"),
            ("uv", "tool", "run"), ("poetry", "run"), ("pdm", "run"), ("hatch", "run"), ("rye", "run")]
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class Command:
    file: str
    line: int  # where the program's name is
    program: str  # the console script, or "python -m <package>"
    text: str
    options: tuple[tuple[str, int], ...]  # each long option, with the line it's on
    argv: tuple[str, ...] = ()  # the words to run, from the program on, without their quotes
    env: tuple[tuple[str, str], ...] = ()  # VAR=value words before the program


@dataclass(frozen=True)
class Problem:
    file: str
    line: int
    program: str
    option: str
    proof: str


def console_scripts(root: Path) -> set[str]:
    """The project's console scripts, from pyproject.toml, setup.cfg, or setup.py."""
    names: set[str] = set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        names |= set((data.get("project") or {}).get("scripts") or {})
        names |= set(((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {})
    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(setup_cfg.read_text(encoding="utf-8", errors="replace"))
            for section in ("options.entry_points", "entry_points"):  # setuptools, and pbr
                text = parser.get(section, "console_scripts", fallback="")
                names |= {line.split("=")[0].strip() for line in text.splitlines() if "=" in line}
        except configparser.Error:
            pass
    setup_py = root / "setup.py"
    if setup_py.is_file():
        text = setup_py.read_text(encoding="utf-8", errors="replace")
        at = text.find("console_scripts")
        if at != -1:
            block = text[at: at + 2000].split("]")[0]
            names |= set(re.findall(r"""["']\s*([A-Za-z0-9_.-]+)\s*=\s*[\w.]+:[\w.]+\s*["']""", block))
    return {n for n in names if n}


def main_packages(root: Path) -> set[str]:
    """Packages that can be run with python -m: the project's packages with a __main__.py."""
    found = set()
    for name in packages(root):
        for base in (root, root / "src"):
            if (base / name / "__main__.py").is_file():
                found.add(name)
    return found


def _balanced(text: str) -> bool:
    try:
        shlex.split(text)
    except ValueError:  # no closing quotation
        return False
    return True


def _rejoin(words: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Join the pieces of an option whose quoted value follows "=", such as --pip-args="--no-deps --pre": the
    lexer keeps a word whole only when the quote starts it, so it splits this one at the spaces in the quotes."""
    out: list[tuple[str, int]] = []
    pending: list[tuple[str, int]] = []
    for word, line in words:
        if pending:
            pending.append((word, line))
            joined = " ".join(w for w, _ in pending)
            if _balanced(joined):
                out.append((joined, pending[0][1]))
                pending = []
        elif _balanced(word) or not QUOTED_VALUE.match(word):
            out.append((word, line))
        else:
            pending = [(word, line)]
    return out + pending  # a quote that never closes: the pieces stay as they were


def _simple_commands(parts: list[tuple[str, int]]) -> list[list[tuple[str, int]]]:
    """The commands in a shell line, each a list of (word, line), the way a shell splits them: at pipes, &&, ||,
    and ;, leaving out redirects and their files, and stopping at a comment. parts: the line's text, with the
    lines it continues onto. Quotes are kept on quoted words, so a quoted value such as "--no-deps" isn't
    mistaken for an option."""
    words: list[tuple[str, int]] = []
    for text, line in parts:
        try:
            lexer = shlex.shlex(text, posix=False, punctuation_chars=True)
            lexer.whitespace_split = True
            words += [(word, line) for word in lexer]
        except ValueError:  # an unbalanced quote: fall back to plain words
            words += [(word, line) for word in text.split()]
    words = _rejoin(words)
    out: list[list[tuple[str, int]]] = [[]]
    skip = False
    for word, line in words:
        if skip:
            skip = False
        elif word.startswith("#"):
            break
        elif word in SEPARATORS:
            out.append([])
        elif word in REDIRECTS:
            skip = True  # "tiny > out.txt --x" still passes --x to tiny
        else:
            out[-1].append((word, line))
    return [c for c in out if c]


def _tokens(text: str) -> list[str]:
    """The words of the first command in a line of shell."""
    found = _simple_commands([(text, 0)])
    return [word for word, _ in found[0]] if found else []


def _program(words: list[str], scripts: set[str], mains: set[str]) -> tuple[str, int] | None:
    """(program, index of its first argument), if the words run one of the project's commands, directly or
    through another program such as uvx or poetry run."""
    skip = 0
    while True:
        rest = words[skip:]
        if rest and rest[0] in scripts:
            return rest[0], skip + 1
        if len(rest) >= 3 and re.fullmatch(r"python(?:3(?:\.\d+)?)?|py", rest[0]) and rest[1] == "-m" and rest[2] in mains:
            return f"python -m {rest[2]}", skip + 3
        if rest and ASSIGNMENT.match(rest[0]):
            skip += 1
            continue
        wrapper = next((w for w in WRAPPERS if tuple(rest[:len(w)]) == w), None)
        if not wrapper:
            return None
        skip += len(wrapper)


def _unquote(word: str) -> str:
    """A word as the program receives it: "--app='hello'" becomes --app=hello."""
    try:
        parts = shlex.split(word)
    except ValueError:  # an unbalanced quote
        return word
    return parts[0] if len(parts) == 1 else word


def _options(words: list[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    """The long options among the words, with their lines."""
    found = []
    for word, line in words:
        if word == "--":
            break  # everything after a lone -- is an argument, not an option
        name = word.split("=", 1)[0]
        if LONG_OPTION.fullmatch(name):
            found.append((name, line))
    return tuple(found)


def _blocks(lines: list[str], markdown: bool) -> list[list[int]]:
    """The code blocks, each a list of 0-based line numbers: fences in Markdown, and literal blocks and code
    directives in reStructuredText (where a line of ~~~ underlines a heading)."""
    blocks: list[list[int]] = []
    i = 0
    while i < len(lines):
        fence = FENCE.match(lines[i]) if markdown else None
        if fence:
            j, block = i + 1, []
            while j < len(lines) and not lines[j].lstrip().startswith(fence.group(1)):
                block.append(j)
                j += 1
            blocks.append(block)
            i = j + 1
            continue
        if not markdown and RST_BLOCK.match(lines[i]) and not lines[i].lstrip().startswith(("http", "#")):
            indent = len(lines[i]) - len(lines[i].lstrip())
            j, block = i + 1, []
            while j < len(lines) and not lines[j].strip():
                j += 1
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                if lines[j].strip():
                    block.append(j)
                j += 1
            blocks.append(block)
            i = j
            continue
        i += 1
    return blocks


def _shell_lines(lines: list[str], markdown: bool) -> list[list[tuple[str, int]]]:
    """The shell lines in code blocks, each as its parts: (text without the prompt, 0-based line), with the lines
    a trailing backslash continues it onto. In a block that shows prompts, only lines with a prompt count, since
    the rest is output."""
    found = []
    for block in _blocks(lines, markdown):
        prompted = any(PROMPT.match(lines[j].strip()) for j in block)
        k = 0
        while k < len(block):
            j = block[k]
            k += 1
            raw = lines[j].strip()
            if prompted and not PROMPT.match(raw):
                continue
            text, parts = PROMPT.sub("", raw), []
            while text.endswith("\\") and k < len(block) and block[k] == j + 1:
                parts.append((text[:-1], j))
                j = block[k]
                k += 1
                text = PROMPT.sub("", lines[j].strip())
            found.append(parts + [(text, j)])
    return found


def _is_markdown(rel: str) -> bool:
    return Path(rel).suffix.lower() not in {".rst", ".txt"}


def _doc_commands(lines: list[str], scripts: set[str], mains: set[str], markdown: bool) -> list[tuple]:
    """(0-based line of the program's name, program, text, options, argv, env) for each of the project's
    commands in a doc."""
    shell = _shell_lines(lines, markdown) + [[(a or b, i)] for i, line in enumerate(lines) for a, b in INLINE.findall(line)]
    found = []
    for parts in sorted(shell, key=lambda p: p[0][1]):
        text = " ".join(t for t, _ in parts)
        for words in _simple_commands([(PROMPT.sub("", t.strip()), i) for t, i in parts]):
            names = [w for w, _ in words]
            start = _program(names, scripts, mains)
            if start:
                begin = start[1] - (3 if start[0].startswith("python -m ") else 1)  # where the program's name is
                argv = tuple(_unquote(w) for w in names[begin:])
                env = tuple(tuple(_unquote(w).split("=", 1)) for w in names[:begin] if ASSIGNMENT.match(w))
                command = (words[start[1] - 1][1], start[0], text, _options(words[start[1]:]), argv, env)
                if command not in found:  # the same inline code twice on a line
                    found.append(command)
    return found


def commands(root: Path, scripts: set[str] | None = None, mains: set[str] | None = None) -> list[Command]:
    """Every documented command that runs one of the project's own programs."""
    scripts = console_scripts(root) if scripts is None else scripts
    mains = main_packages(root) if mains is None else mains
    found: list[Command] = []
    if not scripts and not mains:
        return found
    for rel in doc_files(root):
        for line, program, text, options, argv, env in _doc_commands(read_lines(root / rel), scripts, mains,
                                                                     _is_markdown(rel)):
            found.append(Command(rel, line + 1, program, text, tuple((o, i + 1) for o, i in options), argv, env))
    return found


def problems(root: Path, code: Code | None = None) -> list[Problem]:
    """Options documented commands use that the code doesn't declare. A project whose command line isn't
    declared in Python (no options found at all) isn't checked, since every option would look undeclared."""
    code = Code(root) if code is None else code
    if not code.options():
        return []
    declared = code.declared_options()
    found = []
    for command in commands(root):
        for option, line in dict.fromkeys(command.options):
            if option not in declared:
                found.append(Problem(command.file, line, command.program, option,
                                     f"`{command.program}` declares no {option} option in the code"))
    return found


def new_problems(before: Path, after: Path, old: list[Problem] | None = None) -> list[Problem]:
    """Problems a change created: in the docs after the change, and not before it. old: problems(before),
    when they've already been found."""
    seen = {(p.file, p.line, p.option) for p in (problems(before) if old is None else old)}
    return [p for p in problems(after) if (p.file, p.line, p.option) not in seen]

