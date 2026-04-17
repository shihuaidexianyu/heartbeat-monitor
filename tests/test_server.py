import json
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Use in-memory DB for tests
os.environ["SERVER_CONFIG"] = ""

from server.database import SessionLocal, engine, Base
from server.main import app
from server.models import Node

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
