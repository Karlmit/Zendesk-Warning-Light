"""Application shell: tray icon, menus, and the wiring between UI and monitor."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import webbrowser
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import config as config_module, icons, modes, overlay
from .auth import TokenStore
from .config import Config
from .monitor import Alert, Monitor
from .paths import APP_NAME, log_path
from .settings_ui import SettingsDialog

log = logging.getLogger(__name__)

SINGLE_INSTANCE_KEY = "ZendeskWarningLight.singleton"
PAUSE_TICK_MS = 20_000

PAUSE_CHOICES = [
    ("Pause for 30 minutes", 30),
    ("Pause for 1 hour", 60),
    ("Pause for 4 hours", 240),
]


def setup_logging(verbose: bool = False) -> None:
    handler = logging.handlers.RotatingFileHandler(
        log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(handler)
    if verbose:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(stream)


class WarningLightApp(QObject):
    config_changed = Signal(object)
    dismiss_requested = Signal()
    poll_requested = Signal()
    stop_requested = Signal()
    sign_in_reset_requested = Signal()

    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self._config = config_module.load()
        self._alerts: list[Alert] = []
        self._last_error: str = ""
        self._settings_dialog: SettingsDialog | None = None
        self._was_paused = self._config.is_paused()
        self._last_effective_mode = self._config.effective_mode()
        self._auth_ok = True

        self._tokens = TokenStore(base_url=self._config.base_url,
                                  client_id=self._config.client_id)
        self._tokens.load()

        # A group, not a single window: with the screen set to "all" it mirrors
        # onto every monitor, which is the only way to be seen past a game in
        # exclusive full screen. The interface is the same either way.
        self._overlay = overlay.OverlayGroup(self._config)
        self._overlay.dismissed.connect(self._on_dismiss)
        self._overlay.open_ticket_requested.connect(self._open_ticket)
        self._overlay.pause_requested.connect(self._pause_for)
        self._overlay.settings_requested.connect(self.open_settings)

        self._tray = QSystemTrayIcon(icons.tray_icon(icons.IDLE))
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(self._on_tray_activated)
        self._build_menu()
        self._tray.show()

        self._thread = QThread()
        self._thread.setObjectName("zendesk-monitor")
        self._monitor = Monitor(self._config_copy(), self._tokens)
        self._monitor.moveToThread(self._thread)
        self._thread.started.connect(self._monitor.start)
        self._monitor.alerts_changed.connect(self._on_alerts_changed)
        self._monitor.status_changed.connect(self._on_status_changed)
        self._monitor.error_occurred.connect(self._on_error)
        self._monitor.auth_state_changed.connect(self._on_auth_state)
        self.config_changed.connect(self._monitor.apply_config)
        self.dismiss_requested.connect(self._monitor.dismiss_all)
        self.poll_requested.connect(self._monitor.poll_now)
        self.stop_requested.connect(self._monitor.stop)
        self.sign_in_reset_requested.connect(self._monitor.reset_sign_in)
        self._thread.start()

        # Notice when a pause expires so the icon and menu update on their own.
        self._pause_timer = QTimer(self)
        self._pause_timer.setInterval(PAUSE_TICK_MS)
        self._pause_timer.timeout.connect(self._check_pause_expiry)
        self._pause_timer.start()

        if not self._tokens.is_signed_in:
            QTimer.singleShot(400, self._first_run)

    # ------------------------------------------------------------------ #
    # menu
    # ------------------------------------------------------------------ #

    def _build_menu(self) -> None:
        menu = QMenu()

        self._status_action = QAction("Starting…", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()

        self._enabled_action = QAction("Enabled", menu, checkable=True)
        self._enabled_action.setChecked(self._config.enabled)
        self._enabled_action.toggled.connect(self._on_enabled_toggled)
        menu.addAction(self._enabled_action)

        # Filled in _rebuild_mode_menu, because the user can add and rename modes.
        self._mode_menu = menu.addMenu("Mode")
        self._mode_group: QActionGroup | None = None
        self._mode_actions: dict[str, QAction] = {}
        self._rebuild_mode_menu()

        pause_menu = menu.addMenu("Pause")
        for label, minutes in PAUSE_CHOICES:
            action = pause_menu.addAction(label)
            action.triggered.connect(lambda _c=False, m=minutes: self._pause_for(m))
        pause_menu.addAction("Pause for the rest of today", self._pause_rest_of_day)
        pause_menu.addSeparator()
        self._resume_action = pause_menu.addAction("Resume now", self._resume)

        menu.addSeparator()
        self._sign_in_action = QAction("Sign in to Zendesk…", menu)
        self._sign_in_action.triggered.connect(self._open_sign_in)
        menu.addAction(self._sign_in_action)
        menu.addAction("Check Zendesk now", lambda: self.poll_requested.emit())
        menu.addAction("Dismiss warning", self._on_dismiss)
        menu.addAction("Preview the warning", lambda: overlay.preview(self._config))
        menu.addSeparator()
        menu.addAction("Open Zendesk", self._open_zendesk)
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)

        menu.aboutToShow.connect(self._refresh_menu)
        self._menu = menu
        self._tray.setContextMenu(menu)

    def _rebuild_mode_menu(self) -> None:
        """Rebuild the Mode submenu from the current mode list."""
        self._mode_menu.clear()
        self._mode_actions = {}
        self._mode_group = QActionGroup(self._mode_menu)
        self._mode_group.setExclusive(True)

        entries = [(m.id, m.name) for m in self._config.day_modes]
        entries.append((modes.OFF, modes.OFF_LABEL))
        for value, text in entries:
            action = QAction(text, self._mode_menu, checkable=True)
            action.setActionGroup(self._mode_group)
            action.triggered.connect(
                lambda _checked=False, m=value: self._on_mode_selected(m))
            self._mode_menu.addAction(action)
            self._mode_actions[value] = action

        self._mode_menu.addSeparator()
        schedule_action = QAction("Follow the weekly schedule", self._mode_menu,
                                  checkable=True)
        schedule_action.setActionGroup(self._mode_group)
        schedule_action.triggered.connect(
            lambda _checked=False: self._on_mode_selected(modes.SCHEDULE))
        self._mode_menu.addAction(schedule_action)
        self._mode_actions[modes.SCHEDULE] = schedule_action

        self._mode_menu.addSeparator()
        self._mode_menu.addAction("Edit modes\u2026", self._open_modes)
        self._mode_menu.addAction("Edit the weekly schedule\u2026", self._open_schedule)

    def _refresh_menu(self) -> None:
        needs_sign_in = not self._tokens.is_signed_in or not self._auth_ok
        self._sign_in_action.setVisible(needs_sign_in)

        # Names and membership can change while the menu exists.
        expected = [m.id for m in self._config.day_modes]
        listed = [k for k in self._mode_actions if k not in (modes.SCHEDULE, modes.OFF)]
        stale = sorted(expected) != sorted(listed) or any(
            self._mode_actions[m.id].text() != m.name for m in self._config.day_modes)
        if stale:
            self._rebuild_mode_menu()

        self._mode_menu.setTitle("Mode: {}".format(self._config.mode_label()))
        for value, action in self._mode_actions.items():
            action.blockSignals(True)
            action.setChecked(self._config.mode == value)
            action.blockSignals(False)

        paused = self._config.is_paused()
        self._resume_action.setEnabled(paused or not self._config.enabled)
        self._enabled_action.blockSignals(True)
        self._enabled_action.setChecked(self._config.enabled)
        self._enabled_action.blockSignals(False)
        self._status_action.setText(self._status_text())

    def _status_text(self) -> str:
        if not self._tokens.is_signed_in:
            return "Not signed in to Zendesk"
        if not self._auth_ok:
            return "Zendesk sign-in expired"
        if not self._config.enabled:
            return "Disabled"
        expiry = self._config.pause_expiry()
        if expiry and self._config.is_paused():
            local = expiry.astimezone()
            return "Paused until {}".format(local.strftime("%H:%M on %a %d %b"))
        if self._config.is_off_day():
            return "{} - not polling".format(self._config.mode_label())
        if self._alerts:
            return "{} ticket(s) need attention · {}".format(
                len(self._alerts), self._config.mode_label())
        return "Watching Zendesk · {}".format(self._config.mode_label())

    # ------------------------------------------------------------------ #
    # state changes
    # ------------------------------------------------------------------ #

    def _config_copy(self) -> Config:
        """Hand the worker thread its own Config so the two never share mutable state."""
        return Config.from_dict(self._config.to_dict())

    def _push_config(self) -> None:
        self._config.save()
        self._overlay.reload_appearance(self._config)
        self.config_changed.emit(self._config_copy())
        self._update_icon()

    def _update_icon(self) -> None:
        if not self._tokens.is_signed_in or not self._auth_ok:
            state = icons.ERROR
        elif self._last_error:
            state = icons.ERROR
        elif not self._config.is_active():
            state = icons.PAUSED
        elif self._alerts:
            state = icons.ALERT
        else:
            state = icons.IDLE
        self._tray.setIcon(icons.tray_icon(state))
        tooltip = "{} – {}".format(APP_NAME, self._status_text())
        if self._last_error:
            tooltip += "\n{}".format(self._last_error[:160])
        self._tray.setToolTip(tooltip)

    @Slot(list)
    def _on_alerts_changed(self, alerts: list) -> None:
        self._alerts = list(alerts)
        # While the sign-in is broken the alert list cannot be trusted, so hide the
        # warning rather than let a stale one imply everything is fine.
        if self._auth_ok and self._config.is_active() and self._alerts:
            self._overlay.set_alerts(self._alerts)
        else:
            self._overlay.hide_warning()
        self._update_icon()

    @Slot(str)
    def _on_status_changed(self, status: str) -> None:
        if status not in ("Zendesk error", "Error"):
            self._last_error = ""
        self._update_icon()

    @Slot(str)
    def _on_error(self, message: str) -> None:
        first_time = not self._last_error
        self._last_error = message
        self._update_icon()
        log.error("monitor error surfaced: %s", message)
        if first_time and self._tray.supportsMessages():
            self._tray.showMessage(
                "Zendesk Warning Light",
                message[:220],
                icons.tray_icon(icons.ERROR),
                8000,
            )

    def _on_dismiss(self) -> None:
        self._overlay.hide_warning()
        self.dismiss_requested.emit()

    @Slot(bool, str)
    def _on_auth_state(self, ok: bool, message: str) -> None:
        self._auth_ok = ok
        if not ok:
            self._overlay.hide_warning()
            log.warning("sign-in needs attention: %s", message)
            if self._tray.supportsMessages():
                self._tray.showMessage(
                    "Zendesk Warning Light – sign-in expired",
                    message or "Open Settings and sign in to Zendesk again.",
                    icons.tray_icon(icons.ERROR), 15000)
        else:
            log.info("Zendesk sign-in healthy again")
        self._update_icon()

    def _open_sign_in(self) -> None:
        self.open_settings()
        if self._settings_dialog is not None:
            self._settings_dialog.show_connection_tab()

    # ------------------------------------------------------------------ #
    # enable / pause
    # ------------------------------------------------------------------ #

    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._config.enabled = enabled
        if enabled:
            self._config.paused_until = ""
        else:
            self._overlay.hide_warning()
            self.dismiss_requested.emit()
        log.info("app %s from the tray", "enabled" if enabled else "disabled")
        self._push_config()

    def _on_mode_selected(self, mode: str) -> None:
        if mode == self._config.mode:
            return
        self._config.mode = mode
        self._last_effective_mode = self._config.effective_mode()
        log.info("mode set to %s (today: %s)", mode, self._config.mode_label())
        if self._config.is_off_day():
            self._overlay.hide_warning()
        self._push_config()
        self.poll_requested.emit()
        if self._tray.supportsMessages():
            self._tray.showMessage(
                "Zendesk Warning Light",
                self._mode_summary(),
                icons.tray_icon(icons.IDLE), 5000)

    def _mode_summary(self) -> str:
        active = self._config.active_mode()
        if active is None:
            return ("Off Day - no warnings and no Zendesk calls until the next "
                    "working day.")
        return "{} - warns about {}.".format(active.name, active.summary())

    def _open_schedule(self) -> None:
        self.open_settings()
        if self._settings_dialog is not None:
            self._settings_dialog.show_schedule_tab()

    def _open_modes(self) -> None:
        self.open_settings()
        if self._settings_dialog is not None:
            self._settings_dialog.show_modes_tab()

    def _pause_for(self, minutes: int) -> None:
        until = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        self._apply_pause(until)

    def _pause_rest_of_day(self) -> None:
        tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._apply_pause(tomorrow.astimezone(timezone.utc))

    def _apply_pause(self, until: datetime) -> None:
        self._config.paused_until = until.isoformat()
        self._was_paused = True
        self._overlay.hide_warning()
        self.dismiss_requested.emit()
        log.info("paused until %s", until.astimezone().strftime("%Y-%m-%d %H:%M"))
        self._push_config()

    def _resume(self) -> None:
        self._config.paused_until = ""
        self._config.enabled = True
        self._was_paused = False
        log.info("resumed from the tray")
        self._push_config()
        self.poll_requested.emit()

    def _check_pause_expiry(self) -> None:
        # Also catches midnight on a Schedule day, so Friday's Helpdesk Day becomes
        # Saturday's Off Day without the user restarting anything.
        effective_now = self._config.effective_mode()
        if effective_now != self._last_effective_mode:
            log.info("day mode rolled over: %s -> %s",
                     self._last_effective_mode, effective_now)
            self._last_effective_mode = effective_now
            if effective_now == modes.OFF:
                self._overlay.hide_warning()
            self.config_changed.emit(self._config_copy())
            self._update_icon()

        paused_now = self._config.is_paused()
        if self._was_paused and not paused_now:
            log.info("pause expired, watching again")
            self._was_paused = False
            self._config.save()
            self.config_changed.emit(self._config_copy())
            self._update_icon()
        else:
            self._was_paused = paused_now

    # ------------------------------------------------------------------ #
    # misc actions
    # ------------------------------------------------------------------ #

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # left click
            if self._alerts:
                self._on_dismiss()
            else:
                self.open_settings()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.open_settings()

    def _open_zendesk(self) -> None:
        webbrowser.open("{}/agent/filters".format(self._config.base_url))

    def _open_ticket(self, ticket_id: int) -> None:
        webbrowser.open("{}/agent/tickets/{}".format(self._config.base_url, int(ticket_id)))

    def _first_run(self) -> None:
        if self._tray.supportsMessages():
            self._tray.showMessage(
                "Zendesk Warning Light",
                "Sign in with your Zendesk account to get started.",
                icons.tray_icon(icons.IDLE),
                6000,
            )
        self._open_sign_in()

    @Slot()
    def open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self._config, self._tokens)
        dialog.setWindowIcon(icons.app_icon())
        dialog.saved.connect(self._on_settings_saved)
        dialog.signed_in.connect(self._on_signed_in)
        dialog.signed_out.connect(self._on_signed_out)
        dialog.finished.connect(lambda _: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    @Slot()
    def _on_signed_in(self) -> None:
        self._auth_ok = True
        self._last_error = ""
        self.sign_in_reset_requested.emit()
        self._update_icon()

    @Slot()
    def _on_signed_out(self) -> None:
        self._auth_ok = True          # not broken, just absent
        self._alerts = []
        self._overlay.hide_warning()
        self._update_icon()

    @Slot(object)
    def _on_settings_saved(self, cfg: Config) -> None:
        self._config = cfg
        self._last_error = ""
        self._last_effective_mode = cfg.effective_mode()
        self._rebuild_mode_menu()
        log.info("settings saved (mode=%s, %d mode(s) defined, poll=%ss)",
                 cfg.mode_label(), len(cfg.day_modes), cfg.poll_seconds)
        self._push_config()
        self.poll_requested.emit()

    @Slot()
    def quit(self) -> None:
        log.info("shutting down")
        self._pause_timer.stop()
        self._overlay.hide_warning()
        self._tray.hide()
        self.stop_requested.emit()   # queued: the worker flushes state before quitting
        self._thread.quit()
        self._thread.wait(4000)
        self._app.quit()


def _already_running() -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(300):
        socket.disconnectFromServer()
        return True
    return False


def run(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    verbose = "--verbose" in argv or "-v" in argv
    setup_logging(verbose)
    log.info("=" * 60)
    log.info("%s starting", APP_NAME)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icons.app_icon())

    if _already_running():
        log.info("another instance is already running - exiting")
        QMessageBox.information(
            None, APP_NAME,
            "Zendesk Warning Light is already running.\nLook for the triangle in the system tray.",
        )
        return 0

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "No system tray is available on this desktop.")
        return 1

    controller = WarningLightApp(app)
    app.aboutToQuit.connect(server.close)
    app._zwl_controller = controller  # keep the controller alive for the whole session
    return app.exec()
