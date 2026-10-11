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
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import urllib.error
from pathlib import Path

from .approve import apply_locally, ask
from .check import Finding, check
from .docs import inside, readable
from .fix import patch
from .model import OLLAMA

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
    """The top folder of the git repository a folder is in."""
    if not path.is_dir():
        raise CheckError(f"{path} isn't a folder")
    try:
        return Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel").strip()))
    except CheckError as error:
        if "not a git repository" in str(error):
            raise CheckError(f"{path} isn't in a git repository") from None
        raise


def commit(repo: Path, ref: str) -> str:
    """The commit a branch, tag, or commit names."""
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()
    except CheckError:
        raise CheckError(f"no commit, branch, or tag called {ref} in {repo}") from None


def default_base(repo: Path) -> tuple[str, str]:
    """(the commit where HEAD branched from the default branch, a label for it)."""
    try:
        head = commit(repo, "HEAD")
    except CheckError:
        raise CheckError(f"{repo} has no commit yet, so there's nothing to compare with") from None
    for ref in DEFAULT_BRANCHES:
        try:
            commit(repo, ref)
        except CheckError:
            continue
        try:
            base = git(repo, "merge-base", head, ref).decode().strip()
        except CheckError:  # git says nothing when two histories have no commit in common
            raise CheckError(f"HEAD and {ref} have no commit in common; give --base") from None
        return base, f"{ref} at {base[:7]}"
    raise CheckError("no default branch (main or master) found; give --base")


def blobs(repo: Path, oids: list[str]) -> dict[str, bytes]:
    """The contents of git objects, read with one `git cat-file --batch`."""
    wanted = list(dict.fromkeys(oids))
    if not wanted:
        return {}
    try:
        done = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], capture_output=True,
                              input="".join(f"{oid}\n" for oid in wanted).encode())
    except FileNotFoundError:
        raise CheckError("git isn't installed; give --before and --after folders instead") from None
    out, at, found = done.stdout, 0, {}
    for oid in wanted:
        end = out.find(b"\n", at)
        header = out[at:end].split()
        if done.returncode or len(header) != 3:
            raise CheckError(f"git cat-file couldn't read {oid}: {done.stderr.decode('utf-8', 'replace').strip()}")
        size = int(header[2])
        found[oid] = out[end + 1: end + 1 + size]
        at = end + 1 + size + 1
    return found


def _write(dest: Path, rel: str, mode: bytes, content: bytes) -> None:
    """One file of the project, in the folder: a link only if it points inside the folder, and nothing whose
    name isn't UTF-8 (docs.readable) or that would land outside it."""
    target = dest / rel
    if not readable(rel) or not inside(target, dest):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == b"120000":  # a link, such as docs/README.md to ../README.md
        link = os.fsdecode(content)
        if inside(target.parent / link, dest):
            target.symlink_to(link)
    else:
        target.write_bytes(content)


def export_ref(repo: Path, ref: str, dest: Path) -> None:
    """The files of a commit, as git stores them. Not with git archive, which leaves out files .gitattributes
    marks export-ignore and fills in export-subst ones; submodules are left out."""
    dest.mkdir(parents=True)
    entries = []
    for item in git(repo, "ls-tree", "-r", "-z", "--full-tree", ref).split(b"\0"):
        if item:
            meta, _, name = item.partition(b"\t")
            mode, kind, oid = meta.split()
            if kind == b"blob":
                entries.append((os.fsdecode(name), mode, oid.decode()))
    contents = blobs(repo, [oid for _, _, oid in entries])
    for rel, mode, oid in entries:
        _write(dest, rel, mode, contents[oid])


