# Heartbeat Monitor

轻量节点与任务通知系统。采用 **Client 心跳上报 + Server 主动探测 + 任务 Wrapper 监控 + 飞书/邮件通知** 的架构，适合中小规模服务器集群的节点在线状态监控和任务运行通知。

---

## 特性

- **双重检测**：心跳上报与 TCP 主动探测相结合，降低误报率
- **状态机驱动**：`UP` / `SUSPECT` / `DOWN` / `MAINTENANCE` 四态转换
- **任务监控**：通过 `hb` 包装任务，自动上报开始/结束/退出码/日志摘要
- **统一通知**：飞书 Webhook + SMTP 邮件双通道，支持去重和限流
- **统一 Token 认证**：所有节点共享一个 enrollment token，无需两阶段注册和独立 node token
- **断网缓存**：Client 在 server 不可达时本地缓存事件，恢复后自动补发
- **轻量无依赖**：Python + SQLite + FastAPI，不依赖外部监控平台

---

## 项目结构

```
├── server/                   # Server 端（监控中心）
│   ├── main.py               # FastAPI 入口 + APScheduler 定时任务
│   ├── api.py                # 心跳/节点/状态页 API
│   ├── task_api.py           # 任务运行 API
│   ├── config.py             # YAML 配置加载
│   ├── database.py           # SQLite 连接
│   ├── models.py             # SQLAlchemy 数据模型
│   ├── notification_service.py # 统一通知入口
│   ├── notifier.py           # SMTP 邮件发送
│   ├── feishu_notifier.py    # 飞书 Webhook 发送
│   ├── probe.py              # TCP 主动探测
│   └── status_engine.py      # 状态机与告警判定
├── client/                   # Client 端（被监控节点）
│   ├── cli.py                # hb 统一 CLI
│   ├── agent.py              # 常驻 heartbeat daemon
│   ├── task_runner.py        # 任务 wrapper 执行与上报
│   ├── heartbeat.py          # 心跳上报逻辑
│   ├── spool.py              # 断网本地缓存
│   └── config.py             # 客户端配置加载
├── setup-server.sh           # 服务端交互式配置 + systemd 安装
├── setup-client.sh           # 客户端交互式配置 + systemd 安装
├── remove-service.sh         # 移除 systemd 服务
├── config/                   # 生成的配置文件目录
│   ├── server.yaml
│   └── client.yaml
├── systemd/                  # systemd unit 模板
│   ├── hb-server.service
│   └── hb-client.service
├── tests/                    # 测试
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
uv pip install -e .
```

### 2. 配置并启动 Server

运行交互式配置脚本：

```bash
./setup-server.sh
```

脚本会：

1. 自动运行 `uv sync`
2. 交互式生成 `config/server.yaml`
3. 询问是否自动安装 systemd service

然后启动服务：

```bash
export SERVER_CONFIG=config/server.yaml
uv run python -m server.main
```

Server 将监听配置的端口（默认 `0.0.0.0:9999`），并每 30 秒执行一次主动探测和状态评估。

> **Token 初始化**：`setup-server.sh` 会自动生成一个 **enrollment token** 写入 `config/server.yaml`。Client 端在 `config/client.yaml` 中配置同样的 token，所有请求（心跳、任务上报）均使用此统一 token 鉴权。

### 3. 配置并运行 Client

在每台被监控机器上运行：

```bash
./setup-client.sh
```

脚本会：

1. 自动运行 `uv sync`
2. 交互式生成 `config/client.yaml`
3. 询问是否自动安装 systemd service（常驻 daemon）

**启动常驻 daemon**：

```bash
export CLIENT_CONFIG=config/client.yaml
uv run hb-daemon
```

节点会在第一次成功发送心跳时自动注册。如果安装了 systemd service，daemon 会在后台自动运行，定时发送心跳并 flush 本地 spool。

### 4. 运行被监控的任务

用 `hb` 包装任意命令，自动上报任务生命周期：

```bash
hb --name train_a --timeout 7200 -- python train.py --epochs 20
hb --name backup --timeout 1800 -- bash backup.sh
```

流程：
1. agent 生成 `run_id`，调用 Server `/task-runs/start`
2. 本地用 `subprocess.Popen` 启动命令
3. 等待进程结束，计算 duration / exit_code
4. 取 stdout/stderr 尾部 20 行作为摘要
5. 调用 Server `/task-runs/{run_id}/finish` 上报结果

如果 Server 不可达，任务结果会先写入本地 spool，daemon 下次心跳时自动补发。

### 移除服务

如需卸载本地安装内容，运行：

```bash
./remove-service.sh
```

脚本会按提示选择性清理这些内容：

