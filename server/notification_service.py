import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html import escape
from sqlalchemy.orm import Session

from server.config import load_server_config
from server.models import Node, TaskRun, Notification, now_iso
from server.notifier import EmailNotifier
from server.feishu_notifier import FeishuNotifier

logger = logging.getLogger(__name__)
config = load_server_config()

STATUS_LABELS = {
    "UP": "在线",
    "DOWN": "离线",
    "SUSPECT": "疑似异常",
    "MAINTENANCE": "维护中",
}

STATUS_COLORS = {
    "UP": "#16a34a",
    "DOWN": "#dc2626",
    "SUSPECT": "#d97706",
    "MAINTENANCE": "#2563eb",
}

FEISHU_HEADER_TEMPLATES = {
    "UP": "green",
    "DOWN": "red",
    "SUSPECT": "orange",
    "MAINTENANCE": "blue",
}

TASK_STATUS_LABELS = {
    "SUCCESS": "成功",
    "FAILED": "失败",
    "TIMEOUT": "超时",
    "CANCELLED": "已取消",
    "RUNNING": "运行中",
    "STARTING": "启动中",
    "LOST": "失联",
}

TASK_STATUS_COLORS = {
    "SUCCESS": "#16a34a",
    "FAILED": "#dc2626",
    "TIMEOUT": "#d97706",
    "CANCELLED": "#6b7280",
    "RUNNING": "#2563eb",
    "STARTING": "#0ea5e9",
    "LOST": "#7c3aed",
}

TASK_FEISHU_HEADER_TEMPLATES = {
    "SUCCESS": "green",
    "FAILED": "red",
    "TIMEOUT": "orange",
    "CANCELLED": "grey",
    "RUNNING": "blue",
    "STARTING": "wathet",
    "LOST": "purple",
}


