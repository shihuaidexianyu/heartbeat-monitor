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
EXAMPLE_CONFIG="$CONFIG_DIR/server.yaml.example"

if [[ -f "$SERVER_CONFIG" ]]; then
    echo ""
    echo "Warning: $SERVER_CONFIG already exists. Skipping copy."
    echo "         Remove it first if you want a fresh template."
else
    echo "==> Copying $EXAMPLE_CONFIG -> $SERVER_CONFIG..."
    cp "$EXAMPLE_CONFIG" "$SERVER_CONFIG"
fi

mkdir -p "./logs"

echo ""
echo "========================================"
echo "  Server setup complete"
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
read -rp "==> Install systemd service for server? [y/N]: " INSTALL_SYSTEMD
if [[ "$INSTALL_SYSTEMD" =~ ^[Yy]$ ]]; then
    WORKDIR="$(pwd)"
    SERVICE_FILE="$PROJECT_ROOT/systemd/hb-server.service"
    SYSTEMD_DIR="/etc/systemd/system"

    if [[ ! -f "$SERVICE_FILE" ]]; then
        echo "Warning: systemd unit file not found, skipping installation."
        echo "  Checked: $SERVICE_FILE"
    elif ! command -v systemctl &> /dev/null; then
        echo "Warning: systemctl not found, skipping systemd installation."
    else
        TMP_SERVICE=$(mktemp)
        sed -e "s|/opt/heartbeat-monitor|$WORKDIR|g" \
            -e "s|^User=heartbeat|User=$(id -un)|g" \
            -e "s|^Group=heartbeat|Group=$(id -gn)|g" \
            "$SERVICE_FILE" > "$TMP_SERVICE"

        if _run_privileged cp "$TMP_SERVICE" "$SYSTEMD_DIR/hb-server.service"; then
            _run_privileged systemctl daemon-reload
            _run_privileged systemctl enable hb-server.service
            echo "==> systemd service installed and enabled."
            echo "    Start it with: systemctl start hb-server.service"
        else
            echo "Error: failed to copy service file to $SYSTEMD_DIR."
            echo "Please run with root/sudo privileges, or install manually:"
            echo "  sed -e 's|/opt/heartbeat-monitor|$WORKDIR|g' \\"
            echo "      -e 's|^User=heartbeat|User=$(id -un)|g' \\"
            echo "      -e 's|^Group=heartbeat|Group=$(id -gn)|g' \\"
            echo "      $SERVICE_FILE | sudo tee $SYSTEMD_DIR/hb-server.service"
            echo "  sudo systemctl daemon-reload"
            echo "  sudo systemctl enable --now hb-server.service"
        fi
        rm -f "$TMP_SERVICE"
    fi
else
    echo "==> Skipping systemd installation."
fi
