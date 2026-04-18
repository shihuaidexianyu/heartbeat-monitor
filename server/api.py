import json
import logging
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any

from server.database import get_db
from server.models import Node, Event, now_iso
from server.status_engine import evaluate_node
from server.config import load_server_config

logger = logging.getLogger(__name__)
router = APIRouter()
server_config = load_server_config()


class HeartbeatPayload(BaseModel):
    server_id: str
    token: str
    hostname: Optional[str] = None
    timestamp: Optional[int] = None
    ip: Optional[str] = None
    services: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class HeartbeatResponse(BaseModel):
    ok: bool
    message: str


class RegisterPayload(BaseModel):
    server_id: str
    enrollment_token: str
    hostname: Optional[str] = None
    ip: Optional[str] = None


class RegisterResponse(BaseModel):
    ok: bool
    node_token: str
    server_id: str
    heartbeat_interval_sec: int


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterPayload, db: Session = Depends(get_db)):
    expected = server_config.registration.enrollment_token or server_config.default_token
    if not expected or payload.enrollment_token != expected:
        logger.warning("register rejected: invalid enrollment token for %s", payload.server_id)
        raise HTTPException(status_code=401, detail="invalid enrollment token")

    node = db.query(Node).filter(Node.server_id == payload.server_id).first()
    node_token = secrets.token_urlsafe(32)
    if node:
        node.token_hash = node_token
        if payload.hostname:
            node.hostname = payload.hostname
        if payload.ip:
            node.probe_host = payload.ip
        event_msg = "re-registered via /register"
    else:
        node = Node(
            server_id=payload.server_id,
            hostname=payload.hostname,
            token_hash=node_token,
            probe_host=payload.ip or payload.hostname or "127.0.0.1",
            probe_port=22,
            status="UP",
            last_heartbeat_at=now_iso(),
        )
        db.add(node)
        event_msg = "registered via /register"

    db.add(Event(
        server_id=payload.server_id,
        event_type="node_registered",
        message=event_msg,
    ))
    db.commit()
    logger.info("node registered: %s", payload.server_id)
    return RegisterResponse(
        ok=True,
        node_token=node_token,
        server_id=payload.server_id,
        heartbeat_interval_sec=node.expected_interval_sec,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(payload: HeartbeatPayload, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.server_id == payload.server_id).first()
    if not node:
        # fallback auto-register with enrollment_token
        enrollment = server_config.registration.enrollment_token or server_config.default_token
        if enrollment and payload.token == enrollment:
            node = Node(
                server_id=payload.server_id,
                hostname=payload.hostname,
                token_hash=payload.token,
                probe_host=payload.ip or payload.hostname or "127.0.0.1",
                probe_port=22,
                status="UP",
                last_heartbeat_at=now_iso(),
                last_payload_json=json.dumps(payload.model_dump(exclude={"token"}), ensure_ascii=False),
            )
            db.add(node)
            db.add(Event(
                server_id=payload.server_id,
                event_type="node_registered",
                message="auto-registered from first heartbeat",
            ))
            db.commit()
            logger.info("auto-registered new node: %s", payload.server_id)
            return HeartbeatResponse(ok=True, message="heartbeat received and node registered")

        logger.warning("heartbeat rejected: unknown server_id %s", payload.server_id)
        db.add(Event(
            server_id=payload.server_id,
            event_type="auth_failed",
            message="unknown server_id",
        ))
        db.commit()
        raise HTTPException(status_code=404, detail="server_id not found")

    if node.token_hash != payload.token:
        logger.warning("heartbeat rejected: invalid token for %s", payload.server_id)
        db.add(Event(
            server_id=payload.server_id,
            event_type="auth_failed",
            message="invalid token",
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="invalid token")

    old_status = node.status
    node.last_heartbeat_at = now_iso()
    node.heartbeat_fail_count = 0
    node.last_payload_json = json.dumps(payload.model_dump(exclude={"token"}), ensure_ascii=False)
    if payload.hostname:
        node.hostname = payload.hostname

    # If node was DOWN or SUSPECT, evaluate recovery immediately
    if old_status in ("DOWN", "SUSPECT"):
        evaluate_node(db, node)
    else:
        db.add(node)

    db.add(Event(
        server_id=node.server_id,
        event_type="heartbeat_received",
        message=f"heartbeat from {payload.hostname or payload.server_id}",
    ))
    db.commit()
    logger.info("heartbeat received from %s", payload.server_id)
    return HeartbeatResponse(ok=True, message="heartbeat received")


@router.get("/health")
def health():
    return {
        "ok": True,
        "service": "heartbeat-monitor",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/nodes")
def list_nodes(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    return [
        {
            "server_id": n.server_id,
            "status": n.status,
            "last_heartbeat_at": n.last_heartbeat_at,
            "last_probe_ok": bool(n.last_probe_ok),
        }
        for n in nodes
    ]


@router.get("/nodes/{server_id}")
def get_node(server_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.server_id == server_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    return node.to_dict()


@router.post("/nodes/{server_id}/maintenance/start")
def maintenance_start(server_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.server_id == server_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    node.status = "MAINTENANCE"
    db.add(Event(
        server_id=server_id,
        event_type="maintenance_started",
        message="node entered maintenance mode",
    ))
    db.commit()
    return {"ok": True, "status": "MAINTENANCE"}


@router.post("/nodes/{server_id}/maintenance/end")
def maintenance_end(server_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.server_id == server_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="node not found")
    # Force re-evaluation on next cycle
    node.status = "UP"
    evaluate_node(db, node)
    db.add(Event(
        server_id=server_id,
        event_type="maintenance_ended",
        message="node left maintenance mode, re-evaluating",
    ))
    db.commit()
    return {"ok": True, "status": node.status}


@router.get("/status-page", response_class=HTMLResponse)
def status_page(db: Session = Depends(get_db)):
    from server.models import TaskRun
    from collections import Counter
    nodes = db.query(Node).all()
    all_tasks = db.query(TaskRun).order_by(TaskRun.created_at.desc()).limit(100).all()
    recent_tasks = all_tasks[:20]
    failed_tasks = [t for t in all_tasks if t.status in ("FAILED", "TIMEOUT")][:10]
    running_tasks = [t for t in all_tasks if t.status in ("STARTING", "RUNNING")][:10]

    node_counts = Counter(n.status for n in nodes)
    task_counts = Counter(t.status for t in all_tasks)

    def status_color(status: str) -> str:
        if status == "UP":
            return "#22c55e"
        elif status == "DOWN":
            return "#ef4444"
        elif status == "MAINTENANCE":
            return "#3b82f6"
        return "#f59e0b"

    def task_status_badge(status: str) -> str:
        colors = {
            "STARTING": ("#64748b", "#f1f5f9"),
            "RUNNING": ("#3b82f6", "#eff6ff"),
            "SUCCESS": ("#22c55e", "#f0fdf4"),
            "FAILED": ("#ef4444", "#fef2f2"),
            "TIMEOUT": ("#f97316", "#fff7ed"),
            "CANCELLED": ("#8b5cf6", "#f5f3ff"),
            "LOST": ("#000000", "#f3f4f6"),
        }
        fg, bg = colors.get(status, ("#64748b", "#f1f5f9"))
        return f'<span style="display:inline-block;padding:2px 8px;border-radius:9999px;font-size:0.75rem;font-weight:600;color:{fg};background:{bg};">{status}</span>'

    # Node overview cards
    node_total = len(nodes)
    node_up = node_counts.get("UP", 0)
    node_down = node_counts.get("DOWN", 0)
    node_suspect = node_counts.get("SUSPECT", 0)
    node_maint = node_counts.get("MAINTENANCE", 0)

    # Task overview cards
    task_total = len(all_tasks)
    task_running = task_counts.get("RUNNING", 0) + task_counts.get("STARTING", 0)
    task_success = task_counts.get("SUCCESS", 0)
    task_failed = task_counts.get("FAILED", 0) + task_counts.get("TIMEOUT", 0)

    def _card(label: str, value: int, color: str) -> str:
        return f"""
        <div style="flex:1;min-width:120px;background:white;padding:16px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);text-align:center;">
            <div style="font-size:1.75rem;font-weight:700;color:{color};">{value}</div>
            <div style="font-size:0.875rem;color:#64748b;margin-top:4px;">{label}</div>
        </div>
        """

    overview = f"""
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:1rem;">
        {_card("Nodes", node_total, "#1e293b")}
        {_card("UP", node_up, "#22c55e")}
        {_card("DOWN", node_down, "#ef4444")}
        {_card("SUSPECT", node_suspect, "#f59e0b")}
        {_card("MAINT", node_maint, "#3b82f6")}
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:1rem;">
        {_card("Tasks", task_total, "#1e293b")}
        {_card("Running", task_running, "#3b82f6")}
        {_card("Success", task_success, "#22c55e")}
        {_card("Failed", task_failed, "#ef4444")}
    </div>
    """

    rows = ""
    for n in nodes:
        color = status_color(n.status)
        dot = f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:6px;"></span>'
        rows += f"""
        <tr>
            <td>{n.server_id}</td>
            <td>{n.hostname or "-"}</td>
            <td>{dot}<span style="color:{color};font-weight:bold;">{n.status}</span></td>
            <td>{n.last_heartbeat_at or "Never"}</td>
            <td>{"OK" if n.last_probe_ok else "Failed"}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="5" style="text-align:center;">No nodes registered yet</td></tr>'

    task_rows = ""
    for t in recent_tasks:
        badge = task_status_badge(t.status)
        task_rows += f"""
        <tr>
            <td><strong>{t.task_name}</strong></td>
            <td>{t.server_id}</td>
            <td>{badge}</td>
            <td>{t.started_at or "-"}</td>
            <td>{f"{t.duration_sec:.1f}s" if t.duration_sec else "-"}</td>
            <td>{t.exit_code if t.exit_code is not None else "-"}</td>
        </tr>
        """

    if not task_rows:
        task_rows = '<tr><td colspan="6" style="text-align:center;">No tasks yet</td></tr>'

    running_rows = ""
    for t in running_tasks:
        badge = task_status_badge(t.status)
        running_rows += f"""
        <tr>
            <td><strong>{t.task_name}</strong></td>
            <td>{t.server_id}</td>
            <td>{badge}</td>
            <td>{t.started_at or "-"}</td>
        </tr>
        """

    if not running_rows:
        running_rows = '<tr><td colspan="4" style="text-align:center;">No running tasks</td></tr>'

    failed_rows = ""
    for t in failed_tasks:
        stderr_preview = (t.stderr_tail or "").replace("\n", "<br>")[:300]
        badge = task_status_badge(t.status)
        failed_rows += f"""
        <tr>
            <td><strong>{t.task_name}</strong></td>
            <td>{t.server_id}</td>
            <td>{badge}</td>
            <td>{t.exit_code if t.exit_code is not None else "-"}</td>
            <td style="font-size:0.875rem;color:#64748b;">{stderr_preview or "-"}</td>
        </tr>
        """

    if not failed_rows:
        failed_rows = '<tr><td colspan="5" style="text-align:center;">No failed tasks</td></tr>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Heartbeat Monitor Status</title>
        <meta http-equiv="refresh" content="5">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                max-width: 1200px;
                margin: 40px auto;
                padding: 0 20px;
                background: #f8fafc;
            }}
            h1 {{
                font-size: 1.5rem;
                margin-bottom: 1rem;
            }}
            h2 {{
                font-size: 1.25rem;
                margin-top: 2rem;
                margin-bottom: 0.75rem;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                border-radius: 8px;
                overflow: hidden;
                margin-bottom: 1rem;
            }}
            th, td {{
                padding: 12px 16px;
                text-align: left;
                border-bottom: 1px solid #e2e8f0;
            }}
            th {{
                background: #1e293b;
                color: white;
                font-weight: 500;
            }}
            tr:last-child td {{
                border-bottom: none;
            }}
            .meta {{
                color: #64748b;
                font-size: 0.875rem;
                margin-top: 1rem;
            }}
        </style>
    </head>
    <body>
        <h1>Heartbeat Monitor Status</h1>
        {overview}

        <h2>Nodes</h2>
        <table>
            <thead>
                <tr>
                    <th>Server ID</th>
                    <th>Hostname</th>
                    <th>Status</th>
                    <th>Last Heartbeat</th>
                    <th>Last Probe</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>

        <h2>Running Tasks</h2>
        <table>
            <thead>
                <tr>
                    <th>Task</th>
                    <th>Node</th>
                    <th>Status</th>
                    <th>Started</th>
                </tr>
            </thead>
            <tbody>
                {running_rows}
            </tbody>
        </table>

        <h2>Recent Tasks</h2>
        <table>
            <thead>
                <tr>
                    <th>Task</th>
                    <th>Node</th>
                    <th>Status</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>Exit Code</th>
                </tr>
            </thead>
            <tbody>
                {task_rows}
            </tbody>
        </table>

        <h2>Failed Tasks</h2>
        <table>
            <thead>
                <tr>
                    <th>Task</th>
                    <th>Node</th>
                    <th>Status</th>
                    <th>Exit Code</th>
                    <th>Stderr Tail</th>
                </tr>
            </thead>
            <tbody>
                {failed_rows}
            </tbody>
        </table>

        <p class="meta">Auto-refreshes every 5 seconds</p>
    </body>
    </html>
    """
    return html
