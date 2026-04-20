# Heartbeat Monitor

轻量节点与任务通知系统。采用 **Client 心跳上报 + Server 主动探测 + 任务 Wrapper 监控 + 飞书/邮件通知** 的架构，适合中小规模服务器集群的节点在线状态监控和任务运行通知。

---

## 特性

- **双重检测**：心跳上报与 TCP 主动探测相结合，降低误报率
- **状态机驱动**：`UP` / `SUSPECT` / `DOWN` / `MAINTENANCE` 四态转换
- **任务监控**：通过 `hb` 包装任务，自动上报开始/结束/退出码/日志摘要
- **统一通知**：飞书 Webhook + SMTP 邮件双通道，支持去重
- **统一 Token 认证**：所有节点共享一个 enrollment token，无需两阶段注册和独立 node token
- **断网缓存**：Client 在 server 不可达时本地缓存事件，恢复后自动补发
- **轻量无依赖**：Python + SQLite + FastAPI，不依赖外部监控平台

---

## 快速开始

### 环境要求

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理工具

### 安装依赖

```bash
uv sync
uv pip install -e .
```

### 启动 Server

```bash
./setup-server.sh
export SERVER_CONFIG=config/server.yaml
uv run python -m server.main
```

Server 默认监听 `0.0.0.0:9999`，每 30 秒执行一次主动探测和状态评估。

### 启动 Client Daemon

```bash
./setup-client.sh
export CLIENT_CONFIG=config/client.yaml
uv run hb-daemon
```

节点会在第一次成功发送心跳时自动注册。Daemon 后台定时发送心跳并 flush 本地 spool。

### 运行被监控的任务

```bash
# 基本用法：任务命名为 train_a，执行 python 脚本，自动上报开始和结束。
# 默认仅在失败/超时时发送通知，成功时不通知。
hb --name train_a -- python train.py --epochs 20

# 设置超时：超过 2 小时未结束将强制终止任务，状态记为 TIMEOUT。
hb --name train_a --timeout 7200 -- python train.py --epochs 20

# 成功也通知：加上 --notify-success 后，任务成功（退出码 0）也会发送通知。
hb --name daily_report --notify-success --timeout 300 -- python generate_report.py

# 指定工作目录：进入 /data/scripts 目录后再执行备份脚本。
hb --name backup --cwd /data/scripts --timeout 1800 -- bash backup.sh

# 建议始终保留 -- 分隔符，防止命令中的参数被误解析为 hb 的选项。
hb --name simple_job -- echo "hello"
```

#### `hb` 参数说明

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--name` | **是** | 任务名称，用于在 Server 上标识 | `--name nightly-backup` |
| `--timeout` | 否 | 超时时间（秒），超期后强制终止 | `--timeout 3600` |
| `--notify-success` | 否 | 成功完成时也发送通知（默认仅失败时通知） | `--notify-success` |
| `--cwd` | 否 | 指定工作目录 | `--cwd /data/scripts` |
| `command` | **是** | 要执行的命令，放在 `--` 之后 | `-- python train.py` |

> **提示**：`--` 是 `hb` 参数与命令的分隔符，建议始终保留以避免解析歧义。

### 维护模式

对节点进行维护（如重启、升级）时，可将其标记为 `MAINTENANCE`，避免误报。

```bash
# 进入维护模式（自动读取 config/client.yaml）
./enter-maintenance.sh

# 退出维护模式，恢复自动评估
./exit-maintenance.sh
```

---

## 配置说明

### Server (`config/server.yaml`)

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

### Client (`config/client.yaml`)

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

## API 速查

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/register` | 节点注册（向后兼容） |
| `POST` | `/heartbeat` | Client 上报心跳 |
| `GET`  | `/health` | 监控中心自身健康状态 |
| `GET`  | `/nodes` | 查询所有节点当前状态 |
| `GET`  | `/nodes/{server_id}` | 查询单个节点详细信息 |
| `POST` | `/nodes/{server_id}/maintenance/start` | 进入维护模式 |
| `POST` | `/nodes/{server_id}/maintenance/end` | 结束维护模式 |
| `GET`  | `/status-page` | 可视化状态页面（节点 + 任务） |
| `POST` | `/task-runs/start` | 上报任务开始 |
| `POST` | `/task-runs/{run_id}/finish` | 上报任务结束 |
| `POST` | `/task-runs/{run_id}/cancel` | 取消运行中任务 |
| `GET`  | `/task-runs` | 查询任务列表 |
| `GET`  | `/task-runs/{run_id}` | 查询单个任务详情 |
| `GET`  | `/nodes/{server_id}/task-runs` | 查询某节点的任务列表 |

---

## 开发

### 运行测试

```bash
uv run pytest tests/ -v
```

### 查看日志

```bash
# Server
sudo journalctl -u hb-server.service -f

# Client
sudo journalctl -u hb-client.service -f
```

---

## 许可证

MIT
