#!/usr/bin/env python3
"""
Stand-alone service daemon for multi-step service deployment.
Parses a configuration file on disk, validates parameters, binds to the specified port,
and responds to HEALTH_CHECK queries with JSON status.
"""

import sys
import os
import json
import socket
import argparse
import time


def main():
    parser = argparse.ArgumentParser(description="Multi-step service daemon")
    parser.add_argument("--config", required=True, help="Path to config file")
    args = parser.parse_args()

    cfg_path = os.path.abspath(args.config)
    if not os.path.exists(cfg_path):
        sys.stderr.write(f"FileNotFoundError: Config file not found: {cfg_path}\n")
        sys.exit(1)

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except PermissionError as e:
        sys.stderr.write(f"PermissionError: Permission denied reading config {cfg_path}: {e}\n")
        sys.exit(13)
    except Exception as e:
        sys.stderr.write(f"ValueError: Failed to parse JSON config {cfg_path}: {e}\n")
        sys.exit(2)

    port = cfg.get("port")
    if not isinstance(port, int) or port <= 0 or port > 65535:
        sys.stderr.write(f"ValueError: Invalid port in config: {port}\n")
        sys.exit(2)

    service_name = cfg.get("service_name", "telemetry_agent")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError as e:
        sys.stderr.write(f"OSError: [Errno {e.errno}] {e.strerror} (Port {port})\n")
        sys.exit(e.errno if e.errno else 98)

    s.listen(10)
    # Write PID or readiness indicator to stdout
    sys.stdout.write(f"DAEMON_STARTED:pid={os.getpid()}:port={port}\n")
    sys.stdout.flush()

    while True:
        try:
            conn, _ = s.accept()
            conn.settimeout(2.0)
            data = conn.recv(1024).decode("utf-8", errors="ignore")
            if "HEALTH_CHECK" in data or "GET /health" in data:
                payload = json.dumps({
                    "status": "UP",
                    "service_name": service_name,
                    "port": port,
                    "config_path": cfg_path,
                    "pid": os.getpid(),
                    "timestamp": time.time(),
                })
                conn.sendall(payload.encode("utf-8") + b"\n")
            conn.close()
        except Exception:
            time.sleep(0.1)


if __name__ == "__main__":
    main()
