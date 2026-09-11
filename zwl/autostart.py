"""Start-with-Windows, for both per-user and machine-wide installs.

A per-user install writes the Run value under HKCU and the app can toggle it freely.
A machine-wide install (Intune in system context, ``Setup.exe /ALLUSERS``) writes it
under **HKLM** instead, so every user who logs in gets the app started.

The app must understand both, or two things go wrong on a managed machine: the
Settings checkbox reads "off" while the app demonstrably starts at login, and ticking
it adds a *second* Run entry so Windows launches the app twice - the single-instance
guard would reject the second, but it is noise nobody should have to explain.

HKLM is treated as read-only here: removing it needs administrator rights, and on a
managed machine it is the admin's decision, not the app's.
"""

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


def _read(hive) -> str | None:
    """The Run value under ``hive``, or None when it is not there."""
    winreg = _winreg()
    if winreg is None:
        return None
    try:
        # Always the 64-bit view, which is where a 64-bit installer writes.
        with winreg.OpenKey(hive, _RUN_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return value or None
    except FileNotFoundError:
        return None
    except OSError:
        log.exception("could not read the Run key")
        return None


def machine_wide_target() -> str | None:
    """The HKLM Run value, set by a machine-wide install. None if absent."""
    winreg = _winreg()
    if winreg is None:
        return None
    return _read(winreg.HKEY_LOCAL_MACHINE)


def per_user_target() -> str | None:
    winreg = _winreg()
    if winreg is None:
        return None
    return _read(winreg.HKEY_CURRENT_USER)


def is_machine_wide() -> bool:
    """True when an administrator has set this for every user on the machine."""
    return machine_wide_target() is not None


def is_enabled() -> bool:
    """Whether the app will start at login, from either scope."""
    return is_machine_wide() or per_user_target() is not None


def set_enabled(enabled: bool) -> bool:
    """Change the per-user setting. Returns True when the result matches the request.

    A machine-wide entry is left alone: it cannot be changed without administrator
    rights, and it already satisfies "start at login", so a request to enable is
    reported as satisfied and a request to disable is refused.
    """
    winreg = _winreg()
    if winreg is None:
        return False

    if is_machine_wide():
        if enabled:
            log.info("autostart already set machine-wide; nothing to do")
            return True
        log.warning("autostart is set machine-wide and cannot be turned off here")
        return False

    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
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


def describe() -> str:
    """One line for the settings dialog and the log."""
    machine = machine_wide_target()
    if machine:
        return "set for all users by your administrator ({})".format(machine)
    user = per_user_target()
    if user:
        return "set for you only ({})".format(user)
    return "not set"
