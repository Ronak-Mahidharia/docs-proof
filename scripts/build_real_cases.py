"""Step 6: a second answer key, from the repositories' real history since 2020 (scripts/fetch_history.py).

It starts from the doc fixes: a later commit D that removed a code reference from a doc line. The references are
long options (--name), environment variables (NAME_WITH_UNDERSCORE), names in backticks (`name` or `name()`),
and file paths (dir/name.py). Such a fix counts when:
- the reference was already gone from the code just before D, so the doc line was out of date, and
- an earlier commit C is where it left the code: the reference is in the code just before C and not after.
The code is the Python files outside the top-level tests and docs folders, and a reference counts only where
Python's own parser sees it: as a name (a variable, attribute, parameter, keyword, definition, or import), or as
a string that is exactly the reference, the way options are declared. A comment or a longer string doesn't
count, and neither do the project's own package names or the literals true, false, none, and null.

The case is the change C, and its expected lines are the doc lines in C's tree that D later fixed: lines whose text
is exactly a line D removed, in the same file, mentioning the reference, and that were there before C too (C left
them as they were). A line that changed between C and D can't be matched, so it's left out and counted. Every case
mined is kept (data/real_mined.jsonl) and checked by hand (data/hand_check.json, "real_history"), and the key keeps
the real ones (data/real_cases.jsonl). Nothing here uses docs-proof's own checks, so the key doesn't lean on what
docs-proof finds.

    python scripts/build_real_cases.py              # all 30 repositories: the key, after the hand check
    python scripts/build_real_cases.py --split dev  # one split, to look at it before checking it
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from docsproof.docs import is_doc, split_lines, token_pattern  # noqa: E402
from fetch_history import REF, SINCE, place  # noqa: E402

CODE = ["*.py", ":(exclude)tests/*", ":(exclude)test/*", ":(exclude)docs/*", ":(exclude)doc/*"]
OPTION = re.compile(r"(?<![\w-])--[A-Za-z0-9][\w-]*")
ENV = re.compile(r"(?<![\w$])[A-Z][A-Z0-9]*_[A-Z0-9_]*[A-Z0-9](?!\w)")
TICKED = re.compile(r"`([A-Za-z_][\w.]*?)(?:\(\))?`")
PATH = re.compile(r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+\.(?:py|toml|cfg|ini|json|yaml|yml|txt|sh)(?![\w/])")
KIND = {"option": "option", "env": "identifier", "identifier": "identifier", "path": "path"}
# Old code can make the parser warn (such as "\\s" in a plain string) and is still read; set once, before any thread.
warnings.filterwarnings("ignore", category=SyntaxWarning)
LITERALS = {"true", "false", "none", "null"}


def file_lines(repo: Path, commit: str, file: str) -> list[str] | None:
    """A file's lines at a commit, read and split as docs-proof reads a doc (docs.read_lines), or None if it isn't
    there."""
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{file}"], capture_output=True)
    return split_lines(shown.stdout.decode("utf-8", errors="replace")) if shown.returncode == 0 else None


class History:
    """One repository's history, read with git."""

    def __init__(self, path: Path):
        self.path = path
        self._in_code: dict[tuple[str, str, str], bool] = {}

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, text=True, errors="replace")

    def parent(self, commit: str) -> str | None:
        """The first parent, or None at the start of the fetched history."""
        return self.git("rev-parse", "--verify", "--quiet", f"{commit}^1").stdout.strip() or None

    def in_code(self, commit: str, kind: str, name: str) -> bool:
        """Whether the code at a commit has the reference (a path: whether the file is there). It counts only where
        Python itself sees the name, in a file's syntax tree, so a comment or a longer string doesn't count."""
        key = (commit, kind, name)
        if key not in self._in_code:
            if kind == "path":
                self._in_code[key] = self.git("cat-file", "-e", f"{commit}:{name}").returncode == 0
            else:
                found = self.git("grep", "-l", "-F", "-e", name, commit, "--", *CODE).stdout.split("\n")
                self._in_code[key] = any(occurs(self.git("show", f"{f}").stdout, kind, name) for f in found if f)
        return self._in_code[key]

    def removal(self, before: str, kind: str, name: str) -> str | None:
        """The latest first-parent commit, up to `before`, where the reference left the code."""
        paths = [name] if kind == "path" else CODE
        for commit in self.git("log", "--first-parent", "--format=%H", f"-S{name}", before, "--", *paths).stdout.split():
            parent = self.parent(commit)
            if parent and self.in_code(parent, kind, name) and not self.in_code(commit, kind, name):
                return commit
        return None

    def lines(self, commit: str, file: str) -> list[str] | None:
        """A file's lines at a commit, split as docs-proof splits them, or None if it isn't there."""
        return file_lines(self.path, commit, file)

    def day(self, commit: str) -> str:
        return self.git("log", "-1", "--format=%cs", commit).stdout.strip()

    def own(self, commit: str) -> set[str]:
        """The names the project's own code goes by at a commit: its top-level packages and modules."""
        found = set()
        for rel in self.git("ls-tree", "-r", "--name-only", commit).stdout.split("\n"):
            parts = rel.split("/")
            if rel.endswith(".py") and not {"tests", "test", "docs", "doc"} & set(parts[:-1]):
                parts = parts[1:] if parts[0] == "src" and len(parts) > 1 else parts
                found.add(parts[0].removesuffix(".py"))
        return found


