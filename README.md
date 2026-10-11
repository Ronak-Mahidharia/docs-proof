# docs-proof

Finds the lines in your docs that a code change made wrong, and proves each one: it runs the documented command, or it quotes the code line that contradicts the doc. It suggests a fix and changes nothing without your approval. Its accuracy is measured against an answer key built from real open-source repositories, and every result is published.

**Status:** in progress. Done: the answer key, a baseline of exact checks, the commands in the docs (read, and run in a sandbox), changed values (a search, then a local model), suggested fixes (rules, then an agent, with approval before anything changes), and the command-line tool. Next: a GitHub Action that comments on pull requests, and an MCP server. The steps are in [docs/plan.md](docs/plan.md).

## The problem
- **Docs drift is common.** In GitHub's 2017 Open Source Survey, "incomplete or outdated documentation is a pervasive problem, observed by 93% of respondents" ([opensourcesurvey.org/2017](https://opensourcesurvey.org/2017/)).
- **Even in popular projects.** More than a quarter of the 1,000 most popular projects on GitHub had at least one outdated reference to code in their documentation (Tan, Wagner, and Treude, ICSME 2023: "Wait, wasn't that code here before? Detecting outdated software documentation").
- **README updates are easy to miss.** In a 2026 study of pull requests from 714 repositories, only 0.8% of all pull requests changed the README, and the study's LLM approach recovered half of the README updates that had really been made (Gao et al., [arXiv:2603.00489](https://arxiv.org/abs/2603.00489)).

