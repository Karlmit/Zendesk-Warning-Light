"""Start at login via a per-user LaunchAgent.

The Windows build writes an HKCU Run value. The macOS equivalent is a plist in
``~/Library/LaunchAgents``, which launchd reads when you log in.

We deliberately only *write* the plist and do not ``launchctl bootstrap`` it. The app
is already running when you tick the box, and loading an agent with ``RunAtLoad``
would immediately start a second copy - which the single-instance guard would then
refuse, leaving a confusing error for no benefit. The agent takes effect at the next
login, which is exactly when it is wanted.
"""

from __future__ import annotations

import logging
import plistlib
import subprocess
from pathlib import Path

from .paths import BUNDLE_ID, DISPLAY_NAME, launch_arguments

log = logging.getLogger(__name__)

LABEL = BUNDLE_ID


def agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return agents_dir() / "{}.plist".format(LABEL)


def is_enabled() -> bool:
    return plist_path().is_file()


def _build_plist() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": launch_arguments(),
        "RunAtLoad": True,
        # Never resurrect it: quitting from the menu bar must mean quit.
        "KeepAlive": False,
        "ProcessType": "Interactive",
        # Only in a real logged-in desktop session, not ssh or the login window.
        "LimitLoadToSessionType": "Aqua",
    }


def set_enabled(enabled: bool) -> bool:
    """Returns True when the LaunchAgent now matches the requested state."""
    path = plist_path()
    try:
        if enabled:
            agents_dir().mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                plistlib.dump(_build_plist(), handle)
            log.info("login item written to %s (%s)", path, launch_arguments())
        else:
            _bootout()
            if path.exists():
                path.unlink()
            log.info("login item removed")
        return is_enabled() == enabled
    except OSError:
        log.exception("could not update the LaunchAgent")
        return False


def _bootout() -> None:
    """Best-effort unload, so a currently loaded agent does not linger."""
    try:
        subprocess.run(
            ["/bin/launchctl", "bootout", "gui/{}".format(_uid()), LABEL],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        log.debug("launchctl bootout failed; the plist removal is what matters",
                  exc_info=True)


def _uid() -> int:
    import os

    return os.getuid()


def describe() -> str:
    """One line for the preflight check."""
    if not is_enabled():
        return "{} will not start at login".format(DISPLAY_NAME)
    return "starts at login via {}".format(plist_path())
