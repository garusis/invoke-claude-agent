# AGENTS.md

Instructions for agents contributing to this repository.

## Scope

This repository is a single Codex skill for invoking Claude Code background
agents directly. Keep it independent from Cowork and other orchestration
frameworks. Do not add backend-selection gates, package state machines, receipt
systems, or unrelated agent providers.

The skill must remain useful in two layers:

1. `SKILL.md` tells Codex when and how to use the capability.
2. `scripts/claude_agent.py` performs routine operations deterministically.

When behavior changes, update the instructions, helper, tests, and README where
the change affects them.

## Non-negotiable behavior

- Invoke subprocesses with argument arrays and `shell=False`.
- Never emit raw prompt text in command metadata or dry-run output.
- Use a fresh UUID for every new session.
- Require the full session UUID for resume operations.
- Refuse to resume an active session unless the caller explicitly requests
  `--stop-first`; dry runs must never stop or launch anything.
- Preserve the requested model, effort, permission mode, working directory, and
  session identity in operation output.
- Keep `Agent` and `Task` disabled for directly invoked workers.
- Bound log output and treat agent claims as advisory.
- Do not add implicit permission to commit, push, publish, spend, or communicate
  externally.

## Development workflow

Use Python's standard library unless a dependency has a concrete, compelling
benefit. Support Python 3.9 or newer.

Run before committing:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Tests must be offline and use a fake Claude executable. Never start a real model
session from the test suite. Test meaningful behavior such as command assembly,
prompt redaction, session matching, active-session protection, bounded logs, and
failure handling; avoid tests that merely assert documentation wording.

## CLI compatibility

The installed Claude CLI is the source of truth for flags. Inspect
`claude --help` and the relevant subcommand help before changing an invocation.
Keep provider-specific details inside the helper rather than duplicating them
throughout `SKILL.md`.

If a Claude CLI change cannot be represented safely, fail with a clear JSON
error. Do not silently fall back to a different model, session, permission mode,
or interactive command.

## Repository hygiene

- Keep executable scripts executable.
- Do not commit prompts, logs, session records, credentials, or generated agent
  artifacts.
- Keep changes narrowly scoped and use conventional commit messages.
- Do not commit or push unless the current user request authorizes it.
