---
name: invoke-claude-agent
description: Launch, communicate with, supervise, and collect work from direct Claude Code background agents. Use when asked to invoke, run, spin up, or delegate a bounded task to Claude directly without Cowork. Do not use for Cowork workflow orchestration or Codex-native subagents.
---

# Invoke Claude Agent

Use the installed `claude` CLI directly. Keep this workflow operational: define
one bounded assignment, start one Claude session, communicate through that exact
session, and verify its result. Do not introduce Cowork packages, backend gates,
receipts, or phase machinery.

Use [`scripts/claude_agent.py`](scripts/claude_agent.py) for all routine agent
operations. It owns UUID generation, safe argument assembly, prompt redaction,
background-agent lookup, active-session checks, bounded logs, and JSON output.
Invoke `python3 <skill-dir>/scripts/claude_agent.py --help` when command details
are needed. Call the raw `claude` CLI only if the helper cannot represent a
required operation, and report that deviation.

## Prepare the assignment

Before launch, choose and record:

- one role: investigator, planner, implementer, or reviewer;
- the exact working directory and any additional allowed directories;
- the objective, allowed paths/actions, exclusions, and stopping condition;
- the requested model, effort, and permission mode;
- the expected result shape and verification commands;
- whether commits, pushes, pull requests, spending, or external messages are
  authorized. Never infer these permissions.

Give the agent a self-contained prompt, not a transcript. Include the role,
objective, relevant context or file paths, boundaries, acceptance criteria, and
the concise result it must return. Tell it to report blockers instead of widening
scope.

## Start a fresh background agent

Confirm the CLI exists with `claude --version`. The working directory must
already be trusted. The helper generates a fresh UUID and returns both the full
session UUID and Claude's background-agent record.

Launch with a prompt file when practical so multiline instructions do not need
shell escaping:

```bash
python3 <skill-dir>/scripts/claude_agent.py launch \
  --cwd "<working-directory>" \
  --role "<investigator|planner|implementer|reviewer>" \
  --name "<short-role-and-task>" \
  --model "<model>" \
  --effort "<low|medium|high|xhigh|max>" \
  --prompt-file "<assignment-file>"
```

The helper defaults to `plan` for investigation, planning, and review, and
`auto` for implementation. Override with `--permission-mode` only when the task
requires it. Pass `--disallow Bash` when a reviewer must inspect without running
commands. Pass `--add-dir <path>` only for an explicitly allowed directory.

Use `--safe-mode` when isolation from user/project Claude customizations is more
important than loading their instructions. Otherwise omit it intentionally.
Never use `--dangerously-skip-permissions` unless the user explicitly authorizes
it and the environment is appropriately isolated.

Pin `--model` and `--effort` when identity matters. Preserve the requested
identity and, when stream events expose it, the effective model actually used.
Do not silently substitute a different model.

When machine-readable output matters, pass `--schema-file <json-schema>` and
tell the agent to return only that outcome. Keep control metadata and secrets out
of the prompt and logs. Use `--dry-run` to validate launch construction without
starting Claude; the helper returns only a prompt hash and byte count.

## Observe the agent

Use the helper's read-only commands:

```bash
python3 <skill-dir>/scripts/claude_agent.py list --cwd "<working-directory>" --all
python3 <skill-dir>/scripts/claude_agent.py status --id "<agent-or-session-id>"
python3 <skill-dir>/scripts/claude_agent.py logs --id "<background-agent-id>"
```

Inspect status once per meaningful checkpoint; do not tight-poll or continuously
tail normal output. Treat logs as diagnostics, not proof that the task succeeded.
Validate claimed edits and checks independently in the working directory.

Use the raw `claude attach <background-agent-id>` only when an interactive
handoff is actually useful. Detaching from that view leaves the agent running.

## Communicate and redirect

Do not resume a session while it is still running: current Claude versions may
start a copy instead of injecting the message into the active process.

For ordinary follow-up, wait until the turn is quiescent, then resume the exact
full session UUID with the same model, effort, and permission mode:

```bash
python3 <skill-dir>/scripts/claude_agent.py resume \
  --session-id "<full-session-uuid>" \
  --cwd "<same-working-directory>" \
  --model "<same-model>" \
  --effort "<same-effort>" \
  --permission-mode "<same-mode>" \
  --prompt-file "<compact-follow-up-file>"
```

A follow-up should state what changed, the exact next action, unresolved
findings, and the remaining scope. Do not replay the whole prior prompt.

The helper rejects resuming an active session. If an active agent must be
redirected, use `stop --id <agent-id>` first, or pass `--stop-first` to `resume`
only when stopping it is explicitly intended. Both paths preserve the
conversation and working-tree edits. Use a fresh session instead when the role
changes, the context changed materially, or independent judgment is required.

## Separate roles and collect results

Use fresh sessions for planner, implementer, and reviewer work. A reviewer must
be independent from the implementer and should receive the objective, relevant
diff or changed paths, and acceptance criteria—not the implementer's chat.

At completion:

1. Run `collect --id <agent-id> --cwd <working-directory>` to capture the final
   state, bounded log tail, changed paths, and diff statistics.
2. Inspect the actual changed paths and diff where needed.
3. Run the required checks independently; worker claims are advisory.
4. Report the outcome, changed paths, verification results, unresolved findings,
   and whether any additional authority is needed.

Stop on a scope or permission request rather than granting it implicitly. On a
provider quota or capacity failure, preserve the session and partial work and do
not loop, enable paid overage, or invent a reset time. Resume only after a real
capacity signal or explicit user direction.
