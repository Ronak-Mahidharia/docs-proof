import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from docsproof.commands import Command
from docsproof.run import flagged_lines, proof, refused, runnable
from docsproof.sandbox_run import outcome, summary

HOOKS = Path(__file__).resolve().parent.parent / "src" / "docsproof" / "hooks"


def run_program(tmp_path: Path, source: str, *args: str) -> dict:
    """Run a small program with the hooks loaded, the way sandbox_run.py runs a documented command."""
    program = tmp_path / "prog.py"
    program.write_text(textwrap.dedent(source), encoding="utf-8")
    events = tmp_path / "events.jsonl"
    events.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONPATH": str(HOOKS), "DOCSPROOF_EVENTS": str(events)}
    done = subprocess.run([sys.executable, str(program), *args], cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)
    lines = events.read_text(encoding="utf-8").splitlines() if events.is_file() else []
    return summary([json.loads(line) for line in lines], done.returncode, False)


CLICK = """
    import click
    from pathlib import Path

    class DefaultGroup(click.Group):  # like click-default-group (used by llm): other words go to "prompt"
        def get_command(self, ctx, name):
            if name not in self.commands:
                ctx.arg0 = name
                name = "prompt"
            return super().get_command(ctx, name)

        def resolve_command(self, ctx, args):
            name, command, args = super().resolve_command(ctx, args)
            if hasattr(ctx, "arg0"):
                args.insert(0, ctx.arg0)
                name = command.name
            return name, command, args

    @click.group(cls=DefaultGroup, context_settings={"ignore_unknown_options": True})
    def cli():
        Path("group-ran").write_text("yes")

    @cli.command()
    @click.option("--model")
    @click.argument("words", nargs=-1)
    def prompt(model, words):
        Path("command-ran").write_text("yes")

    @cli.command()
    @click.argument("name")
    def show(name):
        Path("command-ran").write_text("yes")

    cli()
"""


def test_click_commands_stop_after_their_command_line_is_read(tmp_path):
    assert run_program(tmp_path, CLICK, "prompt", "--model", "x", "hello") == \
        {"outcome": "accepted", "exit": 0, "unknown": [], "message": ""}
    assert not (tmp_path / "command-ran").exists() and not (tmp_path / "group-ran").exists()
    # The group passes --model on to the default command: the error it catches isn't a refusal.
    assert run_program(tmp_path, CLICK, "--model", "x", "hello")["outcome"] == "accepted"
    assert run_program(tmp_path, CLICK, "--model") == {"outcome": "rejected", "exit": 2, "unknown": [],
                                                       "message": "Option '--model' requires an argument."}
    refused_option = run_program(tmp_path, CLICK, "--nope", "hello")
    assert refused_option["outcome"] == "rejected" and refused_option["unknown"] == ["--nope"]
    assert refused_option["message"].startswith("No such option '--nope'")
    missing = run_program(tmp_path, CLICK, "show")
    assert missing == {"outcome": "rejected", "exit": 2, "unknown": [], "message": "Missing argument 'NAME'."}
    assert not (tmp_path / "command-ran").exists()


def test_click_unknown_commands(tmp_path):
    source = """
        import click
        @click.group()
        def cli(): pass
        @cli.command()
        def serve(): pass
        cli()
    """
    assert run_program(tmp_path, source, "serve")["outcome"] == "accepted"
    result = run_program(tmp_path, source, "server")
    assert result["outcome"] == "rejected" and result["unknown"] == ["server"]
    assert run_program(tmp_path, source, "--help")["outcome"] == "accepted"


ARGPARSE = """
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(prog="tiny")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int)
    run.add_argument("--max-results", type=int)
    args = parser.parse_args()
    Path("command-ran").write_text("yes")
"""


