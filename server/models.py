import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Float
from server.database import Base


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gen_run_id() -> str:
    return uuid.uuid4().hex[:16]


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String, unique=True, nullable=False)
    hostname = Column(String)
    token_hash = Column(String, nullable=False)
    probe_host = Column(String, nullable=False)
    probe_port = Column(Integer, default=22)
    expected_interval_sec = Column(Integer, default=30)
    heartbeat_timeout_sec = Column(Integer, default=90)
    probe_fail_threshold = Column(Integer, default=3)
    status = Column(String, default="UP")
    last_heartbeat_at = Column(String)
    last_probe_at = Column(String)
    last_probe_ok = Column(Integer, default=0)
    heartbeat_fail_count = Column(Integer, default=0)
    probe_fail_count = Column(Integer, default=0)
    last_alert_status = Column(String)
    last_payload_json = Column(Text)
    created_at = Column(String, nullable=False, default=now_iso)
    updated_at = Column(String, nullable=False, default=now_iso, onupdate=now_iso)

    def to_dict(self) -> dict:
        return {
            "server_id": self.server_id,
            "hostname": self.hostname,
            "status": self.status,
            "last_heartbeat_at": self.last_heartbeat_at,
            "last_probe_at": self.last_probe_at,
            "last_probe_ok": bool(self.last_probe_ok),
            "probe_fail_count": self.probe_fail_count,
            "heartbeat_fail_count": self.heartbeat_fail_count,
            "last_payload": json.loads(self.last_payload_json) if self.last_payload_json else None,
        }


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    message = Column(Text)
    created_at = Column(String, nullable=False, default=now_iso)


class TaskRun(Base):
    __tablename__ = "task_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, unique=True, nullable=False, default=gen_run_id)
    server_id = Column(String, nullable=False)
    task_name = Column(String, nullable=False)
    command_json = Column(Text)
    cwd = Column(String)
    status = Column(String, nullable=False, default="STARTING")
    started_at = Column(String)
    ended_at = Column(String)
    duration_sec = Column(Float)
    exit_code = Column(Integer)
    timeout_sec = Column(Integer)
    stdout_path = Column(String)
    stderr_path = Column(String)
    stdout_tail = Column(Text)
    stderr_tail = Column(Text)
    notify_on_success = Column(Integer, default=0)
    created_at = Column(String, nullable=False, default=now_iso)
    updated_at = Column(String, nullable=False, default=now_iso, onupdate=now_iso)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "server_id": self.server_id,
            "task_name": self.task_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_sec": self.duration_sec,
            "exit_code": self.exit_code,
            "timeout_sec": self.timeout_sec,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "notify_on_success": bool(self.notify_on_success),
        }


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String, nullable=False)  # node / task
    source_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    channel = Column(String, nullable=False)  # email / feishu
    subject = Column(String)
    payload_json = Column(Text)
    success = Column(Integer, default=0)
    response_text = Column(Text)
    created_at = Column(String, nullable=False, default=now_iso)
