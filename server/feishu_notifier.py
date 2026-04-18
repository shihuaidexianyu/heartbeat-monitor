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

    def _post(self, payload: dict) -> tuple[bool, str]:
        try:
            resp = requests.post(
                self.cfg.webhook_url,
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 0:
                return True, json.dumps(data, ensure_ascii=False)
            logger.error("Feishu webhook error: %s", data)
            return False, json.dumps(data, ensure_ascii=False)
        except Exception as e:
            logger.error("Feishu webhook failed: %s", e)
            return False, str(e)

    def send(self, title: str, content: str, card: dict | None = None) -> tuple[bool, str]:
        if not self.cfg.enabled or not self.cfg.webhook_url:
            logger.info("Feishu notifier disabled or no webhook_url")
            return False, "disabled"

        timestamp = int(time.time())
        base_payload = {}
        if self.cfg.secret:
            base_payload["timestamp"] = timestamp
            base_payload["sign"] = sign(self.cfg.secret, timestamp)

        if card:
            ok, response = self._post({
                **base_payload,
                "msg_type": "interactive",
                "card": card,
            })
            if ok:
                return ok, response
            logger.warning("Feishu interactive card failed, fallback to post: %s", response)

        return self._post({
            **base_payload,
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "text", "text": content}]],
                    }
                }
            },
        })