## The answer key
- **246 planted changes in 30 real repositories.** Popular Python tools and libraries with permissive licenses, each pinned to a commit ([data/repos.json](data/repos.json)), are changed one realistic way at a time: a renamed option, function, environment variable, or file, a changed default, or a raised minimum Python version. Each case records the doc lines the change makes wrong ([data/cases.jsonl](data/cases.jsonl)): 601 lines in all.
- **Split by repository:** 116 dev cases in 15 repositories, and 130 test cases in the other 15.
- **Controls:** 54 cases change something no doc mentions, so nothing should be flagged.
- **Checked by hand** ([data/hand_check.json](data/hand_check.json)):
  - every expected line in the 20 cases that change a value, with lines the rules missed added
  - samples of the rename cases: 59 of 60 lines were right on a sample drawn after the rules were final
  - every line of the 15 rename cases that a later fix to the code reading changed: 54 of 61 were right, and the other 7 were removed
  - every line the exact checks flag that the key leaves out: 4 of 16 named the project's own class or function through a short module name (such as `c.ListOfItems` after `config_options as c`), and were added
  - the key's fixed lines (step 4): every value line, every name line that mentions the name more than once or under a package's name, and 40 more drawn at random. 5 value lines need a fix of their own, and 1 name line turned out not to be wrong (bandit's `.. automodule:: bandit.plugins.yaml_load` names the module, not the renamed function), so it was removed

## Results so far
All on the test split (15 repositories, 130 cases). Only the last part uses AI.

**Exact checks:** a search for names the change removed ([docs/results/exact.md](docs/results/exact.md)).
- **Renames** (91 cases, 350 lines): found all 350, with 7 false alarms (precision 98.0%).
- **Changed values** (11 cases, 25 lines): found 0 of 25.
- **Controls** (28 cases): no false alarms.

For renames, the expected lines are the doc lines that still mention the old name, so a search for removed names finds all of them by design. Those cases mostly test false alarms: the 7 are lines the change doesn't make wrong, such as another tool's option with the same name. Changed values are found in step 3, below.

**Commands in the docs, read:** each documented command is read the way a shell reads it, and its options are compared with the options the code declares ([docs/results/commands.md](docs/results/commands.md)).
- **Renamed options** (37 cases, 175 lines): flagged 48 lines in commands, with no false alarms, each with its proof, such as "`flask` declares no --host option in the code".
- **The other 127 lines:** 122 mention the option outside a command, in help output or a sentence, where the exact checks find them. 5 are commands it doesn't read yet, such as PowerShell's `$home_dir = pipx environment --value PIPX_HOME`.
- **An audit of the 30 repositories as they are:** 2,868 documented commands, 874 with long options. 5 use an option the code doesn't declare, and a hand check found none of them out of date: 3 are options that plugins add, 1 is another program's option, and 1 is an error the docs show on purpose.

**Commands in the docs, run:** each documented command runs in a sandbox, a Docker container with no network, and the program is stopped right after it has read its command line, so nothing the command would do is done ([docs/results/run.md](docs/results/run.md)).
- **Renamed options** (37 cases, 175 lines): flagged 29 lines, with no false alarms. The proof is the program's own message, such as flask's "No such option '--host'. (Did you mean one of: '--host2', '--port'?)".
- **Read, then run:** the other 19 lines that reading flags are in commands the program still accepts after the change. argparse and optparse take a unique prefix of an option's name, so a rename from `--include-injected` to `--include-injected2` leaves `--include-injected` working. Reading finds every stale name; running proves which commands break.
- **Found only by running:** renaming the environment variable `PIPX_COOLDOWN` broke `pipx environment --value PIPX_COOLDOWN`, which pipx refuses with "invalid choice: 'PIPX_COOLDOWN'".
- **An audit of the 26 repositories whose programs run:** 1,678 distinct command lines. 22 are refused for a reason other than a missing input, such as a file the sandbox doesn't have. Checked by hand, 7 doc lines in 5 projects are out of date, also on each project's main branch on Oct 10, 2026, such as sqlite-utils' `populate-fts ... --tokenize=porter` (the option belongs to `enable-fts`). The other 15 are commands that the reader's own app or a plugin adds (11), quoted arguments that span several lines (3), and a placeholder (1).

**Changed values:** a search finds every doc line about the setting that shows the old value, and a local model then reads each one in context ([docs/results/values.md](docs/results/values.md)).
- **The search alone, with no AI** (11 cases, 25 lines): found all 25, with 10 false alarms (precision 71.4%).
- **The search, then a local model** (qwen3:8b through Ollama, chosen on dev from 2 models and 4 prompts): 23 of the 25, with 7 false alarms (precision 76.7%). It removed 3 false alarms and dropped 2 right lines, so F1 is about the same (0.837 against 0.833).
- **The false alarms it kept** mention the version in passing, such as an example command, a history note, or a note about which wheel installs.
- **Proof:** each finding quotes the doc line and the code line, and a finding whose quotes aren't really there is dropped (1 of 35 on test).

**Suggested fixes:** each flagged line gets a fix that's checked before it's offered, and a fixed command is run again in the sandbox, after the change ([docs/results/fixes.md](docs/results/fixes.md)). Nothing in a repository changes without approval: the fixes become one patch, and a pull request is opened only after a person says yes to it.
- **The rules, with no AI** (on the 392 lines steps 1 and 3 flag): fixed 370 of the 375 lines the change made wrong, all of them right, and declined 5. The program took every one of the 52 fixed lines that are part of a documented command, run again after the change.
- **An agent for the rest** (qwen3:8b through Ollama, working only through tools, with a turn limit and loop detection; chosen on dev from 2 models and 3 prompts): of the 5 lines, it fixed 3 right and 1 wrong, and left 1 for a person.
- **Together:** 373 of the 375 lines fixed right.
- **Every false alarm got a fix too** (17 of 17), so each fix needs a person's yes.
- **The doc lines step 2 found out of date:** on test's 3, the agent left 2 for a person and fixed 1 wrong: it joined alembic's command onto one line and left the old lines under it. On dev, it fixed llm's `schema dsl` to `schemas dsl`, as the usage line above it says.

## Use it
`docs-proof` checks a change in a Python project's git repository. It uses no AI unless you ask for it, and sends nothing anywhere.

```bash
pip install -e .                       # from this repository: Python 3.12 or newer, no other packages
docs-proof                             # the working tree, against where the branch started from main
docs-proof --base v1.2 --head HEAD     # between two commits, branches, or tags
docs-proof --patch fixes.patch         # the suggested fixes, as a patch to read, then git apply
docs-proof --apply                     # show the fixes, and make them only after a yes
```

For each doc line it flags, it prints the line, the proof, and the rules' fix. Here, after renaming pyupgrade's `--keep-mock` to `--keep-mock2` (one of the planted changes):

```
README.md:316
    - [Unless `--keep-mock` is passed on the commandline](https://github.com/asottile/pyupgrade/issues/314).
  why: --keep-mock was at pyupgrade/_main.py:345 before the change and is gone
  fix: - [Unless `--keep-mock2` is passed on the commandline](https://github.com/asottile/pyupgrade/issues/314).
```

- **The same as the measured steps:** on all 246 cases, it flags exactly the 626 lines that the exact checks, the commands read, and the changed-value search flag, and offers exactly step 4's 612 rule fixes ([scripts/check_tool.py](scripts/check_tool.py)).
- **For scripts and CI:** the exit status is 0 when nothing is flagged, 1 when something is, and 2 when the check couldn't run. `--json` prints the findings, and `--before`/`--after` compare two folders without git.
- **Optional AI:** `--model qwen3:8b` adds step 3's local model for changed values, through Ollama on your computer.
- **Not in it yet:** the sandbox runs, which need an environment built for each project, and the agent.

## Reproduce
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                       # checks the answer key and the published scores
.venv/bin/python scripts/fetch_repos.py          # the 30 repositories at their pinned commits (about 185 MB)
.venv/bin/python scripts/build_cases.py          # rebuilds data/cases.jsonl
.venv/bin/python scripts/run_baseline.py         # reruns the baseline and rewrites its results
.venv/bin/python scripts/run_commands.py         # checks the documented commands and rewrites their results
.venv/bin/python scripts/run_sandbox.py          # the sandbox's flags and scores, from its kept runs
.venv/bin/python scripts/run_values.py           # the changed-value search
.venv/bin/python scripts/run_model.py            # the model's scores, from its kept answers
.venv/bin/python scripts/run_fixes.py            # the fixes and their scores, from the kept runs and answers
.venv/bin/python scripts/check_tool.py           # the docs-proof tool on every case, against the measured steps
```

To ask the models again (Ollama, with qwen3:8b and granite4:3b, about 15 minutes): `.venv/bin/python scripts/run_model.py --ask`. It asks only for answers that aren't kept yet, so first delete `data/results/model-answers.jsonl`.

To run the commands again, with Docker (about 20 minutes on a 10-core Mac; the image is about 1.1 GB):
```bash
.venv/bin/python scripts/build_sandbox.py        # Python 3.14 and the 26 programs, at the versions in data/sandbox/pins/
.venv/bin/python scripts/run_sandbox.py --run    # runs every documented command, as pinned and after each change
.venv/bin/python scripts/run_fixes.py --run      # runs the rules' fixed commands, after each change
```

To run the agent again (Ollama and Docker, about 15 minutes), delete `data/results/agent-answers.jsonl`, then run `.venv/bin/python scripts/run_fixes.py --agent dev` (every setting) and `--agent test` (the setting chosen on dev). Its fixes for the doc lines step 2 found out of date are judged by hand in `data/hand_check.json`, and the scores aren't written until every new fix is judged.

## License
MIT for the code in this repository. The repositories used for measurement keep their own licenses; they're cloned at a pinned commit when the measurement runs, and never copied here.
