import socket
import logging
from sqlalchemy.orm import Session
from server.models import Node, Event, now_iso
from server.config import load_server_config

logger = logging.getLogger(__name__)
config = load_server_config()


def tcp_probe(host: str, port: int, timeout: float = None) -> bool:
    if timeout is None:
        timeout = config.monitor.default_tcp_timeout_sec
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError, ConnectionRefusedError):
        return False


def run_probes(db: Session):
    nodes = db.query(Node).all()
    for node in nodes:
        ok = tcp_probe(node.probe_host, node.probe_port)
        node.last_probe_at = now_iso()
        node.last_probe_ok = 1 if ok else 0
        if ok:
            if node.probe_fail_count > 0:
                db.add(Event(
                    server_id=node.server_id,
                    event_type="probe_success",
                    message="probe recovered after failures",
                ))
            node.probe_fail_count = 0
        else:
            node.probe_fail_count += 1
            db.add(Event(
                server_id=node.server_id,
                event_type="probe_failed",
                message=f"tcp probe failed (count={node.probe_fail_count})",
            ))
        db.add(node)
    db.commit()
