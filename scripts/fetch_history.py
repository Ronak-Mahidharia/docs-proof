"""Download each measurement repository's history (step 6): its pinned commit and every commit before it back to
SINCE, into data/history/, as a bare repository with no files checked out.

The pinned commit is fetched by its hash, with git fetch --shallow-since, so the history is the same on every run.
The window starts at midnight UTC on SINCE, written with its time and time zone: git reads a bare date such as
"2020-01-01" at the current time of day, so the window would move with the clock. A local ref keeps the pinned commit,
the hash is checked afterwards, and the copy records the window it was fetched with. The copies are never committed here; each keeps its own
license.

    python scripts/fetch_history.py
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from failures import explained

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "history"
SINCE = "2020-01-01"
SINCE_GIT = f"{SINCE} 00:00:00 +0000"  # the same moment at any time of day and in any time zone
REF = "refs/heads/pinned"


def place(repo: str) -> Path:
    return HISTORY / (repo.replace("/", "__") + ".git")


def git(target: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(target), *args], capture_output=True, text=True)
    if check and done.returncode:
        said = " ".join(done.stderr.split())  # git's message, on one line
        raise SystemExit(f"{target.name}: git {args[0]} stopped ({said}); run this again to retry")
    return done


def fetch(entry: dict) -> str:
    target = place(entry["repo"])
    if target.is_dir() and git(target, "rev-parse", "--verify", "--quiet", REF, check=False).stdout.strip() == entry["commit"] \
            and git(target, "config", "--get", "docsproof.since", check=False).stdout.strip() == SINCE_GIT:
        return f"{entry['repo']}: already there"
    target.mkdir(parents=True, exist_ok=True)
    git(target, "init", "-q", "--bare")
    if "origin" not in git(target, "remote").stdout.split():
        git(target, "remote", "add", "origin", entry["url"])
    git(target, "fetch", "-q", f"--shallow-since={SINCE_GIT}", "origin", entry["commit"])
    git(target, "update-ref", REF, entry["commit"])
    git(target, "config", "docsproof.since", SINCE_GIT)  # the window this copy was fetched with
    got = git(target, "rev-parse", REF).stdout.strip()
    if got != entry["commit"]:
        raise SystemExit(f"{entry['repo']}: got {got}, pinned {entry['commit']}")
    count = git(target, "rev-list", "--count", REF).stdout.strip()
    return f"{entry['repo']}: {count} commits since {SINCE}"


def main() -> None:
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    with ThreadPoolExecutor(6) as pool:
        for line in pool.map(fetch, repos):
            print(line)


if __name__ == "__main__":
    explained(main)
