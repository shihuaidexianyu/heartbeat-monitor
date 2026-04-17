import os
import yaml
from pydantic import BaseModel


class ClientConfig(BaseModel):
    server_url: str
    server_id: str
    token: str
    interval_sec: int = 30
    timeout_sec: int = 5


def load_client_config(path: str | None = None) -> ClientConfig:
    if path is None:
        path = os.environ.get("CLIENT_CONFIG", "config/client.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ClientConfig.model_validate(data)
    raise FileNotFoundError(f"Client config not found: {path}")
