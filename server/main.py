import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from server.config import load_server_config
from server.database import init_db, SessionLocal
from server.models import Node
from server.probe import run_probes
from server.status_engine import evaluate_all_nodes

config = load_server_config()

def configure_logging():
    root_logger = logging.getLogger()
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    root_logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not root_logger.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    if config.logging.file:
        log_path = Path(config.logging.file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        has_same_file_handler = any(
            isinstance(handler, logging.FileHandler)
            and Path(getattr(handler, "baseFilename", "")).resolve() == log_path
            for handler in root_logger.handlers
        )
        if not has_same_file_handler:
            file_handler = logging.FileHandler(log_path)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)


configure_logging()

logger = logging.getLogger(__name__)


def ensure_seed_nodes():
    db = SessionLocal()
    try:
        count = db.query(Node).count()
        if count == 0:
            logger.info("No nodes found in database, seeding demo nodes if configured")
            seed = os.environ.get("MONITOR_NODES_SEED")
            if seed:
                import json
                for item in json.loads(seed):
                    node = Node(
                        server_id=item["server_id"],
                        hostname=item.get("hostname"),
                        token_hash=item["token_hash"],
                        probe_host=item["probe_host"],
                        probe_port=item.get("probe_port", 22),
                    )
                    db.add(node)
                db.commit()
                logger.info("Seeded %d nodes", len(json.loads(seed)))
    finally:
        db.close()


def probe_and_evaluate_job():
    db = SessionLocal()
    try:
        run_probes(db)
    finally:
        db.close()
    db = SessionLocal()
    try:
        evaluate_all_nodes(db)
    finally:
        db.close()


scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_seed_nodes()
    scheduler.add_job(
        probe_and_evaluate_job,
        "interval",
        seconds=config.monitor.probe_interval_sec,
        id="probe_and_evaluate",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="Heartbeat Monitor", lifespan=lifespan)

from server.api import router as api_router
from server.task_api import router as task_router

app.include_router(api_router)
app.include_router(task_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=config.listen_host,
        port=config.listen_port,
        reload=False,
    )
