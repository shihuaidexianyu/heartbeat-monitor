import argparse
import logging
import sys

from client.task_runner import run_task


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(prog="hb", description="Run a wrapped task and report it to Heartbeat Monitor")
    parser.add_argument("--name", required=True, help="Task name")
    parser.add_argument("--timeout", type=int, default=None, help="Timeout in seconds")
    parser.add_argument("--notify-success", action="store_true", help="Notify on success")
    parser.add_argument("--cwd", default=None, help="Working directory")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")

    args = parser.parse_args()

    if not args.command:
        print("Error: no command provided", file=sys.stderr)
        sys.exit(1)
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


if __name__ == "__main__":
    main()
