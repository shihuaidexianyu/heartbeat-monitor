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

# Interactive defaults
DEFAULT_LISTEN_HOST="0.0.0.0"
DEFAULT_LISTEN_PORT="8000"
DEFAULT_SMTP_HOST="smtp.example.com"
DEFAULT_SMTP_PORT="587"
DEFAULT_SMTP_USER="alert@example.com"
DEFAULT_SMTP_FROM="alert@example.com"
DEFAULT_SMTP_TO="user1@example.com"
DEFAULT_DB_PATH="./monitor.db"
DEFAULT_LOG_FILE="./logs/server.log"

echo ""
echo "==> Please configure the server (press Enter to accept defaults):"
read -rp "Listen host [$DEFAULT_LISTEN_HOST]: " LISTEN_HOST
read -rp "Listen port [$DEFAULT_LISTEN_PORT]: " LISTEN_PORT
read -rp "SMTP host [$DEFAULT_SMTP_HOST]: " SMTP_HOST
read -rp "SMTP port [$DEFAULT_SMTP_PORT]: " SMTP_PORT
read -rp "SMTP username [$DEFAULT_SMTP_USER]: " SMTP_USER
read -rsp "SMTP password (default: smtp-password): " SMTP_PASS
echo ""
read -rp "SMTP from address [$DEFAULT_SMTP_FROM]: " SMTP_FROM
read -rp "SMTP to address [$DEFAULT_SMTP_TO]: " SMTP_TO
read -rp "Database path [$DEFAULT_DB_PATH]: " DB_PATH
read -rp "Log file [$DEFAULT_LOG_FILE]: " LOG_FILE

# Apply defaults
LISTEN_HOST="${LISTEN_HOST:-$DEFAULT_LISTEN_HOST}"
LISTEN_PORT="${LISTEN_PORT:-$DEFAULT_LISTEN_PORT}"
SMTP_HOST="${SMTP_HOST:-$DEFAULT_SMTP_HOST}"
SMTP_PORT="${SMTP_PORT:-$DEFAULT_SMTP_PORT}"
SMTP_USER="${SMTP_USER:-$DEFAULT_SMTP_USER}"
SMTP_PASS="${SMTP_PASS:-smtp-password}"
SMTP_FROM="${SMTP_FROM:-$DEFAULT_SMTP_FROM}"
SMTP_TO="${SMTP_TO:-$DEFAULT_SMTP_TO}"
DB_PATH="${DB_PATH:-$DEFAULT_DB_PATH}"
LOG_FILE="${LOG_FILE:-$DEFAULT_LOG_FILE}"

SERVER_CONFIG="$CONFIG_DIR/server.yaml"

echo "==> Generating server config at $SERVER_CONFIG..."
cat > "$SERVER_CONFIG" <<EOF
listen_host: "$LISTEN_HOST"
listen_port: $LISTEN_PORT

smtp:
  host: "$SMTP_HOST"
  port: $SMTP_PORT
  username: "$SMTP_USER"
  password: "$SMTP_PASS"
  from_addr: "$SMTP_FROM"
  to_addrs:
    - "$SMTP_TO"
  use_tls: true

monitor:
  probe_interval_sec: 30
  evaluation_interval_sec: 30
  default_tcp_timeout_sec: 3

database:
  path: "$DB_PATH"

logging:
  level: "INFO"
  file: "$LOG_FILE"
EOF

mkdir -p "$(dirname "$LOG_FILE")"

echo "==> Server config created at $SERVER_CONFIG"
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
    SERVICE_FILE="systemd/hb-server.service"
    SYSTEMD_DIR="/etc/systemd/system"

    if [[ ! -f "$SERVICE_FILE" ]]; then
        echo "Warning: $SERVICE_FILE not found, skipping systemd installation."
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
            echo "  cp $TMP_SERVICE $SYSTEMD_DIR/hb-server.service"
            echo "  systemctl daemon-reload"
            echo "  systemctl enable --now hb-server.service"
        fi
        rm -f "$TMP_SERVICE"
    fi
else
    echo "==> Skipping systemd installation."
fi

echo ""
echo "To start the server manually, run:"
echo "  export SERVER_CONFIG=$SERVER_CONFIG"
echo "  export MONITOR_NODES_SEED='[{\"server_id\":\"lab-server-1\",\"token_hash\":\"secret-token-1\",\"probe_host\":\"127.0.0.1\",\"probe_port\":22}]'"
echo "  uv run python -m server.main"
