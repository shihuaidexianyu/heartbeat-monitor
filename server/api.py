import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any

from server.database import get_db
from server.models import Node, Event, now_iso
from server.status_engine import evaluate_node

logger = logging.getLogger(__name__)
router = APIRouter()


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
