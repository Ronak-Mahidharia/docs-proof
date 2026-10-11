"""The MCP server, tested through a real MCP client: in-process, and once over stdio, the way an assistant starts
it. It runs the same check as the docs-proof command, so its answers must be the command's."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import anyio
import pytest
from conftest import FILES, write

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters  # noqa: E402
from test_cli import FIX, git, rename_limit, repo  # noqa: E402

from docsproof import cli, mcp_server  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
SRC = Path(__file__).resolve().parent.parent / "src"


def call(tool, arguments, target=None):
    async def go():
        async with Client(target or mcp_server.server) as client:
            return await client.call_tool(tool, arguments)
    return anyio.run(go)


def tools():
    async def go():
        async with Client(mcp_server.server) as client:
            return (await client.list_tools()).tools
    return {t.name: t for t in anyio.run(go)}


def command_json(capsys, argv):
    capsys.readouterr()
    cli.main(argv)
    return json.loads(capsys.readouterr().out)


def fingerprint(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def test_two_read_only_tools_with_input_limits():
    found = tools()
    assert set(found) == {"check_repository", "check_folders"}
    for t in found.values():
        assert t.annotations.read_only_hint and t.annotations.destructive_hint is False
        assert t.annotations.open_world_hint is False and t.output_schema
    assert found["check_repository"].input_schema["required"] == ["repo"]
    assert found["check_repository"].input_schema["properties"]["repo"]["maxLength"] == 4096


def test_the_same_findings_as_the_command(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    before = fingerprint(root)
    got = call("check_repository", {"repo": str(root), "base": "HEAD"})
    assert not got.is_error
    out = got.structured_content
    assert out["findings"] == command_json(capsys, ["--repo", str(root), "--base", "HEAD", "--json"])["findings"]
    assert (out["base"], out["head"], out["flagged"]) == ("HEAD", "the working tree", 1)
    assert f"+{FIX}" in out["patch"] and "read each one before making it" in out["note"]
    assert fingerprint(root) == before  # it changed nothing


def test_commits_and_folders(tmp_path):
    root = repo(tmp_path)
    git(root, "switch", "-q", "-c", "rename")
    rename_limit(root)
    git(root, "commit", "-q", "-am", "rename --limit")
    out = call("check_repository", {"repo": str(root), "base": "main", "head": "HEAD"}).structured_content
    assert [(x["file"], x["line"], x["fix"]["new"]) for x in out["findings"]] == [("README.md", 6, [FIX])]
    old = write(tmp_path / "old", FILES)
    new = shutil.copytree(old, tmp_path / "new")
    rename_limit(new)
    out = call("check_folders", {"before": str(old), "after": str(new)}).structured_content
    assert out["flagged"] == 1 and out["findings"][0]["why"] == ["--limit was at tiny/cli.py:8 before the change and is gone"]


def test_problems_come_back_as_messages(tmp_path):
    plain = write(tmp_path / "plain", FILES)
    for tool, arguments, message in (
            ("check_repository", {"repo": str(plain)}, "not a git repository"),
            ("check_repository", {"repo": str(repo(tmp_path)), "base": "nope"}, "no commit, branch, or tag called nope"),
            ("check_folders", {"before": str(plain), "after": str(tmp_path / "missing")}, "isn't a folder")):
        got = call(tool, arguments)
        assert got.is_error and message in got.content[0].text, message
    assert call("check_repository", {"repo": ""}).is_error  # too short for the input schema


def test_a_long_report_is_capped(tmp_path, monkeypatch):
    root = repo(tmp_path)
    (root / "docs" / "many.md").write_text("".join(f"Line {n}: use --limit.\n" for n in range(5)), encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "many mentions")
    rename_limit(root)
    monkeypatch.setattr(mcp_server, "MAX_FINDINGS", 2)
    out = call("check_repository", {"repo": str(root), "base": "HEAD"}).structured_content
    assert out["flagged"] == 6 and len(out["findings"]) == 2 and out["note"].startswith("Showing 2 of 6 findings")
    added = [line for line in out["patch"].splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert added == [f"+{FIX}", "+Line 0: use --cap."]  # the patch has the fixes of the findings shown, no more


def test_over_stdio_as_an_assistant_starts_it(tmp_path, capsys):
    root = repo(tmp_path)
    rename_limit(root)
    params = StdioServerParameters(command=sys.executable, args=["-m", "docsproof.mcp_server"],
                                   env={**os.environ, "PYTHONPATH": str(SRC)})
    out = call("check_repository", {"repo": str(root), "base": "HEAD"}, params).structured_content
    assert out["findings"] == command_json(capsys, ["--repo", str(root), "--base", "HEAD", "--json"])["findings"]


def test_every_proof_of_a_line_both_checks_flag(tmp_path, capsys):
    files = {**FILES, "pyproject.toml": FILES["pyproject.toml"] + '[project.scripts]\ntiny = "tiny.cli:main"\n',
             "docs/run.md": "```console\n$ tiny --limit 3\n```\n"}
    root = write(tmp_path / "tiny", files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    rename_limit(root)
    out = call("check_repository", {"repo": str(root), "base": "HEAD"}).structured_content
    both = next(x for x in out["findings"] if x["file"] == "docs/run.md")
    assert both["why"] == ["--limit was at tiny/cli.py:8 before the change and is gone",
                           "`tiny` declares no --limit option in the code"]
    assert out["findings"] == command_json(capsys, ["--repo", str(root), "--base", "HEAD", "--json"])["findings"]
