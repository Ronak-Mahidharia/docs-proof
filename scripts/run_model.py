"""Step 3, the model: a local model reads each candidate line for a changed value (from scripts/run_values.py)
and keeps the ones that state the old value as current.

1. Dev: every model and prompt version reads every dev candidate.
2. The setting is chosen on dev by a rule fixed before test was run: the highest F1 on the dev split's
   changed-value lines; then fewer false alarms; then the smaller model; then the earlier prompt version.
3. Test: the chosen setting reads every test candidate, once.
Every answer is kept (data/results/model-answers.jsonl), so the scores are worked out again without a model.

    python scripts/run_model.py --ask   # asks the models (Ollama on this computer), then scores
    python scripts/run_model.py         # scores from the kept answers
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from docsproof.model import OPTIONS, PROMPTS, ask, verdict  # noqa: E402
from docsproof.score import score  # noqa: E402
from run_baseline import RESULTS, load_cases, pct, report  # noqa: E402

MODELS = ["qwen3:8b", "granite4:3b"]  # larger first
ANSWERS = RESULTS / "model-answers.jsonl"


def items(cases: list[dict], split: str) -> list[tuple[dict, dict, dict]]:
    """(case, change, candidate) for every candidate in a split."""
    by_id = {c["id"]: c for c in cases}
    rows = [json.loads(line) for line in (RESULTS / "values-candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    return [(by_id[r["id"]], change, cand) for r in rows if by_id[r["id"]]["split"] == split
            for change in r["changes"] for cand in change["candidates"]]


def key(model: str, version: str, case: dict, cand: dict) -> tuple:
    return model, version, case["id"], cand["file"], cand["line"]


def ask_all(settings: list[tuple[str, str]], todo: list[tuple[dict, dict, dict]], kept: dict) -> None:
    for model, version in settings:
        for case, change, cand in todo:
            k = key(model, version, case, cand)
            if k not in kept:
                kept[k] = {"model": model, "version": version, "id": case["id"], "file": cand["file"],
                           "line": cand["line"], **ask(change, cand, model, version)}
        print(f"  asked {model} {version}", flush=True)


def flagged(answers: dict, model: str, version: str, todo: list[tuple[dict, dict, dict]]) -> dict[str, list]:
    """Doc lines the model flags for each case, and how each candidate was judged."""
    out: dict[str, list] = {}
    for case, change, cand in todo:
        result = verdict(answers[key(model, version, case, cand)]["raw"], change, cand, version)
        if result == "flagged":
            out.setdefault(case["id"], []).append((cand["file"], cand["line"]))
    return out


def verdicts(answers: dict, model: str, version: str, todo: list) -> dict[str, int]:
    tally: dict[str, int] = {}
    for case, change, cand in todo:
        v = verdict(answers[key(model, version, case, cand)]["raw"], change, cand, version)
        tally[v] = tally.get(v, 0) + 1
    return tally


def value_score(cases: list[dict], split: str, predicted: dict) -> dict:
    return score([c for c in cases if c["split"] == split and c["group"] == "value"], predicted)["all"]


def choose(cases: list[dict], answers: dict, dev: list) -> tuple[str, str, list[dict]]:
    """The setting with the highest dev F1; then fewer false alarms; then the smaller model; then the earlier
    prompt version. Returns it, with every setting's dev scores."""
    rows = []
    for m, model in enumerate(MODELS):
        for v, version in enumerate(PROMPTS):
            s = value_score(cases, "dev", flagged(answers, model, version, dev))
            seconds = sum(answers[key(model, version, c, x)]["seconds"] for c, _, x in dev)
            rows.append({"model": model, "version": version, **{k: s[k] for k in ("tp", "fp", "fn", "precision",
                                                                                    "recall", "f1")},
                         "verdicts": verdicts(answers, model, version, dev), "seconds": round(seconds, 1),
                         "_rank": (-(s["f1"] or 0), s["fp"], -m, v)})
    best = min(rows, key=lambda r: r["_rank"])
    for r in rows:
        del r["_rank"]
    return best["model"], best["version"], rows


def load_predictions(name: str) -> dict[str, list[tuple[str, int]]]:
    rows = [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines()]
    return {r["id"]: [(p["file"], p["line"]) for p in r["predicted"]] for r in rows}


def together(cases: list[dict], value_file: str) -> dict:
    """All the checks: exact checks for names (step 1), and the changed-value search or model for values."""
    exact, values = load_predictions("exact.jsonl"), load_predictions(value_file)
    return report(cases, {c["id"]: sorted(set(exact.get(c["id"], [])) | set(values.get(c["id"], []))) for c in cases})


def f1(t: dict) -> str:
    return "n/a" if t["f1"] is None else f"{t['f1']:.3f}"


