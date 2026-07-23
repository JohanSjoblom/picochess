# AI-assisted contributions

AI can help you contribute to Picochess, but you remain the person submitting the change. Treat AI output as a draft to inspect and test, not as a guarantee.

## Before asking an AI to code

1. Start from an accepted, focused GitHub issue. Link its number in your request.
2. Read the whole issue and any maintainer comments. Ask questions on the issue if the intended behaviour is unclear.
3. Work in your own fork and a branch for that issue. In Codespaces or a local terminal, run:

   ```bash
   ./scripts/contribute ISSUE_NUMBER
   ```

   This creates an issue-named branch and checks that the issue exists.

## A useful prompt

Tell the AI:

```text
I am contributing to Picochess for GitHub issue #NUMBER.
Read AGENTS.md and the issue before editing. Explain the smallest safe plan,
make only the changes needed for the issue, and run the relevant tests using
the repository virtual environment. Do not commit, push, or create a pull
request. Show me the changed files and any limitations.
```

Give the AI the issue text, screenshots, logs with private details removed, and the result you expect. Ask it to explain anything you do not understand.

## Review the change yourself

Before submitting, check:

- Does it solve the issue, rather than a different problem?
- Are the changed files ones you would expect?
- Did it add passwords, API keys, personal paths, generated files, or unrelated refactoring? If so, stop and ask for help.
- Did the tests run? If not, say so honestly in the draft PR.
- If it changes web UI behaviour, did you try it in a browser? If it changes board/clock behaviour, explain what hardware testing was or was not possible.

Then run:

```bash
./scripts/submit-contribution
```

The script shows the changes, runs the unit tests unless you explicitly skip them, asks before staging everything, creates a commit, pushes your branch, and opens a draft PR. You can leave the PR as a draft while asking questions.

## Boundaries for AI tools

Do not give an AI your GitHub token, passwords, Wi-Fi credentials, or private Picochess logs. Do not let it delete files, rewrite history, force-push, or make unrelated “cleanup” changes without understanding and approving that action. Use a fresh branch for each issue.

If the AI is uncertain, that is useful information to include in the PR. Maintainers prefer a small, honest draft over a large, unexplained change.
