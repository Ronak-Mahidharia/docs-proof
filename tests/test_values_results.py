"""Checks on step 3's kept results: the changed-value search, the model's kept answers, and the scores and pages
worked out from them (scripts/run_values.py and scripts/run_model.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_baseline  # noqa: E402
import run_model  # noqa: E402
import run_values  # noqa: E402
from docsproof.model import PROMPTS  # noqa: E402

CASES = [json.loads(line) for line in (ROOT / "data" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
RESULTS = ROOT / "data" / "results"
ROWS = [json.loads(line) for line in (RESULTS / "values-candidates.jsonl").read_text(encoding="utf-8").splitlines()]


def load(name):
    return [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines()]


def test_the_search_flags_come_from_its_kept_candidates():
    assert [r["id"] for r in ROWS] == [c["id"] for c in CASES]
    flagged = run_values.baseline(ROWS)
    assert {r["id"]: [(p["file"], p["line"]) for p in r["predicted"]] for r in load("values.jsonl")} == flagged
    scores = json.loads((RESULTS / "values-scores.json").read_text(encoding="utf-8"))
    assert scores["baseline"] == run_baseline.report(CASES, flagged)
    by_id = {c["id"]: c for c in CASES}
    assert all(not r["changes"] for r in ROWS if by_id[r["id"]]["group"] != "value")  # renames change no value


def test_every_candidate_has_its_answers():
    answers = {(a["model"], a["version"], a["id"], a["file"], a["line"]) for a in load("model-answers.jsonl")}
    scores = json.loads((RESULTS / "model-scores.json").read_text(encoding="utf-8"))
    chosen = (scores["chosen"]["model"], scores["chosen"]["version"])
    for split, settings in (("dev", [(m, v) for m in run_model.MODELS for v in PROMPTS]), ("test", [chosen])):
        for case, _, cand in run_model.items(CASES, split):
            for model, version in settings:
                assert (model, version, case["id"], cand["file"], cand["line"]) in answers
    assert len(answers) == len(run_model.items(CASES, "dev")) * len(run_model.MODELS) * len(PROMPTS) + \
        len(run_model.items(CASES, "test"))  # and test was asked only with the chosen setting


def test_the_model_scores_and_page_come_from_the_kept_answers():
    kept = {(a["model"], a["version"], a["id"], a["file"], a["line"]): a for a in load("model-answers.jsonl")}
    dev, test = run_model.items(CASES, "dev"), run_model.items(CASES, "test")
    model, version, rows = run_model.choose(CASES, kept, dev)
    scores = json.loads((RESULTS / "model-scores.json").read_text(encoding="utf-8"))
    assert (model, version) == (scores["chosen"]["model"], scores["chosen"]["version"]) and rows == scores["dev_settings"]
    chosen = {**run_model.flagged(kept, model, version, dev), **run_model.flagged(kept, model, version, test)}
    assert {r["id"]: [(p["file"], p["line"]) for p in r["predicted"]] for r in load("model.jsonl")} == \
        {c["id"]: sorted(chosen.get(c["id"], [])) for c in CASES}
    assert scores["model"] == run_baseline.report(CASES, chosen)
    assert scores["test_verdicts"] == run_model.verdicts(kept, model, version, test)
    assert scores["together_model"] == run_model.together(CASES, "model.jsonl")
    baseline = json.loads((RESULTS / "values-scores.json").read_text(encoding="utf-8"))["baseline"]
    assert (ROOT / "docs" / "results" / "values.md").read_text(encoding="utf-8") == run_model.markdown(baseline, scores)


def test_readme_and_plan_numbers_for_changed_values():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "plan.md").read_text(encoding="utf-8")
    base = json.loads((RESULTS / "values-scores.json").read_text(encoding="utf-8"))["baseline"]["test"]["value"]
    scores = json.loads((RESULTS / "model-scores.json").read_text(encoding="utf-8"))
    m = scores["model"]["test"]["value"]
    name = scores["chosen"]["model"]
    lines = base["tp"] + base["fn"]
    n_settings = len(scores["dev_settings"])
    removed, lost = base["fp"] - m["fp"], base["tp"] - m["tp"]
    expected = [
        f"**The search alone, with no AI** ({base['cases']} cases, {lines} lines): found all {base['tp']}, with "
        f"{base['fp']} false alarms (precision {100 * base['precision']:.1f}%).",
        f"**The search, then a local model** ({name} through Ollama, chosen on dev from {len(run_model.MODELS)} models and "
        f"{len(PROMPTS)} prompts): {m['tp']} of the {lines}, with {m['fp']} false alarms (precision "
        f"{100 * m['precision']:.1f}%). It removed {removed} false alarms and dropped {lost} right lines, so F1 is about "
        f"the same ({m['f1']:.3f} against {base['f1']:.3f}).",
        f"a finding whose quotes aren't really there is dropped ({scores['test_verdicts'].get('bad quote', 0)} of "
        f"{sum(scores['test_verdicts'].values())} on test)",
    ]
    assert base["tp"] == lines and n_settings == len(run_model.MODELS) * len(PROMPTS)
    for sentence in expected:
        assert sentence in readme, sentence
    done = (f"**Done:** on test, a wide search finds all {lines} changed-value lines, with {base['fp']} false alarms; a "
            f"local model ({name}, chosen on dev) removes {removed} of them but drops {lost} right lines, so F1 stays "
            f"about the same ({m['f1']:.3f} against {base['f1']:.3f})")
    assert done in plan
