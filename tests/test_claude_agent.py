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

    def test_launch_dry_run_redacts_prompt_and_does_not_invoke_claude(self):
        result, payload = self.run_script(
            "launch", "--cwd", str(self.root), "--role", "implementer",
            "--name", "builder", "--model", "sonnet", "--effort", "medium",
            "--prompt", "secret task body", "--dry-run",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["permission_mode"], "auto")
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
            "--model", "sonnet", "--effort", "medium", "--permission-mode", "auto",
            "--prompt", "continue", "--dry-run", rows=rows,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Session is active", payload["error"])

    def test_resume_dry_run_never_stops_active_session(self):
        sid = "00000000-0000-4000-8000-000000000000"
        rows = [{"id": "abcd1234", "sessionId": sid, "state": "working", "status": "busy"}]
        result, payload = self.run_script(
            "resume", "--session-id", sid, "--stop-first", "--cwd", str(self.root),
            "--model", "sonnet", "--effort", "medium", "--permission-mode", "auto",
            "--prompt", "redirect", "--dry-run", rows=rows,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["would_stop_first"])
        self.assertFalse(payload["stopped_first"])
        self.assertEqual(self.audit_rows(), [["agents", "--json", "--all"]])


if __name__ == "__main__":
    unittest.main()
