"""The optional sound that accompanies a warning appearing.

Plays through ``afplay``, which ships with macOS, so there is nothing to bundle and
it follows the system output device. "System default" is the Glass alert sound.
Never raises: a missing sound must not cost anyone the visual warning.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .paths import assets_dir

log = logging.getLogger(__name__)

SYSTEM = "system"
SYSTEM_SOUND = Path("/System/Library/Sounds/Glass.aiff")
AFPLAY = "/usr/bin/afplay"

# Config value -> label. The bundled sounds come from the Take-A-Moment app.
CHOICES: tuple[tuple[str, str], ...] = (
    (SYSTEM, "macOS default"),
    ("church-bell.wav", "Church bell"),
    ("pan-flute.wav", "Pan flute"),
    ("singing-bowl.wav", "Singing bowl"),
)
VALID = {value for value, _ in CHOICES}
DEFAULT = SYSTEM


def _resolve(name: str) -> Path | None:
    if name != SYSTEM:
        path = assets_dir() / "sounds" / name
        if path.is_file():
            return path
    return SYSTEM_SOUND if SYSTEM_SOUND.is_file() else None


def play_alert(name: str = DEFAULT) -> None:
    """Play the alert sound without blocking the UI."""
    try:
        path = _resolve(name)
        if path is not None and Path(AFPLAY).is_file():
            subprocess.Popen([AFPLAY, str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
    except Exception:
        log.exception("could not play the alert sound")
