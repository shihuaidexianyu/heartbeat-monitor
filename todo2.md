
## 一、设计目标

这次改造后的系统只解决四件事：

1. 节点是否在线
2. 关键服务是否还可探测
3. 某个任务是否开始、结束、成功、失败、超时
4. 出事后怎么通过飞书和邮件通知出来

这版**不做**：

* 进程树追踪
* 细粒度 CPU/内存时序图
* 分布式任务调度平台
* 多租户/权限系统
* Prometheus 式通用指标平台

这意味着项目边界会很清楚：它是一个**轻量节点与任务通知系统**，不是全栈监控平台。

---

## 二、总体架构

我建议把项目定成下面这个结构：

```text id="otk4a4"
现有 heartbeat-monitor
├─ server 继续做中央服务
│  ├─ 接收 heartbeat
│  ├─ 做外部 probe
│  ├─ 判断节点状态
│  ├─ 接收任务开始/结束事件
│  ├─ 写数据库
│  ├─ 统一发送飞书/邮件
│  └─ 提供状态页/API
│
└─ client 升级为轻量 agent
   ├─ 定时 heartbeat
   ├─ 本地简单服务检查（可选）
   ├─ 以 wrapper 方式运行任务
   ├─ 上报任务开始/结束/结果
   └─ 网络断开时本地缓存，恢复后补发
```

核心原则只有两条：

第一，**server 绝对保留**。
因为只靠 client，你永远不知道机器是不是已经断网、断电、agent 崩溃。

第二，**task monitoring 用 wrapper 模式，不做 watch PID 作为主线**。
也就是任务通过你自己的 agent 启动，这样最容易拿到开始时间、结束时间、退出码、运行时长和日志摘要。你当前 `task_notify` 的 watch 模式本来就很薄，只适合兼容，不适合当主设计。

---

## 三、基于现有 heartbeat 的改造策略

### 1. 保留的部分

这些直接保留：

* `server/main.py`：FastAPI + APScheduler 主入口
* `server/api.py`：heartbeat / health / nodes / status-page 这套 API 逻辑
* `server/status_engine.py`：节点状态机
* `server/probe.py`：TCP 主动探测
* `server/models.py`：节点与事件表
* `server/notifier.py`：SMTP 发送能力
* `client/heartbeat.py`：客户端上报 heartbeat
* `setup-server.sh` / `setup-client.sh`：部署入口

### 2. 需要重构的部分

这几个要改：

* `server/notifier.py`：从“直接发邮件”改成“统一通知入口”
* `server/api.py`：拆出任务相关 API
* `server/models.py`：增加任务运行与通知记录表
* `client/main.py`：从单次心跳脚本变成 agent CLI 入口

### 3. 需要新增的部分

建议新增：

```text id="wfk9e5"
server/
  task_api.py
  task_service.py
  notification_service.py
  feishu_notifier.py
  event_service.py

client/
  agent.py
  task_runner.py
  spool.py
  local_checks.py
  cli.py
```

---

## 四、系统职责划分

## 4.1 Server 职责

Server 是“真相源”和“通知中心”，负责：

* 节点注册与鉴权
* 接收 heartbeat
* 调度外部 probe
* 保存节点状态与历史事件
* 接收任务运行事件
* 判断任务状态
* 统一发送飞书与邮件
* 提供查询接口和状态页

## 4.2 Client 职责

Client 是“本地执行器”和“本地观察者”，负责：

* 心跳上报
* 本地简单服务检查
* wrapper 方式运行任务
* 上报任务开始/结束/退出码/持续时间/日志摘要
* 当 server 不可达时临时缓存事件

---

## 五、节点监控设计

这部分基本沿用你当前 heartbeat 的思路，只做小改。

### 5.1 节点状态

节点状态定义为：

* `UP`
* `SUSPECT`
* `DOWN`
* `MAINTENANCE`

其中前三个你已经有了，新增一个维护态。当前项目已经是 heartbeat timeout + probe fail threshold 的双重判断，适合继续沿用。