def markdown(baseline: dict, scores: dict) -> str:
    chosen, model = scores["chosen"], scores["model"]
    lines = ["# Changed values: a wide search, then a local model", "",
             "Generated by `scripts/run_model.py`. Don't edit by hand.", "",
             "A changed value is a new default for an option (a number in the code) or a higher minimum Python "
             "version. The search, with no AI, finds every doc line about the setting that shows the old value. A "
             "local model then reads each of those lines with the lines around it and says whether it states the "
             "old value as the project's own setting. Each finding must quote the doc line and the code line, and a "
             "finding whose quotes aren't really there is dropped. The models run through Ollama on this computer, "
             "at temperature 0 with a fixed seed.", "",
             "## The search alone", "",
             "| Split | Cases | Lines | Flagged | False alarms | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        v = baseline[split]["value"]
        lines.append(f"| {split} | {v['cases']} | {v['tp'] + v['fn']} | {v['tp'] + v['fp']} | {v['fp']} | "
                     f"{pct(v['precision'])} | {pct(v['recall'])} | {f1(v)} |")
    lines += ["", "No control case had a candidate: no value changed in them.", "",
              "## Choosing the model, on dev", "",
              "| Model | Prompt | Right lines kept | False alarms | F1 | Quote not found | Seconds |",
              "|---|---|---|---|---|---|---|"]
    for r in scores["dev_settings"]:
        lines.append(f"| {r['model']} | {r['version']} | {r['tp']} of {r['tp'] + r['fn']} | {r['fp']} | {f1(r)} | "
                     f"{r['verdicts'].get('bad quote', 0)} | {r['seconds']} |")
    lines += ["", "The prompts: v1 asks whether the line states the old value \"as true now\". v2 adds a list of "
              "lines that only look like the value (another program, a log, a requirement marker, a past release). "
              "v3 asks what the line says, whether or not it's still true. v4 has the model first say what the "
              "line is about, from a fixed list, and which value it states.", "",
              f"Chosen by the rule fixed before test was run (the highest F1; then fewer false alarms; then the "
              f"smaller model; then the earlier prompt): **{chosen['model']}, {chosen['version']}**.", "",
              "## Test, once", "",
              "| | Right lines kept | False alarms | Precision | Recall | F1 |", "|---|---|---|---|---|---|"]
    for label, t in (("The search alone", baseline["test"]["value"]),
                     (f"The search, then {chosen['model']}", model["test"]["value"])):
        lines.append(f"| {label} | {t['tp']} of {t['tp'] + t['fn']} | {t['fp']} | {pct(t['precision'])} | "
                     f"{pct(t['recall'])} | {f1(t)} |")
    n = sum(scores["test_verdicts"].values())
    lines += ["", f"The model read {n} test lines in {scores['test_seconds']} seconds "
              f"({scores['test_seconds'] / n:.1f} a line). Its answers: " +
              ", ".join(f"{k} {v}" for k, v in sorted(scores["test_verdicts"].items())) + ".", "",
              "## All the checks together", "",
              "Exact checks (step 1) find renames, and the changed-value search finds values.", "",
              "| Split | Names: precision | Names: recall | Values: precision | Values: recall | Controls with a false alarm |",
              "|---|---|---|---|---|---|"]
    for label, t in (("with the search alone", scores["together_search"]), (f"with {chosen['model']}", scores["together_model"])):
        for split in ("dev", "test"):
            s = t[split]
            lines.append(f"| {split}, {label} | {pct(s['name']['precision'])} | {pct(s['name']['recall'])} | "
                         f"{pct(s['value']['precision'])} | {pct(s['value']['recall'])} | "
                         f"{s['control']['false_alarm_cases']} of {s['control']['cases']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ask", action="store_true", help="ask the models first (needs Ollama and the models)")
    args = parser.parse_args()
    cases = load_cases()
    dev, test = items(cases, "dev"), items(cases, "test")
    kept = {}
    if ANSWERS.is_file():
        for line in ANSWERS.read_text(encoding="utf-8").splitlines():
            a = json.loads(line)
            kept[(a["model"], a["version"], a["id"], a["file"], a["line"])] = a
    if args.ask:
        ask_all([(m, v) for m in MODELS for v in PROMPTS], dev, kept)
    model, version, dev_rows = choose(cases, kept, dev)
    if args.ask:
        ask_all([(model, version)], test, kept)
        with ANSWERS.open("w", encoding="utf-8") as out:
            for k in sorted(kept):
                out.write(json.dumps(kept[k], ensure_ascii=False) + "\n")
    chosen = {**flagged(kept, model, version, dev), **flagged(kept, model, version, test)}
    with (RESULTS / "model.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps({"id": case["id"], "predicted": [{"file": f, "line": n}
                                                                  for f, n in sorted(chosen.get(case["id"], []))]})
                      + "\n")
    scores = {"chosen": {"model": model, "version": version, "options": OPTIONS}, "dev_settings": dev_rows,
              "test_verdicts": verdicts(kept, model, version, test),
              "test_seconds": round(sum(kept[key(model, version, c, x)]["seconds"] for c, _, x in test), 1),
              "model": report(cases, chosen)}
    scores["together_search"] = together(cases, "values.jsonl")
    scores["together_model"] = together(cases, "model.jsonl")
    (RESULTS / "model-scores.json").write_text(json.dumps(scores, indent=1) + "\n", encoding="utf-8")
    baseline = json.loads((RESULTS / "values-scores.json").read_text(encoding="utf-8"))["baseline"]
    (ROOT / "docs" / "results" / "values.md").write_text(markdown(baseline, scores), encoding="utf-8")
    print(f"chosen on dev: {model} {version}")
    for split in ("dev", "test"):
        s = scores["model"][split]["value"]
        print(f"{split}: value group precision {pct(s['precision'])}, recall {pct(s['recall'])} ({s['tp']} of "
              f"{s['tp'] + s['fn']} lines, {s['fp']} false alarms)")


if __name__ == "__main__":
    main()
