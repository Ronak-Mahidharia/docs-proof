"""The docs-proof command: the doc lines a change made wrong, with proof for each one, and the fixes it suggests.

In a git repository:
    docs-proof                        the working tree, against where it branched from the default branch
    docs-proof --base v1.2            against a tag, a branch, or a commit
    docs-proof --head HEAD            what's committed, instead of the working tree
Without git:
    docs-proof --before old/ --after new/
Output:
    --json                            the findings as JSON
    --patch fixes.patch               the suggested fixes as a patch (apply it with git apply)
    --apply                           show the fixes, and make them in the working tree only after a yes
    --model qwen3:8b                  also ask a local model (Ollama) about lines with a changed value

Exit status: 0 when no doc line is flagged, 1 when some are, 2 when the check couldn't run. Nothing is sent
anywhere, except to Ollama on this computer when --model is given. Git is only read: each side of the change is
copied to a temporary folder, and the repository itself changes only after a yes to --apply.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
from pathlib import Path

from .approve import apply_locally, ask
from .check import Finding, check
from .fix import patch

DEFAULT_BRANCHES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")


class CheckError(Exception):
    pass


def git(repo: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    except FileNotFoundError:
        raise CheckError("git isn't installed; give --before and --after folders instead") from None
    if done.returncode:
        raise CheckError(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def toplevel(path: Path) -> Path:
    return Path(git(path, "rev-parse", "--show-toplevel").decode().strip())


def commit(repo: Path, ref: str) -> str:
    """The commit a branch, tag, or commit names."""
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except CheckError:
        raise CheckError(f"no commit, branch, or tag called {ref} in {repo}") from None


def default_base(repo: Path) -> tuple[str, str]:
    """(the commit where HEAD branched from the default branch, a label for it)."""
    for ref in DEFAULT_BRANCHES:
        try:
            commit(repo, ref)
        except CheckError:
            continue
        base = git(repo, "merge-base", "HEAD", ref).decode().strip()
        return base, f"{ref} at {base[:7]}"
    raise CheckError("no default branch (main or master) found; give --base")


def _inside(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe(member: tarfile.TarInfo, path: str) -> tarfile.TarInfo | None:
    """Leave out anything that would land, or point, outside the folder."""
    try:
        return tarfile.data_filter(member, path)
    except tarfile.FilterError:
        return None


def export_ref(repo: Path, ref: str, dest: Path) -> None:
    """The files of a commit, from git archive."""
    dest.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", "--format=tar", ref))) as archive:
        archive.extractall(dest, filter=_safe)


def export_worktree(repo: Path, dest: Path) -> None:
    """The working tree as git sees it: tracked files and new ones that aren't ignored."""
    dest.mkdir(parents=True)
    for rel in git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0"):
        source = repo / rel
        if not rel or not (source.is_file() or source.is_symlink()):
            continue  # deleted but not yet staged, or a submodule
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            if _inside(source, repo):  # a link inside the repository, such as docs/README.md to README.md
                target.symlink_to(os.readlink(source))
        else:
            shutil.copyfile(source, target)


def sides(args: argparse.Namespace, tmp: Path) -> tuple[Path, Path, str, str, Path | None]:
    """(before, after, their labels, and the folder --apply may change, if any)."""
    if args.before or args.after:
        if not (args.before and args.after):
            raise CheckError("give both --before and --after")
        before, after = Path(args.before), Path(args.after)
        for side in (before, after):
            if not side.is_dir():
                raise CheckError(f"{side} isn't a folder")
        return before, after, str(before), str(after), after
    repo = toplevel(Path(args.repo))
    if args.base:
        base, base_label = commit(repo, args.base), args.base
    else:
        base, base_label = default_base(repo)
    before = tmp / "before"
    export_ref(repo, base, before)
    after = tmp / "after"
    if args.head:
        export_ref(repo, commit(repo, args.head), after)
        return before, after, base_label, args.head, None
    export_worktree(repo, after)
    return before, after, base_label, "the working tree", repo


