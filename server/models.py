import json
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text
from server.database import Base


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
