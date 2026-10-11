"""The scripts' own failures: a fetch that stopped halfway is fetched again, and a missing tool or service stops a
script with one line that says what to do, not a traceback (scripts/failures.py)."""
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import failures  # noqa: E402
import fetch_repos  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def source(tmp_path: Path) -> tuple[Path, str]:
    """A repository to fetch from, over git's file protocol, and its one commit."""
    src = tmp_path / "source"
    src.mkdir()
    git = ["git", "-C", str(src), "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    (src / "README.md").write_text("tiny\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    subprocess.run([*git, "config", "uploadpack.allowReachableSHA1InWant", "true"], check=True)  # as GitHub allows
    return src, subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def test_a_fetch_that_stopped_halfway_is_fetched_again(tmp_path, monkeypatch):
    src, commit = source(tmp_path)
    monkeypatch.setattr(fetch_repos, "REPOS_DIR", tmp_path / "repos")
    entry = {"repo": "me/tiny", "url": src.as_uri(), "commit": commit}
    stopped = fetch_repos.folder(entry["repo"])
    stopped.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(stopped)], check=True)  # what a fetch that failed leaves: a .git, no HEAD
    assert fetch_repos.fetch(entry) == f"me/tiny: fetched {commit[:10]}"
    assert fetch_repos.fetch(entry) == f"me/tiny: already at {commit[:10]}"


def test_a_fetch_that_cant_reach_the_repository_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_repos, "REPOS_DIR", tmp_path / "repos")
    entry = {"repo": "me/tiny", "url": (tmp_path / "nowhere").as_uri(), "commit": "0" * 40}
    with pytest.raises(SystemExit) as stopped:
        fetch_repos.fetch(entry)
    said = str(stopped.value)
    assert said.startswith("me__tiny: git fetch stopped (fatal: ") and said.endswith("); run this again to retry")
    assert "\n" not in said  # git's message is on one line


def stops(error: BaseException) -> str:
    def main():
        raise error
    with pytest.raises(SystemExit) as stopped:
        failures.explained(main)
    return str(stopped.value)


def test_a_missing_tool_or_service_is_one_line():
    assert "Docker, which the sandbox runs need, isn't installed, or isn't on PATH." in \
        stops(FileNotFoundError(2, "No such file or directory", "docker"))
    assert f"couldn't reach Ollama at {failures.OLLAMA} ([Errno 61] refused); start it with ollama serve" in \
        stops(urllib.error.URLError(ConnectionRefusedError(61, "refused")))
    assert "Ollama answered 404 (Not Found)" in stops(urllib.error.HTTPError("http://x", 404, "Not Found", {}, None))
    for said in ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?",
                 "docker: failed to connect to the docker API at unix:///x.sock; check if the daemon is running"):
        assert "Docker isn't running; start it, and run this again." in stops(RuntimeError(f"the sandbox failed: {said}"))
    assert "docker build stopped (exit status 1)" in stops(subprocess.CalledProcessError(1, ["docker", "build", "."]))
    assert stops(FileNotFoundError(2, "No such file or directory", "git")).endswith(failures.KEPT)


def test_anything_else_still_shows_its_traceback():
    for error in (FileNotFoundError(2, "No such file or directory", "data/cases.jsonl"), RuntimeError("a real bug"),
                  KeyError("an answer that isn't kept"), subprocess.CalledProcessError(1, ["git", "log"])):
        def main(error=error):
            raise error
        with pytest.raises(type(error)):
            failures.explained(main)


def test_a_history_fetched_with_another_window_is_fetched_again(tmp_path, monkeypatch):
    import fetch_history
    src, commit = source(tmp_path)
    monkeypatch.setattr(fetch_history, "HISTORY", tmp_path / "history")
    entry = {"repo": "me/tiny", "url": src.as_uri(), "commit": commit}
    copy = fetch_history.place(entry["repo"])
    assert fetch_history.fetch(entry) == "me/tiny: 1 commits since 2020-01-01"
    assert fetch_history.git(copy, "config", "--get", "docsproof.since").stdout.strip() == fetch_history.SINCE_GIT
    assert fetch_history.fetch(entry) == "me/tiny: already there"
    fetch_history.git(copy, "config", "--unset", "docsproof.since")  # a copy fetched before the window was fixed
    assert fetch_history.fetch(entry) == "me/tiny: 1 commits since 2020-01-01"  # fetched again, with the window
    assert fetch_history.fetch(entry) == "me/tiny: already there"


def test_the_fetched_window_is_the_same_at_any_hour_and_in_any_zone(tmp_path, monkeypatch):
    """git fetch --shallow-since reads its date where the fetch runs, so a bare date would fetch more or fewer commits
    depending on the hour and the time zone."""
    import os

    import fetch_history
    src = tmp_path / "source"
    src.mkdir()
    git = ["git", "-C", str(src), "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    for when in ("2019-12-31T23:30:00+00:00", "2020-01-01T00:30:00+00:00", "2020-01-01T23:30:00+00:00"):
        (src / "README.md").write_text(f"Edited at {when}.\n", encoding="utf-8")
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", when], check=True, env=env)
    subprocess.run([*git, "config", "uploadpack.allowReachableSHA1InWant", "true"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    entry = {"repo": "me/tiny", "url": src.as_uri(), "commit": head}
    counts = set()
    for i, (now, tz) in enumerate((("1791760000", "UTC"), ("1791780000", "UTC"), ("1791760000", "Asia/Kolkata"))):
        monkeypatch.setenv("GIT_TEST_DATE_NOW", now)  # two times of day, and two time zones
        monkeypatch.setenv("TZ", tz)
        monkeypatch.setattr(fetch_history, "HISTORY", tmp_path / f"history {i}")
        fetch_history.fetch(entry)
        counts.add(fetch_history.git(fetch_history.place(entry["repo"]), "rev-list", "--count", fetch_history.REF).stdout.strip())
    assert counts == {"2"}  # the two commits after midnight UTC on Jan 1, 2020
