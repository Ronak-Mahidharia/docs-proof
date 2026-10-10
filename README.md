# docs-proof

Finds the lines in your docs that a code change made wrong, and proves each one: it runs the documented command, or it quotes the code line that contradicts the doc. It suggests a fix and changes nothing without your approval. Its accuracy is measured against an answer key built from real open-source repositories, and every result is published.

**Status:** in progress. Done, with no AI: the answer key, a baseline of exact checks, and the commands in the docs, read and then run in a sandbox. Next is the first step with AI: a model for what exact checks miss, such as a changed default. The steps are in [docs/plan.md](docs/plan.md).

## The problem
- **Docs drift is common.** In GitHub's 2017 Open Source Survey, "incomplete or outdated documentation is a pervasive problem, observed by 93% of respondents" ([opensourcesurvey.org/2017](https://opensourcesurvey.org/2017/)).
- **Even in popular projects.** More than a quarter of the 1,000 most popular projects on GitHub had at least one outdated reference to code in their documentation (Tan, Wagner, and Treude, ICSME 2023: "Wait, wasn't that code here before? Detecting outdated software documentation").
- **README updates are easy to miss.** In a 2026 study of pull requests from 714 repositories, only 0.8% of all pull requests changed the README, and the study's LLM approach recovered half of the README updates that had really been made (Gao et al., [arXiv:2603.00489](https://arxiv.org/abs/2603.00489)).

## The answer key
- **246 planted changes in 30 real repositories.** Popular Python tools and libraries with permissive licenses, each pinned to a commit ([data/repos.json](data/repos.json)), are changed one realistic way at a time: a renamed option, function, environment variable, or file, a changed default, or a raised minimum Python version. Each case records the doc lines the change makes wrong ([data/cases.jsonl](data/cases.jsonl)): 602 lines in all.
- **Split by repository:** 116 dev cases in 15 repositories, and 130 test cases in the other 15.
- **Controls:** 54 cases change something no doc mentions, so nothing should be flagged.
- **Checked by hand** ([data/hand_check.json](data/hand_check.json)):
  - every expected line in the 20 cases that change a value, with lines the rules missed added
  - samples of the rename cases: 59 of 60 lines were right on a sample drawn after the rules were final
  - every line of the 15 rename cases that a later fix to the code reading changed: 54 of 61 were right, and the other 7 were removed
  - every line the exact checks flag that the key leaves out: 4 of 15 named the project's own class or function through a short module name (such as `c.ListOfItems` after `config_options as c`), and were added

## Results so far, with no AI
All on the test split (15 repositories, 130 cases).

**Exact checks:** a search for names the change removed ([docs/results/exact.md](docs/results/exact.md)).
- **Renames** (91 cases, 350 lines): found all 350, with 7 false alarms (precision 98.0%).
- **Changed values** (11 cases, 25 lines): found 0 of 25.
- **Controls** (28 cases): no false alarms.

For renames, the expected lines are the doc lines that still mention the old name, so a search for removed names finds all of them by design. Those cases mostly test false alarms: the 7 are lines the change doesn't make wrong, such as another tool's option with the same name. Changed values are what the next steps have to find.

**Commands in the docs, read:** each documented command is read the way a shell reads it, and its options are compared with the options the code declares ([docs/results/commands.md](docs/results/commands.md)).
- **Renamed options** (37 cases, 175 lines): flagged 48 lines in commands, with no false alarms, each with its proof, such as "`flask` declares no --host option in the code".
- **The other 127 lines:** 122 mention the option outside a command, in help output or a sentence, where the exact checks find them. 5 are commands it doesn't read yet, such as PowerShell's `$home_dir = pipx environment --value PIPX_HOME`.
- **An audit of the 30 repositories as they are:** 2,868 documented commands, 874 with long options. 5 use an option the code doesn't declare, and a hand check found none of them out of date: 3 are options that plugins add, 1 is another program's option, and 1 is an error the docs show on purpose.

**Commands in the docs, run:** each documented command runs in a sandbox, a Docker container with no network, and the program is stopped right after it has read its command line, so nothing the command would do is done ([docs/results/run.md](docs/results/run.md)).
- **Renamed options** (37 cases, 175 lines): flagged 29 lines, with no false alarms. The proof is the program's own message, such as flask's "No such option '--host'. (Did you mean one of: '--host2', '--port'?)".
- **Read, then run:** the other 19 lines that reading flags are in commands the program still accepts after the change. argparse and optparse take a unique prefix of an option's name, so a rename from `--include-injected` to `--include-injected2` leaves `--include-injected` working. Reading finds every stale name; running proves which commands break.
- **Found only by running:** renaming the environment variable `PIPX_COOLDOWN` broke `pipx environment --value PIPX_COOLDOWN`, which pipx refuses with "invalid choice: 'PIPX_COOLDOWN'".
- **An audit of the 26 repositories whose programs run:** 1,678 distinct command lines. 22 are refused for a reason other than a missing input, such as a file the sandbox doesn't have. Checked by hand, 7 doc lines in 5 projects are out of date, also on each project's main branch on Oct 10, 2026, such as sqlite-utils' `populate-fts ... --tokenize=porter` (the option belongs to `enable-fts`). The other 15 are commands that the reader's own app or a plugin adds (11), quoted arguments that span several lines (3), and a placeholder (1).

## Reproduce
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # checks the answer key and the published scores
.venv/bin/python scripts/fetch_repos.py          # the 30 repositories at their pinned commits (about 185 MB)
.venv/bin/python scripts/build_cases.py          # rebuilds data/cases.jsonl
.venv/bin/python scripts/run_baseline.py         # reruns the baseline and rewrites its results
.venv/bin/python scripts/run_commands.py         # checks the documented commands and rewrites their results
.venv/bin/python scripts/run_sandbox.py          # the sandbox's flags and scores, from its kept runs
```

To run the commands again, with Docker (about 20 minutes on a 10-core Mac; the image is about 1.1 GB):
```bash
.venv/bin/python scripts/build_sandbox.py        # Python 3.14 and the 26 programs, at the versions in data/sandbox/pins/
.venv/bin/python scripts/run_sandbox.py --run    # runs every documented command, as pinned and after each change
```

## License
MIT for the code in this repository. The repositories used for measurement keep their own licenses; they're cloned at a pinned commit when the measurement runs, and never copied here.
