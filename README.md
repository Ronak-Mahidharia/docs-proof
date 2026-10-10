# docs-proof

Finds the lines in your docs that a code change made wrong, and proves each one: it runs the documented command, or it quotes the code line that contradicts the doc. It suggests a fix and changes nothing without your approval. Its accuracy is measured against an answer key built from real open-source repositories, and every result is published.

**Status:** in progress. Step 1 is done: the answer key and a baseline of exact checks, with no AI. Next is step 2, running the commands in the docs. The steps are in [docs/plan.md](docs/plan.md).

## The problem
- **Docs drift is common.** In GitHub's 2017 Open Source Survey, "incomplete or outdated documentation is a pervasive problem, observed by 93% of respondents" ([opensourcesurvey.org/2017](https://opensourcesurvey.org/2017/)).
- **Even in popular projects.** More than a quarter of the 1,000 most popular projects on GitHub had at least one outdated reference to code in their documentation (Tan, Wagner, and Treude, ICSME 2023: "Wait, wasn't that code here before? Detecting outdated software documentation").
- **README updates are easy to miss.** In a 2026 study of pull requests from 714 repositories, only 0.8% of all pull requests changed the README, and the study's LLM approach recovered half of the README updates that had really been made (Gao et al., [arXiv:2603.00489](https://arxiv.org/abs/2603.00489)).

## The answer key
- **248 planted changes in 30 real repositories.** Popular Python tools and libraries with permissive licenses, each pinned to a commit ([data/repos.json](data/repos.json)), are changed one realistic way at a time: a renamed option, function, environment variable, or file, a changed default, or a raised minimum Python version. Each case records the doc lines the change makes wrong ([data/cases.jsonl](data/cases.jsonl)): 576 lines in all.
- **Split by repository:** 116 dev cases in 15 repositories, and 132 test cases in the other 15.
- **Controls:** 54 cases change something no doc mentions, so nothing should be flagged.
- **Checked by hand** ([data/hand_check.json](data/hand_check.json)):
  - every expected line in the 20 cases that change a value, with lines the rules missed added
  - samples of the rename cases: 59 of 60 lines were right on a sample drawn after the rules were final

## Results so far: exact checks, with no AI
On the test split (15 repositories, 132 cases), a search for names the change removed ([docs/results/exact.md](docs/results/exact.md)):
- **Renames** (93 cases, 324 lines): found all 324, with 7 false alarms (precision 97.9%).
- **Changed values** (11 cases, 25 lines): found 0 of 25.
- **Controls** (28 cases): no false alarms.

For renames, the expected lines are the doc lines that still mention the old name, so a search for removed names finds all of them by design. Those cases mostly test false alarms: the 7 are lines that name something else, such as another package's class. Changed values are what the next steps have to find.

## Reproduce
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # checks the answer key and the published scores
.venv/bin/python scripts/fetch_repos.py          # the 30 repositories at their pinned commits (about 185 MB)
.venv/bin/python scripts/build_cases.py          # rebuilds data/cases.jsonl
.venv/bin/python scripts/run_baseline.py         # reruns the baseline and rewrites the results
```

## License
MIT for the code in this repository. The repositories used for measurement keep their own licenses; they're cloned at a pinned commit when the measurement runs, and never copied here.
