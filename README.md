# docs-proof

Finds the lines in your docs that a code change made wrong, and proves each one: it runs the documented command, or it quotes the code line that contradicts the doc. It suggests a fix and changes nothing without your approval. Its accuracy is measured against an answer key built from real open-source repositories, and every result is published.

**Status:** in progress. Done: the answer key, a baseline of exact checks, the commands in the docs (read, and run in a sandbox), changed values (a search, then a local model), suggested fixes (rules, then an agent, with approval before anything changes), the tools (a command-line tool, a GitHub Action, and an MCP server), real history as a second answer key, a check on my own projects, and a rule for names that could be ordinary words. Next: the fixes, measured on the real-history key, then the write-up. The steps are in [docs/plan.md](docs/plan.md).

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

**A name that could be an ordinary word,** such as a function named `records`, counts only where the doc marks it as code: in a code block, in backticks, as a call, or after a dot. Otherwise every sentence that uses the word is flagged, as on one of my own projects (below). The answer key renames only names that can't be ordinary words, such as `fetch_items` or `PluginSQL`, so the rule changed no result on either answer key. For the same reason, neither key can measure what it costs: a real mention of such a name in a plain sentence.

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

## Real history
The planted changes measure what docs-proof was built to find. A second answer key measures what it would have caught in practice: it comes from the same 30 repositories' own history since 2020, and nobody planted it ([docs/results/real.md](docs/results/real.md)).
- **A case** is a commit that removed an option, a name, an environment variable, or a file from the code while doc lines still mentioned it. Its expected lines are the ones a later commit had to fix.
- **Mined, then checked by hand:** the mining rules were worked out on dev only, and fixed before test was mined. Every case was read by hand before docs-proof ran on any of them, and 27 of the 36 were real ([data/hand_check.json](data/hand_check.json)).
- **Test** (12 cases, 23 lines): reading the code just before and just after each change, with no AI, docs-proof would have flagged 7 of the 23 lines (30.4%), and every line in 4 of the 12 cases. On dev, it would have flagged 19 of 30 (63.3%).
- **Why it misses:** it flagged every line whose name its exact check compares, 7 of 7 on test (19 of 19 on dev). The other 16 test lines name what it doesn't compare: a method (alembic's `compare_against_backend()`), another library's name (livereload's `Server`), a dependency (`sphinx_rtd_theme`), or a value (autopep8's `W690` fixer). So on real history, its misses come from what it compares, not from how it matches doc lines.
- **How long the lines stayed wrong:** on test, a median of 447 days over the 23 lines, and up to 1,424 days (alembic's `SafeConfigParser`, almost 4 years). On dev, a median of 18 days, with 9 of the 30 lines fixed the same day.
- **Not scored:** it also flagged 30 lines the key doesn't list, since the key lists only the lines its rules matched to a later fix. By the pinned commit, 20 of them had changed, 13 in a commit that fixed one of the case's key lines. A hand check of the 10 still there found 4 false alarms and 6 unclear.

## On my own projects
docs-proof checked every pull request merged into main in my two public projects, [Car Safety Checker](https://github.com/Ronak-Mahidharia/car-safety-checker) and [Control Finder](https://github.com/Ronak-Mahidharia/control-finder), the way its GitHub Action would have: just before and just after each merge, with no AI ([docs/results/own.md](docs/results/own.md)).
- **Control Finder** (15 merges): nothing flagged.
- **Car Safety Checker** (18 merges): nothing flagged since the rule for ordinary words (above). Before it, 23 lines were flagged, all in one pull request and all false alarms: that pull request removed a function named `records`, and every flagged line uses "records" as an ordinary word, such as "NHTSA's own records". The suggested fix was wrong too: it paired `records` with an unrelated new function, `words`.
- **What it showed:** neither answer key has a name like this, so checking real projects found a problem the keys couldn't. How an old name is paired with a new one is measured next, on the real-history key.

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

### In GitHub Actions
On a pull request, the action runs the same check and reports it where GitHub shows it: the job summary, a warning on each flagged line, and a failed check. It reads the pull request's code and docs and never runs them, and it needs no write permission.

```yaml
on: pull_request
permissions:
  contents: read
jobs:
  docs-proof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<commit>        # pin each action to a commit
        with:
          fetch-depth: 2                         # the merge commit and its base
          persist-credentials: false
      - uses: Ronak-Mahidharia/docs-proof@<commit>
```

- **A comment on the pull request** is optional: add `comment: true` under `with:`, and `pull-requests: write` under `permissions:`. Later runs update the same comment. On pull requests from forks, GitHub's token is always read-only, so the comment is skipped there, and the job summary still has the report.
- **Inputs:** `base` and `head` (commits), `path` (the repository's folder), and `fail-on-findings: false` to report without failing the check. **Outputs:** `findings`, `fixes`, and `patch`, the suggested fixes as a file.
- **Safe with what a pull request contains:** every input reaches the script through the environment, never pasted into it, and text from the docs is shown only inside code blocks that nothing in it can end.
- **Checked on GitHub's runner** with Python 3.12, in this repository's CI. On a throwaway repository with one option renamed, it must flag that one line, with its fix. It also runs on every pull request here.

### With Claude Code and other assistants (MCP)
The MCP server gives AI assistants two read-only tools: `check_repository` (a change in a git repository, by default the working tree against where the branch started from main) and `check_folders` (the change between two folders). They run the same check as the command. They change no file, run no code, and send nothing anywhere. To make a suggested fix, the assistant edits the doc itself, and Claude Code asks you first.

```bash
pip install -e . -r requirements-mcp.txt        # the official MCP Python SDK and its pinned dependencies
claude mcp add --scope user docs-proof -- "$PWD/.venv/bin/python" -m docsproof.mcp_server
```

- **The same answers as the command:** its tests compare the two, through a real MCP client, in-process and over stdio.
- **Its dependencies:** mcp 2.3.0 and the 27 packages it installs, all with permissive licenses, pinned in [requirements-mcp.txt](requirements-mcp.txt). pip-audit found no known vulnerabilities in them. The rest of docs-proof still uses only Python's standard library.
- **Other MCP clients** start it the same way: `python -m docsproof.mcp_server`, over stdio.

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
.venv/bin/python scripts/run_real.py             # the real-history scores, from the kept results
.venv/bin/python scripts/check_own.py            # the check on my own projects, from the kept results
```

To ask the models again (Ollama, with qwen3:8b and granite4:3b, about 15 minutes): `.venv/bin/python scripts/run_model.py --ask`. It asks only for answers that aren't kept yet, so first delete `data/results/model-answers.jsonl`.

To run the commands again, with Docker (about 20 minutes on a 10-core Mac; the image is about 1.1 GB):
```bash
.venv/bin/python scripts/build_sandbox.py        # Python 3.14 and the 26 programs, at the versions in data/sandbox/pins/
.venv/bin/python scripts/run_sandbox.py --run    # runs every documented command, as pinned and after each change
.venv/bin/python scripts/run_fixes.py --run      # runs the rules' fixed commands, after each change
```

To run the agent again (Ollama and Docker, about 15 minutes), delete `data/results/agent-answers.jsonl`, then run `.venv/bin/python scripts/run_fixes.py --agent dev` (every setting) and `--agent test` (the setting chosen on dev). Its fixes for the doc lines step 2 found out of date are judged by hand in `data/hand_check.json`, and the scores aren't written until every new fix is judged.

To mine the real history again (about 6 minutes on a 10-core Mac; the histories are about 218 MB):
```bash
.venv/bin/python scripts/fetch_history.py        # each repository's history since 2020, up to its pinned commit
.venv/bin/python scripts/build_real_cases.py     # mines the cases, then keeps the ones the hand check found real
.venv/bin/python scripts/run_real.py --run       # runs docs-proof on each case, the way it would have run on the day
```
The mining stops if it finds a case that hasn't been checked by hand, and the scores aren't written until every flagged line that's still there has been read.

To check my own projects again (a few seconds; it fetches their history): `.venv/bin/python scripts/check_own.py --run`. The scores aren't written until every flagged line has a hand verdict.

## License
MIT for the code in this repository. The repositories used for measurement keep their own licenses; they're cloned at a pinned commit when the measurement runs, and never copied here.
