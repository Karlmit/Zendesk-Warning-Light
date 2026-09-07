"""The settings window reached from the tray icon."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)

from . import autostart, overlay
from .auth import AuthError, TokenStore
from .config import Config
from .paths import assets_dir, data_dir, log_path
from .zendesk import ZendeskClient, ZendeskError

log = logging.getLogger(__name__)

ANIMATION_FILTER = "Animations (*.gif *.webp *.png *.apng);;All files (*)"
CORNERS = [
    ("Bottom right", "bottom-right"),
    ("Bottom left", "bottom-left"),
    ("Top right", "top-right"),
    ("Top left", "top-left"),
]

NOT_A_MEMBER_HINT = (
    "You are not a member of this group. It will only raise warnings if your "
    "Zendesk role lets you see every ticket."
)


class _CallThread(QThread):
    """Runs one blocking callable off the UI thread."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn())
        except (AuthError, ZendeskError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("settings background call failed")
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    saved = Signal(object)      # Config
    signed_in = Signal()        # a new user signed in; the monitor must restart
    signed_out = Signal()

    def __init__(self, config: Config, tokens: TokenStore, parent=None):
        super().__init__(parent)
        self._config = Config.from_dict(config.to_dict())  # edit a copy
        self._tokens = tokens
        self._groups: list[dict[str, Any]] = []
        self._my_group_ids: set[int] | None = None
        self._thread: _CallThread | None = None

        self.setWindowTitle("Zendesk Warning Light – Settings")
        self.setMinimumWidth(600)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_groups_tab(), "Groups")
        self._tabs.addTab(self._build_alerts_tab(), "Alerts")
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_general_tab(), "General")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(self._tabs)
        root.addWidget(buttons)

        self._load_from_config()
        if self._tokens.is_signed_in:
            QTimer.singleShot(0, self._on_load_groups)

    # ------------------------------------------------------------------ #
    # tabs
    # ------------------------------------------------------------------ #

    def _build_connection_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        form = QFormLayout()
        self.subdomain_edit = QLineEdit()
        self.subdomain_edit.setPlaceholderText("yourcompany")
        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("https://"))
        sub_row.addWidget(self.subdomain_edit, 1)
        sub_row.addWidget(QLabel(".zendesk.com"))
        sub_wrap = QWidget()
        sub_wrap.setLayout(sub_row)
        form.addRow("Subdomain", sub_wrap)

        self.client_id_edit = QLineEdit()
        self.client_id_edit.setPlaceholderText("warning_light_desktop")
        form.addRow("OAuth client", self.client_id_edit)
        layout.addLayout(form)

        account = QGroupBox("Your Zendesk account")
        account_layout = QVBoxLayout(account)
        self.account_label = QLabel("")
        self.account_label.setWordWrap(True)
        account_layout.addWidget(self.account_label)

        row = QHBoxLayout()
        self.sign_in_button = QPushButton("Sign in with Zendesk")
        self.sign_in_button.clicked.connect(self._on_sign_in)
        row.addWidget(self.sign_in_button)
        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_button.clicked.connect(self._on_sign_out)
        row.addWidget(self.sign_out_button)
        row.addStretch(1)
        account_layout.addLayout(row)
        layout.addWidget(account)

        note = QLabel(
            "Signing in opens your browser, so your normal Microsoft sign-in and MFA "
            "apply. The app uses a <b>public</b> OAuth client with PKCE and holds no "
            "client secret — only a refresh token for your own account, encrypted "
            "with Windows DPAPI. It asks for <code>read</code> access only, so it can "
            "never modify a ticket."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_groups_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.groups_hint = QLabel("")
        self.groups_hint.setWordWrap(True)
        layout.addWidget(self.groups_hint)

        self.group_list = QListWidget()
        self.group_list.setAlternatingRowColors(True)
        layout.addWidget(self.group_list, 1)

        row = QHBoxLayout()
        self.load_groups_button = QPushButton("Refresh from Zendesk")
        self.load_groups_button.clicked.connect(self._on_load_groups)
        row.addWidget(self.load_groups_button)
        self.only_mine_button = QPushButton("Only my groups")
        self.only_mine_button.clicked.connect(self._on_only_my_groups)
        row.addWidget(self.only_mine_button)
        select_all = QPushButton("Select all")
        select_all.clicked.connect(lambda: self._set_all_groups(True))
        row.addWidget(select_all)
        select_none = QPushButton("Clear")
        select_none.clicked.connect(lambda: self._set_all_groups(False))
        row.addWidget(select_none)
        row.addStretch(1)
        layout.addLayout(row)

        self.groups_status = QLabel("")
        self.groups_status.setWordWrap(True)
        self.groups_status.setStyleSheet("color:#888;")
        layout.addWidget(self.groups_status)
        return page

    def _build_alerts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        rules = QGroupBox("Show the warning when…")
        rules_layout = QVBoxLayout(rules)
        self.cb_new_unassigned = QCheckBox("A new ticket arrives with no assignee")
        self.cb_became_unassigned = QCheckBox("An existing ticket is handed back to the queue")
        self.cb_pending_to_open = QCheckBox("A ticket assigned to me goes from pending back to open")
        for cb in (self.cb_new_unassigned, self.cb_became_unassigned, self.cb_pending_to_open):
            rules_layout.addWidget(cb)
        self.identity_label = QLabel("")
        self.identity_label.setWordWrap(True)
        self.identity_label.setStyleSheet("color:#888;")
        rules_layout.addWidget(self.identity_label)
        layout.addWidget(rules)

        timing = QGroupBox("Polling")
        timing_form = QFormLayout(timing)
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(10, 900)
        self.poll_spin.setSuffix(" seconds")
        timing_form.addRow("Check Zendesk every", self.poll_spin)
        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet("color:#888;")
        timing_form.addRow("", self.source_label)
        layout.addWidget(timing)

        layout.addStretch(1)
        return page

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.animation_combo = QComboBox()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse_animation)
        anim_row = QHBoxLayout()
        anim_row.addWidget(self.animation_combo, 1)
        anim_row.addWidget(browse)
        anim_wrap = QWidget()
        anim_wrap.setLayout(anim_row)
        form.addRow("Animation", anim_wrap)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(80, 900)
        self.height_spin.setSingleStep(20)
        self.height_spin.setSuffix(" px")
        form.addRow("Height", self.height_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.2, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setDecimals(2)
        form.addRow("Opacity", self.opacity_spin)

        self.screen_combo = QComboBox()
        self.screen_combo.addItem("Primary screen", "")
        for screen in QGuiApplication.screens():
            geo = screen.geometry()
            self.screen_combo.addItem("{} – {}x{} at ({}, {})".format(
                screen.name(), geo.width(), geo.height(), geo.x(), geo.y()), screen.name())
        form.addRow("Screen", self.screen_combo)

        self.corner_combo = QComboBox()
        for label, value in CORNERS:
            self.corner_combo.addItem(label, value)
        form.addRow("Corner", self.corner_combo)

        self.margin_x_spin = QSpinBox()
        self.margin_x_spin.setRange(0, 600)
        self.margin_x_spin.setSuffix(" px")
        form.addRow("Margin from side", self.margin_x_spin)

        self.margin_y_spin = QSpinBox()
        self.margin_y_spin.setRange(0, 600)
        self.margin_y_spin.setSuffix(" px")
        form.addRow("Margin from top/bottom", self.margin_y_spin)

        self.caption_check = QCheckBox("Show the ticket subject next to the animation")
        form.addRow("", self.caption_check)

        preview_button = QPushButton("Preview for 4 seconds")
        preview_button.clicked.connect(self._on_preview)
        form.addRow("", preview_button)
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.autostart_check = QCheckBox("Start automatically when I sign in to Windows")
        layout.addWidget(self.autostart_check)

        row = QHBoxLayout()
        open_folder = QPushButton("Open settings folder")
        open_folder.clicked.connect(lambda: _open_path(data_dir()))
        row.addWidget(open_folder)
        open_log = QPushButton("Open log file")
        open_log.clicked.connect(lambda: _open_path(log_path()))
        row.addWidget(open_log)
        row.addStretch(1)
        layout.addLayout(row)

        reset = QPushButton("Forget tracked tickets and re-seed")
        reset.setToolTip(
            "Clears the remembered ticket history. The app quietly re-reads recent "
            "activity, so nothing fires until something changes again."
        )
        reset.clicked.connect(self._on_reset_state)
        layout.addWidget(reset, 0, Qt.AlignLeft)

        about = QLabel(
            "<b>Zendesk Warning Light</b><br>"
            "Lights up when a ticket needs an owner.<br><br>"
            "Settings and logs live in:<br><code>{}</code>".format(data_dir())
        )
        about.setWordWrap(True)
        about.setStyleSheet("color:#888;")
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------ #
    # populate / collect
    # ------------------------------------------------------------------ #

    def _load_from_config(self) -> None:
        cfg = self._config
        self.subdomain_edit.setText(cfg.subdomain)
        self.client_id_edit.setText(cfg.client_id)

        self.cb_new_unassigned.setChecked(cfg.alert_on_new_unassigned)
        self.cb_became_unassigned.setChecked(cfg.alert_on_became_unassigned)
        self.cb_pending_to_open.setChecked(cfg.alert_on_pending_to_open)
        self.poll_spin.setValue(cfg.poll_seconds)

        self._populate_animations()
        self.height_spin.setValue(cfg.animation_height)
        self.opacity_spin.setValue(cfg.opacity)
        self._select_data(self.screen_combo, cfg.screen_name)
        self._select_data(self.corner_combo, cfg.corner)
        self.margin_x_spin.setValue(cfg.margin_x)
        self.margin_y_spin.setValue(cfg.margin_y)
        self.caption_check.setChecked(cfg.show_caption)

        self.autostart_check.setChecked(autostart.is_enabled())
        self._refresh_account_state()
        self._render_groups()

    def _refresh_account_state(self) -> None:
        user = self._tokens.user
        signed_in = self._tokens.is_signed_in

        if signed_in and user.id:
            self.account_label.setText(
                "<b style='color:#2e7d32'>Signed in as {}</b><br>"
                "{}<br><span style='color:#888'>Zendesk role: {}{}</span>".format(
                    _escape(user.name), _escape(user.email), _escape(user.role),
                    " · limited to your own groups" if user.restricted_agent else "",
                )
            )
            self.identity_label.setText(
                "The reopen rule watches tickets assigned to <b>{}</b>.".format(
                    _escape(user.email)))
            self.source_label.setText(
                "Admins read the incremental export; everyone else reads the "
                "agent-safe ticket sweep. Chosen automatically."
                if user.is_admin else
                "Reading tickets via the agent-safe sweep."
            )
        else:
            self.account_label.setText(
                "<b style='color:#c62828'>Not signed in.</b><br>"
                "The app cannot see any tickets until you sign in.")
            self.identity_label.setText(
                "Sign in on the Connection tab so the reopen rule knows who you are.")
            self.source_label.setText("")

        self.sign_in_button.setText("Sign in again" if signed_in else "Sign in with Zendesk")
        self.sign_out_button.setEnabled(signed_in)
        self.subdomain_edit.setEnabled(not signed_in)
        self.client_id_edit.setEnabled(not signed_in)
        if signed_in:
            tip = "Sign out first to change where the app connects."
            self.subdomain_edit.setToolTip(tip)
            self.client_id_edit.setToolTip(tip)

    def _populate_animations(self) -> None:
        self.animation_combo.clear()
        seen = set()
        for path in sorted(assets_dir().glob("*")):
            if path.suffix.lower() in (".gif", ".webp", ".png", ".apng"):
                self.animation_combo.addItem(path.stem, path.name)
                seen.add(path.name)
        current = self._config.animation
        if current and current not in seen:
            self.animation_combo.addItem(Path(current).name, current)
        self._select_data(self.animation_combo, current)

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    # --- groups -----------------------------------------------------------

    def _render_groups(self) -> None:
        self.group_list.clear()
        watched = set(self._config.watched_group_ids)
        user = self._tokens.user
        restricted = bool(user.restricted_agent)

        if not self._groups:
            self.groups_hint.setText(
                "Tick the groups the warning light should watch for unassigned tickets. "
                "With nothing ticked it watches <b>every</b> group you can see."
            )
            for group_id in sorted(watched):
                item = QListWidgetItem("Group {} (not loaded yet)".format(group_id))
                item.setData(Qt.UserRole, group_id)
                item.setCheckState(Qt.Checked)
                self.group_list.addItem(item)
            return

        if restricted:
            self.groups_hint.setText(
                "Your Zendesk role limits you to tickets in your own groups, so only "
                "those are listed. With nothing ticked, all of them are watched."
            )
        else:
            self.groups_hint.setText(
                "Tick the groups to watch. With nothing ticked it watches <b>every</b> "
                "group. Groups you are not a member of are greyed out — they still work "
                "for you because your role can see all tickets."
            )

        shown = [
            g for g in self._groups
            if not restricted or self._my_group_ids is None
            or int(g["id"]) in self._my_group_ids
        ]
        for group in shown:
            group_id = int(group["id"])
            item = QListWidgetItem(group.get("name") or "(unnamed)")
            item.setData(Qt.UserRole, group_id)
            item.setCheckState(Qt.Checked if group_id in watched else Qt.Unchecked)
            if self._my_group_ids is not None and group_id not in self._my_group_ids:
                item.setForeground(QBrush(QColor("#8b93a1")))
                item.setToolTip(NOT_A_MEMBER_HINT)
            self.group_list.addItem(item)

    def _remember_ticked(self) -> None:
        """Preserve the user's ticks across a list rebuild."""
        self._config.watched_group_ids = self._collect_ticked()

    def _collect_ticked(self) -> list[int]:
        return [
            int(self.group_list.item(row).data(Qt.UserRole))
            for row in range(self.group_list.count())
            if self.group_list.item(row).checkState() == Qt.Checked
        ]

    def _set_all_groups(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.group_list.count()):
            self.group_list.item(row).setCheckState(state)

    def _on_only_my_groups(self) -> None:
        if self._my_group_ids is None:
            QMessageBox.information(
                self, "Group membership unknown",
                "Zendesk did not tell us which groups you belong to, so the app cannot "
                "narrow the list. Refresh from Zendesk, or tick groups by hand.")
            return
        for row in range(self.group_list.count()):
            item = self.group_list.item(row)
            mine = int(item.data(Qt.UserRole)) in self._my_group_ids
            item.setCheckState(Qt.Checked if mine else Qt.Unchecked)

    def _collect(self) -> Config:
        cfg = self._config
        if not self._tokens.is_signed_in:
            cfg.subdomain = self.subdomain_edit.text().strip().replace(".zendesk.com", "")
            cfg.client_id = self.client_id_edit.text().strip() or cfg.client_id

        cfg.alert_on_new_unassigned = self.cb_new_unassigned.isChecked()
        cfg.alert_on_became_unassigned = self.cb_became_unassigned.isChecked()
        cfg.alert_on_pending_to_open = self.cb_pending_to_open.isChecked()
        cfg.poll_seconds = self.poll_spin.value()

        cfg.animation = self.animation_combo.currentData() or cfg.animation
        cfg.animation_height = self.height_spin.value()
        cfg.opacity = self.opacity_spin.value()
        cfg.screen_name = self.screen_combo.currentData() or ""
        cfg.corner = self.corner_combo.currentData() or "bottom-right"
        cfg.margin_x = self.margin_x_spin.value()
        cfg.margin_y = self.margin_y_spin.value()
        cfg.show_caption = self.caption_check.isChecked()
        cfg.watched_group_ids = self._collect_ticked()
        return cfg

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def _run_async(self, fn: Callable[[], Any], on_ok: Callable[[Any], None],
                   buttons: list[QPushButton]) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self, "Busy",
                                    "Another Zendesk request is still running.")
            return
        for button in buttons:
            button.setEnabled(False)

        thread = _CallThread(fn, self)

        def finish() -> None:
            for button in buttons:
                button.setEnabled(True)
            self._refresh_account_state()

        thread.succeeded.connect(on_ok)
        thread.succeeded.connect(lambda _=None: finish())
        thread.failed.connect(lambda msg: (finish(), self._show_error(msg)))
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Zendesk", message)

    # --- sign in / out ----------------------------------------------------

    def _on_sign_in(self) -> None:
        subdomain = self.subdomain_edit.text().strip().replace(".zendesk.com", "")
        client_id = self.client_id_edit.text().strip()
        if not subdomain:
            QMessageBox.warning(self, "Missing subdomain", "Enter your Zendesk subdomain.")
            return
        if not client_id:
            QMessageBox.warning(self, "Missing OAuth client",
                                "Enter the OAuth client identifier.")
            return

        self._config.subdomain = subdomain
        self._config.client_id = client_id
        base_url = "https://{}.zendesk.com".format(subdomain)

        self.account_label.setText("Waiting for you to finish signing in in the browser…")
        self._run_async(
            lambda: self._tokens.sign_in(base_url, client_id),
            self._on_signed_in,
            [self.sign_in_button, self.sign_out_button],
        )

    def _on_signed_in(self, user) -> None:
        log.info("settings: signed in as %s", user.describe())
        self._groups = []
        self._my_group_ids = None
        self._refresh_account_state()
        self._render_groups()
        self.signed_in.emit()
        QMessageBox.information(
            self, "Signed in",
            "Signed in as {} <{}>.\n\nNow pick the groups to watch on the Groups "
            "tab.".format(user.name, user.email))
        self._on_load_groups()

    def _on_sign_out(self) -> None:
        confirm = QMessageBox.question(
            self, "Sign out",
            "Sign out of Zendesk?\n\nThe warning light stops working until you sign "
            "in again. Your settings are kept.")
        if confirm != QMessageBox.Yes:
            return
        self._tokens.clear()
        self._groups = []
        self._my_group_ids = None
        self._refresh_account_state()
        self._render_groups()
        self.signed_out.emit()

    # --- groups -----------------------------------------------------------

    def _on_load_groups(self) -> None:
        if not self._tokens.is_signed_in:
            QMessageBox.information(self, "Not signed in",
                                    "Sign in on the Connection tab first.")
            return
        self._remember_ticked()
        self.groups_status.setText("Loading…")

        client = ZendeskClient(self._tokens)
        user_id = self._tokens.user.id

        def fetch() -> dict[str, Any]:
            return {"all": client.groups(),
                    "mine": client.my_groups(user_id) if user_id else None}

        self._run_async(fetch, self._on_groups_loaded,
                        [self.load_groups_button, self.only_mine_button])

    def _on_groups_loaded(self, payload: dict[str, Any]) -> None:
        self._groups = payload.get("all") or []
        mine = payload.get("mine")
        self._my_group_ids = {int(g["id"]) for g in mine} if mine is not None else None

        # First run: default to the user's own groups rather than "everything".
        if not self._config.watched_group_ids and self._my_group_ids:
            self._config.watched_group_ids = sorted(self._my_group_ids)
            log.info("defaulted the watch list to the user's %d groups",
                     len(self._my_group_ids))

        self._render_groups()
        if self._my_group_ids is None:
            self.groups_status.setText(
                "{} groups in the account. Zendesk would not say which ones you belong "
                "to, so none are marked.".format(len(self._groups)))
        else:
            self.groups_status.setText(
                "{} groups in the account; you are a member of {}.".format(
                    len(self._groups), len(self._my_group_ids)))

    # --- appearance -------------------------------------------------------

    def _on_browse_animation(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an animation", str(assets_dir()), ANIMATION_FILTER)
        if not path:
            return
        chosen = Path(path)
        try:
            value = chosen.name if chosen.parent == assets_dir() else str(chosen)
        except OSError:
            value = str(chosen)
        if self.animation_combo.findData(value) < 0:
            self.animation_combo.addItem(chosen.stem, value)
        self._select_data(self.animation_combo, value)

    def _on_preview(self) -> None:
        overlay.preview(self._collect())

    def _on_reset_state(self) -> None:
        from .paths import state_path

        confirm = QMessageBox.question(
            self, "Forget tracked tickets",
            "Clear the remembered ticket history and start fresh?\n\n"
            "The app quietly re-reads recent Zendesk activity. Nothing will light up "
            "until a ticket changes after that.")
        if confirm != QMessageBox.Yes:
            return
        try:
            state_path().unlink(missing_ok=True)
            QMessageBox.information(self, "Done", "Ticket history cleared.")
        except OSError as exc:
            self._show_error("Could not delete the state file: {}".format(exc))

    # --- save -------------------------------------------------------------

    def _on_save(self) -> None:
        cfg = self._collect()
        if not cfg.subdomain:
            QMessageBox.warning(self, "Missing subdomain", "Enter your Zendesk subdomain.")
            return
        if not self._tokens.is_signed_in:
            confirm = QMessageBox.question(
                self, "Not signed in",
                "You are not signed in to Zendesk, so no warnings can appear.\n\n"
                "Save anyway?")
            if confirm != QMessageBox.Yes:
                return

        wanted_autostart = self.autostart_check.isChecked()
        if wanted_autostart != autostart.is_enabled():
            if not autostart.set_enabled(wanted_autostart):
                QMessageBox.warning(
                    self, "Autostart",
                    "Could not update the Windows startup entry. Check the log.")
        cfg.start_with_windows = autostart.is_enabled()

        cfg.save()
        self.saved.emit(cfg)
        self.accept()

    def show_connection_tab(self) -> None:
        self._tabs.setCurrentIndex(0)


def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _open_path(path: Path) -> None:
    try:
        if path.exists():
            os.startfile(str(path))  # noqa: S606 - Windows shell open
        else:
            os.startfile(str(path.parent))
    except OSError:
        subprocess.Popen(["explorer", str(path.parent)])
