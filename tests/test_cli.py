import sys

import pytest

from client import cli


def test_hb_cli_runs_wrapped_task(monkeypatch, capsys):
    captured = {}

    def fake_run_task(task_name, command, timeout_sec=None, notify_on_success=False, cwd=None):
        captured["task_name"] = task_name
        captured["command"] = command
        captured["timeout_sec"] = timeout_sec
        captured["notify_on_success"] = notify_on_success
        captured["cwd"] = cwd
        return "run-1", "SUCCESS", 0

    monkeypatch.setattr(cli, "run_task", fake_run_task)
    monkeypatch.setattr(sys, "argv", ["hb", "--name", "backup", "--timeout", "30", "--notify-success", "--cwd", "/tmp", "--", "bash", "backup.sh"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    out = capsys.readouterr().out
    assert exc.value.code == 0
    assert "run_id=run-1 status=SUCCESS exit_code=0" in out
    assert captured == {
        "task_name": "backup",
        "command": ["bash", "backup.sh"],
        "timeout_sec": 30,
        "notify_on_success": True,
        "cwd": "/tmp",
    }


def test_hb_cli_requires_command(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hb", "--name", "backup"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "no command provided" in err
