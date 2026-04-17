# Heartbeat Monitor

内网服务器心跳监测与邮件告警系统。采用 **Client 心跳上报 + Server 主动探测 + 状态机判定 + SMTP 邮件告警** 的轻量级架构，适合 2~10 台规模的服务器监控场景。

---

## 特性

- **双重检测**：心跳上报与 TCP 主动探测相结合，降低误报率
- **状态机驱动**：`UP` / `SUSPECT` / `DOWN` 三态转换，仅在状态变化时发送邮件
- **轻量无依赖**：Python + SQLite + FastAPI，不依赖外部监控平台
- **一键配置**：交互式 Bash 脚本自动完成依赖安装、配置文件生成和 systemd 部署

---

## 项目结构

```
├── server/              # Server 端（监控中心）
│   ├── main.py          # FastAPI 入口 + 定时任务调度
│   ├── api.py           # API 路由
│   ├── config.py        # YAML 配置加载
│   ├── database.py      # SQLite 连接
│   ├── models.py        # SQLAlchemy 数据模型
│   ├── notifier.py      # SMTP 邮件发送
│   ├── probe.py         # TCP 主动探测
│   └── status_engine.py # 状态机与告警判定
├── client/              # Client 端（被监控节点）
│   ├── main.py          # 心跳脚本入口
│   ├── config.py        # 客户端配置加载
│   └── heartbeat.py     # 心跳上报逻辑
├── scripts/             # 自动化配置脚本
│   ├── setup-server.sh  # 服务端交互式配置 + systemd 安装
│   └── setup-client.sh  # 客户端交互式配置 + systemd 安装
├── config/              # 生成的配置文件目录
│   ├── server.yaml
│   └── client.yaml
├── systemd/             # systemd unit 模板
│   ├── hb-server.service
│   ├── hb-client.service
│   └── hb-client.timer
├── tests/               # 测试
│   └── test_server.py
└── pyproject.toml
```

---

## 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理工具

---

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置并启动 Server

运行交互式配置脚本，按提示输入监听地址、SMTP 邮箱和密码等信息：

```bash
./scripts/setup-server.sh
```

脚本会：
1. 自动运行 `uv sync`
2. 交互式生成 `config/server.yaml`
3. 询问是否自动安装 systemd service

然后设置初始节点并启动服务：

```bash
export SERVER_CONFIG=config/server.yaml
export MONITOR_NODES_SEED='[{"server_id":"lab-server-1","token_hash":"secret-token-1","probe_host":"127.0.0.1","probe_port":22}]'
uv run python -m server.main
```

Server 将监听 `0.0.0.0:8000`，并每 30 秒执行一次主动探测和状态评估。

### 3. 配置并运行 Client

在每台被监控机器上运行：

```bash
./scripts/setup-client.sh
```

脚本会：
1. 自动运行 `uv sync`
2. 交互式生成 `config/client.yaml`
3. 询问是否自动安装 systemd timer

发送一次心跳测试：

```bash
export CLIENT_CONFIG=config/client.yaml
uv run python -m client.main
```

如果安装了 systemd timer，心跳将每 30 秒自动发送一次。

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/heartbeat` | Client 上报心跳 |
| `GET`  | `/health` | 监控中心自身健康状态 |
| `GET`  | `/nodes` | 查询所有节点当前状态 |
| `GET`  | `/nodes/{server_id}` | 查询单个节点详细信息 |

### 心跳请求示例

```bash
curl -X POST http://127.0.0.1:8000/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "lab-server-1",
    "token": "secret-token-1",
    "hostname": "lab-node-a",
    "timestamp": 1776384000,
    "ip": "10.0.0.12"
  }'
```

---

## 测试

```bash
uv run pytest tests/test_server.py -v
```

---

## 部署建议

### Server 部署

推荐使用 systemd 托管（配置脚本可自动完成）：

```bash
sudo systemctl start hb-server.service
sudo systemctl status hb-server.service
```

### Client 部署

推荐在每台被监控机器上使用 systemd timer（配置脚本可自动完成）：

```bash
sudo systemctl start hb-client.timer
sudo systemctl status hb-client.timer
```

查看定时任务日志：

```bash
sudo journalctl -u hb-client.service -f
```

---

## 设计文档

详见 `todo.md`。
