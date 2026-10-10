"""Pin the measurement repositories: each one's current commit and license, and a dev/test split.

Run once; the result (data/repos.json) is committed, so every later run uses the same code and docs.
The repositories are real, popular Python command-line tools and libraries with permissive licenses.
The split is by repository, so no repository is in both halves: sorted by a hash of the name, then dev
and test in turn, so each half gets the same number.

    python scripts/pin_repos.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS = [
    "simonw/sqlite-utils", "simonw/llm", "simonw/datasette", "simonw/shot-scraper", "jazzband/pip-tools",
    "pypa/pipx", "psf/black", "pypa/twine", "cookiecutter/cookiecutter", "mkdocs/mkdocs", "pallets/flask",
    "encode/httpx", "theskumar/python-dotenv", "Kludex/uvicorn", "nvbn/thefuck", "gleitz/howdoi",
    "asottile/pyupgrade", "PyCQA/isort", "hhatto/autopep8", "coveragepy/coveragepy", "sqlfluff/sqlfluff",
    "callowayproject/bump-my-version", "tox-dev/pipdeptree", "tldr-pages/tldr-python-client", "yt-dlp/yt-dlp",
    "PyCQA/bandit", "sqlalchemy/alembic", "Delgan/loguru", "psf/requests", "pypa/hatch",
]
PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "Unlicense"}


def main() -> None:
    pinned = []
    for name in REPOS:
        with urllib.request.urlopen(f"https://api.github.com/repos/{name}", timeout=30) as response:
            info = json.load(response)
        license_id = (info.get("license") or {}).get("spdx_id")
        if license_id not in PERMISSIVE or info.get("archived"):
            raise SystemExit(f"{name}: license {license_id}, archived {info.get('archived')}")
        url = f"https://github.com/{info['full_name']}.git"
        head = subprocess.run(["git", "ls-remote", url, f"refs/heads/{info['default_branch']}"],
                              capture_output=True, text=True, check=True).stdout.split()[0]
        pinned.append({"repo": info["full_name"], "url": url, "commit": head, "license": license_id})
    pinned.sort(key=lambda r: hashlib.sha256(r["repo"].encode()).hexdigest())
    for i, r in enumerate(pinned):
        r["split"] = "dev" if i % 2 == 0 else "test"
    out = {"pinned_on": date.today().isoformat(), "repos": sorted(pinned, key=lambda r: r["repo"].lower())}
    (ROOT / "data" / "repos.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"pinned {len(pinned)} repositories: {sum(r['split'] == 'dev' for r in pinned)} dev, "
          f"{sum(r['split'] == 'test' for r in pinned)} test")


if __name__ == "__main__":
    main()
