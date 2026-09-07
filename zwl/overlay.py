"""The always-on-top animated warning that appears in a corner of the screen."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImageReader, QMovie, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from .config import Config
from .monitor import Alert

log = logging.getLogger(__name__)

CAPTION_MAX_WIDTH = 360
RAISE_INTERVAL_MS = 4000
FADE_MS = 260

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

    def __init__(self, config: Config):
        super().__init__(None)
        self._config = config
        self._alerts: list[Alert] = []
        self._movie: QMovie | None = None
        self._source_size = QSize(480, 480)

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
        wanted = (self._config.screen_name or "").strip()
        if wanted:
            for screen in QGuiApplication.screens():
                if screen.name() == wanted:
                    return screen
        return QGuiApplication.primaryScreen()

    def _reposition(self) -> None:
        screen = self._target_screen()
        if screen is None:
            return
        area = screen.availableGeometry()   # excludes the taskbar
        size = self.sizeHint().expandedTo(self.size())
        mx, my = self._config.margin_x, self._config.margin_y
        corner = self._config.corner

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

        subject = newest.subject or "(no subject)"
        if len(subject) > 68:
            subject = subject[:67] + "…"
        detail = "#{} &middot; {}".format(newest.ticket_id, _escape(subject))
        if newest.group_name:
            detail += "<br><span style='color:#9aa0aa'>{}</span>".format(_escape(newest.group_name))

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


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_preview_window: OverlayWindow | None = None


def preview(config: Config, alerts: list[Alert] | None = None, seconds: float = 4.0) -> None:
    """Show a throwaway overlay so the user can judge size and position."""
    global _preview_window
    if QApplication.instance() is None:
        return
    if _preview_window is not None:
        _preview_window.close()
        _preview_window.deleteLater()

    window = OverlayWindow(config)
    window.dismissed.connect(window.hide_warning)
    demo = alerts or [Alert(
        ticket_id=12345,
        reason="new_unassigned",
        subject="Preview – this is how the warning will look",
        group_id=None,
        group_name="Preview",
        raised_at=0.0,
    )]
    window.set_alerts(demo)
    _preview_window = window
    QTimer.singleShot(int(seconds * 1000), window.hide_warning)
