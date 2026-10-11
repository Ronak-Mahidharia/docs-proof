"""Build the answer key: planted changes in the pinned repositories, and the doc lines each one makes wrong.

For each repository (data/repos.json, fetched by scripts/fetch_repos.py), with a fixed random seed:
- up to 3 renamed long options, 2 renamed functions or classes, 2 renamed environment variables, and 2 renamed
  files, each one mentioned in the docs (the "name" group: the docs still say the old name);
- up to 2 changed option defaults, where a doc line states the default, and 1 raised minimum Python version,
  where a doc line states it (the "value" group: no name changes, so a search for removed names can't see them);
- 1 renamed private function and 1 renamed option that no doc mentions (the "control" group: nothing is wrong).

Every change is made on a copy first and kept only if it applies cleanly. The expected lines are the doc lines
that mention the old name or state the old value, recorded with a hash of each line, so a later run can check
that the pinned docs are the same. Hand checks (data/hand_check.json) drop wrong expected lines or cases, and
add lines the rules missed; every case they touch is marked as checked by hand.

    python scripts/build_cases.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docsproof.docs import DOC_DIRS, doc_files, mentions, qualifiers, read_lines  # noqa: E402
from docsproof.exact import repo_files  # noqa: E402
from docsproof.names import TEST_DIRS, TEST_FILE, Code, min_python, packages  # noqa: E402
from docsproof.plant import PlantError, apply  # noqa: E402

REPOS_DIR = ROOT / "data" / "repos"
LIMITS = {"rename_option": 3, "rename_identifier": 2, "rename_env_var": 2, "rename_file": 2,
          "change_default": 2, "raise_python": 1, "rename_private": 1, "rename_unmentioned_option": 1}
GROUP = {"rename_option": "name", "rename_identifier": "name", "rename_env_var": "name", "rename_file": "name",
         "change_default": "value", "raise_python": "value", "rename_private": "control",
         "rename_unmentioned_option": "control"}
# Options so common that docs often show them for other tools (pytest --verbose, pip install --upgrade).
OPTION_STOP = {"--help", "--version", "--verbose", "--quiet", "--debug", "--upgrade", "--user", "--force", "--yes",
               "--pre", "--editable", "--index-url", "--extra-index-url", "--requirement", "--python",
               "--no-cache-dir", "--no-deps"}
# Environment variables that belong to the system or other tools, not to the project.
ENV_STOP = {"HOME", "PATH", "USER", "USERNAME", "SHELL", "TERM", "TMPDIR", "TEMP", "TMP", "PWD", "LANG", "LC_ALL",
            "EDITOR", "VISUAL", "PAGER", "CI", "PYTHONPATH", "VIRTUAL_ENV", "NO_COLOR", "FORCE_COLOR", "COLUMNS",
            "LINES", "TZ", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR", "APPDATA",
            "LOCALAPPDATA", "USERPROFILE", "HOMEPATH", "PYTHONIOENCODING", "PYTHONUTF8", "GITHUB_ACTIONS",
            "GITHUB_TOKEN", "TERM_PROGRAM", "DISPLAY", "CONDA_PREFIX", "SYSTEMROOT", "COMSPEC", "WINDIR"}
VERSION_LINE = [
    r"python\s*(?:version\s*)?(?:>=?\s*)?3\.{m}(?!\d)\s*(?:\+|or\s+(?:later|newer|higher|above|greater))",
    r"(?:requires?|requirement|supports?|support\s+for|compatible\s+with|works\s+(?:with|on))\s+"
    r"(?:cpython\s+|python\s*)(?:>=?\s*)?3\.{m}(?!\d)",
    r"python\s*>=\s*3\.{m}(?!\d)",
    r"python\s+3\.{m}(?!\d)\s*(?:to|-|–|through)\s*3\.\d+",
]


def folder(repo: str) -> Path:
    return REPOS_DIR / repo.replace("/", "__")


def line_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def distinctive(name: str) -> bool:
    """A name unlikely to appear in prose by accident: snake_case or CamelCase, at least 6 characters."""
    return not name.startswith("_") and len(name) >= 6 and ("_" in name or sum(c.isupper() for c in name) >= 2)


def renamed(path: str) -> str:
    stem, dot, suffix = path.rpartition(".")
    return f"{stem}2.{suffix}" if dot and "/" not in suffix else f"{path}2"


def number(value) -> str:
    new = value * 2 if value else 1
    return repr(float(new)) if isinstance(value, float) else str(int(new))


def default_lines(root: Path, docs: list[str], option: str, value) -> list:
    literal = re.compile(rf"(?<![\w.]){re.escape(repr(value))}(?![\w.])")
    return [m for m in mentions(root, option, "option", docs) if literal.search(m.text) and "default" in m.text.lower()]


def python_lines(root: Path, docs: list[str], minor: int) -> list:
    patterns = [re.compile(p.format(m=minor), re.I) for p in VERSION_LINE]
    found = []
    for rel in docs:
        for n, text in enumerate(read_lines(root / rel), 1):
            if any(p.search(text) for p in patterns) or (re.search(rf"3\.{minor}\+", text) and "python" in text.lower()):
                found.append((rel, n, text))
    return found


def candidates(root: Path) -> dict[str, list[tuple[dict, list]]]:
    """Possible cases by kind: (edit, expected [(file, line, text)])."""
    docs = doc_files(root)
    code = Code(root)
    out: dict[str, list] = {k: [] for k in LIMITS}
    options = code.options()
    for option in sorted(options):
        if option in OPTION_STOP:
            continue
        lines = [(m.file, m.line, m.text) for m in mentions(root, option, "option", docs)]
        kind = "rename_option" if lines else "rename_unmentioned_option"
        out[kind].append(({"kind": kind, "old": option, "new": f"{option}2"}, lines))
    own = packages(root)
    public = code.public_names()
    for name in sorted(code.defined_names()):
        # A mention under another package's name ("jinja2_time.TimeExtension") is about that package's object.
        lines = [(m.file, m.line, m.text) for m in mentions(root, name, "identifier", docs)
                 if any(q is None or q in own for q in qualifiers(m.text, name))]
        if distinctive(name) and name in public and lines:
            out["rename_identifier"].append(({"kind": "rename_identifier", "old": name, "new": f"{name}2"}, lines))
        elif name.startswith("_") and not name.startswith("__") and not lines:
            out["rename_private"].append(({"kind": "rename_private", "old": name, "new": f"{name}2"}, []))
    for name in sorted(code.env_vars()):
        lines = [(m.file, m.line, m.text) for m in mentions(root, name, "identifier", docs)]
        if name not in ENV_STOP and lines:
            out["rename_env_var"].append(({"kind": "rename_env_var", "old": name, "new": f"{name}2"}, lines))
    for path in sorted(repo_files(root)):
        parts = path.split("/")
        if "/" not in path or parts[0] in DOC_DIRS or path.startswith(".") or TEST_DIRS & set(parts[:-1]) \
                or TEST_FILE.match(parts[-1]):
            continue  # tutorials often name test files such as tests/conftest.py for the reader's own project
        lines = [(m.file, m.line, m.text) for m in mentions(root, path, "path", docs)]
        if lines:
            out["rename_file"].append(({"kind": "rename_file", "old": path, "new": renamed(path)}, lines))
    declared = {o: len(w) for o, w in options.items()}
    for option, where, const in code.option_defaults():
        if declared.get(option) != 1:
            continue  # declared more than once: a doc line could be about another command's default
        lines = [(m.file, m.line, m.text) for m in default_lines(root, docs, option, const.value)]
        if lines:
            edit = {"kind": "change_default", "option": option, "file": where.file, "line": where.line,
                    "old": repr(const.value), "new": number(const.value)}
            out["change_default"].append((edit, lines))
    py = min_python(root)
    if py:
        lines = python_lines(root, docs, py[1])
        if lines:
            out["raise_python"].append(({"kind": "raise_python", "file": py[0], "old": py[1], "new": py[1] + 2}, lines))
    return out


def clone(src: Path, dst: Path) -> None:
    """A copy of the repository without its .git folder (an instant copy-on-write clone on macOS). Links stay links
    on both systems, as cp -R keeps them, since a doc reached through a link is read only where it really is."""
    if sys.platform == "darwin":
        subprocess.run(["cp", "-c", "-R", str(src), str(dst)], check=True)
        shutil.rmtree(dst / ".git", ignore_errors=True)
    else:
        shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(".git"))


def plants_cleanly(root: Path, edit: dict) -> str | None:
    """None if the change applies cleanly on a copy, or the reason it doesn't."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "repo"
        clone(root, copy)
        try:
            apply(copy, edit)
        except (PlantError, ValueError, OSError) as error:
            return str(error)[:200]
        if edit["kind"] in ("rename_option", "rename_unmentioned_option") and edit["old"] in Code(copy).options():
            return "the old option is still declared"
        if edit["kind"] in ("rename_identifier", "rename_private") and edit["old"] in Code(copy).defined_names():
            return "the old name is still defined"
        if edit["kind"] == "rename_env_var" and edit["old"] in Code(copy).env_vars():
            return "the old variable is still read"
        if edit["kind"] == "raise_python" and min_python(copy) != (edit["file"], edit["new"]):
            return "the minimum Python version didn't change"
    return None


