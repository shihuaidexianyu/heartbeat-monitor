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


class FeishuConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    secret: str = ""


class NotificationsConfig(BaseModel):
    email: SMTPConfig | None = None
    feishu: FeishuConfig = FeishuConfig()


class RegistrationConfig(BaseModel):
    enrollment_token: str = ""
    issue_per_node_token: bool = True


class MonitorConfig(BaseModel):
    probe_interval_sec: int = 30
    evaluation_interval_sec: int = 30
    default_tcp_timeout_sec: float = 3.0
    default_heartbeat_timeout_sec: int = 90
    default_probe_fail_threshold: int = 3


class DatabaseConfig(BaseModel):
    path: str = "./monitor.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str | None = None


class ServerConfig(BaseModel):
    listen_host: str = "0.0.0.0"
    listen_port: int = 8000
    default_token: str = ""  # deprecated, kept for compat
    smtp: SMTPConfig | None = None  # deprecated, kept for compat
    monitor: MonitorConfig = MonitorConfig()
    database: DatabaseConfig = DatabaseConfig()
    logging: LoggingConfig = LoggingConfig()
    registration: RegistrationConfig = RegistrationConfig()
    notifications: NotificationsConfig = NotificationsConfig()


def load_server_config(path: str | None = None) -> ServerConfig:
    if path is None:
        path = os.environ.get("SERVER_CONFIG", "config/server.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # backward compat: move top-level smtp into notifications.email
        if "smtp" in data and "notifications" not in data:
            data["notifications"] = {"email": data.pop("smtp")}
        return ServerConfig.model_validate(data)
    return ServerConfig()
