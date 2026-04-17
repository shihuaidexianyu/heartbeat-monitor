#!/bin/bash
set -e

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

# Systemd setup
read -rp "==> Install systemd timer for client? [y/N]: " INSTALL_SYSTEMD
if [[ "$INSTALL_SYSTEMD" =~ ^[Yy]$ ]]; then
    WORKDIR="$(pwd)"
    SERVICE_FILE="systemd/hb-client.service"
    TIMER_FILE="systemd/hb-client.timer"
    SYSTEMD_DIR="/etc/systemd/system"

    if [[ -f "$SERVICE_FILE" ]]; then
        sed -e "s|/opt/heartbeat-monitor|$WORKDIR|g" \
            -e "s|User=root|User=$(whoami)|g" \
            "$SERVICE_FILE" | sudo tee "$SYSTEMD_DIR/hb-client.service" > /dev/null
    else
        echo "Warning: $SERVICE_FILE not found."
    fi

    if [[ -f "$TIMER_FILE" ]]; then
        sudo cp "$TIMER_FILE" "$SYSTEMD_DIR/hb-client.timer"
        sudo systemctl daemon-reload
        sudo systemctl enable hb-client.timer
        echo "==> systemd timer installed and enabled."
        echo "    Start it with: sudo systemctl start hb-client.timer"
    else
        echo "Warning: $TIMER_FILE not found, skipping timer installation."
    fi
else
    echo "==> Skipping systemd installation."
fi

echo ""
echo "To send a heartbeat manually, run:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  uv run python -m client.main"
