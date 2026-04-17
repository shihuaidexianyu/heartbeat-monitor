# Heartbeat Monitor

内网服务器心跳监测与邮件告警系统。

## 项目结构

```
├── server/           # Server 端代码
│   ├── main.py       # FastAPI 入口 + APScheduler 调度
│   ├── api.py        # API 路由
│   ├── config.py     # 配置加载
│   ├── database.py   # SQLite 连接
│   ├── models.py     # SQLAlchemy 模型
│   ├── notifier.py   # 邮件通知
│   ├── probe.py      # TCP 主动探测
│   └── status_engine.py  # 状态机判定
├── client/           # Client 端代码
│   ├── main.py       # 客户端入口
│   ├── config.py     # 客户端配置
│   └── heartbeat.py  # 心跳发送
├── config/           # 配置示例
│   ├── server.yaml
│   └── client.yaml
├── scripts/          # 自动化脚本
│   ├── setup-server.sh
│   └── setup-client.sh
├── systemd/          # systemd 部署示例
│   ├── hb-server.service
│   ├── hb-client.service
│   └── hb-client.timer
├── tests/            # 测试
│   └── test_server.py
└── pyproject.toml
```

## 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 自动配置并启动 Server

```bash
HM_SMTP_HOST=smtp.gmail.com \
HM_SMTP_USER=alert@gmail.com \
HM_SMTP_PASS=your-app-password \
HM_SMTP_TO=admin@example.com \
./scripts/setup-server.sh
export SERVER_CONFIG=config/server.yaml
export MONITOR_NODES_SEED='[{"server_id":"lab-server-1","token_hash":"secret-token-1","probe_host":"127.0.0.1","probe_port":22}]'
uv run python -m server.main
```

### 3. 自动配置并运行 Client

```bash
HM_SERVER_URL=http://10.0.0.1:8000/heartbeat \
HM_SERVER_ID=lab-server-1 \
HM_TOKEN=secret-token-1 \
./scripts/setup-client.sh
export CLIENT_CONFIG=config/client.yaml
uv run python -m client.main
```

## API 接口

- `POST /heartbeat` — Client 心跳上报
- `GET /health` — 服务健康检查
- `GET /nodes` — 查询所有节点状态
- `GET /nodes/{server_id}` — 查询单个节点详情

## 测试

```bash
uv run pytest tests/test_server.py -v
```

## 部署

参考 `systemd/` 目录下的 service 和 timer 文件进行 systemd 部署。

## 设计文档

详见 `todo.md`。
