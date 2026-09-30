"""Day modes: named bundles of "what may interrupt me, and from which groups".

A mode owns its alert rules *and* its group selection, so there is exactly one place
to look to answer "what fires today". Two modes are seeded on first run - Helpdesk
Day and Focus Day - but both are ordinary editable modes, and you can add your own.

:data:`OFF` is the one reserved, non-editable mode. It is not in the mode list
because there is nothing to configure: it fires nothing and makes no API calls.

``Config.mode`` holds a mode id, or :data:`OFF`, or :data:`SCHEDULE`.
:data:`SCHEDULE` defers to the weekday plan, which maps each day to a mode id or
:data:`OFF`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# --- rule keys (these deliberately match monitor.REASON_* values) ---------
RULE_NEW_UNASSIGNED = "new_unassigned"
RULE_BECAME_UNASSIGNED = "became_unassigned"
RULE_PENDING_TO_OPEN = "pending_to_open"
ALL_RULES = (RULE_NEW_UNASSIGNED, RULE_BECAME_UNASSIGNED, RULE_PENDING_TO_OPEN)

#: Rules that care which groups are watched. The reopen rule deliberately does
#: not: it is about your own tickets wherever they live.
GROUP_SENSITIVE_RULES = (RULE_NEW_UNASSIGNED, RULE_BECAME_UNASSIGNED)

RULE_LABELS = {
    RULE_NEW_UNASSIGNED: "A new ticket arrives with no assignee",
    RULE_BECAME_UNASSIGNED: "An existing ticket is handed back to the queue",
    RULE_PENDING_TO_OPEN: "A ticket assigned to me goes from pending back to open",
}

# --- reserved ids ---------------------------------------------------------
OFF = "off"
SCHEDULE = "schedule"
RESERVED_IDS = (OFF, SCHEDULE)

BUILTIN_HELPDESK = "helpdesk"
BUILTIN_FOCUS = "focus"

OFF_LABEL = "Off Day"
MAX_MODES = 20


@dataclass
class DayMode:
    """One named combination of alert rules and watched groups."""

    id: str
    name: str
    alert_on_new_unassigned: bool = True
    alert_on_became_unassigned: bool = True
    alert_on_pending_to_open: bool = True
    watched_group_ids: list[int] = field(default_factory=list)

    # ---- rules -------------------------------------------------------- #

    def rule_enabled(self, rule: str) -> bool:
        return bool({
            RULE_NEW_UNASSIGNED: self.alert_on_new_unassigned,
            RULE_BECAME_UNASSIGNED: self.alert_on_became_unassigned,
            RULE_PENDING_TO_OPEN: self.alert_on_pending_to_open,
        }.get(rule, False))

    def set_rule(self, rule: str, value: bool) -> None:
        attr = {
            RULE_NEW_UNASSIGNED: "alert_on_new_unassigned",
            RULE_BECAME_UNASSIGNED: "alert_on_became_unassigned",
            RULE_PENDING_TO_OPEN: "alert_on_pending_to_open",
        }.get(rule)
        if attr:
            setattr(self, attr, bool(value))

    @property
    def watches_the_queue(self) -> bool:
        """True when any rule that cares about groups is on."""
        return any(self.rule_enabled(r) for r in GROUP_SENSITIVE_RULES)

    @property
    def is_silent(self) -> bool:
        return not any(self.rule_enabled(r) for r in ALL_RULES)

    def summary(self) -> str:
        """One short line describing what this mode does."""
        if self.is_silent:
            return "nothing (no rules ticked)"
        parts = []
        if self.watches_the_queue:
            count = len(self.watched_group_ids)
            if not count:
                where = "every visible group"
            else:
                where = "{} group{}".format(count, "" if count == 1 else "s")
            parts.append("the queue in " + where)
        if self.rule_enabled(RULE_PENDING_TO_OPEN):
            parts.append("my reopened tickets")
        return " + ".join(parts)

    # ---- persistence -------------------------------------------------- #

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "alert_on_new_unassigned": self.alert_on_new_unassigned,
            "alert_on_became_unassigned": self.alert_on_became_unassigned,
            "alert_on_pending_to_open": self.alert_on_pending_to_open,
            "watched_group_ids": [int(g) for g in self.watched_group_ids],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DayMode | None":
        mode_id = str(raw.get("id") or "").strip()
        if not mode_id or mode_id in RESERVED_IDS:
            return None
        try:
            groups = [int(g) for g in raw.get("watched_group_ids") or []]
        except (TypeError, ValueError):
            groups = []
        return cls(
            id=mode_id,
            name=str(raw.get("name") or mode_id).strip() or mode_id,
            alert_on_new_unassigned=bool(raw.get("alert_on_new_unassigned", True)),
            alert_on_became_unassigned=bool(raw.get("alert_on_became_unassigned", True)),
            alert_on_pending_to_open=bool(raw.get("alert_on_pending_to_open", True)),
            watched_group_ids=groups,
        )

    def copy(self, new_id: str, new_name: str) -> "DayMode":
        clone = DayMode.from_dict(self.to_dict())
        assert clone is not None
        clone.id = new_id
        clone.name = new_name
        return clone


# ---------------------------------------------------------------------- #
# ids
# ---------------------------------------------------------------------- #

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug[:32] or "mode"


def new_id(name: str, taken: set[str]) -> str:
    """A stable, readable, unique id for a new mode."""
    base = slugify(name)
    if base not in taken and base not in RESERVED_IDS:
        return base
    for _ in range(20):
        candidate = "{}-{}".format(base, uuid.uuid4().hex[:4])
        if candidate not in taken and candidate not in RESERVED_IDS:
            return candidate
    return "mode-" + uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------- #
# seeding and repair
# ---------------------------------------------------------------------- #

def seed_modes(rules: dict[str, bool] | None = None,
               groups: list[int] | None = None) -> list[DayMode]:
    """The two starter modes, optionally carrying settings forward from v2.1."""
    rules = rules or {}
    groups = list(groups or [])
    return [
        DayMode(
            id=BUILTIN_HELPDESK,
            name="Helpdesk Day",
            alert_on_new_unassigned=rules.get(RULE_NEW_UNASSIGNED, True),
            alert_on_became_unassigned=rules.get(RULE_BECAME_UNASSIGNED, True),
            alert_on_pending_to_open=rules.get(RULE_PENDING_TO_OPEN, True),
            watched_group_ids=list(groups),
        ),
        DayMode(
            id=BUILTIN_FOCUS,
            name="Focus Day",
            alert_on_new_unassigned=False,
            alert_on_became_unassigned=False,
            alert_on_pending_to_open=rules.get(RULE_PENDING_TO_OPEN, True),
            watched_group_ids=list(groups),
        ),
    ]


def sanitise_modes(raw: Any) -> list[DayMode]:
    """Turn stored JSON into a usable, de-duplicated, non-empty mode list."""
    out: list[DayMode] = []
    seen: set[str] = set()
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        mode = DayMode.from_dict(entry)
        if mode is None or mode.id in seen:
            continue
        seen.add(mode.id)
        out.append(mode)
        if len(out) >= MAX_MODES:
            break
    return out or seed_modes()


def default_schedule(mode_id: str = BUILTIN_HELPDESK) -> dict[str, str]:
    """Working week on the given mode, weekend off."""
    return {key: (OFF if key in ("sat", "sun") else mode_id) for key in WEEKDAY_KEYS}


def sanitise_schedule(raw: Any, valid_ids: set[str],
                      fallback: str = BUILTIN_HELPDESK) -> dict[str, str]:
    """Every weekday maps to a real mode id or OFF; anything else is repaired."""
    allowed = set(valid_ids) | {OFF}
    if fallback not in allowed:
        fallback = next(iter(sorted(valid_ids)), OFF)
    base = default_schedule(fallback)
    for key, value in (raw or {}).items():
        if key in base and value in allowed:
            base[key] = value
    return base


# ---------------------------------------------------------------------- #
# weekdays
# ---------------------------------------------------------------------- #

#: Indexed by ``date.weekday()`` - Monday is 0.
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

WEEKDAY_LABELS = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
    "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def weekday_key(day: date | None = None) -> str:
    return WEEKDAY_KEYS[(day or date.today()).weekday()]


def resolve(mode: str, schedule: dict[str, str], valid_ids: set[str],
            day: date | None = None) -> str:
    """Turn a configured mode into the effective mode id (or OFF) for ``day``."""
    allowed = set(valid_ids) | {OFF}
    fallback = next(iter(sorted(valid_ids)), OFF)
    if mode == SCHEDULE:
        chosen = (schedule or {}).get(weekday_key(day), fallback)
        return chosen if chosen in allowed else fallback
    return mode if mode in allowed else fallback


# ---------------------------------------------------------------------- #
# help text for the Schedule tab
# ---------------------------------------------------------------------- #

HOW_MODES_WORK = (
    "A <b>mode</b> is a named set of alert rules plus the groups they apply to. "
    "Pick one to use every day, or set a weekly plan below and let it change on "
    "its own. Edit modes, or add your own, on the <b>Modes</b> tab."
)

OFF_DESCRIPTION = (
    "<b>Off Day</b> — nothing fires and the app makes <b>no Zendesk API calls</b> "
    "at all. When the next working day starts it quietly catches up on what changed "
    "while you were away, so you do not arrive to a wall of alerts."
)

SEEDED_NOTE = (
    "<b>Helpdesk Day</b> and <b>Focus Day</b> are just the two modes you start with "
    "— rename, retune or delete them like any other. Focus Day ships with only "
    "the reopen rule, so the queue stays quiet while someone else covers it."
)
