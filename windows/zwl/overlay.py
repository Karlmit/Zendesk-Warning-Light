"""The always-on-top animated warning that appears in a corner of the screen."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QObject, QPropertyAnimation, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QGuiApplication, QImageReader, QMovie, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from . import sound
from .config import Config
from .monitor import Alert

log = logging.getLogger(__name__)

CAPTION_MAX_WIDTH = 360
RAISE_INTERVAL_MS = 4000
FADE_MS = 260

# Sentinel for Config.screen_name meaning "mirror onto every monitor". Not a legal
# QScreen name, so it can never collide with a real one.
ALL_SCREENS = "*"

CAPTION_STYLE = """
QLabel#caption {
    background-color: rgba(20, 22, 28, 235);
    color: #f5f6f8;
    border: 1px solid rgba(255, 176, 32, 170);
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 12px;
}
QLabel#caption:hover {
    background-color: rgba(34, 38, 48, 245);
    border: 1px solid rgba(255, 176, 32, 255);
}
"""


class _CaptionLabel(QLabel):
    """The information panel under the animation. Clicking it opens the ticket."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()   # do not fall through to the window's dismiss handler
            return
        # Anything else (right-click) bubbles up to the overlay's context menu.
        event.ignore()


class OverlayWindow(QWidget):
    """Frameless, click-through-to-dismiss animation pinned above everything else."""

    dismissed = Signal()
    open_ticket_requested = Signal(int)
    pause_requested = Signal(int)      # minutes
    settings_requested = Signal()

    def __init__(self, config: Config, screen: QScreen | None = None):
        super().__init__(None)
        self._config = config
        self._alerts: list[Alert] = []
        self._movie: QMovie | None = None
        self._source_size = QSize(480, 480)
        # When set, this window belongs to one specific monitor and ignores the
        # configured screen. OverlayGroup uses this to mirror onto every screen.
        self._pinned_screen = screen

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_AlwaysShowToolTips, True)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)
        self.setStyleSheet(CAPTION_STYLE)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._animation_label = QLabel(self)
        self._animation_label.setAlignment(Qt.AlignCenter)
        self._animation_label.setAttribute(Qt.WA_TranslucentBackground, True)
        self._animation_label.setToolTip("Click to dismiss")
        layout.addWidget(self._animation_label, 0, Qt.AlignRight | Qt.AlignBottom)

        self._caption = _CaptionLabel(self)
        self._caption.setObjectName("caption")
        self._caption.setWordWrap(True)
        self._caption.setMaximumWidth(CAPTION_MAX_WIDTH)
        self._caption.setTextFormat(Qt.RichText)
        self._caption.setAttribute(Qt.WA_Hover, True)
        self._caption.clicked.connect(self._on_caption_clicked)
        layout.addWidget(self._caption, 0, Qt.AlignRight)

        # Some full-screen apps grab the top of the z-order; nudge ourselves back up.
        self._raise_timer = QTimer(self)
        self._raise_timer.setInterval(RAISE_INTERVAL_MS)
        self._raise_timer.timeout.connect(self._keep_on_top)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self.reload_appearance(config)

    # ------------------------------------------------------------------ #
    # appearance
    # ------------------------------------------------------------------ #

    def reload_appearance(self, config: Config) -> None:
        self._config = config
        self._load_movie(config.animation_path())
        self._caption.setVisible(config.show_caption and bool(self._alerts))
        self._render_caption()
        self.adjustSize()
        self._reposition()

    def _load_movie(self, path: str) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

        source = Path(path)
        if not source.exists():
            log.error("animation not found: %s", source)
            self._animation_label.setText(
                "<span style='color:#ffb020'>Animation missing:<br>{}</span>".format(source.name)
            )
            self._animation_label.setFixedSize(240, 80)
            return

        reader = QImageReader(str(source))
        if reader.size().isValid() and reader.size().height() > 0:
            self._source_size = reader.size()

        movie = QMovie(str(source))
        if not movie.isValid():
            log.error("Qt cannot decode %s", source)
            self._animation_label.setText(
                "<span style='color:#ffb020'>Cannot decode {}</span>".format(source.name)
            )
            self._animation_label.setFixedSize(240, 80)
            return

        movie.setCacheMode(QMovie.CacheAll)
        height = max(80, int(self._config.animation_height))
        aspect = self._source_size.width() / max(1, self._source_size.height())
        movie.setScaledSize(QSize(int(height * aspect), height))

        self._movie = movie
        self._animation_label.setMovie(movie)
        self._animation_label.setFixedSize(int(height * aspect), height)
        if self.isVisible():
            movie.start()

    def _target_screen(self) -> QScreen:
        if self._pinned_screen is not None:
            return self._pinned_screen
        wanted = (self._config.screen_name or "").strip()
        if wanted and wanted != ALL_SCREENS:
            for screen in QGuiApplication.screens():
                if screen.name() == wanted:
                    return screen
        return QGuiApplication.primaryScreen()

    def _reposition(self) -> None:
        screen = self._target_screen()
        if screen is None:
            return
        # Tell Qt which monitor this is on before moving it. Geometry alone would
        # land in the right place, but a window whose handle still thinks it is on
        # the old screen scales its contents by that screen's DPI.
        handle = self.windowHandle()
        if handle is not None and handle.screen() is not screen:
            handle.setScreen(screen)

        area = screen.availableGeometry()   # excludes the taskbar
        size = self.sizeHint().expandedTo(self.size())
        mx, my = self._config.margin_x, self._config.margin_y
        # Each monitor can be placed on its own: a game on one screen and a corner
        # you actually look at on another are rarely the same corner.
        corner = self._config.corner_for(screen.name())

        x = area.right() - size.width() - mx if "right" in corner else area.left() + mx
        y = area.bottom() - size.height() - my if "bottom" in corner else area.top() + my
        self.setGeometry(x, y, size.width(), size.height())

    # ------------------------------------------------------------------ #
    # content
    # ------------------------------------------------------------------ #

    def set_alerts(self, alerts: list[Alert]) -> None:
        self._alerts = list(alerts)
        if not self._alerts:
            self.hide_warning()
            return
        self._render_caption()
        self._caption.setVisible(self._config.show_caption)
        self.adjustSize()
        self._reposition()
        self.show_warning()

    def _render_caption(self) -> None:
        if not self._alerts:
            self._caption.clear()
            return
        newest = self._alerts[-1]
        if len(self._alerts) == 1:
            title = newest.headline
        else:
            title = "{} tickets need attention".format(len(self._alerts))

        subject = _clip(newest.subject or "(no subject)", 68)
        detail = "#{} &middot; {}".format(newest.ticket_id, _escape(subject))

        # Who asked, and which queue it landed in, share the grey line. Either can
        # be missing - a name that could not be looked up must not leave a stray
        # separator behind, and the group is blank for a ticket with no group.
        meta = []
        if newest.requester_name:
            meta.append("From {}".format(_escape(_clip(newest.requester_name, 38))))
        if newest.group_name:
            meta.append(_escape(newest.group_name))
        if meta:
            detail += "<br><span style='color:#9aa0aa'>{}</span>".format(
                " &middot; ".join(meta))

        self._caption.setText(
            "<b style='color:#ffb020'>{}</b><br>{}"
            "<br><span style='color:#6fb2ff;font-size:11px'>Open ticket #{} &rarr;</span>".format(
                _escape(title), detail, newest.ticket_id
            )
        )
        self._caption.setToolTip(
            "Open ticket #{} in Zendesk (and dismiss)".format(newest.ticket_id)
        )

    # ------------------------------------------------------------------ #
    # show / hide
    # ------------------------------------------------------------------ #

    def show_warning(self) -> None:
        already_visible = self.isVisible()
        if self._movie is not None:
            self._movie.start()
        if not already_visible:
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(self._config.opacity)
            self._fade.start()
            self._raise_timer.start()
        else:
            self.setWindowOpacity(self._config.opacity)

    def hide_warning(self) -> None:
        self._raise_timer.stop()
        if self._movie is not None:
            self._movie.stop()
        self.hide()

    def _keep_on_top(self) -> None:
        if self.isVisible():
            self.raise_()

    # ------------------------------------------------------------------ #
    # interaction
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event) -> None:
        # Clicks on the caption are handled by _CaptionLabel and never reach here.
        if event.button() == Qt.LeftButton:
            self.dismissed.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_caption_clicked(self) -> None:
        """The caption doubles as a link to the ticket it describes."""
        if self._alerts:
            self.open_ticket_requested.emit(self._alerts[-1].ticket_id)
        self.dismissed.emit()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        for alert in self._alerts[:10]:
            label = "Open #{} – {}".format(alert.ticket_id, alert.subject[:48] or "ticket")
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, tid=alert.ticket_id: self.open_ticket_requested.emit(tid)
            )
        if self._alerts:
            menu.addSeparator()
        menu.addAction("Dismiss", self.dismissed.emit)
        menu.addAction("Pause for 1 hour", lambda: self.pause_requested.emit(60))
        menu.addSeparator()
        menu.addAction("Settings…", self.settings_requested.emit)
        menu.exec(event.globalPos())
        event.accept()


