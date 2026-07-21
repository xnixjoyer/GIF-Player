#!/usr/bin/env python3
"""Load the GTK implementation and inject package-safe paths and commands."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

from gif_player_paths import AppPaths
from gif_player_runtime_guard import install_transition_guards
from gif_player_runtime_patch import install_runtime_patches

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


def packaged_executable(name: str) -> Path | None:
    """Return a package sibling executable before falling back to PATH.

    Nix installs this module below ``libexec/gif-player``. Starting another
    component with the bare Python interpreter would bypass the generated Nix
    wrapper and can lose GTK/GI environment variables. Prefer ``$out/bin``.
    """

    package_candidate = LIBEXEC_DIR.parent.parent / "bin" / name
    if package_candidate.is_file() and os.access(package_candidate, os.X_OK):
        return package_candidate
    path_candidate = shutil.which(name)
    return Path(path_candidate) if path_candidate else None


def daemon_command() -> list[str]:
    executable = packaged_executable("gif-player")
    if executable is not None:
        return [str(executable), "daemon"]
    return [sys.executable, str(LIBEXEC_DIR / "gif_player_cli.py"), "daemon"]


def picker_command() -> list[str]:
    executable = packaged_executable("gif-picker")
    if executable is not None:
        return [str(executable)]
    return [sys.executable, str(LIBEXEC_DIR / "gif_picker_entry.py")]


def configure_main(module: ModuleType, paths: AppPaths) -> None:
    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.DAEMON_LOCK = paths.daemon_lock
    module.CONFIG_DIR = paths.config_dir
    module.STATE_FILE = paths.state_file
    module.LOG_FILE = paths.daemon_log
    module.STATE = module.StateStore(paths.state_file)

    # Keep the established GTK3 implementation and install only the tested
    # decode, pacing, geometry and transition corrections around it.
    install_runtime_patches(module)
    install_transition_guards(module)

    def ensure_dirs() -> None:
        paths.ensure_runtime_dir()
        paths.ensure_config_dir()

    module.ensure_dirs = ensure_dirs


def configure_picker(module: ModuleType, paths: AppPaths) -> None:
    from gif_player_ipc import daemon_send as shared_daemon_send
    from gif_player_ipc import ensure_daemon as shared_ensure_daemon

    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.GIF_DIR = paths.gif_dir
    module.CACHE_DIR = paths.thumbnail_cache
    module.PROFILE_FILE = paths.profile_file
    module.DAEMON_SCRIPT = LIBEXEC_DIR / "gif_player_cli.py"

    # Replace the legacy launch helpers so packaged runs always use the wrapped
    # executable and the exact same XDG socket paths as the CLI.
    module.daemon_send = lambda command, timeout=2.0: shared_daemon_send(
        paths, command, timeout
    )
    module.ensure_daemon = lambda timeout=6.0: shared_ensure_daemon(
        paths, daemon_command(), timeout
    )


def configure_control(module: ModuleType, paths: AppPaths) -> None:
    from gif_player_ipc import daemon_send as shared_daemon_send

    module.RUNTIME_DIR = paths.runtime_dir
    module.DAEMON_SOCK = paths.socket_path
    module.PICKER_SCRIPT = LIBEXEC_DIR / "gif_picker_entry.py"
    module.daemon_send = lambda command, timeout=2.0: shared_daemon_send(
        paths, command, timeout
    )