def text(findings: list[Finding], base: str, head: str) -> str:
    if not findings:
        return (f"docs-proof: no doc line found that the change made wrong ({base} to {head}). It checks the names "
                "the change removed, the options documented commands use, and the values it changed.")
    out = [f"docs-proof: {len(findings)} doc line{'s' if len(findings) != 1 else ''} the change made wrong "
           f"({base} to {head})", ""]
    for x in findings:
        out += [f"{x.file}:{x.line}", f"    {x.text.strip()}"]
        out += [f"  why: {why}" for why in x.why]
        out.append(f"  fix: {x.fix.new[0].strip()}" if x.fix else f"  fix: none ({x.left})")
        out.append("")
    fixes = sum(1 for x in findings if x.fix)
    them = "them" if fixes != 1 else "it"
    out.append(f"{fixes} fix{'es' if fixes != 1 else ''} suggested." +
               (f" Save {them} with --patch FILE, or make {them} with --apply (it asks first)." if fixes else ""))
    return "\n".join(out)


def as_json(findings: list[Finding], base: str, head: str) -> dict:
    return {"base": base, "head": head, "findings": [
        {"file": x.file, "line": x.line, "text": x.text, "why": x.why,
         "fix": {"line": x.fix.line, "old": list(x.fix.old), "new": list(x.fix.new), "reason": x.fix.reason}
         if x.fix else None, "left": x.left} for x in findings]}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docs-proof", description="Find the doc lines a change made wrong, with "
                                "proof for each one, and suggest fixes.", epilog="Exit status: 0 when no doc line "
                                "is flagged, 1 when some are, 2 when the check couldn't run.")
    p.add_argument("--repo", default=".", help="the git repository (default: the current folder)")
    p.add_argument("--base", help="the commit, branch, or tag before the change (default: where the current "
                   "branch started from main or master)")
    p.add_argument("--head", help="the commit, branch, or tag after the change (default: the working tree)")
    p.add_argument("--before", help="a folder with the project before the change (instead of git)")
    p.add_argument("--after", help="a folder with the project after the change (instead of git)")
    p.add_argument("--json", action="store_true", help="print the findings as JSON")
    p.add_argument("--patch", metavar="FILE", help="write the suggested fixes to FILE as a patch")
    p.add_argument("--apply", action="store_true", help="show the suggested fixes, and make them only after a yes")
    p.add_argument("--model", help="a local model in Ollama, such as qwen3:8b, to read the lines with a changed value")
    return p


def main(argv: list[str] | None = None, read=input) -> int:
    args = parser().parse_args(argv)
    if args.apply and args.head:
        print("docs-proof: --apply changes the working tree, so it can't be used with --head", file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory() as tmp:
            before, after, base, head, target = sides(args, Path(tmp))
            findings = check(before, after, args.model)
            fixes = [x.fix for x in findings if x.fix]
            print(json.dumps(as_json(findings, base, head), indent=1, ensure_ascii=False) if args.json
                  else text(findings, base, head))
            if args.patch:
                Path(args.patch).write_text(patch(after, fixes), encoding="utf-8", newline="")
            if args.apply and fixes:
                def approve(diff: str) -> bool:
                    try:
                        return ask(diff, read=read, show=lambda shown: print(shown, file=sys.stderr),
                                   question="Make these fixes in the docs?")
                    except EOFError:  # no one to answer
                        return False
                try:
                    done = apply_locally(target, fixes, approve)
                except (RuntimeError, ValueError):
                    raise CheckError("the docs changed while docs-proof ran, so nothing was changed") from None
                print(f"docs-proof: {'made' if done else 'did not make'} the {len(fixes)} "
                      f"fix{'es' if len(fixes) != 1 else ''}", file=sys.stderr)
    except CheckError as error:
        print(f"docs-proof: {error}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as error:
        print(f"docs-proof: Ollama answered {error.code} for --model {args.model}; is it pulled "
              f"(ollama pull {args.model})?", file=sys.stderr)
        return 2
    except urllib.error.URLError as error:
        print(f"docs-proof: couldn't reach Ollama at 127.0.0.1:11434 for --model ({error.reason})", file=sys.stderr)
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
