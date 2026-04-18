import os

os.environ["SERVER_CONFIG"] = ""

from server.config import FeishuConfig
from server.feishu_notifier import FeishuNotifier
from server.models import Node, now_iso
from server.notification_service import NotificationService
from server.models import TaskRun


def test_build_node_change_message_uses_chinese_copy():
    svc = NotificationService(db=None)
    node = Node(
        server_id="lager",
        hostname="beer-node",
        token_hash="secret",
        probe_host="10.0.0.8",
        probe_port=22,
        status="DOWN",
        last_heartbeat_at=now_iso(),
        last_probe_at=now_iso(),
        last_probe_ok=0,
        probe_fail_count=6,
        heartbeat_timeout_sec=90,
        probe_fail_threshold=3,
    )

    message = svc._build_node_change_message(
        node,
        old_status="SUSPECT",
        new_status="DOWN",
        reason="heartbeat timeout and tcp probe failed 6 times",
    )

    assert "严重告警" in message["subject"]
    assert "心跳超时，且TCP 探测连续失败 6 次" in message["text_body"]
    assert "节点 ID：lager" in message["text_body"]
    assert "Heartbeat Monitor" in message["html_body"]
    assert "探测目标" in message["html_body"]
    assert message["feishu_card"]["header"]["template"] == "red"
    assert message["payload"]["status"]["new_label"] == "离线"


def test_build_node_change_message_for_recovery():
    svc = NotificationService(db=None)
    node = Node(
        server_id="paleale",
        hostname="brewery-2",
        token_hash="secret",
        probe_host="10.0.0.9",
        probe_port=2222,
        status="UP",
        last_heartbeat_at=now_iso(),
        last_probe_at=now_iso(),
        last_probe_ok=1,
        probe_fail_count=0,
        heartbeat_timeout_sec=90,
        probe_fail_threshold=3,
    )

    message = svc._build_node_change_message(
        node,
        old_status="DOWN",
        new_status="UP",
        reason="heartbeat or probe recovered",
    )

    assert "恢复通知" in message["subject"]
    assert "已从离线状态恢复" in message["text_body"]
    assert "心跳或 TCP 探测已恢复" in message["text_body"]
    assert message["feishu_card"]["header"]["template"] == "green"


def test_build_task_finish_message_for_failure():
    svc = NotificationService(db=None)
    task = TaskRun(
        run_id="run-123456",
        server_id="lager",
        task_name="nightly_backup",
        status="FAILED",
        started_at=now_iso(),
        ended_at=now_iso(),
        duration_sec=12.5,
        exit_code=2,
        stderr_tail="Traceback: disk full",
        stdout_tail="backup started",
    )

    message = svc._build_task_finish_message(task)

    assert "任务失败" in message["subject"]
    assert "任务 nightly_backup 执行失败，请尽快排查。" in message["text_body"]
    assert "退出码：2" in message["text_body"]
    assert "标准错误摘要" in message["html_body"]
    assert "标准输出摘要" in message["html_body"]
    assert message["feishu_card"]["header"]["template"] == "red"
    assert message["payload"]["task"]["status_label"] == "失败"
    assert message["payload"]["output_sections"][0]["label"] == "标准错误摘要"
    assert message["payload"]["output_sections"][1]["label"] == "标准输出摘要"

    elements = message["feishu_card"]["elements"]
    assert any(
        element.get("tag") == "div"
        and element.get("text", {}).get("tag") == "plain_text"
        and "Traceback: disk full" in element.get("text", {}).get("content", "")
        for element in elements
    )
    assert not any(
        "```" in element.get("text", {}).get("content", "")
        for element in elements
        if element.get("tag") == "div"
    )


def test_notify_task_finish_sends_feishu_card(monkeypatch):
    class DummyQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return None

    class DummyDB:
        def query(self, *args, **kwargs):
            return DummyQuery()

    captured = {}

    def fake_send_async(self, source_type, source_id, event_type, channel, subject, body, notifier, payload=None, html_body=None, feishu_card=None):
        captured["source_type"] = source_type
        captured["source_id"] = source_id
        captured["event_type"] = event_type
        captured["channel"] = channel
        captured["subject"] = subject
        captured["body"] = body
        captured["payload"] = payload
        captured["feishu_card"] = feishu_card

    monkeypatch.setattr(NotificationService, "_send_async", fake_send_async)

    svc = NotificationService(db=DummyDB())
    svc._feishu = object()
    svc._email = None

    task = TaskRun(
        run_id="run-feishu-1",
        server_id="paleale",
        task_name="train_model",
        status="FAILED",
        started_at=now_iso(),
        ended_at=now_iso(),
        duration_sec=65.2,
        exit_code=137,
        stderr_tail="CUDA out of memory",
        stdout_tail="epoch=1",
    )

    svc.notify_task_finish(task)

    assert captured["source_type"] == "task"
    assert captured["source_id"] == "run-feishu-1"
    assert captured["event_type"] == "task_failed"
    assert captured["channel"] == "feishu"
    assert "任务失败" in captured["subject"]
    assert captured["feishu_card"]["header"]["template"] == "red"
    assert any(
        element.get("tag") == "div"
        and element.get("text", {}).get("tag") == "plain_text"
        and "CUDA out of memory" in element.get("text", {}).get("content", "")
        for element in captured["feishu_card"]["elements"]
    )
    assert captured["payload"]["task"]["task_name"] == "train_model"


def test_feishu_notifier_prefers_interactive_card(monkeypatch):
    calls = []

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "msg": "success"}

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setattr("server.feishu_notifier.requests.post", fake_post)

    notifier = FeishuNotifier(FeishuConfig(enabled=True, webhook_url="https://example.invalid/hook"))
    ok, _ = notifier.send(
        "任务失败",
        "fallback content",
        card={
            "header": {"title": {"tag": "plain_text", "content": "任务失败"}},
            "elements": [],
        },
    )

    assert ok is True
    assert calls[0]["json"]["msg_type"] == "interactive"
    assert calls[0]["json"]["card"]["header"]["title"]["content"] == "任务失败"
