"""Approval before anything changes: the fixes become one patch to read, and a fix pull request is opened only
after a person says yes to that exact patch.

open_pull_request changes no file and runs no command until approve(patch) returns True. If the docs changed
after the patch was made, it stops before changing anything. The commands it runs (git and gh) go through
`run`, so a test can see them without touching a real repository or GitHub.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .fix import Fix, fixed_text, patch

BRANCH = "docs-proof/fixes"
TITLE = "Fix doc lines the code no longer matches"


def summary(fixes: list[Fix]) -> str:
    """The pull request's text: each fix, with why it was made."""
    lines = ["Suggested by docs-proof. Each line was flagged with proof, and the fix was checked before it was "
             "offered.", ""]
    return "\n".join(lines + [f"- `{f.file}`, line {f.line}: {f.reason}" for f in sorted(fixes, key=lambda f: (f.file, f.line))])


def ask(diff: str, read: Callable[[str], str] = input, show: Callable[[str], None] = print) -> bool:
    """Show the patch and ask. Only "y" or "yes" is a yes."""
    show(diff)
    return read("Open a pull request with these fixes? [y/N] ").strip().lower() in ("y", "yes")


def open_pull_request(repo: Path, fixes: list[Fix], approve: Callable[[str], bool], base: str,
                      run: Callable[..., object] = subprocess.run, branch: str = BRANCH, title: str = TITLE) -> bool:
    """Open a pull request with the fixes, only if approve(patch) says yes. Returns whether it was opened."""
    if not fixes:
        return False
    diff = patch(repo, fixes)
    if not approve(diff):
        return False
    if patch(repo, fixes) != diff:
        raise RuntimeError("the docs changed after the patch was made; nothing was changed")
    files = sorted({f.file for f in fixes})
    texts = {rel: fixed_text(repo / rel, [f for f in fixes if f.file == rel]) for rel in files}
    git = ["git", "-C", str(repo)]
    run([*git, "switch", "-c", branch], check=True)
    for rel, text in texts.items():
        (repo / rel).write_bytes(text.encode("utf-8"))
    run([*git, "add", "--", *files], check=True)
    run([*git, "commit", "-m", title, "-m", summary(fixes)], check=True)
    run([*git, "push", "-u", "origin", branch], check=True)
    run(["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", summary(fixes)],
        check=True, cwd=repo)
    return True