def test_argparse_commands(tmp_path):
    assert run_program(tmp_path, ARGPARSE, "run", "--limit", "3")["outcome"] == "accepted"
    assert not (tmp_path / "command-ran").exists()
    result = run_program(tmp_path, ARGPARSE, "run", "--limits", "3")
    assert result["outcome"] == "rejected" and result["unknown"] == ["--limits"]
    assert result["message"] == "unrecognized arguments: --limits 3"
    result = run_program(tmp_path, ARGPARSE, "walk")
    assert result["outcome"] == "rejected" and result["unknown"] == ["walk"]
    # argparse takes a unique abbreviation, so a shortened option still works
    assert run_program(tmp_path, ARGPARSE, "run", "--max", "3")["outcome"] == "accepted"


def test_argparse_words_kept_on_purpose_and_a_second_parser(tmp_path):
    kept = """
        import argparse, sys
        args, rest = argparse.ArgumentParser().parse_known_args()
        sys.exit(0)  # the program passes "rest" on to another tool
    """
    assert run_program(tmp_path, kept, "--for-the-other-tool") == \
        {"outcome": "succeeded", "exit": 0, "unknown": [], "message": ""}
    two_stage = """
        import argparse
        first = argparse.ArgumentParser()
        first.add_argument("command", choices=["upload"])
        first.add_argument("args", nargs=argparse.REMAINDER)
        parsed = first.parse_args()
        second = argparse.ArgumentParser()
        second.add_argument("--repository")
        second.add_argument("dists", nargs="+")
        second.parse_args(parsed.args)
    """
    assert run_program(tmp_path, two_stage, "upload", "--repository", "x", "dist/a.whl")["outcome"] == "accepted"
    result = run_program(tmp_path, two_stage, "upload", "--repo-url", "x", "dist/a.whl")
    assert result["outcome"] == "rejected" and result["unknown"] == ["--repo-url"]


def test_optparse_with_its_own_error_handling(tmp_path):
    source = """
        import optparse, sys
        from pathlib import Path
        class Parser(optparse.OptionParser):  # like coverage: no exit on an error
            def error(self, msg):
                raise ValueError(msg)
        parser = Parser()
        parser.add_option("--source")
        try:
            options, args = parser.parse_args()
        except ValueError:
            sys.exit(1)
        Path("command-ran").write_text("yes")
    """
    assert run_program(tmp_path, source, "--source", "x")["outcome"] == "accepted"
    assert not (tmp_path / "command-ran").exists()
    result = run_program(tmp_path, source, "--sources", "x")
    assert result["outcome"] == "rejected" and result["unknown"] == ["--sources"]


def test_programs_a_command_starts_record_nothing(tmp_path):
    source = """
        import os, subprocess, sys
        child = "import argparse; argparse.ArgumentParser().parse_args(['--x'])"
        subprocess.run([sys.executable, "-c", child])
        # even a child given the hooks' folder on purpose records nothing: the events file isn't passed on
        subprocess.run([sys.executable, "-c", child], env={**os.environ, "PYTHONPATH": sys.argv[1]})
        sys.exit(0)
    """
    assert run_program(tmp_path, source, str(HOOKS)) == {"outcome": "succeeded", "exit": 0, "unknown": [], "message": ""}


def test_a_program_that_keeps_words_and_reports_its_own_error(tmp_path):
    source = """
        import argparse
        parser = argparse.ArgumentParser()
        args, rest = parser.parse_known_args()
        parser.error("--a needs --b")
    """
    assert run_program(tmp_path, source, "--for-the-other-tool") == \
        {"outcome": "rejected", "exit": 2, "unknown": [], "message": "--a needs --b"}


def test_outcomes():
    assert outcome([{"kind": "accepted"}], 0, False) == "accepted"
    assert outcome([], None, True) == "timeout"
    assert outcome([], 0, False) == "succeeded"
    assert outcome([{"kind": "usage_error", "message": "x"}], 2, False) == "rejected"
    assert outcome([], 1, False) == "failed"
    # an unknown word recorded before the parser accepted the command line doesn't count
    assert summary([{"kind": "unknown_option", "option": "--x", "message": ""}, {"kind": "accepted"}], 0, False) == \
        {"outcome": "accepted", "exit": 0, "unknown": [], "message": ""}


def result(outcome_: str, unknown=(), message="") -> dict:
    return {"outcome": outcome_, "exit": 0, "unknown": list(unknown), "message": message}