def main() -> None:
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    hand_path = ROOT / "data" / "hand_check.json"
    hand = json.loads(hand_path.read_text(encoding="utf-8")) if hand_path.is_file() else {}
    drop_cases, drop_lines = set(hand.get("drop_cases", [])), {tuple(x) for x in hand.get("drop_lines", [])}
    add_lines: dict[str, list[tuple[str, int]]] = {}
    for case_id, file, line in hand.get("add_lines", []):
        add_lines.setdefault(case_id, []).append((file, line))
    cases, skipped = [], []
    for entry in repos:
        root = folder(entry["repo"])
        rng = random.Random(f"{entry['repo']}@{entry['commit']}")
        found = candidates(root)
        for kind, limit in LIMITS.items():
            pool = found[kind][:]
            rng.shuffle(pool)
            taken = 0
            for edit, lines in pool:
                if taken == limit:
                    break
                reason = plants_cleanly(root, edit)
                if reason:
                    skipped.append({"repo": entry["repo"], "edit": edit, "reason": reason})
                    continue
                taken += 1
                case_id = f"{entry['repo']}:{kind}:{taken}"
                kept = [(f, n, t) for f, n, t in lines if (case_id, f, n) not in drop_lines]
                for f, n in add_lines.get(case_id, []):
                    if (f, n) not in {(a, b) for a, b, _ in kept}:
                        kept.append((f, n, read_lines(root / f)[n - 1]))
                expected = [{"file": f, "line": n, "sha256": line_hash(t)} for f, n, t in sorted(kept)]
                if case_id in drop_cases:
                    continue
                cases.append({"id": case_id, "repo": entry["repo"], "split": entry["split"], "kind": kind,
                              "group": GROUP[kind], "edit": edit, "expected": expected,
                              "checked": "hand" if case_id in hand.get("checked_cases", []) else "rule"})
    ids = {c["id"] for c in cases}
    unused = [x for x in [*hand.get("drop_lines", []), *hand.get("add_lines", [])] if x[0] not in ids | drop_cases]
    unused += [x for x in hand.get("checked_cases", []) if x not in ids and x not in drop_cases]
    if unused:
        raise SystemExit(f"hand checks name cases that no longer exist: {unused}")
    with (ROOT / "data" / "cases.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps(case, ensure_ascii=False) + "\n")
    (ROOT / "data" / "skipped.json").write_text(json.dumps(skipped, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    by_kind: dict[str, int] = {}
    for case in cases:
        by_kind[f"{case['split']}:{case['kind']}"] = by_kind.get(f"{case['split']}:{case['kind']}", 0) + 1
    print(f"{len(cases)} cases ({sum(c['split'] == 'dev' for c in cases)} dev, {sum(c['split'] == 'test' for c in cases)} test), "
          f"{sum(len(c['expected']) for c in cases)} expected lines, {len(skipped)} changes skipped")
    for key in sorted(by_kind):
        print(f"  {key}: {by_kind[key]}")


if __name__ == "__main__":
    main()
