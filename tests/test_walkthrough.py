"""Checks on the walkthrough (scripts/walkthrough.py): its text page is what a fresh run on the tiny project prints,
so the output it shows can't go stale; the GIF was made from that same run; every note points at lines that show
what it says; and the script stops when a run no longer matches a step. None of this needs Pillow, which only the
drawing does."""
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import walkthrough  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
PAGE = walkthrough.PAGE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def steps():
    return walkthrough.run()


def test_the_page_is_what_a_fresh_run_prints(steps):
    assert walkthrough.markdown(steps) == PAGE


def test_the_gif_was_made_from_the_same_run():
    gif = walkthrough.GIF.read_bytes()
    assert gif[:6] == b"GIF89a"
    assert (int.from_bytes(gif[6:8], "little"), int.from_bytes(gif[8:10], "little")) == (walkthrough.W, walkthrough.H)
    assert f"sha256 {walkthrough.digest(PAGE)}".encode("ascii") in gif  # the comment the drawing writes


def test_every_note_points_at_what_it_says(steps):
    found = steps[2]
    lines = found.commands[-1].lines
    head, why, fix, second, summary = found.notes
    assert [lines[n] for n in head.lines] == ["README.md:3", "    Use `--limit` to cap the list (default: 10)."]
    assert [lines[n] for n in why.lines] == ["  why: --limit was at tiny/cli.py:6 before the change and is gone"]
    assert [lines[n] for n in fix.lines] == ["  fix: Use `--cap` to cap the list (default: 10)."]
    assert [lines[n] for n in second.lines] == ["  why: `tiny` declares no --limit option in the code"]
    assert lines[summary.lines[0]].startswith("2 fixes suggested.")
    value = steps[-1]
    lines = value.commands[-1].lines
    assert [lines[n].split(":")[0] for n in value.notes[0].lines] == ["  why", "  fix"]
    assert "default=20" in lines[value.notes[0].lines[0]] and "(default: 20)" in lines[value.notes[0].lines[1]]


def test_the_steps_show_what_their_captions_say(steps):
    assert [step.commands[-1].status for step in steps] == [0, 0, 1, 1, 0, 0, 1]
    assert steps[5].caption.startswith("Nothing is left to fix, so it exits with status 0. Earlier it exited with 1")
    assert "-    parser.add_argument(\"--limit\"" in steps[1].commands[0].output
    assert "+    parser.add_argument(\"--cap\"" in steps[1].commands[0].output
    assert all(walkthrough.screen(step) for step in steps)  # every step fits on one screen


def test_it_stops_when_a_run_no_longer_matches_a_step(monkeypatch):
    files = {**walkthrough.FILES, "docs/usage.md": "Show three items.\n"}  # one doc line fewer to find
    monkeypatch.setattr(walkthrough, "FILES", files)
    with pytest.raises(SystemExit, match="found 1 doc lines, not 2"):
        walkthrough.run()


def test_it_stops_when_a_command_ends_differently(tmp_path):
    with pytest.raises(SystemExit, match="exited with status 1, not 0"):
        walkthrough.run_as_typed(tmp_path, "cat no-such-file")


def test_a_note_stops_when_its_lines_dont_show_it():
    with pytest.raises(SystemExit, match="don't show"):
        walkthrough.note("Then the proof.", ["  fix: Use `--cap`"], [0], "before the change")
    with pytest.raises(SystemExit, match="don't show"):
        walkthrough.note("Then the proof.", ["  why: gone"], [], "gone")


def test_a_step_that_doesnt_fit_stops():
    def step(lines):  # the typed command, its output, and the prompt after it
        return walkthrough.Step("Tall", "", [walkthrough.Command("cat long.txt", "line\n" * lines, 0)])
    assert walkthrough.screen(step(walkthrough.ROWS - 2))  # exactly fills the terminal
    with pytest.raises(SystemExit, match="rows, and the terminal has"):
        walkthrough.screen(step(walkthrough.ROWS - 1))


def test_edit_changes_exactly_one_place(tmp_path):
    path = tmp_path / "cli.py"
    path.write_text("default=10, default=10\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="exactly one"):
        walkthrough.edit(path, "default=10", "default=20")


def test_long_lines_wrap_under_their_text():
    line = "  why: " + " ".join(f"word{n}" for n in range(40))
    rows = walkthrough.wrap(line, 40)
    assert all(len(row) <= 40 for row in rows) and len(rows) > 2
    assert all(row.startswith(" " * 7) and row[7] != " " for row in rows[1:])  # under the text, past "  why: "
    assert " ".join(row.strip() for row in rows) == line.strip()
    assert walkthrough.wrap("x" * 90, 40) == ["x" * 40, "x" * 40, "x" * 10]  # no space: cut at the edge
    assert walkthrough.wrap("short", 40) == ["short"]
    assert walkthrough.wrap("a" * 40, 40) == ["a" * 40]  # exactly fits
    assert walkthrough.wrap("a" * 20 + " " + "b" * 20, 40) == ["a" * 20, "b" * 20]  # one too wide, so it wraps


def test_the_page_fences_can_hold_a_fence():
    assert walkthrough.fence("```console\n$ tiny\n```") == "````"
    assert walkthrough.fence("no fence here, just `code`") == "```"
    assert "````console\n$ cat tiny/cli.py\n" in PAGE  # step 1 shows docs/usage.md, which has a fence of its own


def test_the_readme_shows_the_walkthrough():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"![{walkthrough.ALT}](docs/walkthrough.gif)" in readme
    assert "[written out as text](docs/walkthrough.md)" in readme
    assert f"![{walkthrough.ALT}](walkthrough.gif)" in PAGE
