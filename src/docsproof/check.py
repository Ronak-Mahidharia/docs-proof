"""Check one change: the doc lines it made wrong, each with its proof, and the rules' fix where they can make one.

It runs the measured checks in the order the plan routes them, with no AI unless a model is named:
- names the change removed that the docs still mention (step 1);
- documented commands that use an option the code no longer declares (step 2, read, not run);
- doc lines that still show a value the change set differently, an option's default or the minimum Python
  version (step 3: a wide search, then, only if a model is named, a local model through Ollama);
- for each flagged line, the rules' fix (step 4), checked before it's offered.
The agent and the sandbox runs aren't here yet: the sandbox needs an environment built for each project.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import model as models
from .commands import new_problems, problems
from .docs import read_lines
from .exact import find
from .fix import Fix, check_shape, renames, rule_fix
from .names import Code, packages
from .values import ValueChange, candidates, value_changes

MODEL_VERSION = "v1"  # the prompt step 3 chose on dev
CONTEXT = 3  # lines shown to the model before and after a candidate line, as in step 3


@dataclass
class Finding:
    file: str
    line: int
    text: str
    why: list[str] = field(default_factory=list)  # the proof from each check that flagged the line
    fix: Fix | None = None
    left: str = ""  # why there's no fix
    names: list[tuple[str, str]] = field(default_factory=list)  # (kind, name) the change removed
    changes: list[ValueChange] = field(default_factory=list)  # values the line may still state


def proof(change: ValueChange) -> str:
    return (f"{models.describe(asdict(change))} The code after the change ({change.file}, line {change.line}): "
            f"`{change.code.strip()}`")


def model_flags(after: Path, change: ValueChange, file: str, line: int, name: str) -> bool:
    """Whether the local model says the line states the old value, quoting the doc line and the code line."""
    lines = read_lines(after / file)
    start = max(0, line - 1 - CONTEXT)
    cand = {"file": file, "line": line, "text": lines[line - 1], "context": lines[start: line + CONTEXT],
            "context_starts": start + 1}
    raw = models.ask(asdict(change), cand, name, MODEL_VERSION)["raw"]
    return models.verdict(raw, asdict(change), cand, MODEL_VERSION) == "flagged"


def check(before: Path, after: Path, model: str | None = None, cache: dict | None = None) -> list[Finding]:
    """The doc lines in `after` that the change from `before` made wrong, in file and line order. A cache dict
    shares the reading of a `before` tree between calls."""
    cache = {} if cache is None else cache
    found: dict[tuple[str, int], Finding] = {}

    def at(file: str, line: int) -> Finding:
        if (file, line) not in found:
            found[(file, line)] = Finding(file, line, read_lines(after / file)[line - 1])
        return found[(file, line)]

    def add(finding: Finding, why: str) -> None:
        if why not in finding.why:
            finding.why.append(why)

    new_code = Code(after)  # read once, for every check
    for f in find(before, after, cache, new_code):  # one finding for each name on a line
        x = at(f.file, f.line)
        x.names.append((f.kind, f.name))
        add(x, f.proof)
    old_code = cache[str(before)][0]
    key = ("problems", str(before))
    if key not in cache:
        cache[key] = problems(before, old_code)
    for p in new_problems(before, after, cache[key], new_code):
        x = at(p.file, p.line)
        if ("option", p.option) not in x.names:
            x.names.append(("option", p.option))
        add(x, p.proof)
    for change in value_changes(before, after, old_code, new_code):
        for c in candidates(after, change):
            if model and not model_flags(after, change, c.file, c.line, model):
                continue
            x = at(c.file, c.line)
            if change not in x.changes:
                x.changes.append(change)
            add(x, proof(change))
    pairs = renames(before, after, cache, new_code) if any(x.names for x in found.values()) else {}
    own = packages(before) | packages(after)
    for x in found.values():
        new, why = rule_fix(x.text, x.names, x.changes, pairs, own)
        if new is None:
            x.left = why
            continue
        fix = Fix(x.file, x.line, (x.text,), (new,), "rule", why)
        problem = check_shape(fix, read_lines(after / x.file), x.line)
        if problem:
            x.left = f"the rules' fix didn't pass its check: {problem}"
        else:
            x.fix = fix
    return sorted(found.values(), key=lambda x: (x.file, x.line))
