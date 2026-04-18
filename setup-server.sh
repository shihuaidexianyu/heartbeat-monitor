#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first: https://docs.astral.sh/uv/"
    exit 1
fi

echo "==> Syncing dependencies with uv..."
uv sync

echo "==> Installing package..."
uv pip install -e . > /dev/null 2>&1

CONFIG_DIR="config"
mkdir -p "$CONFIG_DIR"

SERVER_CONFIG="$CONFIG_DIR/server.yaml"

echo "==> Generating server config template at $SERVER_CONFIG..."
cat > "$SERVER_CONFIG" <<'EOF'
listen_host: "0.0.0.0"
listen_port: 9999

database:
  path: "./monitor.db"

monitor:
  probe_interval_sec: 30
  evaluation_interval_sec: 30
  default_tcp_timeout_sec: 3
  default_heartbeat_timeout_sec: 90
  default_probe_fail_threshold: 3

registration:
  enrollment_token: "CHANGE_ME_TO_A_RANDOM_STRING"
  issue_per_node_token: true

notifications:
  email:
    enabled: true
    host: "smtp.example.com"
    port: 465
    username: "your-email@example.com"
    password: "your-password"
    from_addr: "your-email@example.com"
    to_addrs:
      - "alert-to@example.com"
    use_tls: true
  feishu:
    enabled: false
    webhook_url: ""
    secret: ""

logging:
  level: "INFO"
  file: "./logs/server.log"
EOF

mkdir -p "./logs"

echo ""
echo "========================================"
echo "  Server config template generated"
echo "========================================"
echo ""
echo "Please edit $SERVER_CONFIG before starting the server:"
echo ""
echo "  1. registration.enrollment_token   -> Set a secure random string"
echo "  2. notifications.email.*           -> Fill in your SMTP credentials"
echo "  3. notifications.feishu.*          -> (Optional) Fill in Feishu webhook"
echo "  4. listen_port                     -> (Optional) Change if 9999 is taken"
echo ""
echo "After editing, start the server with:"
echo "  export SERVER_CONFIG=$SERVER_CONFIG"
echo "  uv run python -m server.main"
echo ""

# Systemd setup hint
SERVICE_FILE="$PROJECT_ROOT/systemd/hb-server.service"
if [[ -f "$SERVICE_FILE" ]] && command -v systemctl &> /dev/null; then
    echo "To install systemd service, run:"
    echo "  sed -e 's|/opt/heartbeat-monitor|$(pwd)|g' \\"
    echo "      -e 's|^User=heartbeat|User=$(id -un)|g' \\"
    echo "      -e 's|^Group=heartbeat|Group=$(id -gn)|g' \\"
    echo "      $SERVICE_FILE | sudo tee /etc/systemd/system/hb-server.service"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now hb-server.service"
    echo ""
fi
