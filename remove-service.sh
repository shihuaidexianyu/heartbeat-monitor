#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
USER_BIN_DIR="${HOME}/.local/bin"
CLIENT_LAUNCHER="${USER_BIN_DIR}/hb"
OLD_CLIENT_LAUNCHER="${USER_BIN_DIR}/hb-agent"

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

_remove_path() {
    local path="$1"
    if [[ -e "$path" || -L "$path" ]]; then
        rm -rf "$path"
        echo "==> Removed $path"
    else
        echo "==> $path not found, skipping"
    fi
}

_remove_unit() {
    local unit="$1"
    local path="/etc/systemd/system/$unit"
    if [[ -f "$path" ]]; then
        if _run_privileged systemctl stop "$unit" 2>/dev/null || true; then
            _run_privileged systemctl disable "$unit" 2>/dev/null || true
            _run_privileged rm -f "$path"
            echo "==> Removed $unit"
        else
            echo "Error: failed to remove $unit. Please run with root/sudo privileges."
            return 1
        fi
    else
        echo "==> $unit not found, skipping"
    fi
}

_reload_daemon() {
    if _run_privileged systemctl daemon-reload; then
        echo "==> systemd daemon reloaded"
    else
        echo "Warning: failed to reload systemd daemon"
    fi
}

echo "==> This will remove systemd services for heartbeat-monitor"
echo "==> Project root: $PROJECT_ROOT"

read -rp "Remove server service (hb-server.service)? [y/N]: " REMOVE_SERVER
if [[ "$REMOVE_SERVER" =~ ^[Yy]$ ]]; then
    _remove_unit "hb-server.service"
fi

read -rp "Remove client timer and service (hb-client.timer / hb-client.service)? [y/N]: " REMOVE_CLIENT
if [[ "$REMOVE_CLIENT" =~ ^[Yy]$ ]]; then
    _remove_unit "hb-client.timer"
    _remove_unit "hb-client.service"
fi

_reload_daemon

read -rp "Remove client launcher (${CLIENT_LAUNCHER}) and old alias (${OLD_CLIENT_LAUNCHER})? [y/N]: " REMOVE_LAUNCHER
if [[ "$REMOVE_LAUNCHER" =~ ^[Yy]$ ]]; then
    _remove_path "$CLIENT_LAUNCHER"
    _remove_path "$OLD_CLIENT_LAUNCHER"
fi

read -rp "Uninstall editable package from project virtualenv (.venv)? [y/N]: " REMOVE_PACKAGE
if [[ "$REMOVE_PACKAGE" =~ ^[Yy]$ ]]; then
    if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]] && command -v uv &> /dev/null; then
        (
            cd "$PROJECT_ROOT"
            uv pip uninstall -y heartbeat-monitor >/dev/null 2>&1 || true
        )
        echo "==> Uninstalled heartbeat-monitor from $PROJECT_ROOT/.venv"
    else
        echo "==> .venv or uv not found, skipping package uninstall"
    fi
fi

read -rp "Remove generated runtime files (logs/, spool/, monitor.db)? [y/N]: " REMOVE_RUNTIME
if [[ "$REMOVE_RUNTIME" =~ ^[Yy]$ ]]; then
    _remove_path "$PROJECT_ROOT/logs"
    _remove_path "$PROJECT_ROOT/spool"
    _remove_path "$PROJECT_ROOT/monitor.db"
fi

echo "==> Done"
