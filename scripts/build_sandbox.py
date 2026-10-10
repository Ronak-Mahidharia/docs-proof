"""Builds the sandbox image: Python 3.14 with each pinned repository installed in an environment of its own,
so its documented commands can be run with no network. Building needs the network, to install each project's
dependencies from PyPI; running never does.

    python scripts/build_sandbox.py             # build with the versions pinned in data/sandbox/pins/
    python scripts/build_sandbox.py --resolve   # choose the versions afresh (as of RESOLVED_ON) and pin them

The image holds no secrets and nothing from this computer except the pinned repositories and this project's
own code. Remove it with: docker image rm docsproof-sandbox
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_cases import folder  # noqa: E402
from docsproof.commands import console_scripts, main_packages  # noqa: E402

IMAGE = "docsproof-sandbox"
BASE = "python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170"
UV = "0.12.24"
RESOLVED_ON = "2026-10-10"  # uv's --exclude-newer: no release after this day is chosen
SANDBOX = ROOT / "data" / "sandbox"
PINS = SANDBOX / "pins"
# Extras a documented program needs: the httpx and dotenv command lines, and black's blackd server.
EXTRAS = {"encode/httpx": "cli", "theskumar/python-dotenv": "cli", "psf/black": "d"}
SKIP = {"tox-dev/pipdeptree": "its command line is written in Rust",
        "nvbn/thefuck": "it doesn't run on Python 3.14 at this commit: it imports distutils, removed in Python 3.12"}


def sandboxed(repos: list[dict]) -> list[dict]:
    """The repositories with a command line of their own to run."""
    out = []
    for entry in repos:
        root = folder(entry["repo"])
        if entry["repo"] not in SKIP and (console_scripts(root) or main_packages(root)):
            out.append(entry)
    return out


def dockerfile(repos: list[dict], resolve: bool) -> str:
    lines = [f"FROM {BASE}",
             f"RUN pip install --no-cache-dir uv=={UV} && useradd --create-home --uid 10001 sandbox",
             "ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \\",
             "    SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 PBR_VERSION=0.0.0 COVERAGE_DISABLE_EXTENSION=1",
             "COPY data/sandbox/pins /pins"]
    for entry in repos:
        name = folder(entry["repo"]).name
        target = f"/work/{name}" + (f"[{EXTRAS[entry['repo']]}]" if entry["repo"] in EXTRAS else "")
        python = f"/envs/{name}/bin/python"
        lines.append(f"COPY --chown=10001:10001 data/repos/{name} /work/{name}")
        if resolve:
            install = f'uv pip install --python {python} --exclude-newer {RESOLVED_ON} -e "{target}"'
        else:  # the build tools for the editable install are chosen as of the same day
            install = (f"uv pip install --python {python} --no-deps -r /pins/{name}.txt && "
                       f'uv pip install --python {python} --exclude-newer {RESOLVED_ON} --no-deps -e "{target}"')
        lines.append(f"RUN uv venv --python /usr/local/bin/python3.14 /envs/{name} && {install}")
    lines += ["COPY src/docsproof /opt/docsproof/docsproof",
              "USER sandbox",
              "WORKDIR /work"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="store_true", help="choose dependency versions afresh and pin them")
    parser.add_argument("--only", nargs="*", help="build only these repositories (owner/name), for trying out")
    args = parser.parse_args()
    repos = sandboxed(json.loads((ROOT / "data" / "repos.json").read_text(encoding="utf-8"))["repos"])
    if args.only:
        repos = [r for r in repos if r["repo"] in args.only]
    PINS.mkdir(parents=True, exist_ok=True)
    if not args.resolve:
        missing = [r["repo"] for r in repos if not (PINS / f"{folder(r['repo']).name}.txt").is_file()]
        if missing:
            raise SystemExit(f"No pinned versions for {missing}; run with --resolve first.")
    (SANDBOX / "Dockerfile").write_text(dockerfile(repos, args.resolve), encoding="utf-8")
    subprocess.run(["docker", "build", "--file", str(SANDBOX / "Dockerfile"), "--tag", IMAGE, str(ROOT)], check=True)
    if args.resolve:
        for entry in repos:
            name = folder(entry["repo"]).name
            frozen = subprocess.run(["docker", "run", "--rm", "--network", "none", IMAGE, "uv", "pip", "freeze",
                                     "--python", f"/envs/{name}/bin/python", "--exclude-editable"],
                                    check=True, capture_output=True, text=True).stdout
            (PINS / f"{name}.txt").write_text(frozen, encoding="utf-8")
            print(f"{entry['repo']}: {len(frozen.splitlines())} pinned packages")
    print(f"Built {IMAGE} with {len(repos)} environments.")


if __name__ == "__main__":
    main()
