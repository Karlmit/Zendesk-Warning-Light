"""Persistent user settings.

Deliberately holds no credentials and no identity: the OAuth refresh token and the
signed-in user live in ``tokens.json`` via :mod:`zwl.auth`, so this file stays safe
to read, copy and hand-edit.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from typing import Any

from . import modes, sound
from .auth import CLIENT_ID
from .paths import assets_dir, config_path

log = logging.getLogger(__name__)

DEFAULT_ANIMATION = "Warning-Cat.gif"

# The corners a warning may sit in. Vertical word first, so "bottom" and "right"
# can be tested with a substring the way overlay._reposition does.
VALID_CORNERS = (
    "top-left", "top-right", "bottom-left", "bottom-right",
)
DEFAULT_CORNER = "bottom-right"

# One DNS label. The subdomain is pasted into https://<it>.zendesk.com, so a dot,
# slash, '#', '@' or ':' could otherwise move the host away from zendesk.com.
_SUBDOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def normalise_subdomain(value: Any) -> str:
    """The bare subdomain from what someone typed, or "" when it is not valid."""
    text = str(value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    text = text.rstrip("/")
    if text.endswith(".zendesk.com"):
        text = text[:-len(".zendesk.com")]
    return text if _SUBDOMAIN_RE.fullmatch(text) else ""


@dataclass
class Config:
    # --- Connection -------------------------------------------------------
    subdomain: str = "yourcompany"
    client_id: str = CLIENT_ID

    # --- Day modes --------------------------------------------------------
    # Each mode owns its own alert rules and group selection, so "what fires
    # today" has exactly one answer. `mode` is a mode id, or "off", or
    # "schedule" (which defers to the weekday plan).
    mode: str = modes.BUILTIN_HELPDESK
    day_modes: list = field(default_factory=modes.seed_modes)
    schedule: dict = field(default_factory=modes.default_schedule)

    # --- Polling ----------------------------------------------------------
    poll_seconds: int = 30

    # --- Appearance -------------------------------------------------------
    animation: str = DEFAULT_ANIMATION  # bundled file name or an absolute path
    animation_height: int = 260
    opacity: float = 1.0
    screen_name: str = ""  # empty == primary screen, "*" == every screen
    corner: str = DEFAULT_CORNER
    # Per-monitor overrides, keyed by QScreen name. A monitor with no entry uses
    # `corner` above. Kept separate from `corner` so unplugging a screen cannot
    # lose its placement, and so one monitor can differ without disturbing the rest.
    corner_by_screen: dict = field(default_factory=dict)
    margin_x: int = 24
    margin_y: int = 24
    show_caption: bool = True
    # Off by default: a sound in an open office is something to opt into.
    play_sound: bool = False
    sound_name: str = "system"  # "system" or a file in assets/sounds

    # --- General ----------------------------------------------------------
    start_with_windows: bool = False
    enabled: bool = True
    paused_until: str = ""  # ISO-8601 UTC; empty when not paused

    # ------------------------------------------------------------------ #

    @property
    def base_url(self) -> str:
        # An invalid subdomain gives an address zwl.auth refuses to send tokens to.
        return "https://{}.zendesk.com".format(normalise_subdomain(self.subdomain))

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

    # --- day modes --------------------------------------------------------

    def mode_ids(self) -> set[str]:
        return {m.id for m in self.day_modes}

    def find_mode(self, mode_id: str):
        return next((m for m in self.day_modes if m.id == mode_id), None)

    def effective_mode(self, day=None) -> str:
        """The mode id in force for ``day``, or "off"."""
        return modes.resolve(self.mode, self.schedule, self.mode_ids(), day)

    def active_mode(self, day=None):
        """The DayMode in force, or None on an off day."""
        effective = self.effective_mode(day)
        return None if effective == modes.OFF else self.find_mode(effective)

    def mode_name(self, mode_id: str) -> str:
        if mode_id == modes.OFF:
            return modes.OFF_LABEL
        found = self.find_mode(mode_id)
        return found.name if found else mode_id

    def mode_label(self) -> str:
        """Human name of the effective mode, noting when it came from the plan."""
        name = self.mode_name(self.effective_mode())
        if self.mode == modes.SCHEDULE:
            return "Schedule \u2192 {}".format(name)
        return name

    def is_off_day(self) -> bool:
        """True when the app should make no Zendesk calls at all."""
        return self.effective_mode() == modes.OFF

    def rule_enabled(self, rule: str) -> bool:
        """Whether ``rule`` may fire right now, per the mode in force."""
        active = self.active_mode()
        return bool(active) and active.rule_enabled(rule)

    def sound_enabled(self) -> bool:
        """Whether a warning appearing right now should make a sound.

        The Appearance option is the master switch; the mode in force (which the
        weekday schedule picks) can then silence it for that day.
        """
        active = self.active_mode()
        return self.play_sound and (active is None or active.play_sound)

    @property
    def watched_group_ids(self) -> list[int]:
        """Groups the mode in force watches. Empty means every visible group."""
        active = self.active_mode()
        return list(active.watched_group_ids) if active else []

    # --- pause handling ---------------------------------------------------

    def pause_expiry(self) -> datetime | None:
        if not self.paused_until:
            return None
        try:
            value = datetime.fromisoformat(self.paused_until)
        except ValueError:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def corner_for(self, screen_name: str) -> str:
        """Where the warning sits on a given monitor.

        Falls back to the shared corner, so a new monitor behaves like the rest
        until someone says otherwise.
        """
        override = (self.corner_by_screen or {}).get(screen_name or "")
        if override in VALID_CORNERS:
            return override
        return self.corner if self.corner in VALID_CORNERS else DEFAULT_CORNER

    def set_corner_for(self, screen_name: str, corner: str) -> None:
        """Pin a monitor to a corner, or pass "" to let it follow the default."""
        if not screen_name:
            return
        if corner in VALID_CORNERS:
            self.corner_by_screen[screen_name] = corner
        else:
            self.corner_by_screen.pop(screen_name, None)

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
        data = asdict(self)
        # asdict cannot see inside DayMode instances stored in a plain list.
        data["day_modes"] = [m.to_dict() for m in self.day_modes]
        return data

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

        subdomain = normalise_subdomain(cfg.subdomain)
        if cfg.subdomain and not subdomain:
            log.warning("ignoring invalid Zendesk subdomain %r", cfg.subdomain)
        cfg.subdomain = subdomain

        cfg.poll_seconds = max(10, int(cfg.poll_seconds))
        cfg.animation_height = max(80, min(900, int(cfg.animation_height)))
        cfg.opacity = max(0.2, min(1.0, float(cfg.opacity)))
        if cfg.corner not in VALID_CORNERS:
            log.info("unknown corner %r; using %r", cfg.corner, DEFAULT_CORNER)
            cfg.corner = DEFAULT_CORNER
        # Keep only entries that still mean something. Names of monitors that are
        # not connected right now are deliberately kept: docking and undocking must
        # not throw away where someone put the warning.
        cfg.corner_by_screen = {
            str(name): value
            for name, value in (cfg.corner_by_screen or {}).items()
            if str(name) and value in VALID_CORNERS
        }
        if cfg.sound_name not in sound.VALID:
            cfg.sound_name = sound.DEFAULT
        if not cfg.client_id:
            cfg.client_id = CLIENT_ID

        # v2.1 kept one global set of rules and groups. Fold them into the two
        # seeded modes so behaviour carries over untouched; the old weekday
        # values ("helpdesk"/"focus"/"off") are already valid mode ids.
        if "day_modes" not in data:
            legacy_rules = {
                modes.RULE_NEW_UNASSIGNED: bool(data.get("alert_on_new_unassigned", True)),
                modes.RULE_BECAME_UNASSIGNED: bool(data.get("alert_on_became_unassigned", True)),
                modes.RULE_PENDING_TO_OPEN: bool(data.get("alert_on_pending_to_open", True)),
            }
            legacy_groups = []
            for value in data.get("watched_group_ids") or []:
                try:
                    legacy_groups.append(int(value))
                except (TypeError, ValueError):
                    continue
            cfg.day_modes = modes.seed_modes(legacy_rules, legacy_groups)
            log.info("migrated global rules and %d group(s) into the seeded modes",
                     len(legacy_groups))
        else:
            cfg.day_modes = modes.sanitise_modes(cfg.day_modes)

        ids = cfg.mode_ids()
        fallback = modes.BUILTIN_HELPDESK if modes.BUILTIN_HELPDESK in ids \
            else sorted(ids)[0]
        if cfg.mode not in ids | {modes.OFF, modes.SCHEDULE}:
            log.info("unknown mode %r; falling back to %r", cfg.mode, fallback)
            cfg.mode = fallback
        cfg.schedule = modes.sanitise_schedule(cfg.schedule, ids, fallback)
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

    try:
        cfg = Config.from_dict(raw)
    except Exception:
        # Wrong types (a string poll interval, a list where a dict belongs...) must
        # not stop the app from starting.
        log.exception("invalid settings in %s - falling back to defaults", path)
        return Config()

    # Rewrite the file once when it is out of step with this version, so retired v1
    # keys do not linger and newly added settings are visible and hand-editable
    # rather than silently defaulted on every load.
    legacy = {"client_secret_enc", "my_user_id", "my_email",
              "watched_group_ids", "alert_on_new_unassigned",
              "alert_on_became_unassigned", "alert_on_pending_to_open"} & set(raw)
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
