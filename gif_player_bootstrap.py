#!/usr/bin/env python3
"""Load the unchanged GTK implementation and inject package-safe paths."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

from gif_player_paths import AppPaths

LIBEXEC_DIR = Path(__file__).resolve().parent


def require_wayland() -> None:
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError(
            "GIF Player benötigt eine grafische Wayland-Sitzung mit Layer-Shell-"
            "Unterstützung. WAYLAND_DISPLAY ist nicht gesetzt."
        )


def load_legacy(filename: str, module_name: str) -> ModuleType:
    source = LIBEXEC_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Kann installierte Komponente nicht laden: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_main(module: ModuleType, paths: AppPaths) -> None:
    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.DAEMON_LOCK = paths.daemon_lock
    module.CONFIG_DIR = paths.config_dir
    module.STATE_FILE = paths.state_file
    module.LOG_FILE = paths.daemon_log
    module.STATE = module.StateStore(paths.state_file)

    def ensure_dirs() -> None:
        paths.ensure_runtime_dir()
        paths.ensure_config_dir()

    module.ensure_dirs = ensure_dirs


def configure_picker(module: ModuleType, paths: AppPaths) -> None:
    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.GIF_DIR = paths.gif_dir
    module.CACHE_DIR = paths.thumbnail_cache
    module.PROFILE_FILE = paths.profile_file
    module.DAEMON_SCRIPT = LIBEXEC_DIR / "gif_player_cli.py"


def configure_control(module: ModuleType, paths: AppPaths) -> None:
    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.PICKER_SCRIPT = LIBEXEC_DIR / "gif_picker_entry.py"