def export_worktree(repo: Path, dest: Path) -> None:
    """The working tree as git sees it: tracked files and new ones that aren't ignored. A file a sparse checkout
    leaves out of the folder is taken from the index, where git keeps it."""
    dest.mkdir(parents=True)
    tracked, sparse = [], {}
    for item in git(repo, "ls-files", "-z", "-t", "--stage").split(b"\0"):
        if item:
            meta, _, name = item.partition(b"\t")
            tag, mode, oid, _ = meta.split()
            rel = os.fsdecode(name)
            if tag == b"S":
                sparse[rel] = (mode, oid.decode())
            elif mode != b"160000":  # not a submodule
                tracked.append(rel)
    others = [os.fsdecode(name) for name in git(repo, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0") if name]
    contents = blobs(repo, [oid for _, oid in sparse.values()])
    for rel, (mode, oid) in sparse.items():
        _write(dest, rel, mode, contents[oid])
    for rel in dict.fromkeys(tracked + others):  # a file with a merge conflict is listed once for each side
        source = repo / rel
        if source.is_symlink():
            _write(dest, rel, b"120000", os.fsencode(os.readlink(source)))
        elif source.is_file():  # not deleted, and not yet staged
            _write(dest, rel, b"100644", source.read_bytes())


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


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def shown(value: str) -> str:
    """Text from the docs or the code, safe to print: a control character, which a terminal would act on, is
    shown as an escape, such as \\x1b."""
    return CONTROL.sub(lambda m: f"\\x{ord(m.group()):02x}", value)


def text(findings: list[Finding], base: str, head: str, hint: bool = True) -> str:
    """The report a person reads. hint: say how to save or make the fixes (not when the command already does)."""
    if not findings:
        return (f"docs-proof: no doc line found that the change made wrong ({shown(base)} to {shown(head)}). It "
                "checks the names the change removed, the options documented commands use, and the values it changed.")
    out = [f"docs-proof: {len(findings)} doc line{'s' if len(findings) != 1 else ''} the change made wrong "
           f"({shown(base)} to {shown(head)})", ""]
    for x in findings:
        out += [shown(f"{x.file}:{x.line}"), shown(f"    {x.text.strip()}")]
        out += [shown(f"  why: {why}") for why in x.why]
        out.append(shown(f"  fix: {x.fix.new[0].strip()}" if x.fix else f"  fix: none ({x.left})"))
        out.append("")
    fixes = sum(1 for x in findings if x.fix)
    them = "them" if fixes != 1 else "it"
    out.append(f"{fixes} fix{'es' if fixes != 1 else ''} suggested." +
               (f" Save {them} with --patch FILE, or make {them} with --apply (it asks first)." if fixes and hint else ""))
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
                  else text(findings, base, head, hint=not (args.patch or args.apply)))
            if args.patch:
                try:
                    Path(args.patch).write_text(patch(after, fixes), encoding="utf-8", newline="")
                except OSError as error:
                    raise CheckError(f"couldn't write the patch to {args.patch} ({error.strerror})") from None
                them = "them" if len(fixes) != 1 else "it"
                print(f"docs-proof: wrote {len(fixes)} fix{'es' if len(fixes) != 1 else ''} to {args.patch}" +
                      (f"; make {them} with `git apply {args.patch}` in the project's top folder" if fixes else ""),
                      file=sys.stderr)
            if args.apply and fixes:
                def question(prompt: str) -> str:  # with the patch, on stderr, so --json's output stays JSON
                    print(prompt, end="", file=sys.stderr, flush=True)
                    return read("")

                def approve(diff: str) -> bool:
                    try:
                        return ask(diff, read=question, show=lambda shown: print(shown, file=sys.stderr),
                                   question="Make these fixes in the docs?")
                    except EOFError:  # no one to answer
                        return False
                try:
                    done = apply_locally(target, fixes, approve)
                except RuntimeError:  # the patch was no longer the one approved
                    raise CheckError("the docs changed while docs-proof ran, so nothing was changed") from None
                except ValueError as error:  # a fix that no longer matches its doc, or a file it may not change
                    raise CheckError(f"nothing was changed: {error}") from None
                print(f"docs-proof: {'made' if done else 'did not make'} the {len(fixes)} "
                      f"fix{'es' if len(fixes) != 1 else ''}", file=sys.stderr)
    except CheckError as error:
        print(f"docs-proof: {error}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as error:
        print(f"docs-proof: Ollama answered {error.code} for --model {args.model}" +
              (f"; is it pulled (ollama pull {args.model})?" if error.code == 404 else ""), file=sys.stderr)
        return 2
    except urllib.error.URLError as error:
        print(f"docs-proof: couldn't reach Ollama at {OLLAMA} for --model ({error.reason})", file=sys.stderr)
        return 2
    except Exception as error:  # a bug: exit 2, the check couldn't run, not 1, which says lines were flagged
        traceback.print_exc()
        print(f"docs-proof: the check stopped on an error it doesn't expect ({type(error).__name__}: {error}). "
              "Please report it, with the command you ran.", file=sys.stderr)
        return 2
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
