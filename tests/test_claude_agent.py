import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "claude_agent.py"


class ClaudeAgentScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake = self.root / "claude"
        self.audit = self.root / "audit.jsonl"
        self.fake.write_text(
            """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_AUDIT'], 'a', encoding='utf-8') as out:
    out.write(json.dumps(args) + '\\n')
if args and args[0] == 'agents':
    print(os.environ.get('FAKE_ROWS', '[]'))
elif args and args[0] == 'logs':
    print('bounded fake log')
elif args and args[0] == 'stop':
    print('stopped')
else:
    print('abc12345')
""",
            encoding="utf-8",
        )
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)
        self.env = os.environ.copy()
        self.env["FAKE_AUDIT"] = str(self.audit)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, *args, rows=None):
        env = self.env.copy()
        if rows is not None:
            env["FAKE_ROWS"] = json.dumps(rows)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--claude-bin", str(self.fake), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        return result, json.loads(result.stdout)

    def audit_rows(self):
        if not self.audit.exists():
            return []
        return [json.loads(line) for line in self.audit.read_text(encoding="utf-8").splitlines()]

    def reset_audit(self):
        if self.audit.exists():
            self.audit.unlink()

    def assert_model_flag(self, argv, expected):
        self.assertIn("--model", argv)
        index = argv.index("--model")
        self.assertLess(index + 1, len(argv))
        self.assertEqual(argv[index + 1], expected)

    def test_launch_dry_run_redacts_prompt_and_does_not_invoke_claude(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "builder", "--model", "claude-sonnet-5", "--effort", "medium",
            "--prompt", "secret task body", "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["permission_mode"], "auto")
        self.assertEqual(payload["requested_model"], "claude-sonnet-5")
        self.assertEqual(payload["command"][-1], "<prompt>")
        self.assertNotIn("secret task body", json.dumps(payload))
        self.assertEqual(self.audit_rows(), [])

    def test_list_returns_native_agent_records(self):
        rows = [{"id": "abcd1234", "sessionId": "00000000-0000-4000-8000-000000000000", "state": "done"}]
        result, payload = self.run_script("list", "--all", rows=rows)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["agents"], rows)

    def test_resume_rejects_active_session_without_explicit_stop(self):
        sid = "00000000-0000-4000-8000-000000000000"
        rows = [{"id": "abcd1234", "sessionId": sid, "state": "working", "status": "busy"}]
        result, payload = self.run_script(
            "resume", "--session-id", sid, "--cwd", str(self.root),
            "--model", "claude-sonnet-5", "--effort", "medium", "--permission-mode", "auto",
            "--prompt", "continue", "--dry-run", rows=rows,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Session is active", payload["error"])

    def test_resume_dry_run_never_stops_active_session(self):
        sid = "00000000-0000-4000-8000-000000000000"
        rows = [{"id": "abcd1234", "sessionId": sid, "state": "working", "status": "busy"}]
        result, payload = self.run_script(
            "resume", "--session-id", sid, "--stop-first", "--cwd", str(self.root),
            "--model", "claude-sonnet-5", "--effort", "medium", "--permission-mode", "auto",
            "--prompt", "redirect", "--dry-run", rows=rows,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["would_stop_first"])
        self.assertFalse(payload["stopped_first"])
        self.assertEqual(self.audit_rows(), [["agents", "--json", "--all"]])

    def test_model_selection_is_deterministic(self):
        expected = {
            None: "claude-opus-5",
            "standard": "claude-sonnet-5",
            "complex": "claude-opus-5",
            "frontier": "claude-fable-5-1",
        }
        for task_class, model in expected.items():
            args = ["select-model"]
            if task_class:
                args += ["--task-class", task_class]
            result, payload = self.run_script(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["model"], model)
            self.assertEqual(
                payload["allowed_models"],
                ["claude-sonnet-5", "claude-opus-5", "claude-fable-5-1"],
            )

    def test_launch_defaults_to_opus_five(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "planner",
            "--name", "planner", "--effort", "high", "--prompt", "plan",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["requested_model"], "claude-opus-5")
        self.assertEqual(payload["task_class"], "complex")
        self.assertEqual(payload["model_selection_source"], "default")

    def test_task_class_selects_model_for_launch(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "frontier-builder", "--task-class", "frontier",
            "--effort", "high", "--prompt", "solve hard task", "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["requested_model"], "claude-fable-5-1")
        self.assertEqual(payload["model_selection_source"], "task_class")

    def test_real_cli_launch_receives_selected_model_for_every_task_class(self):
        expected = {
            "standard": "claude-sonnet-5",
            "complex": "claude-opus-5",
            "frontier": "claude-fable-5-1",
        }
        for task_class, model in expected.items():
            with self.subTest(task_class=task_class):
                self.reset_audit()
                result, payload = self.run_script(
                    "launch", "--cwd", str(self.root), "--role", "implementer",
                    "--name", f"{task_class}-worker", "--task-class", task_class,
                    "--effort", "high", "--prompt", "perform bounded work",
                    rows=[],
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload["requested_model"], model)
                audit = self.audit_rows()
                self.assertEqual(len(audit), 2)
                invocation = audit[0]
                self.assertEqual(invocation[:2], ["-p", "--bg"])
                self.assert_model_flag(invocation, model)
                self.assertEqual(audit[1][0], "agents")

    def test_real_cli_launch_receives_opus_when_model_selection_is_omitted(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "planner",
            "--name", "default-worker", "--effort", "high",
            "--prompt", "create a bounded plan", rows=[],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["requested_model"], "claude-opus-5")
        self.assert_model_flag(self.audit_rows()[0], "claude-opus-5")

    def test_bypass_permissions_requires_explicit_flag(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "bypass-builder", "--task-class", "standard",
            "--effort", "medium", "--prompt", "bounded work",
            "--bypass-permissions", "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["bypass_permissions"])
        self.assertEqual(payload["permission_mode"], "bypassPermissions")
        self.assertIn("--allow-dangerously-skip-permissions", payload["command"])

    def test_real_cli_launch_receives_explicit_bypass_flags(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "bypass-worker", "--task-class", "standard",
            "--effort", "medium", "--prompt", "perform isolated work",
            "--bypass-permissions", rows=[],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["bypass_permissions"])
        invocation = self.audit_rows()[0]
        self.assertIn("--allow-dangerously-skip-permissions", invocation)
        mode_index = invocation.index("--permission-mode")
        self.assertEqual(invocation[mode_index + 1], "bypassPermissions")
        self.assert_model_flag(invocation, "claude-sonnet-5")

    def test_real_cli_resume_receives_exact_requested_model(self):
        sid = "00000000-0000-4000-8000-000000000000"
        rows = [{"id": "abcd1234", "sessionId": sid, "state": "done", "status": "idle"}]
        result, payload = self.run_script(
            "resume", "--session-id", sid, "--cwd", str(self.root),
            "--model", "claude-fable-5-1", "--effort", "high",
            "--permission-mode", "auto", "--prompt", "continue bounded work",
            rows=rows,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["requested_model"], "claude-fable-5-1")
        audit = self.audit_rows()
        self.assertEqual(len(audit), 3)
        invocation = audit[1]
        resume_index = invocation.index("--resume")
        self.assertEqual(invocation[resume_index + 1], sid)
        self.assert_model_flag(invocation, "claude-fable-5-1")

    def test_model_and_task_class_are_mutually_exclusive(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "planner",
            "--name", "bad-selection", "--model", "claude-opus-5",
            "--task-class", "complex", "--effort", "high", "--prompt", "plan",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("either --model or --task-class", payload["error"])

    def test_unapproved_model_is_rejected_by_parser(self):
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--claude-bin", str(self.fake),
                "launch", "--cwd", str(self.root), "--role", "planner",
                "--name", "invalid-model", "--model", "claude-haiku-4-5",
                "--effort", "high", "--prompt", "plan", "--dry-run",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertEqual(self.audit_rows(), [])

    def test_bypass_and_permission_mode_are_mutually_exclusive(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "ambiguous-permissions", "--task-class", "standard",
            "--effort", "medium", "--permission-mode", "auto",
            "--bypass-permissions", "--prompt", "work", "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("either --bypass-permissions or --permission-mode", payload["error"])


if __name__ == "__main__":
    unittest.main()
