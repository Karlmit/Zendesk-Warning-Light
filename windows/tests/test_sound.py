"""The alert sound is opt-in and plays once per appearance."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication   # noqa: E402

from zwl import overlay, sound                # noqa: E402
from zwl.config import Config                 # noqa: E402
from zwl.monitor import Alert                 # noqa: E402

app = QApplication.instance() or QApplication([])
CHECKS = []


def check(label, got, want):
    CHECKS.append((label, got == want, got, want))


calls = []
sound.play_alert = lambda name="system": calls.append(name)

alert = Alert(ticket_id=1, reason="new_unassigned", subject="x", group_id=None,
              group_name="g", raised_at=0.0, requester_id=0, requester_name="n")

check("off by default", Config().play_sound, False)
check("round-trips", Config.from_dict(Config(play_sound=True).to_dict()).play_sound, True)
check("old config without the key loads off", Config.from_dict({}).play_sound, False)

group = overlay.OverlayGroup(Config())
group.set_alerts([alert])
check("silent when disabled", len(calls), 0)
group.hide_warning()

group = overlay.OverlayGroup(Config(play_sound=True))
group.set_alerts([alert])
check("plays when the warning appears", len(calls), 1)
group.set_alerts([alert, alert])
check("does not repeat while already showing", len(calls), 1)
group.hide_warning()
group.set_alerts([alert])
check("plays again after being dismissed", len(calls), 2)

check("unknown sound falls back", Config.from_dict({"sound_name": "x.wav"}).sound_name, "system")
check("bundled files exist", all((Path(__file__).resolve().parent.parent / "assets" / "sounds" / v).is_file()
      for v in sound.VALID if v != sound.SYSTEM), True)
check("chosen sound is passed", Config.from_dict({"sound_name": "church-bell.wav"}).sound_name, "church-bell.wav")

from zwl import modes   # noqa: E402

cfg = Config(play_sound=True)
check("a new mode is audible", cfg.active_mode().play_sound, True)
check("sound on when master and mode agree", cfg.sound_enabled(), True)
cfg.active_mode().play_sound = False
check("a silent mode mutes the sound", cfg.sound_enabled(), False)
cfg.find_mode(modes.BUILTIN_FOCUS).play_sound = True
cfg.mode = modes.BUILTIN_FOCUS
check("another mode can still make a sound", cfg.sound_enabled(), True)
check("master switch overrides the mode", Config(play_sound=False).sound_enabled(), False)
check("mode choice survives a save", Config.from_dict(cfg.to_dict()).find_mode(
    modes.BUILTIN_HELPDESK).play_sound, False)
check("old modes without the key stay audible", modes.DayMode.from_dict(
    {"id": "x", "name": "x"}).play_sound, True)
silent_group = overlay.OverlayGroup(Config(play_sound=True, day_modes=[
    modes.DayMode(id="quiet", name="Quiet", play_sound=False)], mode="quiet"))
before = len(calls)
silent_group.set_alerts([alert])
check("overlay stays silent in a silent mode", len(calls), before)

failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
