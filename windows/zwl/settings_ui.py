"""The settings window reached from the tray icon."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTabWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from . import autostart, changelog, modes, overlay, sound
from .auth import AuthError, TokenStore
from .config import Config, DEFAULT_CORNER, normalise_subdomain
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
    signed_in = Signal(str, str)  # subdomain, client_id; the monitor must restart
    signed_out = Signal()

    def __init__(self, config: Config, tokens: TokenStore, parent=None):
        super().__init__(parent)
        self._config = Config.from_dict(config.to_dict())  # edit a copy
        self._tokens = tokens
        self._groups: list[dict[str, Any]] = []
        self._my_group_ids: set[int] | None = None
        self._threads: set[_CallThread] = set()
        self._busy: set[str] = set()
        self._loading = False
        self._editing_id = (self._config.day_modes[0].id
                            if self._config.day_modes else modes.BUILTIN_HELPDESK)

        self.setWindowTitle("Zendesk Warning Light – Settings")
        self.setMinimumWidth(600)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_connection_tab(), "Connection")
        self._tabs.addTab(self._build_modes_tab(), "Modes")
        self._tabs.addTab(self._build_schedule_tab(), "Schedule")
        self._tabs.addTab(self._build_appearance_tab(), "Appearance")
        self._tabs.addTab(self._build_general_tab(), "General")
        self._tabs.addTab(self._build_changelog_tab(), "Changelog")

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

    def _build_modes_tab(self) -> QWidget:
        """One screen per mode: its name, its rules, and the groups they apply to."""
        page = QWidget()
        layout = QVBoxLayout(page)

        picker = QHBoxLayout()
        picker.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumWidth(200)
        self.mode_combo.currentIndexChanged.connect(self._on_editing_mode_changed)
        picker.addWidget(self.mode_combo, 1)
        for text, slot in (("New\u2026", self._on_new_mode),
                           ("Duplicate", self._on_duplicate_mode),
                           ("Rename\u2026", self._on_rename_mode),
                           ("Delete", self._on_delete_mode)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            picker.addWidget(button)
        picker_wrap = QWidget()
        picker_wrap.setLayout(picker)
        layout.addWidget(picker_wrap)

        rules = QGroupBox("Warn me when\u2026")
        rules_layout = QVBoxLayout(rules)
        self.rule_checks: dict[str, QCheckBox] = {}
        for rule in modes.ALL_RULES:
            check = QCheckBox(modes.RULE_LABELS[rule])
            check.toggled.connect(self._on_rule_toggled)
            self.rule_checks[rule] = check
            rules_layout.addWidget(check)
        self.identity_label = QLabel("")
        self.identity_label.setWordWrap(True)
        self.identity_label.setStyleSheet("color:#888;")
        rules_layout.addWidget(self.identity_label)
        layout.addWidget(rules)

        self.mode_sound_check = QCheckBox("Play a sound when a warning appears")
        self.mode_sound_check.setToolTip(
            "Untick for a mode that should warn you silently. Sound must also be "
            "switched on in Appearance."
        )
        self.mode_sound_check.toggled.connect(self._on_rule_toggled)
        rules_layout.addWidget(self.mode_sound_check)
        self.mode_sound_hint = QLabel("")
        self.mode_sound_hint.setWordWrap(True)
        self.mode_sound_hint.setStyleSheet("color:#888;")
        rules_layout.addWidget(self.mode_sound_hint)

        self.groups_box = QGroupBox("Groups this mode watches")
        groups_layout = QVBoxLayout(self.groups_box)
        self.groups_hint = QLabel("")
        self.groups_hint.setWordWrap(True)
        groups_layout.addWidget(self.groups_hint)

        self.group_list = QListWidget()
        self.group_list.setAlternatingRowColors(True)
        groups_layout.addWidget(self.group_list, 1)

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
        groups_layout.addLayout(row)

        self.groups_status = QLabel("")
        self.groups_status.setWordWrap(True)
        self.groups_status.setStyleSheet("color:#888;")
        groups_layout.addWidget(self.groups_status)
        layout.addWidget(self.groups_box, 1)

        self.mode_summary = QLabel("")
        self.mode_summary.setWordWrap(True)
        layout.addWidget(self.mode_summary)
        return page

    # --- mode editing -----------------------------------------------------

    def _editing_mode(self):
        return self._config.find_mode(self._editing_id)

    def _rebuild_mode_combo(self) -> None:
        self._loading = True
        try:
            self.mode_combo.clear()
            for mode in self._config.day_modes:
                self.mode_combo.addItem(mode.name, mode.id)
            index = self.mode_combo.findData(self._editing_id)
            if index < 0:
                index = 0
                if self._config.day_modes:
                    self._editing_id = self._config.day_modes[0].id
            self.mode_combo.setCurrentIndex(index)
        finally:
            self._loading = False

    def _load_editing_mode(self) -> None:
        """Push the selected mode into the widgets."""
        mode = self._editing_mode()
        if mode is None:
            return
        self._loading = True
        try:
            for rule, check in self.rule_checks.items():
                check.setChecked(mode.rule_enabled(rule))
            self.mode_sound_check.setChecked(mode.play_sound)
        finally:
            self._loading = False
        self._render_groups()
        self._refresh_mode_summary()

    def _flush_editing_mode(self) -> None:
        """Read the widgets back into the selected mode."""
        mode = self._editing_mode()
        if mode is None or self._loading:
            return
        for rule, check in self.rule_checks.items():
            mode.set_rule(rule, check.isChecked())
        mode.play_sound = self.mode_sound_check.isChecked()
        mode.watched_group_ids = self._collect_ticked()

    def _on_editing_mode_changed(self) -> None:
        if self._loading:
            return
        self._flush_editing_mode()
        chosen = self.mode_combo.currentData()
        if chosen:
            self._editing_id = chosen
        self._load_editing_mode()

    def _on_rule_toggled(self) -> None:
        if self._loading:
            return
        self._flush_editing_mode()
        self._render_groups()
        self._refresh_mode_summary()

    def _refresh_sound_hint(self) -> None:
        if not hasattr(self, "mode_sound_hint") or not hasattr(self, "sound_check"):
            return
        self.mode_sound_hint.setText(
            "" if self.sound_check.isChecked()
            else "Sound is switched off in Appearance, so no mode will play one."
        )

    def _refresh_mode_summary(self) -> None:
        mode = self._editing_mode()
        if mode is None:
            return
        in_force = self._config.effective_mode()
        today = ""
        if in_force == mode.id:
            today = "  <b>This is the mode in force right now.</b>"
        elif self._config.mode == modes.SCHEDULE:
            today = "  Today is running <b>{}</b>.".format(
                _escape(self._config.mode_name(in_force)))
        self.mode_summary.setText(
            "<span style='color:#888'><b>{}</b> warns about: {}.{}</span>".format(
                _escape(mode.name), _escape(mode.summary()), today))

    def _next_mode_name(self, base: str) -> str:
        taken = {m.name for m in self._config.day_modes}
        if base not in taken:
            return base
        for n in range(2, 50):
            candidate = "{} {}".format(base, n)
            if candidate not in taken:
                return candidate
        return base

    def _add_mode(self, mode) -> None:
        self._config.day_modes.append(mode)
        self._editing_id = mode.id
        self._rebuild_mode_combo()
        self._rebuild_schedule_rows()
        self._load_editing_mode()

    def _on_new_mode(self) -> None:
        if len(self._config.day_modes) >= modes.MAX_MODES:
            QMessageBox.information(self, "Too many modes",
                                    "{} modes is the limit.".format(modes.MAX_MODES))
            return
        name, ok = QInputDialog.getText(self, "New mode", "Name for the new mode:",
                                        text=self._next_mode_name("New mode"))
        name = (name or "").strip()
        if not ok or not name:
            return
        self._flush_editing_mode()
        # Start from the user's own groups when we know them - a far more useful
        # default than "every group in the account".
        groups = sorted(self._my_group_ids) if self._my_group_ids else []
        self._add_mode(modes.DayMode(
            id=modes.new_id(name, self._config.mode_ids()),
            name=name, watched_group_ids=groups))

    def _on_duplicate_mode(self) -> None:
        source = self._editing_mode()
        if source is None:
            return
        if len(self._config.day_modes) >= modes.MAX_MODES:
            QMessageBox.information(self, "Too many modes",
                                    "{} modes is the limit.".format(modes.MAX_MODES))
            return
        self._flush_editing_mode()
        name = self._next_mode_name("{} (copy)".format(source.name))
        self._add_mode(source.copy(modes.new_id(name, self._config.mode_ids()), name))

    def _on_rename_mode(self) -> None:
        mode = self._editing_mode()
        if mode is None:
            return
        name, ok = QInputDialog.getText(self, "Rename mode", "New name:", text=mode.name)
        name = (name or "").strip()
        if not ok or not name:
            return
        mode.name = name
        self._rebuild_mode_combo()
        self._rebuild_schedule_rows()
        self._refresh_mode_summary()

    def _on_delete_mode(self) -> None:
        mode = self._editing_mode()
        if mode is None:
            return
        if len(self._config.day_modes) <= 1:
            QMessageBox.information(
                self, "Cannot delete", "You need at least one mode.")
            return

        remaining = [m for m in self._config.day_modes if m.id != mode.id]
        fallback = remaining[0]
        used_on = [modes.WEEKDAY_LABELS[k] for k, v in self._config.schedule.items()
                   if v == mode.id]
        warning = ""
        if used_on:
            warning = "\n\n{} in the weekly schedule will switch to {}.".format(
                ", ".join(used_on), fallback.name)

        confirm = QMessageBox.question(
            self, "Delete mode",
            "Delete the mode {}?{}".format(mode.name, warning))
        if confirm != QMessageBox.Yes:
            return

        self._config.day_modes = remaining
        for key, value in list(self._config.schedule.items()):
            if value == mode.id:
                self._config.schedule[key] = fallback.id
        if self._config.mode == mode.id:
            self._config.mode = fallback.id
        self._editing_id = fallback.id
        self._rebuild_mode_combo()
        self._rebuild_schedule_rows()
        self._load_editing_mode()

    def _build_schedule_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        intro = QLabel(modes.HOW_MODES_WORK)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)

        chooser = QGroupBox("Which mode to use")
        chooser_layout = QVBoxLayout(chooser)
        self.fixed_radio = QRadioButton("Use one mode every day:")
        self.fixed_radio.toggled.connect(self._on_mode_radio_changed)
        fixed_row = QHBoxLayout()
        fixed_row.addWidget(self.fixed_radio)
        self.fixed_combo = QComboBox()
        self.fixed_combo.currentIndexChanged.connect(self._refresh_today_label)
        fixed_row.addWidget(self.fixed_combo, 1)
        fixed_wrap = QWidget()
        fixed_wrap.setLayout(fixed_row)
        chooser_layout.addWidget(fixed_wrap)

        self.schedule_radio = QRadioButton("Follow the weekly schedule below")
        self.schedule_radio.toggled.connect(self._on_mode_radio_changed)
        chooser_layout.addWidget(self.schedule_radio)

        self.today_label = QLabel("")
        self.today_label.setWordWrap(True)
        chooser_layout.addWidget(self.today_label)
        layout.addWidget(chooser)

        self.week_box = QGroupBox("Weekly schedule")
        self.week_form = QFormLayout(self.week_box)
        self.day_combos: dict[str, QComboBox] = {}
        current_key = modes.weekday_key()
        for key in modes.WEEKDAY_KEYS:
            combo = QComboBox()
            combo.currentIndexChanged.connect(self._refresh_today_label)
            self.day_combos[key] = combo
            name = modes.WEEKDAY_LABELS[key]
            if key == current_key:
                name = "{}  (today)".format(name)
            self.week_form.addRow(name, combo)
        layout.addWidget(self.week_box)

        explain = QGroupBox("How modes work")
        explain_layout = QVBoxLayout(explain)
        for text in (modes.SEEDED_NOTE, modes.OFF_DESCRIPTION):
            row = QLabel(text)
            row.setWordWrap(True)
            row.setTextFormat(Qt.RichText)
            explain_layout.addWidget(row)
        layout.addWidget(explain)

        layout.addStretch(1)
        return page

    def _rebuild_schedule_rows(self) -> None:
        """Refresh every mode dropdown after modes are added, renamed or removed."""
        if not hasattr(self, "day_combos"):
            return
        self._loading = True
        try:
            for combo in list(self.day_combos.values()) + [self.fixed_combo]:
                previous = combo.currentData()
                combo.clear()
                for mode in self._config.day_modes:
                    combo.addItem(mode.name, mode.id)
                if combo is not self.fixed_combo:
                    combo.addItem(modes.OFF_LABEL, modes.OFF)
                index = combo.findData(previous)
                combo.setCurrentIndex(index if index >= 0 else 0)
            for key, combo in self.day_combos.items():
                wanted = self._config.schedule.get(key)
                index = combo.findData(wanted)
                if index >= 0:
                    combo.setCurrentIndex(index)
            if self._config.mode not in (modes.SCHEDULE, modes.OFF):
                index = self.fixed_combo.findData(self._config.mode)
                if index >= 0:
                    self.fixed_combo.setCurrentIndex(index)
        finally:
            self._loading = False
        self._refresh_today_label()

    def _on_mode_radio_changed(self) -> None:
        self.week_box.setEnabled(self.schedule_radio.isChecked())
        self.fixed_combo.setEnabled(self.fixed_radio.isChecked())
        self._refresh_today_label()

    def _selected_mode(self) -> str:
        if self.schedule_radio.isChecked():
            return modes.SCHEDULE
        return self.fixed_combo.currentData() or modes.BUILTIN_HELPDESK

    def _refresh_today_label(self) -> None:
        """Show what the current choices mean for today, right now."""
        if self._loading or not hasattr(self, "today_label"):
            return
        chosen = self._selected_mode()
        schedule = {key: combo.currentData() for key, combo in self.day_combos.items()}
        effective = modes.resolve(chosen, schedule, self._config.mode_ids())
        name = self._config.mode_name(effective)
        colour = "#8b93a1" if effective == modes.OFF else "#2e7d32"
        article = "an" if name[:1].upper() in "AEIOU" else "a"
        if chosen == modes.SCHEDULE:
            detail = "Today is {}, so the app is on {} <b>{}</b>.".format(
                modes.WEEKDAY_LABELS[modes.weekday_key()], article, _escape(name))
        else:
            detail = "Every day is {} <b>{}</b> until you change this.".format(
                article, _escape(name))
        self.today_label.setText("<span style='color:{}'>{}</span>".format(colour, detail))

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
        screens = QGuiApplication.screens()
        for screen in screens:
            geo = screen.geometry()
            self.screen_combo.addItem("{} – {}x{} at ({}, {})".format(
                screen.name(), geo.width(), geo.height(), geo.x(), geo.y()), screen.name())
        # Always offered, even with one monitor: the combo falls back to the first
        # item when it cannot find the saved value, so omitting this would silently
        # reset someone's choice the moment they undocked.
        self.screen_combo.addItem(
            "All screens ({} connected)".format(len(screens)) if len(screens) > 1
            else "All screens (1 connected)", overlay.ALL_SCREENS)
        form.addRow("Screen", self.screen_combo)

        screen_hint = QLabel(
            "A game or video in <i>exclusive</i> full screen owns its monitor and nothing "
            "can draw over it. Showing the warning on every screen means you still see it "
            "on another monitor — clicking any copy dismisses them all."
        )
        screen_hint.setWordWrap(True)
        screen_hint.setStyleSheet("color: #6b7280;")
        form.addRow("", screen_hint)

        self.corner_combo = QComboBox()
        for label, value in CORNERS:
            self.corner_combo.addItem(label, value)
        form.addRow("Corner", self.corner_combo)

        # Per-monitor placement. One row per connected screen, each free to differ
        # from the default above — a game filling one screen and the corner you
        # actually glance at on another are rarely the same corner.
        self.corner_by_screen_combos: dict[str, QComboBox] = {}
        if len(screens) > 1:
            for screen in screens:
                combo = QComboBox()
                combo.addItem("Same as above", "")
                for label, value in CORNERS:
                    combo.addItem(label, value)
                self.corner_by_screen_combos[screen.name()] = combo
                form.addRow("    on {}".format(screen.name()), combo)

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

        self.sound_check = QCheckBox("Play a sound when a warning appears")
        form.addRow("", self.sound_check)

        self.sound_combo = QComboBox()
        for value, label in sound.CHOICES:
            self.sound_combo.addItem(label, value)
        test_sound = QPushButton("Test")
        test_sound.clicked.connect(
            lambda: sound.play_alert(self.sound_combo.currentData()))
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.sound_combo, 1)
        sound_row.addWidget(test_sound)
        form.addRow("Sound", sound_row)
        self.sound_combo.setEnabled(False)
        self.sound_check.toggled.connect(self.sound_combo.setEnabled)
        self.sound_check.toggled.connect(self._refresh_sound_hint)

        preview_button = QPushButton("Preview for 4 seconds")
        preview_button.clicked.connect(self._on_preview)
        form.addRow("", preview_button)
        return page

    def _build_changelog_tab(self) -> QWidget:
        """What changed in each version. Read-only, and needs nothing from Zendesk."""
        from . import __version__

        page = QWidget()
        layout = QVBoxLayout(page)

        header = QLabel("You are running <b>version {}</b>.".format(__version__))
        header.setWordWrap(True)
        layout.addWidget(header)

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(changelog.to_html(__version__))
        # Start at the top: the newest release is the one worth reading.
        view.moveCursor(QTextCursor.Start)
        layout.addWidget(view, 1)

        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Polling is global rather than per mode: how often we ask is a different
        # question from what we care about when we do.
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

        self.autostart_check = QCheckBox("Start automatically when I sign in to Windows")
        layout.addWidget(self.autostart_check)
        self.autostart_note = QLabel("")
        self.autostart_note.setWordWrap(True)
        self.autostart_note.setStyleSheet("color:#888;")
        layout.addWidget(self.autostart_note)

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

        self.poll_spin.setValue(cfg.poll_seconds)

        self._loading = True
        try:
            if cfg.mode == modes.SCHEDULE:
                self.schedule_radio.setChecked(True)
            else:
                self.fixed_radio.setChecked(True)
        finally:
            self._loading = False
        self._rebuild_mode_combo()
        self._rebuild_schedule_rows()
        self._load_editing_mode()
        self._on_mode_radio_changed()

        self._populate_animations()
        self.height_spin.setValue(cfg.animation_height)
        self.opacity_spin.setValue(cfg.opacity)
        self._select_data(self.screen_combo, cfg.screen_name)
        self._select_data(self.corner_combo, cfg.corner)
        for name, combo in self.corner_by_screen_combos.items():
            self._select_data(combo, (cfg.corner_by_screen or {}).get(name, ""))
        self.margin_x_spin.setValue(cfg.margin_x)
        self.margin_y_spin.setValue(cfg.margin_y)
        self.caption_check.setChecked(cfg.show_caption)
        self.sound_check.setChecked(cfg.play_sound)
        self._select_data(self.sound_combo, cfg.sound_name)
        self.sound_combo.setEnabled(cfg.play_sound)
        self._refresh_sound_hint()

        self._refresh_autostart_state()
        self._refresh_account_state()
        self._render_groups()

    def _refresh_autostart_state(self) -> None:
        """Reflect a machine-wide login item instead of silently disagreeing with it."""
        self.autostart_check.setChecked(autostart.is_enabled())
        if autostart.is_machine_wide():
            # Set under HKLM by a machine-wide install; removing it needs admin
            # rights, so offering a tickbox that cannot work would be a lie.
            self.autostart_check.setEnabled(False)
            self.autostart_check.setToolTip(
                "Set for all users by your administrator.")
            self.autostart_note.setText(
                "Your administrator has set this for everyone on this machine, so it "
                "cannot be changed here.")
        else:
            self.autostart_check.setEnabled(True)
            self.autostart_check.setToolTip("")
            self.autostart_note.setText("")

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
                "The reopen rule watches tickets assigned to <b>{}</b>, in any "
                "group.".format(_escape(user.email)))
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
        mode = self._editing_mode()
        watched = set(mode.watched_group_ids) if mode else set()
        user = self._tokens.user
        restricted = bool(user.restricted_agent)

        # The reopen rule ignores groups, so a mode with no queue rule has no use
        # for this list. Grey it out rather than implying it does something.
        queue_watched = bool(mode and mode.watches_the_queue)
        self.groups_box.setEnabled(queue_watched)
        if not queue_watched:
            self.group_list.clear()
            self.groups_hint.setText(
                "This mode only warns about your own reopened tickets, which are not\n"
                "tied to a group. Tick one of the first two rules above to choose groups."
            )
            self.groups_status.setText("")
            return

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

        # Narrow to the user's own groups only when we actually know them. An
        # unknown or empty membership set used to filter the list down to nothing,
        # which left the tab blank with no explanation.
        narrow = restricted and bool(self._my_group_ids)

        if narrow:
            self.groups_hint.setText(
                "Your Zendesk role limits you to tickets in your own groups, so only "
                "those are listed. With nothing ticked, all of them are watched."
            )
        elif restricted:
            self.groups_hint.setText(
                "Your Zendesk role limits you to tickets in your own groups, but "
                "Zendesk would not confirm which, so every group is listed. Ticking "
                "one you are not in simply never fires. <b>Leaving everything "
                "unticked is the safe choice</b> \u2014 it watches exactly the tickets "
                "you can see."
            )
        else:
            self.groups_hint.setText(
                "Tick the groups to watch. With nothing ticked it watches <b>every</b> "
                "group. Groups you are not a member of are greyed out — they still work "
                "for you because your role can see all tickets."
            )

        shown = [g for g in self._groups
                 if not narrow or int(g["id"]) in self._my_group_ids]
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
        """Preserve the ticks of the mode being edited across a list rebuild."""
        self._flush_editing_mode()

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

        cfg.poll_seconds = self.poll_spin.value()

        self._flush_editing_mode()
        cfg.mode = self._selected_mode()
        cfg.schedule = {key: combo.currentData() or modes.OFF
                        for key, combo in self.day_combos.items()}

        cfg.animation = self.animation_combo.currentData() or cfg.animation
        cfg.animation_height = self.height_spin.value()
        cfg.opacity = self.opacity_spin.value()
        cfg.screen_name = self.screen_combo.currentData() or ""
        cfg.corner = self.corner_combo.currentData() or DEFAULT_CORNER
        # Overrides for monitors that are not connected right now are left alone:
        # this dialog can only speak for the screens it can see.
        for name, combo in self.corner_by_screen_combos.items():
            cfg.set_corner_for(name, combo.currentData() or "")
        cfg.margin_x = self.margin_x_spin.value()
        cfg.margin_y = self.margin_y_spin.value()
        cfg.show_caption = self.caption_check.isChecked()
        cfg.play_sound = self.sound_check.isChecked()
        cfg.sound_name = self.sound_combo.currentData() or sound.DEFAULT
        return cfg

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def _run_async(self, key: str, fn: Callable[[], Any],
                   on_ok: Callable[[Any], None], buttons: list[QPushButton]) -> None:
        """Run ``fn`` off the UI thread.

        Keyed per operation rather than globally. Signing in and loading groups are
        independent, and one shared busy flag meant the group load fired straight
        after a sign-in could be refused while the sign-in thread was still winding
        down - leaving a brand new install with an empty group list.
        """
        if key in self._busy:
            log.info("ignoring a duplicate %r request", key)
            return
        self._busy.add(key)
        for button in buttons:
            button.setEnabled(False)

        thread = _CallThread(fn, self)
        self._threads.add(thread)

        def finish() -> None:
            self._busy.discard(key)
            self._threads.discard(thread)
            for button in buttons:
                button.setEnabled(True)
            self._refresh_account_state()

        thread.succeeded.connect(on_ok)
        thread.succeeded.connect(lambda _=None: finish())
        thread.failed.connect(lambda msg: (finish(), self._show_error(msg)))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _show_error(self, message: str) -> None:
        # Errors can quote Zendesk's reply; never let Qt guess it is rich text.
        _plain_message(self, QMessageBox.Critical, "Zendesk", message)

    # --- sign in / out ----------------------------------------------------

    def _on_sign_in(self) -> None:
        typed = self.subdomain_edit.text().strip()
        subdomain = normalise_subdomain(typed)
        client_id = self.client_id_edit.text().strip()
        if not typed:
            QMessageBox.warning(self, "Missing subdomain", "Enter your Zendesk subdomain.")
            return
        if not subdomain:
            QMessageBox.warning(self, "Invalid subdomain", INVALID_SUBDOMAIN)
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
            "sign-in",
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
        self.signed_in.emit(self._config.subdomain, self._config.client_id)
        _plain_message(
            self, QMessageBox.Information, "Signed in",
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
            # Report a refusal rather than raising, so the tab can explain itself
            # instead of showing a modal over a blank list.
            payload: dict[str, Any] = {"all": [], "mine": None, "error": ""}
            try:
                payload["all"] = client.groups()
            except ZendeskError as exc:
                payload["error"] = str(exc)
                log.warning("could not list groups: %s", exc)
            if user_id:
                payload["mine"] = client.my_group_ids(user_id)
            return payload

        self._run_async("groups", fetch, self._on_groups_loaded,
                        [self.load_groups_button, self.only_mine_button])

    def _on_groups_loaded(self, payload: dict[str, Any]) -> None:
        self._groups = payload.get("all") or []
        mine = payload.get("mine")
        self._my_group_ids = set(mine) if mine else None
        error = payload.get("error") or ""

        # First run: default every mode that has no groups yet to the user's own,
        # which is far more useful than "every group in the account".
        if self._my_group_ids:
            for mode in self._config.day_modes:
                if not mode.watched_group_ids:
                    mode.watched_group_ids = sorted(self._my_group_ids)
                    log.info("defaulted mode %r to the user's %d group(s)",
                             mode.id, len(self._my_group_ids))

        self._load_editing_mode()

        if error:
            self.groups_status.setText(
                "<span style='color:#c62828'>Zendesk would not list the groups.</span> "
                "Leaving everything unticked still works \u2014 the app then watches "
                "every group your account can see.<br>"
                "<span style='color:#888'>{}</span>".format(_escape(error[:220])))
        elif self._my_group_ids is None:
            self.groups_status.setText(
                "{} groups in the account. Zendesk would not say which ones you "
                "belong to, so nothing is pre-ticked.".format(len(self._groups)))
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
        if not self._tokens.is_signed_in and not _valid_subdomain(cfg.subdomain):
            QMessageBox.warning(self, "Invalid subdomain", INVALID_SUBDOMAIN)
            return
        if not self._tokens.is_signed_in:
            confirm = QMessageBox.question(
                self, "Not signed in",
                "You are not signed in to Zendesk, so no warnings can appear.\n\n"
                "Save anyway?")
            if confirm != QMessageBox.Yes:
                return

        wanted_autostart = self.autostart_check.isChecked()
        if not autostart.is_machine_wide() and wanted_autostart != autostart.is_enabled():
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

    def show_schedule_tab(self) -> None:
        self._tabs.setCurrentIndex(2)

    def show_modes_tab(self) -> None:
        self._tabs.setCurrentIndex(1)


INVALID_SUBDOMAIN = ("Enter just the subdomain - the part before .zendesk.com - "
                     "using letters, digits and hyphens.")


def _valid_subdomain(subdomain: str) -> bool:
    # Same rule as config.normalise_subdomain: one DNS label, or the subdomain
    # would turn https://<it>.zendesk.com into an address on some other host.
    return bool(normalise_subdomain(subdomain))


def _plain_message(parent, icon, title: str, text: str) -> None:
    """A message box that shows ``text`` literally, never as HTML."""
    box = QMessageBox(icon, title, text, QMessageBox.Ok, parent)
    box.setTextFormat(Qt.PlainText)
    box.exec()


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