### 5.2 节点状态来源

节点状态由三部分共同决定：

1. heartbeat 是否按时到达
2. server 对该节点的外部 probe 是否成功
3. 可选：agent 上报的本地关键服务状态

### 5.3 节点状态判定规则

建议保持你现在的精神不变：

* `UP -> SUSPECT`：heartbeat 超时，或 probe 连续失败
* `SUSPECT -> DOWN`：heartbeat 继续超时且 probe 连续失败
* `DOWN -> UP`：heartbeat 恢复且 probe 恢复
* `任意 -> MAINTENANCE`：手动进入维护
* `MAINTENANCE -> 重新评估`：维护结束后恢复自动判断

### 5.4 heartbeat payload 扩展

当前 `/heartbeat` 已经允许 `services` 和 `meta` 字段，建议正式用起来。

推荐 payload：

```json id="qsfd0w"
{
  "server_id": "lab-node-01",
  "token": "node-token",
  "hostname": "gpu-a",
  "timestamp": 1776384000,
  "ip": "10.0.0.12",
  "services": {
    "ssh": "up",
    "jupyter": "up"
  },
  "meta": {
    "agent_version": "0.2.0",
    "os": "Ubuntu 24.04"
  }
}
```

---

## 六、任务监控设计

这是这次改造的重点。

### 6.1 设计原则

任务监控只做“简要运行情况”，所以只记录这些：

* 任务名
* 所在节点
* 命令
* 开始时间
* 结束时间
* 运行时长
* 最终状态
* 退出码
* 日志摘要

不做：

* 子进程树
* 每秒 CPU/内存采样
* 复杂资源图表

### 6.2 任务状态模型

建议定义：

* `STARTING`
* `RUNNING`
* `SUCCESS`
* `FAILED`
* `TIMEOUT`
* `CANCELLED`
* `LOST`

说明：

* `STARTING`：agent 已接到命令，还没正式拉起
* `RUNNING`：进程已启动
* `SUCCESS`：退出码 0
* `FAILED`：退出码非 0
* `TIMEOUT`：超过限制时间
* `CANCELLED`：人工终止
* `LOST`：任务开始后 agent 与 server 长时间失联，无法确认结果

### 6.3 任务启动模式

只保留一个主模式：**wrapper run**

示例：

```bash id="mbc11l"
hb-agent run --name train_a --timeout 7200 -- python train.py --epochs 20
```

其运行流程是：

1. agent 生成 `run_id`
2. agent 调用 server：`/task-runs/start`
3. agent 用 Python `subprocess.Popen` 启动命令
4. stdout/stderr 重定向到本地日志文件
5. 本地等待进程结束
6. 结束后计算 duration / exit_code / 状态
7. 读取 stderr / stdout 尾部若干行作为摘要
8. 调用 server：`/task-runs/finish`

