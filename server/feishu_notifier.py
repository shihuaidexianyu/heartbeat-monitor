import json
import logging
import time
import base64
import hmac
import hashlib
import requests
from server.config import FeishuConfig

logger = logging.getLogger(__name__)


def sign(secret: str, timestamp: int) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


class FeishuNotifier:
    def __init__(self, cfg: FeishuConfig):
        self.cfg = cfg

    def send(self, title: str, content: str) -> tuple[bool, str]:
        if not self.cfg.enabled or not self.cfg.webhook_url:
            logger.info("Feishu notifier disabled or no webhook_url")
            return False, "disabled"

        timestamp = int(time.time())
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "text", "text": content}]],
                    }
                }
            },
        }
        if self.cfg.secret:
            payload["timestamp"] = timestamp
            payload["sign"] = sign(self.cfg.secret, timestamp)

        try:
            resp = requests.post(
                self.cfg.webhook_url,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return True, json.dumps(data)
            else:
                logger.error("Feishu webhook error: %s", data)
                return False, json.dumps(data)
        except Exception as e:
            logger.error("Feishu webhook failed: %s", e)
            return False, str(e)
