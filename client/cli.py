import argparse
import logging
import sys

from client.agent import run_daemon
from client.heartbeat import send_heartbeat
from client.task_runner import run_task


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(prog="hb-agent")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help="Run heartbeat daemon")
    sub.add_parser("register", help="Trigger manual registration")
    sub.add_parser("heartbeat-once", help="Send one heartbeat and exit")

    run_parser = sub.add_parser("run", help="Run a wrapped task")
    run_parser.add_argument("--name", required=True, help="Task name")
    run_parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    run_parser.add_argument("--notify-success", action="store_true", help="Notify on success")
    run_parser.add_argument("--cwd", default=None, help="Working directory")
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")

    args = parser.parse_args()

    if args.cmd == "daemon":
        run_daemon()
    elif args.cmd == "heartbeat-once":
        ok, _ = send_heartbeat()
        sys.exit(0 if ok else 1)
    elif args.cmd == "register":
        import requests
        from client.config import load_client_config
        cfg = load_client_config()
        payload = {
            "server_id": cfg.server.server_id,
            "enrollment_token": cfg.server.enrollment_token,
        }
        url = cfg.server.base_url.rstrip("/") + "/register"
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            print(f"Registered successfully. node_token={data.get('node_token')}")
            print(f"Please save node_token to your client config.")
            sys.exit(0)
        except Exception as e:
            print(f"Registration failed: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.cmd == "run":
        if not args.command:
            print("Error: no command provided", file=sys.stderr)
            sys.exit(1)
        # strip leading '--' if present
        command = args.command
        if command[0] == "--":
            command = command[1:]
        run_id, status, exit_code = run_task(
            task_name=args.name,
            command=command,
            timeout_sec=args.timeout,
            notify_on_success=args.notify_success,
            cwd=args.cwd,
        )
        print(f"run_id={run_id} status={status} exit_code={exit_code}")
        sys.exit(0 if status == "SUCCESS" else 1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