class NotificationService:
    _executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="notify")

    def __init__(self, db: Session):
        self.db = db
        email_cfg = config.notifications.email
        self._email = EmailNotifier(email_cfg) if email_cfg and email_cfg.enabled else None
        self._feishu = FeishuNotifier(config.notifications.feishu)

    @staticmethod
    def _label_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)

    @staticmethod
    def _format_time(ts: str | None) -> str:
        if not ts:
            return "暂无"
        try:
            return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        except ValueError:
            return ts

    @staticmethod
    def _format_probe_result(last_probe_ok: int | None, last_probe_at: str | None) -> str:
        if last_probe_at is None:
            return "暂无探测记录"
        result = "成功" if last_probe_ok else "失败"
        return f"{result}（{NotificationService._format_time(last_probe_at)}）"

    @staticmethod
    def _format_duration(duration_sec: float | None) -> str:
        if duration_sec is None:
            return "暂无"
        if duration_sec < 60:
            return f"{duration_sec:.1f} 秒"
        minutes, seconds = divmod(duration_sec, 60)
        if minutes < 60:
            return f"{int(minutes)} 分 {seconds:.1f} 秒"
        hours, minutes = divmod(int(minutes), 60)
        return f"{hours} 小时 {minutes} 分 {seconds:.1f} 秒"

    @staticmethod
    def _truncate_text(text: str | None, limit: int = 1200) -> str | None:
        if not text:
            return None
        if len(text) <= limit:
            return text
        return text[: limit - 13] + "\n...已截断"

    def _build_task_output_sections(self, task: TaskRun) -> list[dict]:
        sections = []
        stderr_excerpt = self._truncate_text(task.stderr_tail)
        stdout_excerpt = self._truncate_text(task.stdout_tail)
        if stderr_excerpt:
            sections.append({
                "label": "标准错误摘要",
                "content": stderr_excerpt,
            })
        if stdout_excerpt:
            sections.append({
                "label": "标准输出摘要",
                "content": stdout_excerpt,
            })
        return sections

    @staticmethod
    def _translate_reason(reason: str) -> str:
        translated = reason
        translated = re.sub(r"tcp probe failed (\d+) times", r"TCP 探测连续失败 \1 次", translated)
        translated = translated.replace("heartbeat timeout", "心跳超时")
        translated = translated.replace("heartbeat or probe recovered", "心跳或 TCP 探测已恢复")
        translated = translated.replace(" and ", "，且")
        return translated

    def _build_node_change_message(self, node: Node, old_status: str, new_status: str, reason: str) -> dict:
        old_label = self._label_status(old_status)
        new_label = self._label_status(new_status)
        reason_zh = self._translate_reason(reason)
        happened_at = self._format_time(now_iso())
        last_heartbeat = self._format_time(node.last_heartbeat_at)
        last_probe = self._format_probe_result(node.last_probe_ok, node.last_probe_at)
        probe_target = f"{node.probe_host}:{node.probe_port}"

        if new_status == "DOWN":
            subject = f"[严重告警] 节点 {node.server_id} 已离线"
            summary = f"节点 {node.server_id} 当前状态变为离线，请尽快处理。"
        elif new_status == "SUSPECT":
            subject = f"[状态预警] 节点 {node.server_id} 疑似异常"
            summary = f"节点 {node.server_id} 出现异常迹象，建议尽快排查。"
        elif new_status == "UP" and old_status == "DOWN":
            subject = f"[恢复通知] 节点 {node.server_id} 已恢复在线"
            summary = f"节点 {node.server_id} 已从离线状态恢复。"
        else:
            subject = f"[状态变更] 节点 {node.server_id} {old_label} -> {new_label}"
            summary = f"节点 {node.server_id} 状态发生变化。"

        text_body = "\n".join([
            summary,
            "",
            f"节点 ID：{node.server_id}",
            f"主机名：{node.hostname or '暂无'}",
            f"探测目标：{probe_target}",
            f"状态变化：{old_label} -> {new_label}",
            f"变化原因：{reason_zh}",
            f"最近心跳：{last_heartbeat}",
            f"最近探测：{last_probe}",
            f"探测失败次数：{node.probe_fail_count}",
            f"心跳超时阈值：{node.heartbeat_timeout_sec} 秒",
            f"TCP 失败阈值：{node.probe_fail_threshold} 次",
            f"通知时间：{happened_at}",
        ])

        status_color = STATUS_COLORS.get(new_status, "#2563eb")
        escaped_summary = escape(summary)
        escaped_reason = escape(reason_zh)
        escaped_hostname = escape(node.hostname or "暂无")
        escaped_target = escape(probe_target)
        escaped_server_id = escape(node.server_id)
        escaped_transition = escape(f"{old_label} -> {new_label}")
        escaped_last_heartbeat = escape(last_heartbeat)
        escaped_last_probe = escape(last_probe)
        escaped_happened_at = escape(happened_at)
        html_body = f"""\
<html>
  <body style="margin:0;padding:24px;background:#f5f7fb;font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2937;">
    <div style="max-width:720px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;">
      <div style="padding:20px 24px;background:{status_color};color:#ffffff;">
        <div style="font-size:14px;opacity:0.9;">Heartbeat Monitor</div>
        <div style="margin-top:6px;font-size:24px;font-weight:700;">{escaped_summary}</div>
      </div>
      <div style="padding:24px;">
        <p style="margin:0 0 18px 0;font-size:15px;line-height:1.7;">{escaped_reason}</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr><td style="padding:10px 0;color:#6b7280;width:140px;">节点 ID</td><td style="padding:10px 0;font-weight:600;">{escaped_server_id}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">主机名</td><td style="padding:10px 0;">{escaped_hostname}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">探测目标</td><td style="padding:10px 0;">{escaped_target}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">状态变化</td><td style="padding:10px 0;"><span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:{status_color};font-weight:700;">{escaped_transition}</span></td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">最近心跳</td><td style="padding:10px 0;">{escaped_last_heartbeat}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">最近探测</td><td style="padding:10px 0;">{escaped_last_probe}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">探测失败次数</td><td style="padding:10px 0;">{node.probe_fail_count}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">心跳超时阈值</td><td style="padding:10px 0;">{node.heartbeat_timeout_sec} 秒</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">TCP 失败阈值</td><td style="padding:10px 0;">{node.probe_fail_threshold} 次</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">通知时间</td><td style="padding:10px 0;">{escaped_happened_at}</td></tr>
        </table>
      </div>
    </div>
  </body>
</html>
"""

        feishu_card = {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": FEISHU_HEADER_TEMPLATES.get(new_status, "blue"),
                "title": {
                    "tag": "plain_text",
                    "content": subject,
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{summary}**\n{reason_zh}",
                    },
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "fields": [
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**节点 ID**\n{node.server_id}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**主机名**\n{node.hostname or '暂无'}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**状态变化**\n{old_label} -> {new_label}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**探测目标**\n{probe_target}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**最近心跳**\n{last_heartbeat}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**最近探测**\n{last_probe}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**探测失败次数**\n{node.probe_fail_count}"}},
                        {"is_short": True, "text": {"tag": "lark_md", "content": f"**通知时间**\n{happened_at}"}},
                    ],
                },
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": f"心跳超时阈值：{node.heartbeat_timeout_sec} 秒"},
                        {"tag": "plain_text", "content": f"TCP 失败阈值：{node.probe_fail_threshold} 次"},
                    ],
                },
            ],
        }

        return {
            "subject": subject,
            "text_body": text_body,
            "html_body": html_body,
            "feishu_card": feishu_card,
            "payload": {
                "summary": summary,
                "reason": reason_zh,
                "node": {
                    "server_id": node.server_id,
                    "hostname": node.hostname,
                    "probe_target": probe_target,
                },
                "status": {
                    "old": old_status,
                    "new": new_status,
                    "old_label": old_label,
                    "new_label": new_label,
                },
                "metrics": {
                    "last_heartbeat_at": node.last_heartbeat_at,
                    "last_probe_at": node.last_probe_at,
                    "last_probe_ok": bool(node.last_probe_ok),
                    "probe_fail_count": node.probe_fail_count,
                    "heartbeat_timeout_sec": node.heartbeat_timeout_sec,
                    "probe_fail_threshold": node.probe_fail_threshold,
                },
                "sent_at": now_iso(),
            },
        }

    def _build_task_finish_message(self, task: TaskRun) -> dict:
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        status_color = TASK_STATUS_COLORS.get(task.status, "#2563eb")
        header_template = TASK_FEISHU_HEADER_TEMPLATES.get(task.status, "blue")
        duration = self._format_duration(task.duration_sec)
        started_at = self._format_time(task.started_at)
        ended_at = self._format_time(task.ended_at)
        output_sections = self._build_task_output_sections(task)

        if task.status == "SUCCESS":
            subject = f"[任务成功] {task.task_name} @ {task.server_id}"
            summary = f"任务 {task.task_name} 已执行成功。"
        elif task.status == "FAILED":
            subject = f"[任务失败] {task.task_name} @ {task.server_id}"
            summary = f"任务 {task.task_name} 执行失败，请尽快排查。"
        elif task.status == "TIMEOUT":
            subject = f"[任务超时] {task.task_name} @ {task.server_id}"
            summary = f"任务 {task.task_name} 执行超时。"
        elif task.status == "CANCELLED":
            subject = f"[任务取消] {task.task_name} @ {task.server_id}"
            summary = f"任务 {task.task_name} 已被取消。"
        else:
            subject = f"[任务状态变更] {task.task_name} @ {task.server_id}"
            summary = f"任务 {task.task_name} 状态变为 {status_label}。"

        text_lines = [
            summary,
            "",
            f"任务名称：{task.task_name}",
            f"节点 ID：{task.server_id}",
            f"运行 ID：{task.run_id}",
            f"当前状态：{status_label}",
            f"开始时间：{started_at}",
            f"结束时间：{ended_at}",
            f"运行时长：{duration}",
        ]
        if task.exit_code is not None:
            text_lines.append(f"退出码：{task.exit_code}")
        for section in output_sections:
            text_lines.extend(["", f"{section['label']}：", section["content"]])
        text_body = "\n".join(text_lines)

        escaped_summary = escape(summary)
        escaped_task_name = escape(task.task_name)
        escaped_server_id = escape(task.server_id)
        escaped_run_id = escape(task.run_id)
        escaped_status = escape(status_label)
        escaped_started_at = escape(started_at)
        escaped_ended_at = escape(ended_at)
        escaped_duration = escape(duration)
        exit_code_row = ""
        if task.exit_code is not None:
            exit_code_row = f'<tr><td style="padding:10px 0;color:#6b7280;">退出码</td><td style="padding:10px 0;">{task.exit_code}</td></tr>'
        excerpt_blocks = []
        for section in output_sections:
            excerpt_blocks.append(f"""
        <div style="margin-top:20px;">
          <div style="margin-bottom:8px;font-size:14px;color:#6b7280;">{escape(section['label'])}</div>
          <pre style="margin:0;padding:16px;background:#0f172a;color:#e2e8f0;border-radius:12px;white-space:pre-wrap;font-size:13px;line-height:1.6;">{escape(section['content'])}</pre>
        </div>
""")
        excerpt_block = "".join(excerpt_blocks)
        html_body = f"""\
<html>
  <body style="margin:0;padding:24px;background:#f5f7fb;font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2937;">
    <div style="max-width:720px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;">
      <div style="padding:20px 24px;background:{status_color};color:#ffffff;">
        <div style="font-size:14px;opacity:0.9;">Heartbeat Monitor</div>
        <div style="margin-top:6px;font-size:24px;font-weight:700;">{escaped_summary}</div>
      </div>
      <div style="padding:24px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr><td style="padding:10px 0;color:#6b7280;width:140px;">任务名称</td><td style="padding:10px 0;font-weight:600;">{escaped_task_name}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">节点 ID</td><td style="padding:10px 0;">{escaped_server_id}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">运行 ID</td><td style="padding:10px 0;">{escaped_run_id}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">当前状态</td><td style="padding:10px 0;"><span style="display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:{status_color};font-weight:700;">{escaped_status}</span></td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">开始时间</td><td style="padding:10px 0;">{escaped_started_at}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">结束时间</td><td style="padding:10px 0;">{escaped_ended_at}</td></tr>
          <tr><td style="padding:10px 0;color:#6b7280;">运行时长</td><td style="padding:10px 0;">{escaped_duration}</td></tr>
          {exit_code_row}
        </table>
{excerpt_block}
      </div>
    </div>
  </body>
</html>
"""

        feishu_elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{summary}**",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**任务名称**\n{task.task_name}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**节点 ID**\n{task.server_id}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**运行 ID**\n{task.run_id}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**当前状态**\n{status_label}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**开始时间**\n{started_at}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**结束时间**\n{ended_at}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**运行时长**\n{duration}"}},
                ],
            },
        ]
        if task.exit_code is not None:
            feishu_elements.append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": f"退出码：{task.exit_code}"}],
            })
        for section in output_sections:
            feishu_elements.extend([
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{section['label']}**",
                    },
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": section["content"],
                    },
                },
            ])

        feishu_card = {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": header_template,
                "title": {
                    "tag": "plain_text",
                    "content": subject,
                },
            },
            "elements": feishu_elements,
        }

        return {
            "subject": subject,
            "text_body": text_body,
            "html_body": html_body,
            "feishu_card": feishu_card,
            "payload": {
                "summary": summary,
                "task": {
                    "run_id": task.run_id,
                    "task_name": task.task_name,
                    "server_id": task.server_id,
                    "status": task.status,
                    "status_label": status_label,
                    "started_at": task.started_at,
                    "ended_at": task.ended_at,
                    "duration_sec": task.duration_sec,
                    "exit_code": task.exit_code,
                },
                "output_sections": output_sections,
                "sent_at": now_iso(),
            },
        }

    def _should_notify_node(self, node: Node, old_status: str, new_status: str) -> dict:
        # dedup: same node same status within 10 min
        if new_status == "DOWN":
            return {"email": True, "feishu": True}
        if new_status == "UP" and old_status == "DOWN":
            return {"email": True, "feishu": True}
        return {}

    def _recent_notification_exists(self, source_type: str, source_id: str, event_type: str, channel: str, seconds: int = 600) -> bool:
        from sqlalchemy import text
        sql = text("""
            SELECT id FROM notifications
            WHERE source_type = :st AND source_id = :sid AND event_type = :et AND channel = :ch
            AND created_at > datetime('now', :sec)
            LIMIT 1
        """)
        result = self.db.execute(sql, {
            "st": source_type, "sid": source_id, "et": event_type, "ch": channel,
            "sec": f"-{seconds} seconds"
        })
        return result.fetchone() is not None

    def notify_node_change(self, node: Node, old_status: str, new_status: str, reason: str):
        channels = self._should_notify_node(node, old_status, new_status)
        if not channels:
            return

        event_type = f"node_{new_status.lower()}"
        message = self._build_node_change_message(node, old_status, new_status, reason)
        subject = message["subject"]
        body = message["text_body"]

        for channel, enabled in channels.items():
            if not enabled:
                continue
            if channel == "email" and self._email:
                if self._recent_notification_exists("node", node.server_id, event_type, "email"):
                    logger.info("dedup: skip email for %s %s", node.server_id, event_type)
                    continue
                self._send_async(
                    "node",
                    node.server_id,
                    event_type,
                    "email",
                    subject,
                    body,
                    self._email,
                    payload=message["payload"],
                    html_body=message["html_body"],
                )
            if channel == "feishu" and self._feishu:
                if self._recent_notification_exists("node", node.server_id, event_type, "feishu"):
                    logger.info("dedup: skip feishu for %s %s", node.server_id, event_type)
                    continue
                self._send_async(
                    "node",
                    node.server_id,
                    event_type,
                    "feishu",
                    subject,
                    body,
                    self._feishu,
                    payload=message["payload"],
                    feishu_card=message["feishu_card"],
                )

    def notify_task_finish(self, task: TaskRun):
        if task.status == "SUCCESS" and not task.notify_on_success:
            return
        if task.status not in ("SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"):
            return

        # dedup: same run_id only once
        existing = self.db.query(Notification).filter(
            Notification.source_type == "task",
            Notification.source_id == task.run_id,
            Notification.event_type == f"task_{task.status.lower()}",
        ).first()
        if existing:
            logger.info("dedup: skip task notification for run_id=%s", task.run_id)
            return

        event_type = f"task_{task.status.lower()}"
        message = self._build_task_finish_message(task)
        subject = message["subject"]
        body = message["text_body"]

        channels = {"feishu": True}
        if task.status in ("FAILED", "TIMEOUT"):
            channels["email"] = True

        for channel, enabled in channels.items():
            if not enabled:
                continue
            if channel == "email" and self._email:
                self._send_async(
                    "task",
                    task.run_id,
                    event_type,
                    "email",
                    subject,
                    body,
                    self._email,
                    payload=message["payload"],
                    html_body=message["html_body"],
                )
            if channel == "feishu" and self._feishu:
                self._send_async(
                    "task",
                    task.run_id,
                    event_type,
                    "feishu",
                    subject,
                    body,
                    self._feishu,
                    payload=message["payload"],
                    feishu_card=message["feishu_card"],
                )

    def _send_async(
        self,
        source_type: str,
        source_id: str,
        event_type: str,
        channel: str,
        subject: str,
        body: str,
        notifier,
        payload: dict | None = None,
        html_body: str | None = None,
        feishu_card: dict | None = None,
    ):
        def _do():
            # Double-check dedup right before sending (reduces race window)
            try:
                from server.database import SessionLocal
                check_db = SessionLocal()
                dup = check_db.query(Notification).filter(
                    Notification.source_type == source_type,
                    Notification.source_id == source_id,
                    Notification.event_type == event_type,
                    Notification.channel == channel,
                ).first()
                check_db.close()
                if dup:
                    logger.info("async dedup: skip %s %s %s", source_type, source_id, event_type)
                    return
            except Exception:
                pass

            try:
                if isinstance(notifier, EmailNotifier):
                    ok, response = notifier.send(subject, body, html_body=html_body)
                elif isinstance(notifier, FeishuNotifier):
                    ok, response = notifier.send(subject, body, card=feishu_card)
                else:
                    ok, response = False, "unknown notifier"
            except Exception as e:
                ok, response = False, str(e)
            db = None
            try:
                from server.database import SessionLocal
                db = SessionLocal()
                db.add(Notification(
                    source_type=source_type,
                    source_id=source_id,
                    event_type=event_type,
                    channel=channel,
                    subject=subject,
                    payload_json=json.dumps(payload or {"body": body}, ensure_ascii=False),
                    success=1 if ok else 0,
                    response_text=response[:500] if response else None,
                ))
                db.commit()
            except Exception as e:
                logger.error("failed to record notification: %s", e)
            finally:
                if db:
                    db.close()

        self._executor.submit(_do)