def occurs(source: str, kind: str, name: str) -> bool:
    """Whether a Python file has the reference: as a string that is exactly it (how options are declared), or, for
    a name, as a variable, attribute, parameter, keyword, definition, or import."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == name:
            return True
        if kind == "option":
            continue
        if (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name) \
                or (isinstance(node, (ast.arg, ast.keyword)) and node.arg == name) \
                or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name) \
                or (isinstance(node, ast.alias) and name in (node.name.split(".")[-1], node.asname)):
            return True
    return False


def references(text: str) -> set[tuple[str, str]]:
    found = {("option", t) for t in OPTION.findall(text)}
    found |= {("env", t) for t in ENV.findall(text)}
    found |= {("identifier", t.split(".")[-1]) for t in TICKED.findall(text) if len(t.split(".")[-1]) >= 4}
    found |= {("path", t) for t in PATH.findall(text)}
    return found


def hunks(h: History, before: str, commit: str, files: list[str]) -> list[dict]:
    """Every hunk of a commit's doc changes, read in full: its file, and the lines it removed and added."""
    out = h.git("diff", "-U0", "--no-color", "--no-renames", before, commit, "--", *files).stdout
    file, found, header = None, [], False
    for line in out.split("\n"):
        if line.startswith("diff --git "):  # a file's header, up to its first hunk: a removed "-- x" isn't "--- a/"
            file, header = None, True
        elif header and line.startswith("+++ "):
            file = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            header = False
            found.append({"file": file, "removed": [], "added": []})
        elif not header and found and line.startswith("-"):
            found[-1]["removed"].append(line[1:])
        elif not header and found and line.startswith("+"):
            found[-1]["added"].append(line[1:])
    return [x for x in found if x["file"]]


def doc_fixes(h: History, pinned: str, funnel: dict) -> list[dict]:
    """The later doc fixes: a reference removed from a doc line after it had left the code."""
    found = []
    for commit in h.git("rev-list", "--first-parent", "--reverse", f"--since={SINCE}", pinned).stdout.split():
        before = h.parent(commit)
        if not before:
            continue
        files = [f for f in h.git("diff", "--name-only", "--no-renames", before, commit).stdout.split("\n")
                 if f and is_doc(f)]
        if not files:
            continue
        funnel["commits_touching_docs"] += 1
        own = h.own(before)
        for hunk in hunks(h, before, commit, files):
            gone = set().union(set(), *map(references, hunk["removed"])) - set().union(set(), *map(references, hunk["added"]))
            funnel["references_removed"] += len(gone)
            for kind, name in sorted(gone):
                if name in own or name.lower() in LITERALS:
                    continue  # the project itself, or a literal such as `false`, not a reference to its code
                if h.in_code(before, kind, name):
                    continue
                funnel["already_gone"] += 1
                cause = h.removal(before, kind, name)
                if cause is None:
                    continue
                funnel["with_a_removal_commit"] += 1
                pattern = token_pattern(name, KIND[kind])
                found.append({"cause": cause, "fix": commit, "kind": kind, "name": name, "file": hunk["file"],
                              "removed": [line for line in hunk["removed"] if pattern.search(line)]})
    return found


