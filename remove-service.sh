#!/bin/bash
set -e

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

echo "==> Done"
