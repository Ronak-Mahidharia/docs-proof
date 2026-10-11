"""The GitHub Action (action.yml): check a pull request, and report it where GitHub shows it.

- The step's log and the job summary get each doc line the change made wrong, with its proof and the suggested
  fix, and all the suggested fixes as one patch. Text from the docs and the code is shown only inside code blocks,
  fenced so that nothing in it can end the block, so a doc line can't change how the page looks.
- Each flagged line gets a warning annotation on its file.
- With comment: true, one comment on the pull request says the same, and later runs update it rather than add
  more. That needs a token with pull-requests: write. On pull requests from forks GitHub's token is always
  read-only, so the comment is skipped there, with a note.
- The step fails when a doc line is flagged, unless fail-on-findings is false.

It reads the pull request's code and docs, and never runs them.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .check import Finding, check
from .cli import CheckError, commit, export_ref, git, text, toplevel
from .fix import patch

MARKER = "<!-- docs-proof -->"
API = "https://api.github.com"
PART = 30000  # characters of the report, and of the patch, that a comment keeps (GitHub allows 65,536 in all)
WARNINGS = 10  # the warnings GitHub shows for one step; it drops the rest (actions/toolkit, docs/problem-matchers.md)


def fence(body: str, info: str = "") -> str:
    """A fenced code block that nothing inside it can end: its fence is longer than any run of backticks in it."""
    body = body.rstrip("\n")
    longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{info}\n{body}\n{ticks}"


def escape(value: str, prop: bool = False) -> str:
    """A value for a workflow command, such as an annotation's message, or (prop) its file name."""
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return value.replace(":", "%3A").replace(",", "%2C") if prop else value


def annotation(file: str | None, line: int, message: str) -> str:
    """A warning on a file's line, or, for a file outside the workspace (file None), one that names it instead."""
    if file is None:
        return f"::warning title=docs-proof::{escape(message)}"
    return f"::warning file={escape(file, True)},line={line},title=docs-proof::{escape(message)}"


def pull_request_base(repo: Path) -> str:
    """The base of the checked-out pull request: the first parent of the merge commit GitHub checks out."""
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    if len(parents) != 3:
        raise CheckError("no base commit: run it on a pull request, checked out with fetch-depth: 2, or set base")
    return parents[1]


def _cut(body: str, part: int | None) -> str:
    return body if part is None or len(body) <= part else body[:part] + "\n(cut short: all of it is in the job summary)"


def report(findings: list[Finding], log: str, diff: str, part: int | None = None) -> str:
    """The Markdown report for the job summary (all of it) and the comment (at most `part` characters of the
    findings, and of the patch)."""
    if not findings:
        return f"{MARKER}\n### docs-proof\nNo doc line found that this change made wrong.\n"
    lines = [MARKER, f"### docs-proof: {len(findings)} doc line{'s' if len(findings) != 1 else ''} this change "
             "made wrong", "", fence(_cut(log, part), "text")]
    if diff:
        them = "them" if sum(1 for x in findings if x.fix) != 1 else "it"
        lines += ["", "<details><summary>The suggested fixes, as one patch</summary>", "", fence(_cut(diff, part), "diff"), "",
                  "</details>", "", f"To make {them}, run `docs-proof --apply` in your copy of the branch, or save the "
                  "patch and run `git apply`."]
    return "\n".join(lines) + "\n"


