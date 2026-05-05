from __future__ import annotations

import importlib.util
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegressionTests(unittest.TestCase):
    def test_phase_h_cron_creation_uses_launcher_file_not_inline_python(self) -> None:
        phase_h = load_script("phase_h_libs.py")
        commands: list[str] = []
        copied: list[tuple[str, str]] = []

        with tempfile.NamedTemporaryFile("w", delete=False) as prompt:
            prompt.write("prompt with 'single quotes' and \"double quotes\"")
            prompt_path = Path(prompt.name)

        def fake_scp(local, host, remote, ssh_key=None):
            copied.append((str(local), str(remote)))
            return subprocess.CompletedProcess([], 0, "", "")

        def fake_run(host, cmd, ssh_key=None, timeout=None):
            commands.append(cmd)
            return subprocess.CompletedProcess([], 0, "created job test", "")

        try:
            with mock.patch.object(phase_h.ssh, "scp", side_effect=fake_scp), \
                 mock.patch.object(phase_h.ssh, "run", side_effect=fake_run), \
                 contextlib.redirect_stdout(io.StringIO()):
                ok = phase_h._create_cron("root@example", "/tmp/key", "test-job", "* * * * *", prompt_path, "telegram:-100:7")
        finally:
            prompt_path.unlink(missing_ok=True)

        self.assertTrue(ok)
        self.assertEqual(len(copied), 2)
        self.assertIn("/tmp/hermes_create_cron_test-job.py", copied[1][1])
        self.assertEqual(len(commands), 1)
        self.assertNotIn(" -c '", commands[0])
        self.assertIn("/tmp/hermes_create_cron_test-job.py", commands[0])

    def test_phase_j_smoke_does_not_directly_execute_proposal(self) -> None:
        phase_j = load_script("phase_j_smoke.py")
        self.assertNotIn("proposal_executor", phase_j.SMOKE_PROGRAM)
        self.assertNotIn(".execute(", phase_j.SMOKE_PROGRAM)
        self.assertIn("proposals.mint", phase_j.SMOKE_PROGRAM)

    def test_phase_f_blocks_when_remote_mutation_fails(self) -> None:
        phase_f = load_script("phase_f_routing.py")
        fake_state = {
            "vps": {"host": "root@example", "ssh_key": "/tmp/key"},
            "telegram": {
                "supergroup_chat_id": -100,
                "daily_thread_id": 3,
                "proactive_thread_id": 7,
            },
        }
        marked: list[tuple[str, str, str | None]] = []

        def fake_run(host, cmd, ssh_key=None, timeout=None):
            if "cat /root/.hermes/cron/jobs.json" in cmd:
                return subprocess.CompletedProcess([], 0, '{"jobs":[{"id":"abc","name":"morning-brief","deliver":"local"}]}', "")
            return subprocess.CompletedProcess([], 2, "", "edit failed")

        def fake_mark(phase, status, blocker=None):
            marked.append((phase, status, blocker))
            return {}

        with mock.patch.object(phase_f.state, "is_complete", return_value=False), \
             mock.patch.object(phase_f.state, "read", return_value=fake_state), \
             mock.patch.object(phase_f.state, "mark_phase", side_effect=fake_mark), \
             mock.patch.object(phase_f.ssh, "run", side_effect=fake_run), \
             mock.patch("builtins.input", return_value="y"), \
             contextlib.redirect_stdout(io.StringIO()):
            rc = phase_f.run()

        self.assertEqual(rc, 1)
        self.assertIn(("f_routing", "blocked", "1 cron routing command(s) failed"), marked)


if __name__ == "__main__":
    unittest.main()
