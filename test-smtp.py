#!/usr/bin/env python3
"""
Test SMTP configuration by sending a test email.
"""
import sys
from server.config import load_server_config
from server.notifier import send_email


def main():
    config = load_server_config()
    if not config.smtp:
        print("Error: SMTP config not found in server.yaml", file=sys.stderr)
        sys.exit(1)

    print(f"SMTP Host: {config.smtp.host}:{config.smtp.port}")
    print(f"From: {config.smtp.from_addr}")
    print(f"To: {', '.join(config.smtp.to_addrs)}")
    print(f"TLS: {config.smtp.use_tls}")
    print("Sending test email...")

    ok = send_email(
        subject="[TEST] Heartbeat Monitor SMTP Test",
        body="This is a test email from heartbeat-monitor.\nIf you receive this, your SMTP config is working.",
        smtp_cfg=config.smtp,
    )

    if ok:
        print("Success: Test email sent.")
    else:
        print("Failed: Could not send test email. Check your SMTP settings and network.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