def test_a_command_is_flagged_when_the_change_makes_the_program_refuse_it():
    assert refused(result("accepted"), result("rejected", ["--limit"], "No such option")) == ["--limit"]
    # a file the docs name isn't in the sandbox, so it's refused before and after; the new unknown word counts
    assert refused(result("rejected", message="Path 'x' does not exist"), result("rejected", ["--limit"])) == ["--limit"]
    assert refused(result("rejected", ["--x"]), result("rejected", ["--x"])) is None  # already refused
    assert refused(result("accepted"), result("rejected", message="Missing argument")) == []
    assert refused(result("failed"), result("rejected", message="Missing argument")) is None
    assert refused(result("accepted"), result("accepted")) is None
    assert refused(result("rejected", ["--x"]), result("accepted")) is None


def test_lines_flagged_and_their_proof():
    command = Command("README.md", 6, "tiny", "tiny --limit 3 \\ --also", (("--limit", 6), ("--also", 7)),
                      ("tiny", "--limit", "3", "--also"))
    assert flagged_lines([command], ["--also"]) == {("README.md", 7)}
    assert flagged_lines([command], ["walk"]) == {("README.md", 6)}  # not an option: the program's line
    assert proof(("tiny", "--also"), result("rejected", ["--also"], "No such option '--also'.")) == \
        "After the change, `tiny` refuses this command: No such option '--also'."
    assert proof(("python", "-m", "tiny", "--x"), result("rejected", ["--x"])) == \
        "After the change, `python -m tiny` refuses this command: --x"


def test_commands_that_need_the_shell_arent_run():
    def make(*argv):
        return Command("README.md", 1, "tiny", " ".join(argv), (), argv)
    assert runnable(make("tiny", "--limit", "3")) is None
    assert runnable(make("tiny", "--name", "$(whoami)")) == "its words need the shell"
    assert runnable(make("tiny", "`date`")) == "its words need the shell"


def test_the_sandbox_keeps_its_limits():
    from docsproof.run import SANDBOX
    flags = " ".join(SANDBOX)
    for limit in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 256",
                  "--memory 768m", "--rm"):
        assert limit in flags, limit
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from build_sandbox import BASE, dockerfile
    text = dockerfile([{"repo": "pallets/flask"}], resolve=False)
    assert text.startswith(f"FROM {BASE}\n") and "@sha256:" in BASE  # the base image is pinned by digest
    assert "\nUSER sandbox\n" in text  # commands never run as root
    assert "--no-deps -r /pins/pallets__flask.txt" in text and "--exclude-newer" in text


def test_a_captured_command_returns_what_it_printed(tmp_path):
    from docsproof.sandbox_run import run
    env_bin = tmp_path / "bin"
    env_bin.mkdir()
    script = tmp_path / "tiny.py"
    script.write_text("import argparse\np = argparse.ArgumentParser(prog='tiny')\n"
                      "p.add_argument('--limit', help='at most N')\np.parse_args()\n", encoding="utf-8")
    program = env_bin / "tiny"  # a wrapper, since a #! line can't hold a path with a space in it
    program.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
    program.chmod(0o755)
    captured = run({"id": 0, "argv": ["tiny", "--help"], "capture": True}, tmp_path, env_bin, 30)
    assert captured["outcome"] == "succeeded" and "--limit LIMIT  at most N" in captured["output"]
    plain = run({"id": 1, "argv": ["tiny", "--help"]}, tmp_path, env_bin, 30)
    assert plain == {"id": 1, "outcome": "succeeded", "exit": 0, "unknown": [], "message": ""}  # as before: no output


def test_a_job_asks_for_output_only_when_told_to():
    from docsproof.run import job_commands
    keys = [(("tiny", "--help"), ())]
    assert job_commands(keys) == [{"id": 0, "argv": ["tiny", "--help"], "env": {}}]
    assert job_commands(keys, capture=True) == [{"id": 0, "argv": ["tiny", "--help"], "env": {}, "capture": True}]