def _request(method: str, url: str, token: str, data: dict | None = None) -> tuple[int, object]:
    request = urllib.request.Request(url, method=method, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "docs-proof"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def comment(body: str, flagged: bool, env: dict, request=_request) -> str:
    """Post the report on the pull request, or update the one an earlier run posted. Returns what was done."""
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")) if env.get("GITHUB_EVENT_PATH") else {}
    number = (event.get("pull_request") or {}).get("number")
    if not number:
        return "skipped: this isn't a pull request"
    api, repo, token = env.get("GITHUB_API_URL", API).rstrip("/"), env["GITHUB_REPOSITORY"], env.get("DOCSPROOF_TOKEN", "")
    page = 1
    while True:
        _, comments = request("GET", f"{api}/repos/{repo}/issues/{number}/comments?per_page=100&page={page}", token)
        # only a comment an earlier run made: written by a bot (such as github-actions[bot]), starting with the marker
        old = next((c for c in comments if (c.get("user") or {}).get("type") == "Bot"
                    and str(c.get("body", "")).startswith(MARKER)), None)
        if old or len(comments) < 100:
            break
        page += 1
    if old:
        request("PATCH", f"{api}/repos/{repo}/issues/comments/{old['id']}", token, {"body": body})
        return "updated"
    if not flagged:
        return "skipped: nothing to report"
    request("POST", f"{api}/repos/{repo}/issues/{number}/comments", token, {"body": body})
    return "created"


def main(env: dict | None = None, request=_request, out=sys.stdout) -> int:
    env = dict(os.environ) if env is None else env
    fail = env.get("DOCSPROOF_FAIL", "true").strip().lower() != "false"
    try:
        repo = toplevel(Path(env.get("DOCSPROOF_PATH") or "."))
        base = commit(repo, env["DOCSPROOF_BASE"]) if env.get("DOCSPROOF_BASE") else pull_request_base(repo)
        head = commit(repo, env.get("DOCSPROOF_HEAD") or "HEAD")
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "before", Path(tmp) / "after"
            export_ref(repo, base, before)
            export_ref(repo, head, after)
            findings = check(before, after)
            diff = patch(after, [x.fix for x in findings if x.fix])
    except CheckError as error:
        print(f"::error title=docs-proof::{escape(str(error))}", file=out)
        return 2
    log = text(findings, base[:7], head[:7])
    # The log shows lines from the docs, and GitHub reads a line that starts with "::" as a command (such as
    # "::stop-commands::"), even after spaces. So commands stop while it's printed, until a token no doc can know.
    resume = secrets.token_hex(16)
    print(f"::stop-commands::{resume}\n{log}\n::{resume}::", file=out)
    here, workspace = repo.resolve(), Path(env.get("GITHUB_WORKSPACE") or repo).resolve()
    # annotations name files from the workspace's top: a repository in a subfolder needs its folder in front, and
    # one outside the workspace gets annotations that name the file, so none lands on an unrelated file
    inside = here.is_relative_to(workspace)
    prefix = here.relative_to(workspace).as_posix() + "/" if inside and here != workspace else ""
    for x in findings:
        fixed = f" Suggested fix: {x.fix.new[0].strip()}" if x.fix else ""
        message = " ".join(x.why) + fixed
        print(annotation(prefix + x.file if inside else None, x.line,
                         message if inside else f"{x.file}:{x.line}: {message}"), file=out)
    if len(findings) > WARNINGS:
        more = len(findings) - WARNINGS
        print(f"::notice title=docs-proof::GitHub shows {WARNINGS} warnings for a step, so the other {more} flagged "
              f"line{'s are' if more != 1 else ' is'} only in the job summary and the log.", file=out)
    patch_file = Path(env.get("RUNNER_TEMP") or tempfile.gettempdir()) / "docs-proof.patch"
    patch_file.write_text(diff, encoding="utf-8", newline="")
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(report(findings, log, diff))
    if env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"findings={len(findings)}\nfixes={sum(1 for x in findings if x.fix)}\npatch={patch_file}\n")
    if env.get("DOCSPROOF_COMMENT", "false").strip().lower() == "true":
        try:
            done = comment(report(findings, log, diff, PART), bool(findings), env, request)
            print(f"docs-proof: comment {done}", file=out)
        except urllib.error.HTTPError as error:
            print(f"::notice title=docs-proof::No comment ({error.code}): the token can't write to the pull request. "
                  "On pull requests from forks it never can. The report is in the job summary.", file=out)
    return 1 if findings and fail else 0


if __name__ == "__main__":
    sys.exit(main())
