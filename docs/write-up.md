# Building docs-proof: what I measured, and what I learned

docs-proof finds the lines in a project's docs that a code change made wrong, and proves each one: it runs the documented command, or it points to the code line that contradicts the doc. It suggests a fix for each line and changes nothing without a person's yes. It runs as a command, as a GitHub Action, and as an MCP server for AI assistants, and it uses no AI unless you ask it to.

I set myself one rule: no claim without a number behind it. This write-up follows the project in order, with the numbers that shaped each decision. The details are in the [README](../README.md) and the results pages it links.

## The problem
Docs drift is common, even in well-run projects. In GitHub's 2017 Open Source Survey, 93% of respondents called incomplete or outdated documentation a pervasive problem. More than a quarter of the 1,000 most popular GitHub projects had at least one outdated reference to code in their docs (Tan, Wagner, and Treude, ICSME 2023). And in a 2026 study of pull requests from 714 repositories, only 0.8% changed the README (Gao et al.).

## An answer key from planted changes
To measure a checker, I needed changes whose wrong doc lines were known in advance.
- **The key:** 246 changes planted one at a time in 30 popular Python projects with permissive licenses, each pinned to a commit: a renamed option, function, environment variable, or file, a changed default, or a raised minimum Python version. Each case records the doc lines it makes wrong, 587 in all. The projects are split by repository: 116 cases for choosing settings (dev) and 130 for the final score (test).
- **Exact checks first, with no AI:** a search for names the change removed. On test it found all 338 rename lines, with 7 false alarms (precision 98.0%), and none of the 25 changed-value lines.
- **That 100% is by design.** A rename case's expected lines are the doc lines that still name the old name, so a search for removed names finds all of them. Those cases really test false alarms.
- **Reading the "false alarms" one by one paid off.** Several turned out to name the project's own class through a short module name. The key had missed them, so I fixed the key and corrected the numbers I'd published.

## Commands in the docs, read and then run
- **Read the way a shell reads them:** documented commands' options were compared with the options the code declares. On test it flagged 47 of the 174 renamed-option lines, with no false alarms. An audit of the projects as they are found 2,855 documented commands, and its 5 findings were all false alarms on a closer look.
- **Then run in a sandbox:** each command ran in Docker with no network, and the program stopped right after reading its command line, so nothing it would do was done. On test it flagged 28 of the 174 lines, with no false alarms, and its proof is the program's own error message.
- **Running finds fewer lines than reading, for a real reason.** argparse and optparse accept a unique prefix of an option's name, so after `--x` became `--x2`, a command with `--x` still works. Reading finds every stale name; running proves which commands break.
- **The audit found real errors:** of 1,678 distinct command lines, 7 doc lines in 5 projects were out of date, each confirmed on the project's main branch.

## Changed values, and a local model
A changed default keeps every name, so exact checks can't see it.
- **A wide search** for doc lines that show the old value found all 25 test lines, with 10 false alarms (precision 71.4%).
- **A local model** (qwen3:8b through Ollama, chosen on dev from 2 models and 4 prompts) then read each line in context. It kept 23 of the 25, with 7 false alarms (precision 76.7%). F1 went from 0.833 to 0.837: an 8B local model barely helped here, and I report it that way.

## Suggested fixes, and why each one needs a yes
- **Rules first:** a rename puts the new name where the old one was, and a changed value puts the new value where the old one was. On test they fixed 358 of the 363 lines the change made wrong, all of them right, and declined 5. Every fixed line in a documented command was run again in the sandbox, and the program took all 51 of them.
- **An agent for the rest:** qwen3:8b, working only through read-only tools, with a turn limit and loop detection. Of the 5 lines, it fixed 3 right and 1 wrong, and left 1 for a person.
- **Every false alarm got a fix too** (17 of 17). A fix is only as right as the flag behind it, so the fixes become one patch, and nothing changes until a person says yes to that exact patch.

## Three ways to use it
- **A command:** on all 246 cases, it flags exactly the 612 lines the measured steps flag, and offers exactly their 598 rule fixes.
- **A GitHub Action:** it reports in the job summary and with a warning on each flagged line, needs no write permission, and comments on a pull request only when asked.
- **An MCP server:** two read-only tools that give assistants such as Claude Code the command's findings.

## Real history: what it would have caught
Planted changes measure what the tool was built to find. Real history measures what it would have caught in practice.
- **A second key, nobody planted it:** commits in the same projects' history since 2020 that removed a name from the code while doc lines still mentioned it, with the lines a later commit had to fix. I mined 36 cases with rules worked out on dev and read every one by hand before running docs-proof on any of them; 27 were real.
- **On test, it would have flagged 7 of the 23 lines (30.4%).** On dev, 19 of 30 (63.3%).
- **The misses come from what it compares, not how it matches.** It flagged every line whose name its exact check compares, 7 of 7 on test and 19 of 19 on dev. The rest name methods, parameters, other libraries' names, dependencies, or values.
- **The lines stayed wrong a long time:** on test, a median of 447 days, and up to 1,424.

## My own projects found what both keys missed
I ran it on every pull request merged into my two public projects, 33 in all. Control Finder had nothing flagged. Car Safety Checker had 23 false alarms in one pull request: it removed a function named `records`, and every sentence that uses the word "records" was flagged.
- **The answer key could never show this.** It renames only names that can't be ordinary words, such as `fetch_items`, and the real-history key reads code names only in backticks.
- **The rule it led to:** a removed function or class whose name could be an ordinary word counts only where the doc marks it as code, in backticks, in a code block, as a call, or after a dot. It changed no result on either key and removed all 23 false alarms. For the same reason the keys never had such a name, neither can measure what the rule costs.

## The fixes, against the real ones
Each real-history line was later fixed by a person, so their fix shows what the line became. I judged each of docs-proof's 23 fixes against the code after the change.
- **14 right, 6 incomplete, 3 wrong.** On dev, all 18 used the right new name; the incomplete ones left something else stale, such as a help line's old description.
- **The wrong ones taught the most.** coverage.py replaced three tracer variables with a different scheme, and the rules paired them one to one because the names looked alike. Pairing can't tell a rename from a replacement.
- **A stricter check I'd deferred was measured and not added.** It would allow a fix to change a line only where the old name is. On dev it stopped none of the agent's fixes, and the people who fixed these lines changed more than the old name in 7 of the 14 lines they edited. Its only benefit showed on test, where it would have stopped 2 bad agent fixes, so it stays a known limit.

## What I'd do next
- **Compare more kinds of names:** methods, parameters, and attributes, which most real misses named.
- **Pair with care:** when a change removes several names and adds several, say the pairing is a guess instead of offering a confident fix.
- **Fix the rest of a line:** a help line needs its new description, not only the new option.
- **Bring the sandbox and the agent into the command,** so its users get the run proofs and the harder fixes.

## How it's checked
- Every change runs the whole test suite in GitHub Actions, pinned to exact commits, with read-only permissions. Another CI job runs the Action itself, and a third rebuilds the answer key and its results from the pinned projects, recomputes the rest from the kept runs, and checks that nothing changed.
- Every step planted bugs on purpose to test its tests, and every one was caught; when one wasn't at first, a test was added for it.
- The key and every result rebuild byte for byte the same on macOS and on Linux, and every number in the README and this write-up is checked by a test.
- Every model answer and sandbox run is kept, so CI recomputes every score without running a model or Docker.
- It costs $0 to run: local models through Ollama, and public projects with permissive licenses.
