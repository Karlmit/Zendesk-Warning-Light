"""Day modes: how much the warning light is allowed to interrupt you.

A mode decides which alert rules may fire. The per-rule tickboxes on the Alerts tab
still apply *within* a mode, so a mode can only ever narrow what you asked for -
never widen it. That keeps one source of truth per concern: the mode says what kind
of day it is, the tickboxes say what you care about on a full day.

``Config.mode`` holds one of :data:`HELPDESK`, :data:`FOCUS` or :data:`SCHEDULE`.
:data:`SCHEDULE` is never an *effective* mode - it defers to the weekday plan, which
resolves to Helpdesk, Focus or :data:`OFF`.
"""

from __future__ import annotations

from datetime import date

# --- rule keys (these deliberately match monitor.REASON_* values) ---------
RULE_NEW_UNASSIGNED = "new_unassigned"
RULE_BECAME_UNASSIGNED = "became_unassigned"
RULE_PENDING_TO_OPEN = "pending_to_open"
ALL_RULES = (RULE_NEW_UNASSIGNED, RULE_BECAME_UNASSIGNED, RULE_PENDING_TO_OPEN)

# --- modes ----------------------------------------------------------------
HELPDESK = "helpdesk"
FOCUS = "focus"
OFF = "off"
SCHEDULE = "schedule"

#: What the user can pick as a standing mode in the tray.
SELECTABLE = (HELPDESK, FOCUS, SCHEDULE)

#: What a day can actually resolve to.
EFFECTIVE = (HELPDESK, FOCUS, OFF)

#: What a weekday in the schedule can be set to.
DAY_CHOICES = (HELPDESK, FOCUS, OFF)

LABELS = {
    HELPDESK: "Helpdesk Day",
    FOCUS: "Focus Day",
    OFF: "Off Day",
    SCHEDULE: "Schedule",
}

#: Which rules each effective mode permits.
ALLOWED_RULES = {
    HELPDESK: frozenset(ALL_RULES),
    FOCUS: frozenset({RULE_PENDING_TO_OPEN}),
    OFF: frozenset(),
}

#: Shown on the Schedule tab. Keep these in step with ALLOWED_RULES above.
DESCRIPTIONS = {
    HELPDESK: (
        "You are on the queue. Every rule you have ticked can fire: new unassigned "
        "tickets, tickets handed back to the queue, and your own tickets reopening."
    ),
    FOCUS: (
        "You are heads-down on something else. Only <b>your own tickets reopening</b> "
        "can interrupt you — unassigned tickets in the queue stay silent, because "
        "someone else is covering. Zendesk is still polled, so nothing is missed once "
        "the day ends."
    ),
    OFF: (
        "Nothing at all. The app makes <b>no Zendesk API calls</b> and shows no "
        "warnings. When the next working day starts it quietly catches up on what "
        "changed while you were away, so you do not arrive to a wall of alerts."
    ),
}

# --- weekdays -------------------------------------------------------------
#: Indexed by ``date.weekday()`` - Monday is 0.
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

WEEKDAY_LABELS = {
    "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday",
    "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def default_schedule() -> dict[str, str]:
    """Working week on the queue, weekend off."""
    return {key: (OFF if key in ("sat", "sun") else HELPDESK) for key in WEEKDAY_KEYS}


def weekday_key(day: date | None = None) -> str:
    return WEEKDAY_KEYS[(day or date.today()).weekday()]


def resolve(mode: str, schedule: dict[str, str], day: date | None = None) -> str:
    """Turn a configured mode into the effective mode for ``day``."""
    if mode == SCHEDULE:
        chosen = (schedule or {}).get(weekday_key(day), HELPDESK)
        return chosen if chosen in EFFECTIVE else HELPDESK
    return mode if mode in (HELPDESK, FOCUS) else HELPDESK


def rule_allowed(effective_mode: str, rule: str) -> bool:
    return rule in ALLOWED_RULES.get(effective_mode, ALLOWED_RULES[HELPDESK])


def label(mode: str) -> str:
    return LABELS.get(mode, mode)


def sanitise_schedule(raw: dict | None) -> dict[str, str]:
    """Fill in any missing or bogus weekday with the default for that day."""
    base = default_schedule()
    for key, value in (raw or {}).items():
        if key in base and value in DAY_CHOICES:
            base[key] = value
    return base
