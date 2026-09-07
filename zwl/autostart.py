"""Register the app in the per-user Windows Run key."""

from __future__ import annotations

import logging

from .paths import APP_NAME, launch_target

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _winreg():
    try:
        import winreg
        return winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None


def is_enabled() -> bool:
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.exception("could not read the Run key")
        return False


def set_enabled(enabled: bool) -> bool:
    """Returns True when the registry now matches the requested state."""
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_target())
                log.info("autostart enabled: %s", launch_target())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    log.info("autostart disabled")
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("could not write the Run key")
        return False
