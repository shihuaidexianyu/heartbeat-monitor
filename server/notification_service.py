import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from server.config import load_server_config
from server.models import Node, TaskRun, Notification, now_iso
from server.notifier import EmailNotifier
from server.feishu_notifier import FeishuNotifier

logger = logging.getLogger(__name__)
config = load_server_config()


class NotificationService:
    _executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="notify")

    def __init__(self, db: Session):
        self.db = db
        email_cfg = config.notifications.email
        self._email = EmailNotifier(email_cfg) if email_cfg and email_cfg.enabled else None
        self._feishu = FeishuNotifier(config.notifications.feishu)

    def _should_notify_node(self, node: Node, old_status: str, new_status: str) -> dict:
        # dedup: same node same status within 10 min
        if new_status == "DOWN":
            return {"email": True, "feishu": True}
        if new_status == "UP" and old_status == "DOWN":
            return {"email": True, "feishu": True}
        return {}

    def _recent_notification_exists(self, source_type: str, source_id: str, event_type: str, channel: str, seconds: int = 600) -> bool:
        from sqlalchemy import text
        sql = text("""
            SELECT id FROM notifications
            WHERE source_type = :st AND source_id = :sid AND event_type = :et AND channel = :ch
            AND created_at > datetime('now', :sec)
            LIMIT 1
        """)
        result = self.db.execute(sql, {
            "st": source_type, "sid": source_id, "et": event_type, "ch": channel,
            "sec": f"-{seconds} seconds"
        })
        return result.fetchone() is not None

    def notify_node_change(self, node: Node, old_status: str, new_status: str, reason: str):
        channels = self._should_notify_node(node, old_status, new_status)
        if not channels:
            return

        event_type = f"node_{new_status.lower()}"
        subject = f"[{'ALERT' if new_status == 'DOWN' else 'RECOVERY'}] {node.server_id} is {new_status}"
        body_lines = [
            f"Server ID: {node.server_id}",
            f"Hostname: {node.hostname or 'N/A'}",
            f"Status: {new_status}",
            f"Last heartbeat: {node.last_heartbeat_at or 'N/A'}",
            f"Last probe: {'ok' if node.last_probe_ok else 'failed'}",
            f"Reason: {reason}",
            f"Time: {now_iso()}",
        ]
        body = "\n".join(body_lines)

        for channel, enabled in channels.items():
            if not enabled:
                continue
            if channel == "email" and self._email:
                if self._recent_notification_exists("node", node.server_id, event_type, "email"):
                    logger.info("dedup: skip email for %s %s", node.server_id, event_type)
                    continue
                self._send_async("node", node.server_id, event_type, "email", subject, body, self._email)
            if channel == "feishu" and self._feishu:
                if self._recent_notification_exists("node", node.server_id, event_type, "feishu"):
                    logger.info("dedup: skip feishu for %s %s", node.server_id, event_type)
                    continue
                self._send_async("node", node.server_id, event_type, "feishu", subject, body, self._feishu)

    def notify_task_finish(self, task: TaskRun):
        if task.status == "SUCCESS" and not task.notify_on_success:
            return
        if task.status not in ("SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"):
            return

        # dedup: same run_id only once
        existing = self.db.query(Notification).filter(
            Notification.source_type == "task",
            Notification.source_id == task.run_id,
            Notification.event_type == f"task_{task.status.lower()}",
        ).first()
        if existing:
            logger.info("dedup: skip task notification for run_id=%s", task.run_id)
            return

        event_type = f"task_{task.status.lower()}"
        subject = f"[TASK {task.status}] {task.task_name} on {task.server_id}"
        body_lines = [
            f"Task: {task.task_name}",
            f"Node: {task.server_id}",
            f"Status: {task.status}",
            f"Duration: {task.duration_sec}s" if task.duration_sec else "Duration: N/A",
            f"Exit code: {task.exit_code}" if task.exit_code is not None else "",
        ]
        if task.stderr_tail:
            body_lines.append("\n--- stderr tail ---\n" + task.stderr_tail)
        body = "\n".join([l for l in body_lines if l])

        channels = {"feishu": True}
        if task.status in ("FAILED", "TIMEOUT"):
            channels["email"] = True

        for channel, enabled in channels.items():
            if not enabled:
                continue
            if channel == "email" and self._email:
                self._send_async("task", task.run_id, event_type, "email", subject, body, self._email)
            if channel == "feishu" and self._feishu:
                self._send_async("task", task.run_id, event_type, "feishu", subject, body, self._feishu)

    def _send_async(self, source_type: str, source_id: str, event_type: str, channel: str, subject: str, body: str, notifier):
        def _do():
            # Double-check dedup right before sending (reduces race window)
            try:
                from server.database import SessionLocal
                check_db = SessionLocal()
                dup = check_db.query(Notification).filter(
                    Notification.source_type == source_type,
                    Notification.source_id == source_id,
                    Notification.event_type == event_type,
                    Notification.channel == channel,
                ).first()
                check_db.close()
                if dup:
                    logger.info("async dedup: skip %s %s %s", source_type, source_id, event_type)
                    return
            except Exception:
                pass

            try:
                if isinstance(notifier, EmailNotifier):
                    ok, response = notifier.send(subject, body)
                elif isinstance(notifier, FeishuNotifier):
                    ok, response = notifier.send(subject, body)
                else:
                    ok, response = False, "unknown notifier"
            except Exception as e:
                ok, response = False, str(e)
            db = None
            try:
                from server.database import SessionLocal
                db = SessionLocal()
                db.add(Notification(
                    source_type=source_type,
                    source_id=source_id,
                    event_type=event_type,
                    channel=channel,
                    subject=subject,
                    payload_json=json.dumps({"body": body}, ensure_ascii=False),
                    success=1 if ok else 0,
                    response_text=response[:500] if response else None,
                ))
                db.commit()
            except Exception as e:
                logger.error("failed to record notification: %s", e)
            finally:
                if db:
                    db.close()

        self._executor.submit(_do)
