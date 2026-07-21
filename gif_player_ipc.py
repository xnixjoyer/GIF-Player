#!/usr/bin/env python3
"""Protocol-v2 client helpers shared by CLI and GUI launchers."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from gif_player_paths import AppPaths

DAEMON_BOOT_TIMEOUT = 6.0


def daemon_send(paths: AppPaths, command: dict[str, Any], timeout: float = 2.0) -> dict[str, Any]:
    if not paths.socket_path.exists():
        return {"error": "Daemon läuft nicht"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(paths.socket_path))
            client.sendall((json.dumps(command) + "\n").encode("utf-8"))
            data = bytearray()
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
                if data.endswith(b"\n"):
                    break
        return json.loads(data.decode("utf-8").strip()) if data else {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}


def daemon_alive(paths: AppPaths) -> bool:
    return bool(daemon_send(paths, {"action": "ping"}, timeout=0.6).get("ok"))


def ensure_daemon(
    paths: AppPaths,
    cli_script: Path,
    timeout: float = DAEMON_BOOT_TIMEOUT,
) -> bool:
    if daemon_alive(paths):
        return True
    paths.ensure_runtime_dir()
    try:
        subprocess.Popen(
            [sys.executable, str(cli_script), "daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        print(f"Daemon-Start fehlgeschlagen: {exc}", file=sys.stderr)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_alive(paths):
            return True
        time.sleep(0.1)
    return False


def build_widget_cmd(widget_id: str, action_args: list[str]) -> dict[str, Any]:
    if not action_args:
        return {"error": "Keine Aktion angegeben"}
    action, *args = action_args
    command: dict[str, Any] = {"action": action, "id": widget_id}
    try:
        if action == "move":
            command["x"], command["y"] = float(args[0]), float(args[1])
        elif action == "move-by":
            command["dx"], command["dy"] = float(args[0]), float(args[1])
        elif action == "scale":
            command["scale"] = float(args[0])
        elif action == "corner":
            command["position"] = args[0]
        elif action == "opacity":
            command["opacity"] = float(args[0])
        elif action == "flip":
            command["mode"] = args[0]
        elif action == "speed":
            command["speed"] = float(args[0])
        elif action == "jump-rate":
            command["seconds"] = float(args[0])
    except (IndexError, ValueError) as exc:
        return {"error": f"Ungültige Argumente für {action}: {exc}"}
    return command