class OverlayGroup(QObject):
    """One or many :class:`OverlayWindow`s, presented as if there were only one.

    An exclusive full-screen app owns the monitor it is on and nothing composites
    over it, so the only reliable way to be seen while gaming is to also appear on
    another monitor. Setting the screen to "all" mirrors the warning everywhere;
    dismissing any copy dismisses the lot, because they are all the same alert.
    """

    dismissed = Signal()
    open_ticket_requested = Signal(int)
    pause_requested = Signal(int)
    settings_requested = Signal()

    def __init__(self, config: Config):
        super().__init__(None)
        self._config = config
        self._windows: list[OverlayWindow] = []
        self._alerts: list[Alert] = []
        self._build()

        # A monitor arriving or leaving changes how many windows we need. Rebuild
        # rather than patch: cheap, and it cannot drift out of step with reality.
        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._on_screens_changed)
            app.screenRemoved.connect(self._on_screens_changed)

    # ------------------------------------------------------------------ #
    # composition
    # ------------------------------------------------------------------ #

    def _mirrors_everywhere(self) -> bool:
        return (self._config.screen_name or "").strip() == ALL_SCREENS

    def _build(self) -> None:
        if self._mirrors_everywhere():
            screens = QGuiApplication.screens() or [None]
        else:
            screens = [None]   # a single window that follows the configured screen

        for screen in screens:
            window = OverlayWindow(self._config, screen)
            window.dismissed.connect(self._on_dismissed)
            window.open_ticket_requested.connect(self.open_ticket_requested)
            window.pause_requested.connect(self.pause_requested)
            window.settings_requested.connect(self.settings_requested)
            self._windows.append(window)

    def _teardown(self) -> None:
        for window in self._windows:
            window.hide_warning()
            window.deleteLater()
        self._windows = []

    def _rebuild(self) -> None:
        """Replace the windows, putting any live warning back on screen."""
        alerts, self._alerts = self._alerts, []
        self._teardown()
        self._build()
        if alerts:
            self.set_alerts(alerts)

    def _on_screens_changed(self, _screen: QScreen) -> None:
        if self._mirrors_everywhere():
            self._rebuild()
        else:
            # The configured monitor may have just come back, or gone away and left
            # the window stranded off-screen. Either way, re-place it.
            for window in self._windows:
                window.reload_appearance(self._config)

    # ------------------------------------------------------------------ #
    # the OverlayWindow interface app.py uses
    # ------------------------------------------------------------------ #

    def set_alerts(self, alerts: list[Alert]) -> None:
        # Sound once per appearance, not once per poll or per mirrored monitor.
        was_showing = any(w.isVisible() for w in self._windows)
        self._alerts = list(alerts)
        for window in self._windows:
            window.set_alerts(alerts)
        if alerts and not was_showing and self._config.sound_enabled():
            sound.play_alert(self._config.sound_name)

    def show_warning(self) -> None:
        for window in self._windows:
            window.show_warning()

    def hide_warning(self) -> None:
        self._alerts = []
        for window in self._windows:
            window.hide_warning()

    def reload_appearance(self, config: Config) -> None:
        was_mirroring = self._mirrors_everywhere()
        self._config = config
        if was_mirroring != self._mirrors_everywhere():
            self._rebuild()      # the number of windows changed
            return
        for window in self._windows:
            window.reload_appearance(config)

    def _on_dismissed(self) -> None:
        # One click clears every copy: they all describe the same tickets.
        self.hide_warning()
        self.dismissed.emit()

    @property
    def windows(self) -> list[OverlayWindow]:
        """Exposed for tests and for logging how many monitors are in use."""
        return list(self._windows)


def _clip(text: str, limit: int) -> str:
    """Keep the caption a readable width; an ellipsis says it was cut."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_preview_window: OverlayGroup | None = None


def preview(config: Config, alerts: list[Alert] | None = None, seconds: float = 4.0) -> None:
    """Show a throwaway overlay so the user can judge size and position."""
    global _preview_window
    if QApplication.instance() is None:
        return
    if _preview_window is not None:
        _preview_window.hide_warning()
        _preview_window.deleteLater()

    # A group, not a bare window, so previewing "all screens" really shows all of
    # them - otherwise the preview would quietly disagree with the setting.
    window = OverlayGroup(config)
    demo = alerts or [Alert(
        ticket_id=12345,
        reason="new_unassigned",
        subject="Preview – this is how the warning will look",
        group_id=None,
        group_name="Preview",
        raised_at=0.0,
        # A requester too, so the preview shows the real shape of the box rather
        # than a shorter one than you will actually get.
        requester_id=0,
        requester_name="Sam Example",
    )]
    window.set_alerts(demo)
    _preview_window = window
    QTimer.singleShot(int(seconds * 1000), window.hide_warning)
