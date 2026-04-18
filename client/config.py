import os
import yaml
from pydantic import BaseModel


class ServerConfig(BaseModel):
    base_url: str = "http://127.0.0.1:8000"
    server_id: str = ""
    enrollment_token: str = ""
    node_token: str | None = None
    heartbeat_interval_sec: int = 30


class AgentConfig(BaseModel):
    log_dir: str = "/var/log/hb-agent"
    spool_dir: str = "/var/lib/hb-agent/spool"
    default_timeout_sec: int = 7200


class ClientConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    agent: AgentConfig = AgentConfig()


def load_client_config(path: str | None = None) -> ClientConfig:
    if path is None:
        path = os.environ.get("CLIENT_CONFIG", "config/client.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ClientConfig.model_validate(data)
    raise FileNotFoundError(f"Client config not found: {path}")
