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

from .auth import CLIENT_ID
from .paths import assets_dir, config_path

log = logging.getLogger(__name__)

DEFAULT_ANIMATION = "Warning-Cat.gif"


@dataclass
class Config:
    # --- Connection -------------------------------------------------------
    subdomain: str = "yourcompany"
    client_id: str = CLIENT_ID

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
        return self.enabled and not self.is_paused()

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

    # Rewrite a v1 file once, so the retired client secret does not linger on disk
    # and the migration notice is not logged on every start.
    legacy = {"client_secret_enc", "my_user_id", "my_email"} & set(raw)
    if legacy:
        log.info("removing retired v1 settings from config.json: %s",
                 ", ".join(sorted(legacy)))
        try:
            cfg.save()
        except Exception:
            log.exception("could not rewrite %s", path)
    return cfg
