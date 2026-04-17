import json
import logging
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


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(payload: HeartbeatPayload, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.server_id == payload.server_id).first()
    if not node:
        if server_config.default_token and payload.token == server_config.default_token:
            # Auto-register new node on first heartbeat with default token
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


@router.get("/status-page", response_class=HTMLResponse)
def status_page(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()

    def status_color(status: str) -> str:
        if status == "UP":
            return "#22c55e"  # green
        elif status == "DOWN":
            return "#ef4444"  # red
        return "#f59e0b"  # yellow for SUSPECT

    rows = ""
    for n in nodes:
        color = status_color(n.status)
        rows += f"""
        <tr>
            <td>{n.server_id}</td>
            <td>{n.hostname or "-"}</td>
            <td style="color:{color};font-weight:bold;">{n.status}</td>
            <td>{n.last_heartbeat_at or "Never"}</td>
            <td>{"OK" if n.last_probe_ok else "Failed"}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="5" style="text-align:center;">No nodes registered yet</td></tr>'

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
                max-width: 900px;
                margin: 40px auto;
                padding: 0 20px;
                background: #f8fafc;
            }}
            h1 {{
                font-size: 1.5rem;
                margin-bottom: 1rem;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                border-radius: 8px;
                overflow: hidden;
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
        <p class="meta">Auto-refreshes every 5 seconds</p>
    </body>
    </html>
    """
    return html
