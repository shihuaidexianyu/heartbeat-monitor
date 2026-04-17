import logging
import socket
import time
from datetime import datetime, timezone
import requests
from client.config import load_client_config

logger = logging.getLogger(__name__)
config = load_client_config()


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


def build_payload() -> dict:
    hostname = socket.gethostname()
    return {
        "server_id": config.server_id,
        "token": config.token,
        "hostname": hostname,
        "timestamp": int(time.time()),
        "ip": get_local_ip(),
        "services": {},
        "meta": {},
    }


def send_heartbeat() -> bool:
    payload = build_payload()
    try:
        resp = requests.post(
            config.server_url,
            json=payload,
            timeout=config.timeout_sec,
        )
        resp.raise_for_status()
        logger.info("heartbeat sent successfully: %s", resp.json().get("message"))
        return True
    except requests.Timeout:
        logger.error("heartbeat request timeout")
    except requests.ConnectionError as e:
        logger.error("heartbeat connection error: %s", e)
    except requests.HTTPError as e:
        logger.error("heartbeat failed: %s", e)
    except Exception as e:
        logger.error("heartbeat unexpected error: %s", e)
    return False
