import logging
import sys
from client.heartbeat import send_heartbeat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


def main():
    ok = send_heartbeat()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
