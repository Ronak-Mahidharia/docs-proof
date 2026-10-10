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
2. **Real history (step 6).** Pull requests in public repositories whose docs were corrected by a later commit. The correction shows which lines were wrong.

**What's committed:** only repository names, commit hashes, the planted edits, and line numbers. The repositories are cloned at run time, and their licenses are recorded.

**Not reused:** Gao et al.'s study (2026) publishes its outputs at [Haoyu-Gao/README-auto-update](https://github.com/Haoyu-Gao/README-auto-update), but that repository has no license, so its data isn't used here. Its published numbers are cited for context only.

## Steps
1. **The answer key and an exact-check baseline, with no AI.** The baseline flags doc lines that still mention what the change removed or renamed. Measured: precision and recall for each kind of change.
2. **Commands.** It runs the commands in the docs' code blocks before and after the change, in a sandbox with an allowlist and a time limit, and flags the ones that start failing, with their output as proof.
3. **A model for what exact checks miss,** such as a changed default or a changed behavior:
   - **Search first:** it reads the diff and the doc sections that a search finds (RAG).
   - **Structured findings:** each finding must quote the doc line and the code line, and a finding without both quotes is dropped.
   - **Routing:** exact checks run first, and the model handles only the rest. Local models through Ollama come first.
4. **Suggested fixes.** It opens a fix pull request only after approval: an agent with step limits and loop detection.
5. **The tools:**
   - a command-line tool
   - a GitHub Action that comments on pull requests
   - an MCP server for Claude Code and other MCP clients
6. **Real history** as a second answer key, plus a check on my own repositories.
7. **The write-up and a demo.**

## Rules
- **Doc and pull-request text is untrusted.** It can try to steer the model (prompt injection), so it's passed to the model as data, and commands run only in the sandbox.
- **Every number in the README is checked by a test.**
- **It's free to run:** local models, and GitHub Actions for public repositories.
- **Use it only on code you're allowed to share with an AI model.**
