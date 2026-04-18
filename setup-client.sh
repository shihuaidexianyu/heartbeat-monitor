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

CLIENT_CONFIG="$CONFIG_DIR/client.yaml"

echo "==> Generating client config template at $CLIENT_CONFIG..."
cat > "$CLIENT_CONFIG" <<'EOF'
server:
  base_url: "http://127.0.0.1:9999"
  server_id: "lab-node-01"
  enrollment_token: "CHANGE_ME_TO_MATCH_SERVER"
  node_token: null
  heartbeat_interval_sec: 30

agent:
  log_dir: "./logs/hb-agent"
  spool_dir: "./spool"
  default_timeout_sec: 7200
EOF

mkdir -p "./logs/hb-agent" "./spool"

echo ""
echo "========================================"
echo "  Client config template generated"
echo "========================================"
echo ""
echo "Please edit $CLIENT_CONFIG before running the agent:"
echo ""
echo "  1. server.base_url                 -> Your server's URL (e.g. http://10.0.0.1:9999)"
echo "  2. server.server_id                -> Unique name for this machine"
echo "  3. server.enrollment_token         -> Same as server's registration.enrollment_token"
echo ""
echo "After editing, register this node to get a node_token:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  hb-agent register"
echo ""
echo "Then save the returned node_token into the config file, and start the daemon:"
echo "  hb-agent daemon"
echo ""
echo "Or send a one-time heartbeat test:"
echo "  hb-agent heartbeat-once"
echo ""

# Systemd setup hint
SERVICE_FILE="$PROJECT_ROOT/systemd/hb-client.service"
if [[ -f "$SERVICE_FILE" ]] && command -v systemctl &> /dev/null; then
    echo "To install systemd service, run:"
    echo "  sed -e 's|/opt/heartbeat-monitor|$(pwd)|g' \\"
    echo "      -e 's|^User=root|User=$(id -un)|g' \\"
    echo "      $SERVICE_FILE | sudo tee /etc/systemd/system/hb-client.service"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl enable --now hb-client.service"
    echo ""
fi
