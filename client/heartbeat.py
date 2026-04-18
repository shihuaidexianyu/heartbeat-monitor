import logging
import socket
import time
import requests
from client.config import load_client_config

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def build_payload(cfg=None) -> dict:
    cfg = cfg or load_client_config()
    hostname = socket.gethostname()
    token = cfg.server.node_token or cfg.server.enrollment_token
    return {
        "server_id": cfg.server.server_id,
        "token": token,
        "hostname": hostname,
        "timestamp": int(time.time()),
        "ip": get_local_ip(),
        "services": {},
        "meta": {
            "agent_version": "0.2.0",
            "os": "Linux",
        },
    }


def send_heartbeat(cfg=None) -> tuple[bool, dict]:
    cfg = cfg or load_client_config()
    payload = build_payload(cfg)
    url = cfg.server.base_url.rstrip("/") + "/heartbeat"
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        logger.info("heartbeat sent successfully: %s", data.get("message"))
        return True, data
    except requests.Timeout:
        logger.error("heartbeat request timeout")
    except requests.ConnectionError as e:
        logger.error("heartbeat connection error: %s", e)
    except requests.HTTPError as e:
        logger.error("heartbeat failed: %s", e)
    except Exception as e:
        logger.error("heartbeat unexpected error: %s", e)
    return False, {}
