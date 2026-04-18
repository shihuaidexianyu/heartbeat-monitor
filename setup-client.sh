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

USER_BIN_DIR="${HOME}/.local/bin"
LAUNCHER_PATH="${USER_BIN_DIR}/hb"
OLD_LAUNCHER_PATH="${USER_BIN_DIR}/hb-agent"
VENV_AGENT="$PROJECT_ROOT/.venv/bin/hb"

mkdir -p "$USER_BIN_DIR"
rm -f "$OLD_LAUNCHER_PATH"
rm -f "$LAUNCHER_PATH"
cat > "$LAUNCHER_PATH" <<EOF
#!/bin/sh
export CLIENT_CONFIG="$PROJECT_ROOT/config/client.yaml"
cd "$PROJECT_ROOT" || exit 1
exec "$VENV_AGENT" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"

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
echo "The client will auto-register on its first heartbeat when the enrollment token matches."
echo ""
echo "To start the heartbeat daemon manually:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  uv run hb-daemon"
echo ""
echo "To run a monitored task manually:"
echo "  export CLIENT_CONFIG=$CLIENT_CONFIG"
echo "  hb --name backup --timeout 1800 -- bash backup.sh"
echo ""
echo "If hb is still not found in a new shell, use one of these:"
echo "  $LAUNCHER_PATH --name backup --timeout 1800 -- bash backup.sh"
echo "  uv run hb --name backup --timeout 1800 -- bash backup.sh"
echo ""

case ":$PATH:" in
    *":$USER_BIN_DIR:"*) ;;
    *)
        echo "Note: $USER_BIN_DIR is not in your PATH yet."
        echo "Add this line to your shell profile (~/.bashrc or ~/.zshrc):"
        echo "  export PATH=\"$USER_BIN_DIR:\$PATH\""
        echo ""
        ;;
esac

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
