"""Running the documented commands in the sandbox, and flagging the ones a change makes the program refuse.

The sandbox is a Docker container with no network, no Linux capabilities, a process limit, a memory limit,
and a time limit for each command (sandbox_run.py runs inside it). Only the project's own programs run, with
no shell, so pipes, redirects, and other programs in a documented line never run; a command that needs the
shell to build its words (such as "$(...)") isn't run at all. The hooks stop each program right after it has
read its command line.

A documented command is flagged when, after the change, the program's parser names a word it doesn't know
that it didn't name before, or refuses a command line it took before. The proof is the parser's own message.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from .commands import Command, commands

IMAGE = "docsproof-sandbox"
SANDBOX = ["--rm", "-i", "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--pids-limit", "256", "--memory", "768m", "--cpus", "1", "--tmpfs", "/tmp:rw,size=256m"]
SHELL_ONLY = ("$(", "`", "${")
TIMEOUT = 20  # seconds for each command


def runnable(command: Command) -> str | None:
    """None if the command can be run as documented, or the reason it can't."""
    if not command.argv:
        return "no program"
    if any(part in word for word in command.argv for part in SHELL_ONLY):
        return "its words need the shell"
    return None


Key = tuple[tuple[str, ...], tuple[tuple[str, str], ...]]  # (argv, env)


def documented(root: Path) -> dict[Key, list[Command]]:
    """Each distinct runnable command line, with the places the docs show it."""
    found: dict[Key, list[Command]] = defaultdict(list)
    for command in commands(root):
        if runnable(command) is None:
            found[(command.argv, command.env)].append(command)
    return dict(sorted(found.items()))


def job_commands(keys: list[Key], capture: bool = False) -> list[dict]:
    return [{"id": i, "argv": list(argv), "env": dict(env), **({"capture": True} if capture else {})}
            for i, (argv, env) in enumerate(keys)]


def run_in_sandbox(folder: str, keys: list[Key], edit: dict | None = None, image: str = IMAGE,
                   capture: bool = False) -> dict[Key, dict]:
    """Run the commands in a fresh container for this repository, after applying the planted change if given.
    With capture, each result also has the start of what the command printed."""
    job = {"repo": f"/work/{folder}", "env": f"/envs/{folder}", "edit": edit, "timeout": TIMEOUT,
           "commands": job_commands(keys, capture)}
    done = subprocess.run(["docker", "run", *SANDBOX, image, "python3", "/opt/docsproof/docsproof/sandbox_run.py"],
                          input=json.dumps(job), capture_output=True, text=True, timeout=4 * 3600)
    if done.returncode != 0:
        raise RuntimeError(f"the sandbox failed for {folder} (edit {edit}): {done.stderr[-2000:]}")
    results = [json.loads(line) for line in done.stdout.splitlines()]
    if [r["id"] for r in results] != list(range(len(keys))):
        raise RuntimeError(f"the sandbox returned {len(results)} results for {len(keys)} commands ({folder})")
    return {key: {k: v for k, v in result.items() if k != "id"} for key, result in zip(keys, results)}


# A refusal for something the sandbox doesn't have, or the docs leave out on purpose: a file or folder, a
# required argument or value, a subcommand (the docs name only the program), or the network.
MISSING_INPUT = re.compile(r"does not exist|No such file|can't open|not found|Not a directory|is a directory|"
                           r"not a valid directory path|Missing argument|Missing option|required|"
                           r"the following arguments|requires an argument|expected one argument|requires \d+ arguments|"
                           r"name resolution|^\s*Usage:", re.I)


def missing_input(result: dict) -> bool:
    """Whether the program refused a command line only for an input the sandbox doesn't have."""
    return result["outcome"] == "rejected" and not result["unknown"] and bool(MISSING_INPUT.search(result["message"]))


def refused(before: dict, after: dict) -> list[str] | None:
    """The words the change made the program's parser refuse ([] when it refused the command line for another
    reason), or None if the change didn't make the program refuse it."""
    if after["outcome"] == "accepted":
        return None
    new = sorted(set(after["unknown"]) - set(before["unknown"]))
    if new:
        return new
    if before["outcome"] in ("accepted", "succeeded") and after["outcome"] == "rejected":
        return []
    return None


def flagged_lines(occurrences: list[Command], words: list[str]) -> set[tuple[str, int]]:
    """The doc lines to flag: the line of each refused option, or the program's line."""
    lines = set()
    for command in occurrences:
        hits = {line for option, line in command.options if option in words}
        lines |= {(command.file, line) for line in hits} or {(command.file, command.line)}
    return lines


def proof(argv: tuple[str, ...], after: dict) -> str:
    program = " ".join(argv[:3]) if argv[0].startswith("python") else argv[0]
    reason = after["message"] or ", ".join(after["unknown"]) or after["outcome"]
    return f"After the change, `{program}` refuses this command: {reason}"
