#!/usr/bin/env python3
"""Operate Claude Code background agents without a shell wrapper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from typing import Any, Sequence


ROLE_MODES = {
    "investigator": "plan",
    "planner": "plan",
    "implementer": "auto",
    "reviewer": "plan",
}
MODELS_BY_TASK_CLASS = {
    "standard": "claude-sonnet-5",
    "complex": "claude-opus-5",
    "frontier": "claude-fable-5-1",
}
ALLOWED_MODELS = tuple(MODELS_BY_TASK_CLASS.values())
DEFAULT_TASK_CLASS = "complex"
ACTIVE_STATES = {"working", "starting", "running"}
ACTIVE_STATUSES = {"busy", "working", "starting"}


class AgentError(RuntimeError):
    pass


def emit(payload: dict[str, Any], code: int = 0) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


def claude_executable(value: str) -> str:
    resolved = shutil.which(value) if os.sep not in value else value
    if not resolved or not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
        raise AgentError(f"Claude executable not found or not executable: {value}")
    return os.path.realpath(resolved)


def working_directory(value: str) -> str:
    path = os.path.realpath(value)
    if not os.path.isdir(path):
        raise AgentError(f"Working directory does not exist: {value}")
    return path


def read_prompt(args: argparse.Namespace) -> str:
    if bool(args.prompt) == bool(args.prompt_file):
        raise AgentError("Provide exactly one of --prompt or --prompt-file")
    if args.prompt:
        text = args.prompt
    else:
        path = Path(args.prompt_file)
        if not path.is_file() or path.is_symlink():
            raise AgentError("Prompt file must be a regular, non-symlink file")
        text = path.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        raise AgentError("Prompt must not be empty")
    return text


def read_schema(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file() or path.is_symlink():
        raise AgentError("Schema file must be a regular, non-symlink file")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentError(f"Invalid JSON schema file: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AgentError("JSON schema root must be an object")
    return json.dumps(parsed, separators=(",", ":"), sort_keys=True)


def invoke(argv: Sequence[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(argv), cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise AgentError(f"Failed to execute Claude CLI: {type(exc).__name__}") from exc
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown CLI failure"
        raise AgentError(f"Claude CLI exited {result.returncode}: {message[-2000:]}")
    return result


def agent_rows(executable: str, cwd_filter: str | None = None, include_all: bool = True) -> list[dict[str, Any]]:
    argv = [executable, "agents", "--json"]
    if cwd_filter:
        argv += ["--cwd", cwd_filter]
    if include_all:
        argv.append("--all")
    result = invoke(argv)
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AgentError("Claude returned malformed agent-list JSON") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise AgentError("Claude returned an unexpected agent-list shape")
    return rows


def matches(row: dict[str, Any], identifier: str) -> bool:
    return row.get("id") == identifier or row.get("sessionId") == identifier


def find_agent(rows: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    found = [row for row in rows if matches(row, identifier)]
    if not found:
        raise AgentError(f"Claude agent not found: {identifier}")
    if len(found) != 1:
        raise AgentError(f"Claude agent identifier is ambiguous: {identifier}")
    return found[0]


def is_active(row: dict[str, Any]) -> bool:
    return row.get("state") in ACTIVE_STATES or row.get("status") in ACTIVE_STATUSES


def prompt_fingerprint(text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def add_execution_options(
    parser: argparse.ArgumentParser, *, role: bool, require_model: bool,
) -> None:
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    if role:
        parser.add_argument("--role", required=True, choices=sorted(ROLE_MODES))
        parser.add_argument("--name", required=True)
    else:
        parser.add_argument("--name")
    parser.add_argument("--model", required=require_model, choices=ALLOWED_MODELS)
    if not require_model:
        parser.add_argument("--task-class", choices=tuple(MODELS_BY_TASK_CLASS))
    parser.add_argument("--effort", required=True, choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--permission-mode", choices=("plan", "auto", "acceptEdits", "dontAsk", "manual"))
    parser.add_argument(
        "--bypass-permissions", action="store_true",
        help="explicitly run with bypassPermissions; never enabled by default",
    )
    parser.add_argument("--add-dir", action="append", default=[])
    parser.add_argument("--disallow", action="append", default=[])
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--schema-file")
    parser.add_argument("--dry-run", action="store_true")


def resolve_model(args: argparse.Namespace) -> tuple[str, str, str]:
    task_class = getattr(args, "task_class", None)
    if args.model and task_class:
        raise AgentError("Choose either --model or --task-class, not both")
    if args.model:
        inferred = next(
            key for key, value in MODELS_BY_TASK_CLASS.items() if value == args.model
        )
        return args.model, inferred, "explicit_model"
    selected_class = task_class or DEFAULT_TASK_CLASS
    return MODELS_BY_TASK_CLASS[selected_class], selected_class, (
        "task_class" if task_class else "default"
    )


def resolve_permission_mode(args: argparse.Namespace) -> str:
    if args.bypass_permissions and args.permission_mode:
        raise AgentError(
            "Choose either --bypass-permissions or --permission-mode, not both"
        )
    if args.bypass_permissions:
        return "bypassPermissions"
    if args.permission_mode:
        return args.permission_mode
    if not hasattr(args, "role"):
        raise AgentError("--permission-mode is required for resume unless bypass is explicit")
    return ROLE_MODES[args.role]


def execution_argv(
    args: argparse.Namespace, executable: str, prompt: str, *, session_id: str,
    resume: bool, model: str, permission_mode: str,
) -> list[str]:
    disallowed = ["Agent", "Task", *args.disallow]
    argv = [executable, "-p", "--bg"]
    if args.name:
        argv += ["--name", args.name]
    argv += ["--resume" if resume else "--session-id", session_id]
    argv += [
        "--model", model,
        "--effort", args.effort,
        "--permission-mode", permission_mode,
        "--disallowedTools", ",".join(dict.fromkeys(disallowed)),
        "--output-format", "stream-json",
        "--verbose",
    ]
    if args.bypass_permissions:
        argv.append("--allow-dangerously-skip-permissions")
    if args.safe_mode:
        argv.append("--safe-mode")
    for value in args.add_dir:
        argv += ["--add-dir", working_directory(value)]
    schema = read_schema(args.schema_file)
    if schema:
        argv += ["--json-schema", schema]
    argv.append(prompt)
    return argv


def redacted_command(argv: list[str]) -> list[str]:
    return [*argv[:-1], "<prompt>"]


def command_launch(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    cwd = working_directory(args.cwd)
    prompt = read_prompt(args)
    model, task_class, model_source = resolve_model(args)
    permission_mode = resolve_permission_mode(args)
    session_id = str(uuid.uuid4())
    argv = execution_argv(
        args, executable, prompt, session_id=session_id, resume=False,
        model=model, permission_mode=permission_mode,
    )
    base = {
        "operation": "launch",
        "cwd": cwd,
        "session_id": session_id,
        "requested_model": model,
        "task_class": task_class,
        "model_selection_source": model_source,
        "effort": args.effort,
        "permission_mode": permission_mode,
        "bypass_permissions": args.bypass_permissions,
        "prompt": prompt_fingerprint(prompt),
        "command": redacted_command(argv),
    }
    if args.dry_run:
        return {**base, "dry_run": True}
    result = invoke(argv, cwd=cwd)
    rows = agent_rows(executable, cwd_filter=cwd)
    record = next((row for row in rows if row.get("sessionId") == session_id), None)
    return {**base, "dry_run": False, "agent": record, "launcher_output": result.stdout.strip()}


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    cwd = working_directory(args.cwd) if args.cwd else None
    rows = agent_rows(executable, cwd_filter=cwd, include_all=args.all)
    return {"operation": "list", "count": len(rows), "agents": rows}


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    row = find_agent(agent_rows(executable), args.id)
    return {"operation": "status", "active": is_active(row), "agent": row}


def command_logs(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    result = invoke([executable, "logs", args.id])
    text = result.stdout
    truncated = len(text) > args.max_chars
    if truncated:
        text = text[-args.max_chars:]
    return {"operation": "logs", "id": args.id, "truncated": truncated, "text": text}


def command_resume(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    cwd = working_directory(args.cwd)
    prompt = read_prompt(args)
    model, task_class, model_source = resolve_model(args)
    permission_mode = resolve_permission_mode(args)
    rows = agent_rows(executable)
    row = find_agent(rows, args.session_id)
    if row.get("sessionId") != args.session_id:
        raise AgentError("Resume requires the full session UUID, not the short agent ID")
    stopped = False
    would_stop = False
    if is_active(row):
        if not args.stop_first:
            raise AgentError("Session is active; wait for it or pass --stop-first explicitly")
        if args.dry_run:
            would_stop = True
        else:
            invoke([executable, "stop", str(row["id"])])
            stopped = True
    argv = execution_argv(
        args, executable, prompt, session_id=args.session_id, resume=True,
        model=model, permission_mode=permission_mode,
    )
    base = {
        "operation": "resume",
        "cwd": cwd,
        "session_id": args.session_id,
        "prior_agent_id": row.get("id"),
        "stopped_first": stopped,
        "would_stop_first": would_stop,
        "requested_model": model,
        "task_class": task_class,
        "model_selection_source": model_source,
        "effort": args.effort,
        "permission_mode": permission_mode,
        "bypass_permissions": args.bypass_permissions,
        "prompt": prompt_fingerprint(prompt),
        "command": redacted_command(argv),
    }
    if args.dry_run:
        return {**base, "dry_run": True}
    result = invoke(argv, cwd=cwd)
    updated = next(
        (item for item in agent_rows(executable, cwd_filter=cwd) if item.get("sessionId") == args.session_id),
        None,
    )
    return {**base, "dry_run": False, "agent": updated, "launcher_output": result.stdout.strip()}


def command_stop(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    row = find_agent(agent_rows(executable), args.id)
    if not is_active(row):
        return {"operation": "stop", "stopped": False, "reason": "already_quiescent", "agent": row}
    invoke([executable, "stop", str(row["id"])])
    return {"operation": "stop", "stopped": True, "agent_id": row.get("id"), "session_id": row.get("sessionId")}


def git_read(cwd: str, args: Sequence[str]) -> str | None:
    git_bin = shutil.which("git")
    if not git_bin:
        return None
    result = subprocess.run(
        [git_bin, "-C", cwd, *args], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def command_collect(args: argparse.Namespace) -> dict[str, Any]:
    executable = claude_executable(args.claude_bin)
    cwd = working_directory(args.cwd)
    row = find_agent(agent_rows(executable), args.id)
    logs = command_logs(argparse.Namespace(claude_bin=args.claude_bin, id=str(row["id"]), max_chars=args.max_chars))
    status = git_read(cwd, ["status", "--short", "--untracked-files=all"])
    diffstat = git_read(cwd, ["diff", "--stat"])
    return {
        "operation": "collect",
        "agent": row,
        "active": is_active(row),
        "logs": {"truncated": logs["truncated"], "text": logs["text"]},
        "git": {"status": status, "diffstat": diffstat},
        "note": "Agent output is advisory; run required verification independently.",
    }


def command_select_model(args: argparse.Namespace) -> dict[str, Any]:
    task_class = args.task_class or DEFAULT_TASK_CLASS
    return {
        "operation": "select-model",
        "task_class": task_class,
        "model": MODELS_BY_TASK_CLASS[task_class],
        "selection_source": "task_class" if args.task_class else "default",
        "allowed_models": list(ALLOWED_MODELS),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--claude-bin", default="claude")
    sub = root.add_subparsers(dest="command", required=True)

    select_model = sub.add_parser("select-model", help="resolve the deterministic model policy")
    select_model.add_argument("--task-class", choices=tuple(MODELS_BY_TASK_CLASS))
    select_model.set_defaults(handler=command_select_model)

    launch = sub.add_parser("launch", help="start a fresh Claude background agent")
    add_execution_options(launch, role=True, require_model=False)
    launch.set_defaults(handler=command_launch)

    listing = sub.add_parser("list", help="list Claude background agents")
    listing.add_argument("--cwd")
    listing.add_argument("--all", action="store_true")
    listing.set_defaults(handler=command_list)

    status = sub.add_parser("status", help="show one agent's current state")
    status.add_argument("--id", required=True)
    status.set_defaults(handler=command_status)

    logs = sub.add_parser("logs", help="read a bounded tail of agent logs")
    logs.add_argument("--id", required=True)
    logs.add_argument("--max-chars", type=int, default=12000)
    logs.set_defaults(handler=command_logs)

    resume = sub.add_parser("resume", help="send a follow-up to an exact quiescent session")
    resume.add_argument("--session-id", required=True)
    resume.add_argument("--stop-first", action="store_true")
    add_execution_options(resume, role=False, require_model=True)
    resume.set_defaults(handler=command_resume)

    stop = sub.add_parser("stop", help="stop an active agent while preserving its conversation")
    stop.add_argument("--id", required=True)
    stop.set_defaults(handler=command_stop)

    collect = sub.add_parser("collect", help="collect agent state, bounded logs, and git summary")
    collect.add_argument("--id", required=True)
    collect.add_argument("--cwd", required=True)
    collect.add_argument("--max-chars", type=int, default=12000)
    collect.set_defaults(handler=command_collect)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if hasattr(args, "max_chars") and not 1 <= args.max_chars <= 100_000:
        return emit({"ok": False, "error": "--max-chars must be between 1 and 100000"}, 2)
    try:
        return emit({"ok": True, **args.handler(args)})
    except AgentError as exc:
        return emit({"ok": False, "error": str(exc)}, 2)


if __name__ == "__main__":
    sys.exit(main())
