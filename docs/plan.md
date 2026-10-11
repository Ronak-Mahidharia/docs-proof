# Plan

**The goal:** on a pull request, find the doc lines the change made wrong, prove each one, and suggest a fix. Every claim about accuracy comes from an answer key, measured the same way each time.

## The answer key
Two kinds of cases. Both are split into dev and test by repository, so no repository appears in both, and test is scored only at the end of each step.

1. **Planted changes (step 1).** Real open-source repositories with permissive licenses, pinned to a commit. A script makes one realistic change at a time and records which doc lines that change makes wrong:
   - a renamed command-line option, function, class, file, or environment variable
   - a changed default value
   - a raised minimum Python version
   - a removed option or command

   **A lesson from an earlier project:** an answer key that plain text search already solves can't tell better methods apart. So the key mixes changes that leave the old name in the docs, which exact search can find, with changes it can't find by name, such as a changed default described in a sentence. Each kind is scored separately.
2. **Real history (step 6).** Commits in the same repositories' history that left doc lines wrong, found from the later commit that corrected them. The correction shows which lines were wrong; nothing is planted.

**What's committed:** repository names, commit hashes, the planted edits, line numbers, and a hash of each expected line; the hand-check notes quote a few words where a decision needs it. The repositories are cloned at run time, and their licenses are recorded.

**Not reused:** Gao et al.'s study (2026) publishes its outputs at [Haoyu-Gao/README-auto-update](https://github.com/Haoyu-Gao/README-auto-update), but that repository has no license, so its data isn't used here. Its published numbers are cited for context only.

## Steps
1. **The answer key and an exact-check baseline, with no AI.** The baseline flags doc lines that still mention what the change removed or renamed. Measured: precision and recall for each kind of change.
   **Done:** 246 cases in 30 repositories. On test, the baseline found all 350 rename lines with 7 false alarms, and 0 of 25 changed-value lines ([results](results/exact.md)).
2. **Commands,** in two halves:
   - **Read, not run:** it reads the commands in the docs the way a shell does, and checks their options against the options the code declares. **Done:** on test, it flagged 48 of the 175 renamed-option lines with no false alarms, and an audit of 2,868 documented commands found none out of date ([results](results/commands.md)).
   - **Run:** it runs the commands in the docs' code blocks before and after the change, in a sandbox with an allowlist and a time limit, and flags the ones that start failing, with their output as proof. **Done:** on test, it flagged 29 of the 175 renamed-option lines with no false alarms, and an audit of 1,678 command lines found 7 doc lines in 5 projects that their programs refuse ([results](results/run.md)).
3. **A model for what exact checks miss,** such as a changed default or a changed behavior:
   - **Search first:** it reads the diff and the doc sections that a search finds (RAG).
   - **Structured findings:** each finding must quote the doc line and the code line, and a finding without both quotes is dropped.
   - **Routing:** exact checks run first, and the model handles only the rest. Local models through Ollama come first.

   **Done:** on test, a wide search finds all 25 changed-value lines, with 10 false alarms; a local model (qwen3:8b, chosen on dev) removes 3 of them but drops 2 right lines, so F1 stays about the same (0.837 against 0.833) ([results](results/values.md)).
4. **Suggested fixes.** It opens a fix pull request only after approval: an agent with step limits and loop detection.
   **Done:** on test, the rules fix 370 of the 375 lines the change made wrong, all right, and the agent fixes 3 of the other 5 right; but every false alarm gets a fix too (17 of 17), so a fix waits for a person's yes ([results](results/fixes.md)).
5. **The tools:**
   - a command-line tool
   - a GitHub Action that comments on pull requests
   - an MCP server for Claude Code and other MCP clients

   **Done:**
   - the command-line tool: on all 246 cases it flags exactly the 626 lines the measured steps flag, and offers exactly step 4's 612 rule fixes ([the check](../scripts/check_tool.py))
   - the GitHub Action ([action.yml](../action.yml)): it reports in the job summary and with warnings on the flagged lines, needs no write permission, and comments on the pull request only when asked to. CI runs it on a throwaway repository and on every pull request here
   - the MCP server ([src/docsproof/mcp_server.py](../src/docsproof/mcp_server.py)): two read-only tools that give assistants such as Claude Code the command's findings; its tests compare the two, in-process and over stdio
6. **Real history** as a second answer key, plus a check on my own repositories.
   **Done:** the key: 27 real cases, of 36 mined, in the 30 repositories' history since 2020. On test, docs-proof would have flagged 7 of the 23 lines a later commit fixed (30.4%), including every line whose name it compares ([results](results/real.md)). Next: the check on my own repositories.
7. **The write-up and a demo.**

## Rules
- **Doc and pull-request text is untrusted.** It can try to steer the model (prompt injection), so it's passed to the model as data, and commands run only in the sandbox.
- **Every number in the README is checked by a test.**
- **It's free to run:** local models, and GitHub Actions for public repositories.
- **Use it only on code you're allowed to share with an AI model.**
