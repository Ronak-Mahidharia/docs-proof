"""Checks on step 7: the write-up is exactly what scripts/write_up.py writes from the results, so its numbers can't
drift; it stops when a result no longer supports what it says; and the demo (scripts/demo.py) shows what the
real-history results say about yt-dlp's rename. Running the demo needs the fetched history, so the last test reruns
it only when the history is there."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import demo  # noqa: E402
import write_up  # noqa: E402
from fetch_history import place  # noqa: E402

PAGE = (ROOT / "docs" / "demo.md").read_text(encoding="utf-8")


def test_the_write_up_is_what_the_script_writes():
    text = (ROOT / "docs" / "write-up.md").read_text(encoding="utf-8")
    assert write_up.render() == text
    assert "{" not in text and "}" not in text  # every number was filled in


def test_the_write_up_stops_when_a_result_no_longer_supports_it(monkeypatch):
    real = write_up.load

    def changed(name):
        data = real(name)
        if name == "exact-scores":
            data["test"]["name"]["fn"] = 1  # a rename line the exact checks missed
        return data
    monkeypatch.setattr(write_up, "load", changed)
    with pytest.raises(SystemExit, match="the exact checks found all rename lines"):
        write_up.render()


def test_the_write_up_numbers_come_from_the_results():
    n = write_up.numbers()
    exact = write_up.load("exact-scores")
    assert n["cases"] == exact["dev"]["cases"] + exact["test"]["cases"] == 246
    assert (n["real_found"], n["real_lines"], n["rf_right"], n["rf_fixed"]) == (7, 23, 14, 23)
    text = (ROOT / "docs" / "write-up.md").read_text(encoding="utf-8")
    assert f"it would have flagged {n['real_found']} of the {n['real_lines']} lines ({n['real_recall']})" in text


def test_the_demo_shows_the_kept_results():
    row = next(json.loads(line) for line in (ROOT / "data" / "results" / "real.jsonl").read_text(encoding="utf-8").splitlines()
               if json.loads(line)["id"] == demo.CASE)
    console = PAGE.split("```console\n", 1)[1].split("```", 1)[0]
    shown = re.findall(r"^(\S+\.md):(\d+)$", console, re.M)
    assert [(f, int(n)) for f, n in shown] == [(x["file"], x["line"]) for x in row["flagged"]]
    for x in row["flagged"]:
        assert f"  fix: {x['fix'].strip()}\n" in console and f"  why: {x['why'][0]}\n" in console
    assert f"docs-proof: {len(row['flagged'])} doc lines the change made wrong ({demo.SHORT}^1 to {demo.SHORT})" in console
    assert "It exits with status 1," in PAGE
    for line in demo.afterwards():  # what happened next comes from the real-history key
        assert line in PAGE


def test_what_happened_afterwards_for_each_kind_of_line():
    case = {"expected": [{"file": "a.md", "line": 1, "fixed_on": "2022-01-06", "days": 5, "fixed_by": "1" * 40},
                         {"file": "a.md", "line": 2, "fixed_on": "2023-01-01", "days": 365, "fixed_by": "2" * 40}]}
    row = {"flagged": [{"file": "a.md", "line": 1}, {"file": "a.md", "line": 2},
                       {"file": "a.md", "line": 3, "still_there": True},
                       {"file": "a.md", "line": 4, "still_there": False, "key_rules_see": True, "name_kept": True, "changed_in": "3" * 40},
                       {"file": "a.md", "line": 5, "still_there": False, "key_rules_see": True, "name_kept": False, "changed_in": "4" * 40}]}
    out = demo.afterwards(case, row)
    assert out[0] == "- **a.md:1:** fixed on 2022-01-06, 5 days later (commit `11111111`)."
    assert out[2] == "- **a.md:3:** still there at the commit the key is pinned to."
    assert "still names the old option" in out[3] and "rules don't read" in out[4]
    assert out[-1] == "The lines the key counts stayed wrong for between 5 and 365 days."


def test_the_readme_links_the_write_up_and_the_demo():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[the write-up](docs/write-up.md)" in readme and "[a demo on a real change](docs/demo.md)" in readme
    assert "## How it fits together\n```mermaid\nflowchart LR\n" in readme


@pytest.mark.skipif(not place("yt-dlp/yt-dlp").is_dir(), reason="needs the fetched history (scripts/fetch_history.py)")
def test_the_demo_reruns_the_same():
    assert demo.markdown(*demo.run()) == PAGE
