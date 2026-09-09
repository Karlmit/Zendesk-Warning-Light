"""Filesystem locations, for both a built .app bundle and a run from source."""

from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "ZendeskWarningLight"
DISPLAY_NAME = "Zendesk Warning Light"
BUNDLE_ID = "com.yourcompany.zendeskwarninglight"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_bundle() -> Path | None:
    """The enclosing .app directory, when we are running from one."""
    if not _is_frozen():
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def resource_dir() -> Path:
    """Directory holding bundled read-only resources."""
    if not _is_frozen():
        return Path(__file__).resolve().parent.parent
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def assets_dir() -> Path:
    """Where the animations live.

    PyInstaller has moved bundled data between Contents/Frameworks and
    Contents/Resources across versions, so check the plausible places rather than
    hard-coding one and shipping an app that cannot find its own cat.
    """
    candidates = [resource_dir() / "assets"]
    bundle = app_bundle()
    if bundle is not None:
        candidates += [
            bundle / "Contents" / "Resources" / "assets",
            bundle / "Contents" / "Frameworks" / "assets",
            bundle / "Contents" / "MacOS" / "assets",
        ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def data_dir() -> Path:
    """Per-user writable directory for config, state and logs."""
    path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "state.json"


def tokens_path() -> Path:
    """Non-secret sign-in details. The refresh token itself goes to the Keychain."""
    return data_dir() / "tokens.json"


def log_path() -> Path:
    return data_dir() / "warning-light.log"


def launch_arguments() -> list[str]:
    """Argv that starts this app, for the LaunchAgent plist.

    A list rather than a string, because launchd takes ProgramArguments and quoting
    a single command line is exactly the sort of thing that breaks on a path with
    a space in it - and this project lives under "OneDrive - KWA".
    """
    bundle = app_bundle()
    if bundle is not None:
        return [str(bundle / "Contents" / "MacOS" / APP_NAME)]
    if _is_frozen():
        return [str(Path(sys.executable).resolve())]
    return [str(Path(sys.executable).resolve()),
            str((resource_dir() / "main.py").resolve())]
