import os
import yaml
from typing import List
from pydantic import BaseModel


class SMTPConfig(BaseModel):
    host: str
    port: int = 587
    username: str
    password: str
    from_addr: str
    to_addrs: List[str]
    use_tls: bool = True


class MonitorConfig(BaseModel):
    probe_interval_sec: int = 30
    evaluation_interval_sec: int = 30
    default_tcp_timeout_sec: float = 3.0


class DatabaseConfig(BaseModel):
    path: str = "./monitor.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str | None = None


class ServerConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = 8000
    default_token: str = ""
    smtp: SMTPConfig | None = None
    monitor: MonitorConfig = MonitorConfig()
    database: DatabaseConfig = DatabaseConfig()
    logging: LoggingConfig = LoggingConfig()


def load_server_config(path: str | None = None) -> ServerConfig:
    if path is None:
        path = os.environ.get("SERVER_CONFIG", "config/server.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ServerConfig.model_validate(data)
    return ServerConfig()
