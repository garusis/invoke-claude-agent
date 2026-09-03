# Deterministic Claude model selection

Policy reviewed against Anthropic's official documentation on 2026-09-03.

## Allowed models

| Task class | Claude model | Exact CLI model ID | Use for |
| --- | --- | --- | --- |
| `standard` | Sonnet 5 | `claude-sonnet-5` | Well-specified, bounded work where speed and cost matter. |
| `complex` | Opus 5 | `claude-opus-5` | Complex agentic coding and knowledge work; default when uncertain. |
| `frontier` | Fable 5.1 | `claude-fable-5-1` | Exceptionally demanding reasoning and long-horizon agentic work. |

No other model or alias is permitted by the helper.

## Task guide

### Sonnet 5: standard work

Choose `standard` for tasks with a clear solution space and bounded execution:

- targeted code generation or a localized bug fix;
- routine tests, documentation, transformations, or content production;
- straightforward data analysis and visual understanding;
- short or medium tool-use sequences with explicit acceptance criteria;
- high-volume work where fast responses and lower per-token cost matter.

Anthropic describes Sonnet 5 as the best combination of speed and intelligence,
with its largest gains in coding and agentic tasks. It is the fastest and least
expensive of the three models allowed by this skill.

### Opus 5: complex work and the default

Choose `complex` for tasks where stronger judgment and sustained autonomy are
material:

- multi-file or cross-cutting implementation;
- architecture and systems-engineering decisions;
- large refactors and difficult debugging across components;
- advanced research, professional knowledge work, or tool-heavy workflows;
- ambiguous work that must form and revise a plan while executing;
- independent review of a consequential or technically complex candidate.

Anthropic describes Opus 5 as intended for complex agentic coding and enterprise
work and recommends starting with it for most workloads. Therefore this skill
selects Opus 5 when neither a task class nor an explicit model is provided.

### Fable 5.1: frontier work

Choose `frontier` only when the task genuinely requires unusually deep thought
or a long horizon:

- long-running autonomous coding with many dependent stages;
- demanding reasoning where errors emerge only after extended analysis;
- multistep research or synthesis across a very large context;
- complex document, spreadsheet, or slide work that requires long-lived state;
- a task for which a representative attempt or evaluation on Opus 5 at higher
  effort still falls short.

Fable 5.1 is the slowest and has the highest per-token price of the three. Its
extra capability should be reserved for work that needs it, not merely work that
is important. Anthropic specifically positions it for demanding reasoning and
long-horizon agentic work, and recommends it when Opus 5 at higher effort is
insufficient.

## Resolution rules

The helper applies these rules without model inference from free-form prompt
text:

1. An explicit `--model` is accepted only if it is one of the three exact IDs.
2. Otherwise, an explicit `--task-class` maps through the table above.
3. If neither is supplied, select `complex` and `claude-opus-5`.
4. `--model` and `--task-class` are mutually exclusive.
5. Resume requires the exact model ID used by the original session. To change
   models, start a fresh session with a compact handoff.
6. Never auto-escalate to a more expensive model after failure. Reclassification
   must be an explicit supervisor or user decision.

Use `scripts/claude_agent.py select-model [--task-class ...]` to inspect the
decision without launching a model.

## Official sources

- [Anthropic models overview](https://platform.claude.com/docs/en/models/overview)
- [Choosing the right model](https://platform.claude.com/docs/en/docs/about-claude/models/choosing-a-model)
- [Claude Fable 5.1 overview](https://platform.claude.com/docs/en/models/fable-5-1/overview)
- [What's new in Claude Opus 5](https://platform.claude.com/docs/en/models/opus-5/whats-new-opus-5)
- [What's new in Claude Sonnet 5](https://platform.claude.com/docs/en/models/sonnet-5/whats-new-sonnet-5)
- [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
