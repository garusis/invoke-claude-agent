# Invoke Claude Agent

A Codex skill for launching and supervising Claude Code background agents
directly, without the Cowork orchestration framework.

The skill provides operational guidance plus a dependency-free Python helper
for creating agents, checking their state, reading bounded logs, sending
follow-up instructions to an exact session, stopping agents safely, and
collecting their output with a Git working-tree summary.

## Requirements

- Codex with local skill support.
- Python 3.9 or newer.
- An authenticated `claude` CLI that supports `--bg`, `claude agents --json`,
  `claude logs`, `claude stop`, and exact-session `--resume`.
- Git for the optional working-tree summary returned by `collect`.

Verify the local dependencies:

```bash
python3 --version
claude --version
claude agents --help
```

## Installation

Clone the repository into the personal Codex skills directory:

```bash
git clone https://github.com/garusis/invoke-claude-agent.git \
  ~/.codex/skills/invoke-claude-agent
```

Restart Codex or begin a new task if the skill does not appear immediately.
Invoke it explicitly with `$invoke-claude-agent`, or ask Codex to launch or
supervise a direct Claude agent.

To update an existing installation:

```bash
git -C ~/.codex/skills/invoke-claude-agent pull --ff-only
```

## Helper commands

The helper always emits JSON and never runs prompt text through a shell:

```bash
python3 scripts/claude_agent.py --help
```

Available operations:

| Command | Purpose |
| --- | --- |
| `launch` | Start a fresh named Claude background agent with a new session UUID. |
| `list` | List native Claude agent records, optionally filtered by directory. |
| `status` | Resolve a short agent ID or full session UUID and report whether it is active. |
| `logs` | Return a bounded tail of the agent's native logs. |
| `resume` | Send a compact follow-up to an exact, quiescent session. |
| `stop` | Stop an active agent while preserving its conversation and edits. |
| `collect` | Return agent state, bounded logs, Git status, and diff statistics. |

Example launch:

```bash
python3 scripts/claude_agent.py launch \
  --cwd /absolute/path/to/project \
  --role implementer \
  --name fix-parser-boundary \
  --model sonnet \
  --effort medium \
  --prompt-file /absolute/path/to/assignment.md
```

Add `--dry-run` to validate the invocation without starting Claude. The output
contains a SHA-256 digest and byte count for the prompt, but not its text.

Example follow-up after the agent is no longer active:

```bash
python3 scripts/claude_agent.py resume \
  --session-id 00000000-0000-4000-8000-000000000000 \
  --cwd /absolute/path/to/project \
  --model sonnet \
  --effort medium \
  --permission-mode auto \
  --prompt-file /absolute/path/to/follow-up.md
```

`resume` requires the full session UUID and refuses to copy or resume an active
session accidentally. Use `--stop-first` only when stopping the active agent is
explicitly intended.

## Permission model

Role presets use `plan` mode for investigators, planners, and reviewers, and
`auto` mode for implementers. Every invocation disables Claude's `Agent` and
`Task` tools so the directly invoked worker cannot silently create another
delegation layer.

The helper does not grant permission to commit, push, publish, spend money, or
contact external parties. Those boundaries belong in the assignment and must
come from the user. Avoid `--dangerously-skip-permissions`; the helper does not
expose it.

## Repository layout

```text
invoke-claude-agent/
├── AGENTS.md
├── README.md
├── SKILL.md
├── agents/openai.yaml
├── scripts/claude_agent.py
└── tests/test_claude_agent.py
```

`SKILL.md` is the Codex entrypoint. `agents/openai.yaml` supplies UI metadata.
The helper contains the execution mechanics, and its tests use a fake Claude
executable so they never start a real model session.

## Development

Run the offline test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Validate the skill structure when the bundled Codex skill validator is
available:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Before changing a CLI flag, compare it with the currently installed
`claude --help`. Keep subprocess calls shell-free, keep prompts out of emitted
metadata, and add an offline regression test for every execution-path change.

## Safety notes

- Treat background-agent logs as potentially sensitive.
- Prefer `--prompt-file` for multiline assignments.
- Do not resume an active session; Claude may create a copy instead of injecting
  the message into the running process.
- Worker output is advisory. Inspect changes and run verification independently.
- On quota or capacity failures, preserve the session and stop retrying until a
  real capacity signal or explicit user direction exists.
