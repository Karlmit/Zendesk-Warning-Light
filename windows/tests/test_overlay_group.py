"""OverlayGroup: mirroring onto every monitor, and one click clearing them all.

Needs a real QApplication because the group counts actual QScreens. Runs
offscreen, so it works headless and in CI.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QGuiApplication                        # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

from zwl import overlay                                          # noqa: E402
from zwl.config import Config                                    # noqa: E402
from zwl.monitor import Alert                                    # noqa: E402

CHECKS = []


def check(label: str, got, want) -> None:
    CHECKS.append((label, got == want, got, want))


def an_alert(ticket_id: int = 4242) -> Alert:
    return Alert(
        ticket_id=ticket_id,
        reason="new_unassigned",
        subject="Printer on fire",
        group_id=7,
        group_name="Support",
        raised_at=0.0,
    )


app = QApplication.instance() or QApplication(sys.argv)
SCREEN_COUNT = len(QGuiApplication.screens())


# --- one window when a single screen is configured ------------------------

cfg = Config()
cfg.screen_name = ""
group = overlay.OverlayGroup(cfg)
check("default: one window", len(group.windows), 1)
check("default: not pinned", group.windows[0]._pinned_screen, None)

# --- one window per monitor when mirroring --------------------------------

cfg_all = Config()
cfg_all.screen_name = overlay.ALL_SCREENS
mirrored = overlay.OverlayGroup(cfg_all)
check("all screens: one window per monitor", len(mirrored.windows), SCREEN_COUNT)
check(
    "all screens: every window pinned",
    all(w._pinned_screen is not None for w in mirrored.windows),
    True,
)
check(
    "all screens: no two windows share a monitor",
    len({w._pinned_screen.name() for w in mirrored.windows}),
    SCREEN_COUNT,
)

# --- an alert reaches every copy ------------------------------------------

mirrored.set_alerts([an_alert()])
check(
    "alert shown on every monitor",
    all(w.isVisible() for w in mirrored.windows),
    True,
)
check(
    "every copy names the same ticket",
    {w._alerts[0].ticket_id for w in mirrored.windows},
    {4242},
)

# --- dismissing one clears the rest ---------------------------------------

seen = []
mirrored.dismissed.connect(lambda: seen.append(1))
mirrored.windows[0].dismissed.emit()          # as a click on one copy would

check("dismiss: group reported it once", len(seen), 1)
check(
    "dismiss: every copy hidden",
    any(w.isVisible() for w in mirrored.windows),
    False,
)
check("dismiss: group forgot the alerts", mirrored._alerts, [])

# --- opening a ticket from any copy is relayed once -----------------------

opened = []
mirrored.set_alerts([an_alert(99)])
mirrored.open_ticket_requested.connect(opened.append)
last = mirrored.windows[-1]
last.open_ticket_requested.emit(99)
check("open ticket relayed once", opened, [99])

# --- switching the setting rebuilds, and keeps a live warning -------------

single = overlay.OverlayGroup(Config())
single.set_alerts([an_alert(7)])
check("before switch: one window, visible", len(single.windows), 1)

switched = Config()
switched.screen_name = overlay.ALL_SCREENS
single.reload_appearance(switched)
check("after switch: one window per monitor", len(single.windows), SCREEN_COUNT)
check(
    "after switch: the warning is still up",
    all(w.isVisible() for w in single.windows),
    True,
)
check(
    "after switch: still the same ticket",
    {w._alerts[0].ticket_id for w in single.windows},
    {7},
)

# and back again
single.reload_appearance(Config())
check("switched back: one window", len(single.windows), 1)
check("switched back: warning still up", single.windows[0].isVisible(), True)

# --- a rebuild while nothing is showing must not show anything -----------

quiet = overlay.OverlayGroup(Config())
quiet.reload_appearance(switched)
check(
    "rebuild while idle stays hidden",
    any(w.isVisible() for w in quiet.windows),
    False,
)

# --- hide_warning clears every copy and the remembered alerts -------------

mirrored.set_alerts([an_alert(11)])
mirrored.hide_warning()
check("hide_warning: all hidden", any(w.isVisible() for w in mirrored.windows), False)
check("hide_warning: alerts forgotten", mirrored._alerts, [])

# --- the sentinel cannot collide with a real monitor name ----------------

check(
    "sentinel is not a real screen name",
    overlay.ALL_SCREENS in {s.name() for s in QGuiApplication.screens()},
    False,
)

# --- a pinned window ignores the configured screen -----------------------

if SCREEN_COUNT:
    only = QGuiApplication.screens()[0]
    elsewhere = Config()
    elsewhere.screen_name = "a monitor that does not exist"
    pinned = overlay.OverlayWindow(elsewhere, only)
    check("pinned window ignores config", pinned._target_screen().name(), only.name())

    unpinned = overlay.OverlayWindow(elsewhere, None)
    check(
        "unpinned window falls back to primary",
        unpinned._target_screen().name(),
        QGuiApplication.primaryScreen().name(),
    )


# --- each copy must actually sit on its own monitor -----------------------
#
# The substance of the feature: two monitors at different DPI scaling is where
# geometry maths goes wrong, and a window placed off its own screen is invisible
# rather than obviously broken.

placed = overlay.OverlayGroup(cfg_all)
placed.set_alerts([an_alert(1)])
for window in placed.windows:
    screen = window._pinned_screen
    area = screen.availableGeometry()
    geo = window.geometry()
    check(
        "window on {} is inside that screen".format(screen.name()),
        area.contains(geo.center()),
        True,
    )
    check(
        "window on {} sits in the bottom-right corner".format(screen.name()),
        (abs(geo.right() - (area.right() - cfg_all.margin_x)) <= 2,
         abs(geo.bottom() - (area.bottom() - cfg_all.margin_y)) <= 2),
        (True, True),
    )
if len(placed.windows) > 1:
    centres = {(w.geometry().center().x(), w.geometry().center().y()) for w in placed.windows}
    check("copies do not stack on one spot", len(centres), len(placed.windows))
placed.hide_warning()


# --- per-monitor corners -------------------------------------------------

from zwl.config import DEFAULT_CORNER, VALID_CORNERS   # noqa: E402

per = Config()
check("no overrides: falls back to the default", per.corner_for("XV322U"), DEFAULT_CORNER)
check("no overrides: unknown screen too", per.corner_for("nothing"), DEFAULT_CORNER)

per.set_corner_for("XV322U", "top-left")
check("override applies to that screen", per.corner_for("XV322U"), "top-left")
check("other screens unaffected", per.corner_for("DELL"), DEFAULT_CORNER)

per.set_corner_for("XV322U", "")          # back to following the default
check("cleared override follows default", per.corner_for("XV322U"), DEFAULT_CORNER)
check("cleared override leaves no entry", per.corner_by_screen, {})

per.set_corner_for("XV322U", "nonsense")
check("rubbish corner is not stored", per.corner_by_screen, {})
per.set_corner_for("", "top-left")
check("nameless screen is not stored", per.corner_by_screen, {})

per.corner = "top-right"
check("default applies where there is no override", per.corner_for("anything"), "top-right")
per.corner = "sideways"
check("rubbish default falls back", per.corner_for("anything"), DEFAULT_CORNER)

# survives a save/load round trip, and keeps screens that are not plugged in
saved = Config()
saved.set_corner_for("XV322U", "top-left")
saved.set_corner_for("A MONITOR AT HOME", "bottom-left")
saved.corner = "top-right"
loaded = Config.from_dict(saved.to_dict())
check("round trip: override kept", loaded.corner_for("XV322U"), "top-left")
check("round trip: absent monitor kept", loaded.corner_for("A MONITOR AT HOME"), "bottom-left")
check("round trip: default kept", loaded.corner_for("elsewhere"), "top-right")

# a corrupt config must not crash the app
dirty = Config.from_dict({
    "corner": "diagonal",
    "corner_by_screen": {"good": "top-left", "bad": "sideways", "": "top-right", 7: "top-left"},
})
check("bad default sanitised", dirty.corner, DEFAULT_CORNER)
# A non-string key is coerced rather than dropped. JSON keys are always strings,
# so this can only come from a hand-built dict, and a bogus name simply never
# matches a monitor - whereas crashing on load would cost someone their settings.
check("bad entries dropped, odd keys coerced", dirty.corner_by_screen,
      {"good": "top-left", "7": "top-left"})

# --- the overlay honours a per-monitor corner ----------------------------

if SCREEN_COUNT > 1:
    names = [s.name() for s in QGuiApplication.screens()]
    mixed = Config()
    mixed.screen_name = overlay.ALL_SCREENS
    mixed.corner = "bottom-right"
    mixed.set_corner_for(names[0], "top-left")

    group_mixed = overlay.OverlayGroup(mixed)
    group_mixed.set_alerts([an_alert(3)])
    for window in group_mixed.windows:
        name = window._pinned_screen.name()
        area = window._pinned_screen.availableGeometry()
        geo = window.geometry()
        if name == names[0]:
            check("{}: pinned to the top-left".format(name),
                  (abs(geo.left() - (area.left() + mixed.margin_x)) <= 2,
                   abs(geo.top() - (area.top() + mixed.margin_y)) <= 2),
                  (True, True))
        else:
            check("{}: still bottom-right".format(name),
                  (abs(geo.right() - (area.right() - mixed.margin_x)) <= 2,
                   abs(geo.bottom() - (area.bottom() - mixed.margin_y)) <= 2),
                  (True, True))
    group_mixed.hide_warning()

check("every corner is reachable", len(VALID_CORNERS), 4)
for corner in VALID_CORNERS:
    one = Config()
    one.corner = corner
    win = overlay.OverlayWindow(one, QGuiApplication.screens()[0])
    win.set_alerts([an_alert(5)])
    area = QGuiApplication.screens()[0].availableGeometry()
    geo = win.geometry()
    want_left = "left" in corner
    want_top = "top" in corner
    got_left = abs(geo.left() - (area.left() + one.margin_x)) <= 2
    got_top = abs(geo.top() - (area.top() + one.margin_y)) <= 2
    check("corner {} places correctly".format(corner),
          (got_left, got_top), (want_left, want_top))
    win.hide_warning()


# --- report ---------------------------------------------------------------

failed = [c for c in CHECKS if not c[1]]
print("screens detected:", SCREEN_COUNT)
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