对你这个需求，`subprocess.Popen` 完全够用，不需要 psutil。Python 官方文档也给了这套子进程模型，退出码和管道行为都很明确。([docs.python.org](https://docs.python.org/zh-tw/3.12/library/subprocess.html?utm_source=chatgpt.com))

### 6.4 任务超时策略

支持可选 `timeout_sec`。

实现方式：

* 启动任务时记录 `started_at`
* 本地等待时检查 wall-clock
* 超时后先尝试 `terminate`
* 仍未退出则 `kill`
* 最终状态记为 `TIMEOUT`

### 6.5 日志摘要策略

任务结束后只取：

* stdout 最后 20 行
* stderr 最后 20 行

存在本地日志文件中，server 只存：

* `stdout_tail`
* `stderr_tail`
* `stdout_path`
* `stderr_path`

这样数据库不会膨胀，但通知里能带足够的错误上下文。

---

## 七、自动注册设计

你明确说了希望继续支持自动注册，我建议把当前的 `default_token` 自动注册升级成“两阶段注册”。

你当前项目已经支持：未知节点带着默认 token 发第一次 heartbeat 时，server 自动登记节点。这个机制很好用，应该保留。

### 7.1 注册阶段分两步

**第一步：enrollment token**

* 所有新节点安装时先使用统一 enrollment token
* 第一次 heartbeat 时带上 enrollment token
* server 校验通过后创建节点记录

**第二步：正式 node token**

* server 为新节点签发独立 node token
* agent 收到后写入本地配置
* 后续 heartbeat 都改用 node token
* enrollment token 不再用于日常通信

### 7.2 好处

这样能同时满足：

* 保留“自动注册”的便利
* 避免所有节点长期共用一个 token
* 方便单节点吊销、重置、轮换凭证

### 7.3 新增注册 API

建议新增：

* `POST /register`

返回：

```json id="h1bjsq"
{
  "ok": true,
  "node_token": "issued-node-token",
  "server_id": "lab-node-01",
  "heartbeat_interval_sec": 30
}
```

---

## 八、通知系统设计

当前 `server/notifier.py` 只负责 SMTP，而且状态机变化时直接发邮件。这个做法在只有邮件时够用，但一旦加飞书，最好抽成统一通知层。

### 8.1 新的通知流程

改成：

```text id="uhsdlt"
状态变化 / 任务结束
-> 写 Event
-> 规则引擎判定是否需要通知
-> NotificationService
-> EmailNotifier / FeishuNotifier
-> 写 notification 记录
```

### 8.2 通知渠道

初版两种：

* `EmailNotifier`
* `FeishuNotifier`

### 8.3 触发规则

建议默认规则：

* `node DOWN`：飞书 + 邮件
* `node RECOVERY`：飞书 + 邮件
* `task FAILED`：飞书
* `task TIMEOUT`：飞书 + 邮件
* `task SUCCESS`：默认不发；可在命令行加 `--notify-success` 开启
* `node SUSPECT`：默认只记事件，不发通知

### 8.4 去重和限流

初版至少做两个简单规则：

* 同一节点 10 分钟内重复 DOWN 不重复发
* 同一任务 run_id 只发一次终态通知

---

## 九、数据库设计

现有 `Node` 和 `Event` 表保留。再新增两张表就够：

### 9.1 `task_runs`

字段建议：

* `id`
* `run_id`，唯一
* `server_id`
* `task_name`
* `command_json`
* `cwd`
* `status`
* `started_at`
* `ended_at`
* `duration_sec`
* `exit_code`
* `timeout_sec`
* `stdout_path`
* `stderr_path`
* `stdout_tail`
* `stderr_tail`
* `notify_on_success`
* `created_at`
* `updated_at`

### 9.2 `notifications`

字段建议：

* `id`
* `source_type`（node/task）
* `source_id`
* `event_type`
* `channel`（email/feishu）
* `subject`
* `payload_json`
* `success`
* `response_text`
* `created_at`

### 9.3 是否需要 `tasks` 表

初版**不需要**。

因为你现在并不是在做“任务模板管理平台”，而是在做“任务运行通知”。
只记录 `task_runs` 就已经足够。

---

## 十、API 设计

## 10.1 保留现有 API

保留：

* `POST /heartbeat`
* `GET /health`
* `GET /nodes`
* `GET /nodes/{server_id}`
* `GET /status-page`

## 10.2 新增 API

### 注册

* `POST /register`

### 任务运行

* `POST /task-runs/start`
* `POST /task-runs/{run_id}/finish`
* `POST /task-runs/{run_id}/cancel`

### 查询

* `GET /task-runs`
* `GET /task-runs/{run_id}`
* `GET /nodes/{server_id}/task-runs`

### 维护模式（可选）

* `POST /nodes/{server_id}/maintenance/start`
* `POST /nodes/{server_id}/maintenance/end`

---

## 十一、状态页改造

当前已有简单 HTML 状态页。继续保持“轻量无前端框架”的路线即可。

新增两块：

### 11.1 节点概览

保留现有：

* server_id
* hostname
* status
* last heartbeat
* last probe

### 11.2 最近任务

新增：

* task_name
* server_id
* status
* started_at
* duration
* exit_code

### 11.3 失败任务摘要

新增一块“最近失败任务”，直接展示：

* task_name
* node
* exit_code
* stderr_tail 前几行

这样状态页就既能看机器，也能看任务。

---

## 十二、配置设计

## 12.1 服务端配置

在现有 `server.yaml` 上扩展：

```yaml id="g55umh"
listen_host: 0.0.0.0
listen_port: 8000

database:
  url: sqlite:///./monitor.db

monitor:
  probe_interval_sec: 30
  default_tcp_timeout_sec: 3
  default_heartbeat_timeout_sec: 90
  default_probe_fail_threshold: 3

registration:
  enrollment_token: "bootstrap-secret"

notifications:
  email:
    enabled: true
    host: smtp.example.com
    port: 465
    username: xxx
    password: xxx
    from_addr: xxx@example.com
    to_addrs:
      - me@example.com

  feishu:
    enabled: true
    webhook_url: "..."
    secret: "..."
```

## 12.2 客户端配置

在现有 `client.yaml` 上扩展：

```yaml id="g1j1pq"
server:
  base_url: "http://10.0.0.1:8000"
  server_id: "lab-node-01"
  enrollment_token: "bootstrap-secret"
  node_token: null
  heartbeat_interval_sec: 30

agent:
  log_dir: "/var/log/hb-agent"
  spool_dir: "/var/lib/hb-agent/spool"
  default_timeout_sec: 7200
```

---

## 十三、客户端 CLI 设计

建议把 `client/main.py` 改成统一 CLI：

```bash id="1tewe3"
hb-agent daemon
hb-agent register
hb-agent heartbeat-once
hb-agent run --name train_a -- python train.py
hb-agent run --name backup --timeout 1800 -- bash backup.sh
```

### 各命令职责

* `daemon`：常驻发送 heartbeat
* `register`：手动触发注册
* `heartbeat-once`：测试 server 通路
* `run`：包装任务并上报结果

---

## 十四、部署方案

### 14.1 服务端

继续用你现有做法：

* systemd 托管 server
* APScheduler 负责 probe/evaluate
* SQLite 本地持久化
* 可选 Nginx 反代

### 14.2 客户端

建议拆成两个 systemd unit：

* `hb-agent.service`：常驻 heartbeat daemon
* 不需要给 `run` 单独做 timer，它是命令式使用

### 14.3 网络不通时的策略

新增 `spool.py`：

* server 不可达时，把 heartbeat 或 task finish event 先写本地 JSON 文件
* daemon 每次 heartbeat 前顺便尝试补发
* 这样不会因为短时断网丢任务结果

---

## 十五、安全设计

这版至少做到：

* enrollment token 仅用于首次注册
* 后续统一使用独立 node token
* token 在服务端存 hash
* 飞书与 SMTP 密钥仅在服务端持有
* 客户端本地配置文件权限收紧
* status page 默认只内网访问
* 可选：为 API 增加简单 admin token

---

## 十六、测试方案

### 单元测试

重点测：

* 节点状态机
* 注册逻辑
* task run 状态转换
* timeout 行为
* notifier 去重

### 集成测试

至少做四条：

1. 新节点自动注册
2. 节点 heartbeat 中断 -> SUSPECT -> DOWN -> RECOVERY
3. 一个成功任务完整跑通
4. 一个失败/超时任务完整跑通并通知

---

## 十七、推荐的代码改造顺序

这个顺序最稳：

### 第一步：模型扩展

* 给 `server/models.py` 增加 `TaskRun` 和 `Notification`

### 第二步：注册逻辑升级

* 在现有自动注册基础上补“签发 node token”

### 第三步：任务 API

* 增加 `/task-runs/start` 和 `/task-runs/finish`

### 第四步：client wrapper

* 新增 `hb-agent run`

### 第五步：通知抽象

* 把 `server/notifier.py` 改成统一通知入口
* 先保持 SMTP 兼容，再补 Feishu

### 第六步：状态页扩展

* 显示最近任务

### 第七步：本地 spool

* 处理断网补发

---
