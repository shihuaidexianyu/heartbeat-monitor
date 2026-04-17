import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from server.models import Node, Event, now_iso
from server.notifier import notify_status_change

logger = logging.getLogger(__name__)


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def heartbeat_timed_out(node: Node) -> bool:
    if not node.last_heartbeat_at:
        return True
    last = parse_iso(node.last_heartbeat_at)
    if not last:
        return True
    delta = (datetime.now(timezone.utc) - last).total_seconds()
    return delta > node.heartbeat_timeout_sec


def evaluate_node(db: Session, node: Node):
    old_status = node.status
    hb_timeout = heartbeat_timed_out(node)
    probe_failed = node.probe_fail_count >= node.probe_fail_threshold

    # Determine new status based on state machine
    if old_status == "UP":
        if hb_timeout or probe_failed:
            new_status = "SUSPECT"
        else:
            new_status = "UP"
    elif old_status == "SUSPECT":
        if hb_timeout and probe_failed:
            new_status = "DOWN"
        elif not hb_timeout and not probe_failed:
            new_status = "UP"
        else:
            new_status = "SUSPECT"
    elif old_status == "DOWN":
        if not hb_timeout or not probe_failed:
            new_status = "UP"
        else:
            new_status = "DOWN"
    else:
        # Unknown status fallback
        if hb_timeout and probe_failed:
            new_status = "DOWN"
        elif hb_timeout or probe_failed:
            new_status = "SUSPECT"
        else:
            new_status = "UP"

    if new_status != old_status:
        reasons = []
        if hb_timeout:
            reasons.append("heartbeat timeout")
        if probe_failed:
            reasons.append(f"tcp probe failed {node.probe_fail_count} times")
        if not reasons:
            reasons.append("heartbeat or probe recovered")
        reason = " and ".join(reasons)

        node.status = new_status
        node.last_alert_status = new_status
        logger.info("status changed: %s %s -> %s (%s)", node.server_id, old_status, new_status, reason)
        db.add(Event(
            server_id=node.server_id,
            event_type="status_changed",
            message=f"{old_status} -> {new_status}: {reason}",
        ))
        notify_status_change(db, node, old_status, new_status, reason)
    else:
        # Log heartbeat timeout event when staying in same non-UP state
        if hb_timeout and old_status != "UP":
            # Avoid spamming events; only log if we haven't recently
            pass

    db.add(node)


def evaluate_all_nodes(db: Session):
    nodes = db.query(Node).all()
    for node in nodes:
        evaluate_node(db, node)
    db.commit()
