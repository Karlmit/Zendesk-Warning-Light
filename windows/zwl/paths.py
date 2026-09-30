"""Filesystem locations used by the app, both frozen (PyInstaller) and from source."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ZendeskWarningLight"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (the shipped animations)."""
    if _is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return resource_dir() / "assets"


def data_dir() -> Path:
    """Per-user writable directory for config, state and logs."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "state.json"


def tokens_path() -> Path:
    """OAuth tokens live apart from config.json, which stays human-editable."""
    return data_dir() / "tokens.json"


def log_path() -> Path:
    return data_dir() / "warning-light.log"


def launch_target() -> str:
    """Command line that starts this app, for the Windows Run key."""
    if _is_frozen():
        return f'"{Path(sys.executable)}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    entry = resource_dir() / "main.py"
    return f'"{interpreter}" "{entry}"'
