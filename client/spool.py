import json
import logging
import os
import glob
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _spool_path(spool_dir: str, prefix: str) -> str:
    os.makedirs(spool_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3]
    return os.path.join(spool_dir, f"{prefix}_{ts}.json")


def save(spool_dir: str, payload: dict, prefix: str = "event") -> str:
    path = _spool_path(spool_dir, prefix)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    logger.info("spooled event to %s", path)
    return path


def iter_spool(spool_dir: str, prefix: str = "event"):
    os.makedirs(spool_dir, exist_ok=True)
    pattern = os.path.join(spool_dir, f"{prefix}_*.json")
    for path in sorted(glob.glob(pattern)):
        yield path


def remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def load(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("failed to load spool file %s: %s", path, e)
        return None
