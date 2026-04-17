import logging
import smtplib
import threading
import ssl
from email.mime.text import MIMEText
from sqlalchemy.orm import Session
from server.database import SessionLocal
from server.config import load_server_config, SMTPConfig
from server.models import Node, Event, now_iso

logger = logging.getLogger(__name__)
config = load_server_config()


def send_email(subject: str, body: str, smtp_cfg: SMTPConfig, timeout: float = 10.0) -> bool:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.from_addr
    msg["To"] = ", ".join(smtp_cfg.to_addrs)
    try:
        if smtp_cfg.port == 465:
            # SSL connection (e.g. Gmail, QQ)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_cfg.host, smtp_cfg.port, timeout=timeout, context=context) as server:
                server.login(smtp_cfg.username, smtp_cfg.password)
                server.sendmail(smtp_cfg.from_addr, smtp_cfg.to_addrs, msg.as_string())
        elif smtp_cfg.use_tls:
            with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=timeout) as server:
                server.starttls()
                server.login(smtp_cfg.username, smtp_cfg.password)
                server.sendmail(smtp_cfg.from_addr, smtp_cfg.to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=timeout) as server:
                server.sendmail(smtp_cfg.from_addr, smtp_cfg.to_addrs, msg.as_string())
        return True
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False


def _send_email_async(subject: str, body: str, smtp_cfg: SMTPConfig, server_id: str, event_type: str, reason: str):
    ok = send_email(subject, body, smtp_cfg)
    db = SessionLocal()
    try:
        db.add(Event(
            server_id=server_id,
            event_type=event_type if ok else "email_failed",
            message=reason,
        ))
        db.commit()
        if not ok:
            logger.error("Email failed for %s: %s", server_id, subject)
    except Exception as e:
        logger.error("Failed to record email event for %s: %s", server_id, e)
        db.rollback()
    finally:
        db.close()


def notify_status_change(db: Session, node: Node, old_status: str, new_status: str, reason: str):
    if not config.smtp:
        logger.info("No SMTP config, skipping notification for %s", node.server_id)
        return

    if new_status == "DOWN":
        subject = f"[ALERT] {node.server_id} is DOWN"
        body_lines = [
            f"Server ID: {node.server_id}",
            f"Hostname: {node.hostname or 'N/A'}",
            f"Status: DOWN",
            f"Last heartbeat: {node.last_heartbeat_at or 'N/A'}",
            f"Last probe: {'ok' if node.last_probe_ok else 'failed'}",
            f"Reason: {reason}",
            f"Time: {now_iso()}",
        ]
        event_type = "alert_sent"
    elif new_status == "UP" and old_status == "DOWN":
        subject = f"[RECOVERY] {node.server_id} is UP again"
        body_lines = [
            f"Server ID: {node.server_id}",
            f"Hostname: {node.hostname or 'N/A'}",
            f"Status: UP",
            f"Recovered at: {now_iso()}",
            f"Reason: {reason}",
        ]
        event_type = "recovery_sent"
    else:
        # SUSPECT or UP from SUSPECT: no email
        return

    body = "\n".join(body_lines)
    # Fire-and-forget in background thread to avoid blocking scheduler
    thread = threading.Thread(
        target=_send_email_async,
        args=(subject, body, config.smtp, node.server_id, event_type, reason),
        daemon=True,
    )
    thread.start()
