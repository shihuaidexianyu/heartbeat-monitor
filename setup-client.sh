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
EXAMPLE_CONFIG="$CONFIG_DIR/example.client.yaml"

if [[ -f "$CLIENT_CONFIG" ]]; then
    echo ""
    echo "Warning: $CLIENT_CONFIG already exists. Skipping copy."
    echo "         Remove it first if you want a fresh template."
else
    echo "==> Copying $EXAMPLE_CONFIG -> $CLIENT_CONFIG..."
    cp "$EXAMPLE_CONFIG" "$CLIENT_CONFIG"
fi

mkdir -p "./logs/hb-agent" "./spool"

echo ""
echo "========================================"
echo "  Client setup complete"
echo "========================================"
echo ""
echo "Please edit $CLIENT_CONFIG before running the agent:"
echo ""
echo "  1. server.base_url                 -> Your server's URL"
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
            echo "  sed -e 's|/opt/heartbeat-monitor|$WORKDIR|g' \\"
            echo "      -e 's|^User=root|User=$(id -un)|g' \\"
            echo "      $SERVICE_FILE | sudo tee $SYSTEMD_DIR/hb-client.service"
            echo "  sudo systemctl daemon-reload"
            echo "  sudo systemctl enable --now hb-client.service"
        fi
        rm -f "$TMP_SERVICE"
    fi
else
    echo "==> Skipping systemd installation."
fi
