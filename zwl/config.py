"""Persistent user settings.

Deliberately holds no credentials and no identity: the OAuth refresh token and the
signed-in user live in ``tokens.json`` via :mod:`zwl.auth`, so this file stays safe
to read, copy and hand-edit.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import Any

from . import modes
from .auth import CLIENT_ID
from .paths import assets_dir, config_path

log = logging.getLogger(__name__)

DEFAULT_ANIMATION = "Warning-Cat.gif"


@dataclass
class Config:
    # --- Connection -------------------------------------------------------
    subdomain: str = "yourcompany"
    client_id: str = CLIENT_ID

    # --- Day mode ---------------------------------------------------------
    # "helpdesk" | "focus" | "schedule". Helpdesk is the post-install default.
    mode: str = modes.HELPDESK
    schedule: dict = field(default_factory=modes.default_schedule)

    # --- What to watch ----------------------------------------------------
    watched_group_ids: list[int] = field(default_factory=list)
    alert_on_new_unassigned: bool = True
    alert_on_became_unassigned: bool = True
    alert_on_pending_to_open: bool = True
    poll_seconds: int = 30

    # --- Appearance -------------------------------------------------------
    animation: str = DEFAULT_ANIMATION  # bundled file name or an absolute path
    animation_height: int = 260
    opacity: float = 1.0
    screen_name: str = ""  # empty == primary screen
    corner: str = "bottom-right"
    margin_x: int = 24
    margin_y: int = 24
    show_caption: bool = True

    # --- General ----------------------------------------------------------
    start_with_windows: bool = False
    enabled: bool = True
    paused_until: str = ""  # ISO-8601 UTC; empty when not paused

    # ------------------------------------------------------------------ #

    @property
    def base_url(self) -> str:
        return "https://{}.zendesk.com".format(self.subdomain.strip())

    def animation_path(self) -> str:
        """Resolve :attr:`animation` to a concrete file path."""
        from pathlib import Path

        candidate = Path(self.animation)
        if candidate.is_absolute():
            return str(candidate)
        return str(assets_dir() / self.animation)

    def is_configured(self) -> bool:
        """Whether we know *where* to connect. Signing in is tracked separately."""
        return bool(self.subdomain and self.client_id)

    # --- day mode ---------------------------------------------------------

    def effective_mode(self, day=None) -> str:
        """Today's mode: "helpdesk", "focus" or "off"."""
        return modes.resolve(self.mode, self.schedule, day)

    def mode_label(self) -> str:
        """Human name of the effective mode, noting when it came from the plan."""
        effective = self.effective_mode()
        if self.mode == modes.SCHEDULE:
            return "Schedule → {}".format(modes.label(effective))
        return modes.label(effective)

    def is_off_day(self) -> bool:
        """True when the app should make no Zendesk calls at all."""
        return self.effective_mode() == modes.OFF

    def rule_enabled(self, rule: str) -> bool:
        """A rule fires only if you ticked it *and* today's mode permits it."""
        ticked = {
            modes.RULE_NEW_UNASSIGNED: self.alert_on_new_unassigned,
            modes.RULE_BECAME_UNASSIGNED: self.alert_on_became_unassigned,
            modes.RULE_PENDING_TO_OPEN: self.alert_on_pending_to_open,
        }.get(rule, False)
        return bool(ticked) and modes.rule_allowed(self.effective_mode(), rule)

    # --- pause handling ---------------------------------------------------

    def pause_expiry(self) -> datetime | None:
        if not self.paused_until:
            return None
        try:
            value = datetime.fromisoformat(self.paused_until)
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def is_paused(self) -> bool:
        """True when alerts are suppressed right now (expired pauses clear themselves)."""
        expiry = self.pause_expiry()
        if expiry is None:
            return False
        if datetime.now(timezone.utc) >= expiry:
            self.paused_until = ""
            return False
        return True

    def is_active(self) -> bool:
        """Whether warnings may appear right now."""
        return self.enabled and not self.is_paused() and not self.is_off_day()

    # --- persistence ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        # Unknown keys are dropped, which also migrates a v1 config: its
        # client_secret_enc / my_user_id / my_email entries simply fall away.
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})

        # A stored client_secret is the marker of a v1 install. Its client_id names
        # the old *confidential* client, which cannot do the PKCE sign-in, so move
        # the user onto the public client instead of letting sign-in fail.
        if "client_secret_enc" in data and cfg.client_id != CLIENT_ID:
            log.info("migrating v1 OAuth client %r -> %r", cfg.client_id, CLIENT_ID)
            cfg.client_id = CLIENT_ID

        cfg.watched_group_ids = [int(g) for g in cfg.watched_group_ids]
        cfg.poll_seconds = max(10, int(cfg.poll_seconds))
        cfg.animation_height = max(80, min(900, int(cfg.animation_height)))
        cfg.opacity = max(0.2, min(1.0, float(cfg.opacity)))
        if not cfg.client_id:
            cfg.client_id = CLIENT_ID
        if cfg.mode not in modes.SELECTABLE:
            cfg.mode = modes.HELPDESK
        cfg.schedule = modes.sanitise_schedule(cfg.schedule)
        return cfg

    def save(self) -> None:
        path = config_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)
        log.debug("config saved to %s", path)


def load() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.exception("could not read %s - falling back to defaults", path)
        return Config()

    cfg = Config.from_dict(raw)

    # Rewrite the file once when it is out of step with this version, so retired v1
    # keys do not linger and newly added settings are visible and hand-editable
    # rather than silently defaulted on every load.
    legacy = {"client_secret_enc", "my_user_id", "my_email"} & set(raw)
    missing = {f.name for f in fields(Config)} - set(raw)
    if legacy or missing:
        if legacy:
            log.info("removing retired settings from config.json: %s",
                     ", ".join(sorted(legacy)))
        if missing:
            log.info("adding new settings to config.json: %s", ", ".join(sorted(missing)))
        try:
            cfg.save()
        except Exception:
            log.exception("could not rewrite %s", path)
    return cfg
