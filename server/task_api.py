import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional, List, Literal

from server.database import get_db
from server.models import Node, TaskRun, Event, gen_run_id
from server.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_TASK_STATUSES = ("STARTING", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT", "CANCELLED", "LOST")
MAX_TAIL_LEN = 10000
MAX_LIMIT = 1000


def _verify_node(db: Session, server_id: str, token: str):
    node = db.query(Node).filter(Node.server_id == server_id).first()
    if not node or node.token_hash != token:
        raise HTTPException(status_code=401, detail="invalid token")


class TaskStartPayload(BaseModel):
    server_id: str
    task_name: str = Field(..., max_length=255)
    command: List[str]
    cwd: Optional[str] = None
    timeout_sec: Optional[int] = None
    notify_on_success: bool = False
    run_id: Optional[str] = None
    token: str


class TaskStartResponse(BaseModel):
    ok: bool
    run_id: str


class TaskFinishPayload(BaseModel):
    status: Literal["SUCCESS", "FAILED", "TIMEOUT", "CANCELLED", "LOST"]
    ended_at: Optional[str] = None
    duration_sec: Optional[float] = None
    exit_code: Optional[int] = None
    stdout_tail: Optional[str] = Field(default=None, max_length=MAX_TAIL_LEN)
    stderr_tail: Optional[str] = Field(default=None, max_length=MAX_TAIL_LEN)
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    token: str


class TaskFinishResponse(BaseModel):
    ok: bool


@router.post("/task-runs/start", response_model=TaskStartResponse)
def task_start(payload: TaskStartPayload, db: Session = Depends(get_db)):
    _verify_node(db, payload.server_id, payload.token)
    run_id = payload.run_id or gen_run_id()
    existing = db.query(TaskRun).filter(TaskRun.run_id == run_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="run_id already exists")

    task = TaskRun(
        run_id=run_id,
        server_id=payload.server_id,
        task_name=payload.task_name,
        command_json=json.dumps(payload.command, ensure_ascii=False),
        cwd=payload.cwd,
        status="RUNNING",
        started_at=datetime.now(timezone.utc).isoformat(),
        timeout_sec=payload.timeout_sec,
        notify_on_success=1 if payload.notify_on_success else 0,
    )
    db.add(task)
    db.add(Event(
        server_id=payload.server_id,
        event_type="task_started",
        message=f"task {payload.task_name} started (run_id={run_id})",
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="run_id already exists")
    logger.info("task started: %s run_id=%s", payload.task_name, run_id)
    return TaskStartResponse(ok=True, run_id=run_id)


@router.post("/task-runs/{run_id}/finish", response_model=TaskFinishResponse)
def task_finish(run_id: str, payload: TaskFinishPayload, db: Session = Depends(get_db)):
    task = db.query(TaskRun).filter(TaskRun.run_id == run_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="run_id not found")

    _verify_node(db, task.server_id, payload.token)

    task.status = payload.status
    task.ended_at = payload.ended_at or datetime.now(timezone.utc).isoformat()
    task.duration_sec = payload.duration_sec
    task.exit_code = payload.exit_code
    task.stdout_tail = payload.stdout_tail
    task.stderr_tail = payload.stderr_tail
    task.stdout_path = payload.stdout_path
    task.stderr_path = payload.stderr_path

    db.add(Event(
        server_id=task.server_id,
        event_type=f"task_{payload.status.lower()}",
        message=f"task {task.task_name} finished with status {payload.status} (run_id={run_id})",
    ))
    db.commit()

    # trigger notification
    svc = NotificationService(db)
    svc.notify_task_finish(task)

    logger.info("task finished: %s run_id=%s status=%s", task.task_name, run_id, payload.status)
    return TaskFinishResponse(ok=True)


@router.get("/task-runs")
def list_task_runs(
    server_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    limit = min(limit, MAX_LIMIT)
    q = db.query(TaskRun)
    if server_id:
        q = q.filter(TaskRun.server_id == server_id)
    if status:
        q = q.filter(TaskRun.status == status)
    q = q.order_by(TaskRun.created_at.desc()).limit(limit)
    return [t.to_dict() for t in q.all()]


@router.get("/task-runs/{run_id}")
def get_task_run(run_id: str, db: Session = Depends(get_db)):
    task = db.query(TaskRun).filter(TaskRun.run_id == run_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="run_id not found")
    return task.to_dict()


@router.post("/task-runs/{run_id}/cancel")
def task_cancel(
    run_id: str,
    x_node_token: str = Header(..., alias="X-Node-Token"),
    db: Session = Depends(get_db),
):
    task = db.query(TaskRun).filter(TaskRun.run_id == run_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="run_id not found")
    _verify_node(db, task.server_id, x_node_token)
    if task.status not in ("STARTING", "RUNNING"):
        raise HTTPException(status_code=409, detail=f"cannot cancel task in status {task.status}")
    task.status = "CANCELLED"
    task.ended_at = datetime.now(timezone.utc).isoformat()
    db.add(Event(
        server_id=task.server_id,
        event_type="task_cancelled",
        message=f"task {task.task_name} cancelled (run_id={run_id})",
    ))
    db.commit()
    return {"ok": True, "status": "CANCELLED"}


@router.get("/nodes/{server_id}/task-runs")
def list_node_task_runs(server_id: str, limit: int = 100, db: Session = Depends(get_db)):
    limit = min(limit, MAX_LIMIT)
    tasks = (
        db.query(TaskRun)
        .filter(TaskRun.server_id == server_id)
        .order_by(TaskRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return [t.to_dict() for t in tasks]