1. `hb-server.service` / `hb-client.service` / `hb-client.timer`
2. `~/.local/bin/hb` 启动器
3. `.venv` 中的 editable 安装包
4. `logs/`、`spool/`、`monitor.db`

你的配置文件会被保留，不在清理范围内。

---

## API 接口

### 现有 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/register` | 节点注册（向后兼容，统一使用 enrollment token） |
| `POST` | `/heartbeat` | Client 上报心跳 |
| `GET`  | `/health` | 监控中心自身健康状态 |
| `GET`  | `/nodes` | 查询所有节点当前状态 |
| `GET`  | `/nodes/{server_id}` | 查询单个节点详细信息 |
| `POST` | `/nodes/{server_id}/maintenance/start` | 进入维护模式 |
| `POST` | `/nodes/{server_id}/maintenance/end` | 结束维护模式 |
| `GET`  | `/status-page` | 可视化状态页面（节点 + 任务） |

### 任务 API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/task-runs/start` | 上报任务开始（需 X-Node-Token） |
| `POST` | `/task-runs/{run_id}/finish` | 上报任务结束（需 X-Node-Token） |
| `POST` | `/task-runs/{run_id}/cancel` | 取消运行中任务（需 X-Node-Token） |
| `GET`  | `/task-runs` | 查询任务列表 |
| `GET`  | `/task-runs/{run_id}` | 查询单个任务详情 |
| `GET`  | `/nodes/{server_id}/task-runs` | 查询某节点的任务列表 |

### 注册请求示例

```bash
curl -X POST http://127.0.0.1:9999/register \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "lab-node-01",
    "enrollment_token": "bootstrap-secret",
    "hostname": "gpu-a",
    "ip": "10.0.0.12"
  }'
```

返回：
```json
{
  "ok": true,
  "server_id": "lab-node-01",
  "heartbeat_interval_sec": 30
}
```

### 心跳请求示例

```bash
curl -X POST http://127.0.0.1:9999/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "lab-node-01",
    "token": "bootstrap-secret",
    "hostname": "gpu-a",
    "timestamp": 1776384000,
    "ip": "10.0.0.12",
    "services": {"ssh": "up", "jupyter": "up"},
    "meta": {"agent_version": "0.2.0", "os": "Ubuntu 24.04"}
  }'
```

### 任务开始示例

```bash
curl -X POST http://127.0.0.1:9999/task-runs/start \
  -H "Content-Type: application/json" \
  -d '{
    "server_id": "lab-node-01",
    "task_name": "train_a",
    "command": ["python", "train.py"],
    "timeout_sec": 7200,
    "token": "bootstrap-secret"
  }'
```

---

## 配置说明

### Server 配置 (`config/server.yaml`)

```yaml
listen_host: "0.0.0.0"
listen_port: 9999

database:
  path: "./monitor.db"

monitor:
  probe_interval_sec: 30
  default_tcp_timeout_sec: 3
  default_heartbeat_timeout_sec: 90
  default_probe_fail_threshold: 3

registration:
  enrollment_token: "your-secret-token"

notifications:
  email:
    enabled: true
    host: "smtp.example.com"
    port: 465
    username: "xxx"
    password: "xxx"
    from_addr: "xxx@example.com"
    to_addrs:
      - "me@example.com"
    use_tls: true
  feishu:
    enabled: false
    webhook_url: "..."
    secret: "..."

logging:
  level: "INFO"
  file: "./logs/server.log"
```

### Client 配置 (`config/client.yaml`)

```yaml
server:
  base_url: "http://10.0.0.1:9999"
  server_id: "lab-node-01"
  enrollment_token: "your-secret-token"
  heartbeat_interval_sec: 30

agent:
  log_dir: "/var/log/hb-agent"
  spool_dir: "/var/lib/hb-agent/spool"
  default_timeout_sec: 7200
```

---

## 测试

```bash
uv run pytest tests/test_server.py -v
```

---

## 部署建议

### Server 部署

推荐使用 systemd 托管：

```bash
sudo systemctl start hb-server.service
sudo systemctl status hb-server.service
```

状态页默认内网访问，如需公网暴露建议加 Nginx 反代和基本认证。

### Client 部署

推荐在每台被监控机器上使用 systemd service（常驻 daemon）：

```bash
sudo systemctl start hb-client.service
sudo systemctl status hb-client.service
```

查看 daemon 日志：

```bash
sudo journalctl -u hb-client.service -f
```

### 网络不通时的策略

Client 的 spool 机制会在 server 不可达时：
- 把 heartbeat 和 task finish 事件写入本地 JSON 文件
- daemon 每次心跳前自动尝试补发
- 不会因短时断网丢失任务结果

---

## 设计文档

- `todo.md` — 原始 heartbeat 监控设计
- `todo2.md` — v0.2.0 改造设计（节点监控 + 任务监控 + 通知系统）