def line_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build(entry: dict, h: History | None = None) -> tuple[list[dict], dict]:
    """The cases of one repository, and its funnel of counts."""
    h = h or History(place(entry["repo"]))
    pinned = h.git("rev-parse", REF).stdout.strip()
    if pinned != entry["commit"]:
        raise SystemExit(f"{entry['repo']}: the history isn't at the pinned commit; run scripts/fetch_history.py")
    funnel = dict.fromkeys(("commits_touching_docs", "references_removed", "already_gone", "with_a_removal_commit",
                            "lines_changed_before_the_fix", "lines_new_in_the_change", "expected_lines"), 0)
    by_cause: dict[str, dict] = {}
    for fix in doc_fixes(h, pinned, funnel):
        lines = h.lines(fix["cause"], fix["file"]) or []
        hits = [n for n, text in enumerate(lines, 1) if text in fix["removed"]]
        if not hits:
            funnel["lines_changed_before_the_fix"] += 1
            continue
        # a line the change wrote itself isn't one it left out of date: it must be there before the change too
        earlier = set(h.lines(h.parent(fix["cause"]), fix["file"]) or [])
        kept = [n for n in hits if lines[n - 1] in earlier]
        funnel["lines_new_in_the_change"] += len(hits) - len(kept)
        hits = kept
        if not hits:
            continue
        case = by_cause.setdefault(fix["cause"], {"repo": entry["repo"], "split": entry["split"], "commit": fix["cause"],
                                                  "parent": h.parent(fix["cause"]), "date": h.day(fix["cause"]),
                                                  "expected": []})
        for n in hits:
            if not any((e["file"], e["line"]) == (fix["file"], n) for e in case["expected"]):
                fixed = h.day(fix["fix"])
                case["expected"].append({
                    "file": fix["file"], "line": n, "sha256": line_hash(lines[n - 1]), "kind": fix["kind"],
                    "name": fix["name"], "fixed_by": fix["fix"], "fixed_on": fixed,
                    "days": (date.fromisoformat(fixed) - date.fromisoformat(case["date"])).days})
    cases = sorted(by_cause.values(), key=lambda c: (c["date"], c["commit"]))
    for case in cases:
        case["expected"].sort(key=lambda e: (e["file"], e["line"]))
        case["id"] = f"{entry['repo']}@{case['commit'][:10]}"
    funnel["expected_lines"] = sum(len(c["expected"]) for c in cases)
    return cases, funnel


def checked(cases: list[dict]) -> tuple[list[dict], dict]:
    """The key: the mined cases the hand check found real, without the lines it dropped. Stops if a mined case
    hasn't been checked, or a check names a case or line that isn't mined any more."""
    hand = json.loads((ROOT / "data" / "hand_check.json").read_text(encoding="utf-8"))["real_history"]
    verdicts = {c["case"]: c["verdict"] for c in hand["cases"]}
    mined = {c["id"] for c in cases}
    if mined != set(verdicts):
        raise SystemExit(f"Check these real-history cases by hand first: {sorted(mined - set(verdicts))}; "
                         f"no longer mined: {sorted(set(verdicts) - mined)}")
    drop = {tuple(x) for x in hand["drop_lines"]}
    lines = {(c["id"], e["file"], e["line"]) for c in cases for e in c["expected"]}
    if drop - lines:
        raise SystemExit(f"Dropped lines that aren't mined any more: {sorted(drop - lines)}")
    key = []
    for case in cases:
        if verdicts[case["id"]] == "real":
            kept = [e for e in case["expected"] if (case["id"], e["file"], e["line"]) not in drop]
            key.append({**case, "expected": kept})
    counts = {split: {"mined_cases": sum(c["split"] == split for c in cases),
                      "mined_lines": sum(len(c["expected"]) for c in cases if c["split"] == split),
                      "cases": sum(c["split"] == split for c in key),
                      "lines": sum(len(c["expected"]) for c in key if c["split"] == split)} for split in ("dev", "test")}
    return key, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test"],
                        help="mine only one split, to look at it (writes data/real_cases.<split>.jsonl, unchecked)")
    args = parser.parse_args()
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    repos = [r for r in repos if not args.split or r["split"] == args.split]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(build, repos))
    cases = sorted((c for found, _ in results for c in found), key=lambda c: c["id"])
    if args.split:
        with (ROOT / "data" / f"real_cases.{args.split}.jsonl").open("w", encoding="utf-8") as out:
            for case in cases:
                out.write(json.dumps(case, ensure_ascii=False) + "\n")
        print(f"{len(cases)} cases, {sum(len(c['expected']) for c in cases)} lines mined, not yet checked by hand")
        return
    with (ROOT / "data" / "real_mined.jsonl").open("w", encoding="utf-8") as out:  # every case mined, unchecked
        for case in cases:
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
    key, counts = checked(cases)
    with (ROOT / "data" / "real_cases.jsonl").open("w", encoding="utf-8") as out:
        for case in key:
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
    funnel = {entry["repo"]: f for entry, (_, f) in zip(repos, results)}
    (ROOT / "data" / "results" / "real-mining.json").write_text(
        json.dumps({"since": SINCE, "funnel": funnel, "hand_check": counts}, indent=1) + "\n", encoding="utf-8")
    for split, c in counts.items():
        print(f"{split}: {c['mined_cases']} cases mined, {c['cases']} real after the hand check, {c['lines']} lines")


if __name__ == "__main__":
    main()
