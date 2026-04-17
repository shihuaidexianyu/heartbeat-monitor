#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install uv first: https://docs.astral.sh/uv/"
    exit 1
fi

echo "==> Syncing dependencies with uv..."
uv sync

CONFIG_DIR="config"
mkdir -p "$CONFIG_DIR"

DEFAULT_SERVER_URL="http://127.0.0.1:8000/heartbeat"
DEFAULT_SERVER_ID="lab-server-1"
DEFAULT_TOKEN="your-secret-token"
DEFAULT_TIMEOUT="5"

echo ""
echo "==> Please configure the client (press Enter to accept defaults):"
read -rp "Server heartbeat URL [$DEFAULT_SERVER_URL]: " SERVER_URL
read -rp "Server ID [$DEFAULT_SERVER_ID]: " SERVER_ID
read -rsp "Token (default: your-secret-token): " TOKEN
echo ""
read -rp "Request timeout in seconds [$DEFAULT_TIMEOUT]: " TIMEOUT

SERVER_URL="${SERVER_URL:-$DEFAULT_SERVER_URL}"
SERVER_ID="${SERVER_ID:-$DEFAULT_SERVER_ID}"
TOKEN="${TOKEN:-$DEFAULT_TOKEN}"
TIMEOUT="${TIMEOUT:-$DEFAULT_TIMEOUT}"

CLIENT_CONFIG="$CONFIG_DIR/client.yaml"

echo "==> Generating client config at $CLIENT_CONFIG..."
cat > "$CLIENT_CONFIG" <<EOF
server_url: "$SERVER_URL"
server_id: "$SERVER_ID"
token: "$TOKEN"
timeout_sec: $TIMEOUT
EOF

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
read -rp "==> Install systemd timer for client? [y/N]: " INSTALL_SYSTEMD
if [[ "$INSTALL_SYSTEMD" =~ ^[Yy]$ ]]; then
    WORKDIR="$(pwd)"
    SERVICE_FILE="$PROJECT_ROOT/systemd/hb-client.service"
    TIMER_FILE="$PROJECT_ROOT/systemd/hb-client.timer"
    SYSTEMD_DIR="/etc/systemd/system"

    if [[ ! -f "$SERVICE_FILE" || ! -f "$TIMER_FILE" ]]; then
        echo "Warning: systemd unit files not found, skipping installation."
    elif ! command -v systemctl &> /dev/null; then
        echo "Warning: systemctl not found, skipping systemd installation."
    else
        TMP_SERVICE=$(mktemp)
        sed -e "s|/opt/heartbeat-monitor|$WORKDIR|g" \
            -e "s|^User=root|User=$(id -un)|g" \
            "$SERVICE_FILE" > "$TMP_SERVICE"

        if _run_privileged cp "$TMP_SERVICE" "$SYSTEMD_DIR/hb-client.service" && \
           _run_privileged cp "$TIMER_FILE" "$SYSTEMD_DIR/hb-client.timer"; then
            _run_privileged systemctl daemon-reload
            _run_privileged systemctl enable hb-client.timer
            echo "==> systemd timer installed and enabled."
            echo "    Start it with: systemctl start hb-client.timer"
        else
            echo "Error: failed to copy systemd files to $SYSTEMD_DIR."
            echo "Please run with root/sudo privileges, or install manually:"
            echo "  sed -e 's|/opt/heartbeat-monitor|$WORKDIR|g' -e 's|^User=root|User=$(id -un)|g' $SERVICE_FILE | sudo tee $SYSTEMD_DIR/hb-client.service"
            echo "  sudo cp $TIMER_FILE $SYSTEMD_DIR/hb-client.timer"
            echo "  sudo systemctl daemon-reload"
            echo "  sudo systemctl enable --now hb-client.timer"
        fi
        rm -f "$TMP_SERVICE"
    fi
else
    echo "==> Skipping systemd installation."
fi

echo ""
echo "To send a heartbeat manually, run:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  uv run python -m client.main"
