import json
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Use in-memory DB for tests
os.environ["SERVER_CONFIG"] = ""

from server.database import SessionLocal, engine, Base
from server.main import app
from server.models import Node, TaskRun

client = TestClient(app)


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    node = Node(
        server_id="lab-server-1",
        hostname="lab-node-a",
        token_hash="secret-token-1",
        probe_host="127.0.0.1",
        probe_port=22,
    )
    db.add(node)
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["service"] == "heartbeat-monitor"


def test_heartbeat_success():
    payload = {
        "server_id": "lab-server-1",
        "token": "secret-token-1",
        "hostname": "lab-node-a",
    }
    resp = client.post("/heartbeat", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_heartbeat_wrong_token():
    payload = {
        "server_id": "lab-server-1",
        "token": "wrong-token",
    }
    resp = client.post("/heartbeat", json=payload)
    assert resp.status_code == 401


def test_heartbeat_auto_register():
    import server.api
    server.api.server_config.default_token = "test-default-token"
    payload = {
        "server_id": "lab-server-99",
        "token": "test-default-token",
        "hostname": "new-node",
        "ip": "10.0.0.99",
    }
    resp = client.post("/heartbeat", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "registered" in data["message"]

    # Verify node was created
    resp2 = client.get("/nodes/lab-server-99")
    assert resp2.status_code == 200
    node = resp2.json()
    assert node["server_id"] == "lab-server-99"
    assert node["status"] == "UP"


def test_heartbeat_unknown_server():
    import server.api
    server.api.server_config.default_token = "test-default-token"
    # Wrong token should be rejected for unknown server_id
    payload = {
        "server_id": "lab-server-999",
        "token": "wrong-token",
    }
    resp = client.post("/heartbeat", json=payload)
    assert resp.status_code == 404


def test_list_nodes():
    resp = client.get("/nodes")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(n["server_id"] == "lab-server-1" for n in data)


def test_get_node():
    resp = client.get("/nodes/lab-server-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_id"] == "lab-server-1"


def test_get_node_not_found():
    resp = client.get("/nodes/lab-server-999")
    assert resp.status_code == 404


def test_probe_function():
    from server.probe import tcp_probe
    # localhost:22 may or may not be open; just ensure no exception
    result = tcp_probe("127.0.0.1", 22, timeout=1)
    assert isinstance(result, bool)
    # A closed/high port should fail
    result2 = tcp_probe("127.0.0.1", 65432, timeout=1)
    assert result2 is False


def test_status_engine_evaluate():
    from server.status_engine import evaluate_node
    db = SessionLocal()
    try:
        node = db.query(Node).filter(Node.server_id == "lab-server-1").first()
        # Set state to DOWN artificially
        node.status = "DOWN"
        node.last_heartbeat_at = None
        node.probe_fail_count = 5
        db.commit()

        evaluate_node(db, node)
        assert node.status == "DOWN"

        # Recover via heartbeat
        import time
        from server.models import now_iso
        node.last_heartbeat_at = now_iso()
        node.probe_fail_count = 0
        db.commit()

        evaluate_node(db, node)
        assert node.status == "UP"
    finally:
        db.close()


def test_register_endpoint():
    import server.api
    server.api.server_config.registration.enrollment_token = "enroll-test"
    payload = {
        "server_id": "lab-server-new",
        "enrollment_token": "enroll-test",
        "hostname": "registered-node",
        "ip": "10.0.0.100",
    }
    resp = client.post("/register", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "node_token" in data
    assert data["server_id"] == "lab-server-new"

    # use the returned token for heartbeat
    token = data["node_token"]
    hb_resp = client.post("/heartbeat", json={
        "server_id": "lab-server-new",
        "token": token,
    })
    assert hb_resp.status_code == 200


def test_register_invalid_token():
    import server.api
    server.api.server_config.registration.enrollment_token = "enroll-test"
    payload = {
        "server_id": "lab-server-bad",
        "enrollment_token": "wrong-token",
    }
    resp = client.post("/register", json=payload)
    assert resp.status_code == 401


def test_maintenance_mode():
    resp = client.post("/nodes/lab-server-1/maintenance/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "MAINTENANCE"

    # evaluate should keep maintenance
    from server.status_engine import evaluate_node
    db = SessionLocal()
    try:
        node = db.query(Node).filter(Node.server_id == "lab-server-1").first()
        evaluate_node(db, node)
        assert node.status == "MAINTENANCE"
    finally:
        db.close()

    resp2 = client.post("/nodes/lab-server-1/maintenance/end")
    assert resp2.status_code == 200


def test_task_run_lifecycle():
    # start
    start_payload = {
        "server_id": "lab-server-1",
        "task_name": "test_task",
        "command": ["echo", "hello"],
        "cwd": "/tmp",
        "timeout_sec": 60,
        "notify_on_success": False,
    }
    resp = client.post("/task-runs/start", json=start_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    run_id = data["run_id"]

    # get
    resp2 = client.get(f"/task-runs/{run_id}")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "RUNNING"

    # finish
    finish_payload = {
        "status": "SUCCESS",
        "ended_at": "2024-01-01T00:00:00+00:00",
        "duration_sec": 1.5,
        "exit_code": 0,
        "stdout_tail": "hello",
        "stderr_tail": "",
    }
    resp3 = client.post(f"/task-runs/{run_id}/finish", json=finish_payload)
    assert resp3.status_code == 200
    assert resp3.json()["ok"] is True

    # query finished
    resp4 = client.get(f"/task-runs/{run_id}")
    assert resp4.json()["status"] == "SUCCESS"
    assert resp4.json()["exit_code"] == 0

    # list
    resp5 = client.get("/task-runs")
    assert resp5.status_code == 200
    assert any(t["run_id"] == run_id for t in resp5.json())

    # node task runs
    resp6 = client.get("/nodes/lab-server-1/task-runs")
    assert any(t["run_id"] == run_id for t in resp6.json())


def test_task_run_duplicate_run_id():
    start_payload = {
        "server_id": "lab-server-1",
        "task_name": "dup_task",
        "command": ["sleep", "1"],
        "run_id": "duplicate-id-123",
    }
    resp = client.post("/task-runs/start", json=start_payload)
    assert resp.status_code == 200

    resp2 = client.post("/task-runs/start", json=start_payload)
    assert resp2.status_code == 409


def test_task_run_finish_not_found():
    resp = client.post("/task-runs/nonexistent/finish", json={"status": "SUCCESS"})
    assert resp.status_code == 404


def test_task_cancel():
    start_payload = {
        "server_id": "lab-server-1",
        "task_name": "cancel_me",
        "command": ["sleep", "100"],
    }
    resp = client.post("/task-runs/start", json=start_payload)
    run_id = resp.json()["run_id"]

    cancel_resp = client.post(f"/task-runs/{run_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # cannot cancel again
    cancel2 = client.post(f"/task-runs/{run_id}/cancel")
    assert cancel2.status_code == 409

    # cancel nonexistent
    cancel3 = client.post("/task-runs/nonexistent/cancel")
    assert cancel3.status_code == 404


def test_status_page():
    resp = client.get("/status-page")
    assert resp.status_code == 200
    html = resp.text
    assert "Heartbeat Monitor Status" in html
    assert "Recent Tasks" in html
    assert "Failed Tasks" in html
