"""Download each measurement repository at its pinned commit (data/repos.json) into data/repos/.

Only that one commit is fetched, with no history. The commit hash is checked afterwards, so the code and
docs are exactly the pinned ones. The copies are never committed here; each keeps its own license.

    python scripts/fetch_repos.py
"""
from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_DIR = ROOT / "data" / "repos"


def folder(repo: str) -> Path:
    return REPOS_DIR / repo.replace("/", "__")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def fetch(entry: dict) -> str:
    target = folder(entry["repo"])
    if (target / ".git").is_dir() and git(target, "rev-parse", "HEAD") == entry["commit"]:
        return f"{entry['repo']}: already at {entry['commit'][:10]}"
    target.mkdir(parents=True, exist_ok=True)
    git(target, "init", "-q")
    if "origin" not in git(target, "remote"):
        git(target, "remote", "add", "origin", entry["url"])
    git(target, "fetch", "-q", "--depth", "1", "origin", entry["commit"])
    git(target, "checkout", "-q", "--detach", "FETCH_HEAD")
    head = git(target, "rev-parse", "HEAD")
    if head != entry["commit"]:
        raise SystemExit(f"{entry['repo']}: got {head}, pinned {entry['commit']}")
    return f"{entry['repo']}: fetched {head[:10]}"


def main() -> None:
    repos = json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"]
    with ThreadPoolExecutor(6) as pool:
        for line in pool.map(fetch, repos):
            print(line)


if __name__ == "__main__":
    main()
