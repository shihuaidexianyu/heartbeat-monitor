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

CONFIG_DIR="config"
mkdir -p "$CONFIG_DIR"

DEFAULT_BASE_URL="http://127.0.0.1:8000"
DEFAULT_SERVER_ID="lab-node-01"
DEFAULT_ENROLLMENT_TOKEN="your-secret-token"
DEFAULT_HEARTBEAT_INTERVAL="30"

LOG_DIR="./logs/hb-agent"
SPOOL_DIR="./spool"

echo ""
echo "==> Please configure the client (press Enter to accept defaults):"
read -rp "Server base URL [$DEFAULT_BASE_URL]: " BASE_URL
read -rp "Server ID (unique name for this machine) [$DEFAULT_SERVER_ID]: " SERVER_ID
read -rsp "Enrollment token (from server setup): " ENROLLMENT_TOKEN
echo ""
read -rp "Heartbeat interval in seconds [$DEFAULT_HEARTBEAT_INTERVAL]: " HEARTBEAT_INTERVAL

BASE_URL="${BASE_URL:-$DEFAULT_BASE_URL}"
SERVER_ID="${SERVER_ID:-$DEFAULT_SERVER_ID}"
ENROLLMENT_TOKEN="${ENROLLMENT_TOKEN:-$DEFAULT_ENROLLMENT_TOKEN}"
HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-$DEFAULT_HEARTBEAT_INTERVAL}"

CLIENT_CONFIG="$CONFIG_DIR/client.yaml"

echo "==> Generating client config at $CLIENT_CONFIG..."
cat > "$CLIENT_CONFIG" <<EOF
server:
  base_url: "$BASE_URL"
  server_id: "$SERVER_ID"
  enrollment_token: "$ENROLLMENT_TOKEN"
  node_token: null
  heartbeat_interval_sec: $HEARTBEAT_INTERVAL

agent:
  log_dir: "$LOG_DIR"
  spool_dir: "$SPOOL_DIR"
  default_timeout_sec: 7200
EOF

mkdir -p "$LOG_DIR" "$SPOOL_DIR"

echo "==> Client config created at $CLIENT_CONFIG"
echo ""

# Helper for privilege escalation
_run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
        sudo "$@"
    elif command -v sudo &> /dev/null && [[ -t 0 ]]; then
        sudo "$@"
    else
        return 1
    fi
}

# Systemd setup
read -rp "==> Install systemd service for client daemon? [y/N]: " INSTALL_SYSTEMD
if [[ "$INSTALL_SYSTEMD" =~ ^[Yy]$ ]]; then
    WORKDIR="$(pwd)"
    SERVICE_FILE="$PROJECT_ROOT/systemd/hb-client.service"
    SYSTEMD_DIR="/etc/systemd/system"

    if [[ ! -f "$SERVICE_FILE" ]]; then
        echo "Warning: systemd unit file not found, skipping installation."
        echo "  Checked: $SERVICE_FILE"
    elif ! command -v systemctl &> /dev/null; then
        echo "Warning: systemctl not found, skipping systemd installation."
    else
        TMP_SERVICE=$(mktemp)
        sed -e "s|/opt/heartbeat-monitor|$WORKDIR|g" \
            -e "s|^User=root|User=$(id -un)|g" \
            "$SERVICE_FILE" > "$TMP_SERVICE"

        if _run_privileged cp "$TMP_SERVICE" "$SYSTEMD_DIR/hb-client.service"; then
            _run_privileged systemctl daemon-reload
            _run_privileged systemctl enable hb-client.service
            echo "==> systemd service installed and enabled."
            echo "    Start it with: systemctl start hb-client.service"
        else
            echo "Error: failed to copy service file to $SYSTEMD_DIR."
            echo "Please run with root/sudo privileges, or install manually:"
            echo "  sed -e 's|/opt/heartbeat-monitor|$WORKDIR|g' -e 's|^User=root|User=$(id -un)|g' $SERVICE_FILE | sudo tee $SYSTEMD_DIR/hb-client.service"
            echo "  sudo systemctl daemon-reload"
            echo "  sudo systemctl enable --now hb-client.service"
        fi
        rm -f "$TMP_SERVICE"
    fi
else
    echo "==> Skipping systemd installation."
fi

echo ""
echo "To send a heartbeat manually, run:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  hb-agent heartbeat-once"
echo ""
echo "To register this node, run:"
echo "  hb-agent register"
echo ""
echo "To run a wrapped task, run:"
echo "  hb-agent run --name my_task -- python script.py"
