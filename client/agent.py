import logging
import os
import time
import requests
from client.config import load_client_config
from client.heartbeat import send_heartbeat
from client import spool

logger = logging.getLogger(__name__)


def _flush_spool(cfg):
    for path in spool.iter_spool(cfg.agent.spool_dir, "heartbeat"):
        data = spool.load(path)
        if not data:
            spool.remove(path)
            continue
        url = cfg.server.base_url.rstrip("/") + "/heartbeat"
        try:
            resp = requests.post(url, json=data, timeout=10)
            resp.raise_for_status()
            logger.info("spooled heartbeat flushed: %s", path)
            spool.remove(path)
        except Exception as e:
            logger.warning("failed to flush spooled heartbeat %s: %s", path, e)
            break

    for path in spool.iter_spool(cfg.agent.spool_dir, "task_finish"):
        data = spool.load(path)
        if not data:
            spool.remove(path)
            continue
        run_id = data.get("run_id")
        url = cfg.server.base_url.rstrip("/") + f"/task-runs/{run_id}/finish"
        try:
            resp = requests.post(url, json=data.get("payload"), timeout=10)
            if resp.status_code in (200, 409):
                logger.info("spooled task finish flushed: %s", path)
                spool.remove(path)
            else:
                logger.warning("failed to flush spooled task finish %s: %s", path, resp.status_code)
                break
        except Exception as e:
            logger.warning("failed to flush spooled task finish %s: %s", path, e)
            break


def run_daemon():
    cfg = load_client_config()
    os.makedirs(cfg.agent.log_dir, exist_ok=True)
    os.makedirs(cfg.agent.spool_dir, exist_ok=True)

    interval = cfg.server.heartbeat_interval_sec
    logger.info("hb daemon started, server_id=%s, interval=%ds", cfg.server.server_id, interval)

    while True:
        _flush_spool(cfg)
        ok, data = send_heartbeat(cfg)
        if not ok:
            payload = {
                "server_id": cfg.server.server_id,
                "token": cfg.server.node_token or cfg.server.enrollment_token,
                "hostname": os.uname().nodename,
                "timestamp": int(time.time()),
                "ip": "",
                "services": {},
                "meta": {},
            }
            spool.save(cfg.agent.spool_dir, payload, "heartbeat")
            logger.info("heartbeat spooled for retry")
        time.sleep(interval)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_daemon()


if __name__ == "__main__":
    main()
