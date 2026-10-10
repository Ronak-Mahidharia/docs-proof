"""Runs inside the sandbox (scripts/run_sandbox.py starts it). It reads a job as JSON on stdin, applies a
planted change to the repository if the job has one, runs each command with the hooks loaded
(hooks/sitecustomize.py), and writes one JSON line per command.

Each command runs with no shell, no input, an empty home folder of its own, and a time limit. The hooks stop
it right after its parser has read the command line, so what it would do is never done.

The job: {"repo": "/work/<folder>", "env": "/envs/<folder>", "edit": null or a planted change,
          "timeout": seconds, "commands": [{"id": 0, "argv": ["tiny", "--limit", "3"], "env": {}}]}
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).resolve().parent / "hooks"
PYTHON = {"python", "python3", "py"}


def outcome(events: list[dict], exit_code: int | None, timed_out: bool) -> str:
    """accepted: the parser took the command line. rejected: the parser refused it. Otherwise the program ran
    without the hooks stopping it: succeeded, failed, or timed out."""
    if any(e["kind"] == "accepted" for e in events):
        return "accepted"
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return "succeeded"
    if any(e["kind"] in ("unknown_option", "unknown_command", "usage_error") for e in events):
        return "rejected"
    return "failed"


def summary(events: list[dict], exit_code: int | None, timed_out: bool) -> dict:
    """What a run showed, without anything that differs between runs (such as timings or temporary paths)."""
    result = outcome(events, exit_code, timed_out)
    unknown = [] if result == "accepted" else sorted(
        {e.get("option") or e.get("command") for e in events if e["kind"] in ("unknown_option", "unknown_command")})
    # the parser's own complaint, or the unknown word's (for programs, such as yt-dlp, that report it their way)
    messages = [e["message"] for e in events if e["kind"] == "usage_error"] or \
        [e["message"] for e in events if e["kind"] in ("unknown_option", "unknown_command")]
    return {"outcome": result, "exit": None if timed_out else exit_code, "unknown": unknown,
            "message": messages[-1] if messages and result != "accepted" else ""}


def run(command: dict, repo: Path, env_bin: Path, timeout: float) -> dict:
    argv = list(command["argv"])
    program = env_bin / ("python" if argv[0] in PYTHON or argv[0].startswith("python3.") else argv[0])
    if not program.is_file():
        return {"id": command["id"], "outcome": "missing", "exit": None, "unknown": [], "message": ""}
    with tempfile.TemporaryDirectory() as tmp:
        events = Path(tmp) / "events.jsonl"
        home = Path(tmp) / "home"
        home.mkdir()
        env = {"PATH": f"{env_bin}:/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "TMPDIR": tmp,
               "LANG": "C.UTF-8", "TERM": "dumb", "NO_COLOR": "1", "COLUMNS": "100",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(HOOKS), "DOCSPROOF_EVENTS": str(events),
               **command.get("env", {})}
        timed_out, exit_code = False, None
        try:
            done = subprocess.run([str(program), *argv[1:]], cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            exit_code = done.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        lines = events.read_text(encoding="utf-8").splitlines() if events.is_file() else []
    return {"id": command["id"], **summary([json.loads(line) for line in lines], exit_code, timed_out)}


def main() -> None:
    job = json.load(sys.stdin)
    repo = Path(job["repo"])
    if job.get("edit"):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from docsproof.plant import apply
        apply(repo, job["edit"])
    env_bin = Path(job["env"]) / "bin"
    for command in job["commands"]:
        print(json.dumps(run(command, repo, env_bin, job["timeout"])), flush=True)


if __name__ == "__main__":
    main()
