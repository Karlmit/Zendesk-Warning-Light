"""The optional sound that accompanies a warning appearing.

Uses the Windows system "Exclamation" sound, so it follows whatever the person has
chosen in their Sound settings (and stays silent if they have sounds switched off
there). Never raises: a missing sound must not cost anyone the visual warning.
"""

from __future__ import annotations

import logging
from .paths import assets_dir

log = logging.getLogger(__name__)

try:                                    # Windows only; absent when testing on Linux
    import winsound
except ImportError:                     # pragma: no cover
    winsound = None


SYSTEM = "system"

# Config value -> (label, bundled file). The bundled sounds come from the
# Take-A-Moment app; SYSTEM is the Windows Exclamation sound.
CHOICES: tuple[tuple[str, str], ...] = (
    (SYSTEM, "Windows default"),
    ("church-bell.wav", "Church bell"),
    ("pan-flute.wav", "Pan flute"),
    ("singing-bowl.wav", "Singing bowl"),
)
VALID = {value for value, _ in CHOICES}
DEFAULT = SYSTEM


def play_alert(name: str = DEFAULT) -> None:
    """Play the alert sound without blocking the UI."""
    try:
        if winsound is not None:
            path = assets_dir() / "sounds" / name
            # Only the bundled files: a path from config (e.g. a UNC share) must
            # never reach PlaySound.
            if name != SYSTEM and name in VALID and path.is_file():
                winsound.PlaySound(
                    str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            winsound.PlaySound(
                "SystemExclamation",
                winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
    except Exception:
        log.exception("could not play the alert sound")
