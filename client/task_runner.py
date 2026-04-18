import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import requests
from client.config import load_client_config
from client import spool

logger = logging.getLogger(__name__)


def _tail(path: str, lines: int = 20) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            # simple tail: read last 8KB, decode, take last lines
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192), 0)
            text = f.read().decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception as e:
        logger.warning("failed to tail %s: %s", path, e)
        return ""


def run_task(
    task_name: str,
    command: list[str],
    timeout_sec: int | None = None,
    notify_on_success: bool = False,
    cwd: str | None = None,
):
    cfg = load_client_config()
    run_id = uuid.uuid4().hex[:16]
    log_dir = cfg.agent.log_dir
    os.makedirs(log_dir, exist_ok=True)
    stdout_path = os.path.join(log_dir, f"{task_name}_{run_id}.out")
    stderr_path = os.path.join(log_dir, f"{task_name}_{run_id}.err")

    token = cfg.server.node_token or cfg.server.enrollment_token

    # 1. report start
    start_payload = {
        "server_id": cfg.server.server_id,
        "task_name": task_name,
        "command": command,
        "cwd": cwd or os.getcwd(),
        "timeout_sec": timeout_sec,
        "notify_on_success": notify_on_success,
        "run_id": run_id,
        "token": token,
    }
    base_url = cfg.server.base_url.rstrip("/")
    try:
        resp = requests.post(f"{base_url}/task-runs/start", json=start_payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error("failed to report task start: %s", e)
        # continue locally; will try to report finish later

    # 2. run subprocess
    started_at = datetime.now(timezone.utc)
    with open(stdout_path, "wb") as out_f, open(stderr_path, "wb") as err_f:
        proc = subprocess.Popen(
            command,
            stdout=out_f,
            stderr=err_f,
            cwd=cwd,
        )
        try:
            exit_code = proc.wait(timeout=timeout_sec)
            status = "SUCCESS" if exit_code == 0 else "FAILED"
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            exit_code = proc.returncode or -1
            status = "TIMEOUT"

    ended_at = datetime.now(timezone.utc)
    duration_sec = (ended_at - started_at).total_seconds()

    stdout_tail = _tail(stdout_path)
    stderr_tail = _tail(stderr_path)

    finish_payload = {
        "status": status,
        "ended_at": ended_at.isoformat(),
        "duration_sec": duration_sec,
        "exit_code": exit_code,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "token": token,
    }

    try:
        resp = requests.post(f"{base_url}/task-runs/{run_id}/finish", json=finish_payload, timeout=10)
        resp.raise_for_status()
        logger.info("task %s finished, status=%s, run_id=%s", task_name, status, run_id)
    except Exception as e:
        logger.error("failed to report task finish: %s", e)
        spool.save(cfg.agent.spool_dir, {
            "run_id": run_id,
            "payload": finish_payload,
        }, "task_finish")
        logger.info("task finish spooled for retry")

    return run_id, status, exit_code
