"""Covers day modes: resolution, the rule mask, and the no-API-calls off day.

No network - an exploding client proves an off day never reaches Zendesk.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from zwl import auth as auth_module  # noqa: E402
from zwl import modes  # noqa: E402
from zwl import monitor as monitor_module  # noqa: E402
from zwl.auth import SignedInUser, TokenStore  # noqa: E402
from zwl.config import Config  # noqa: E402
from zwl.monitor import (  # noqa: E402
    REASON_BECAME_UNASSIGNED, REASON_NEW_UNASSIGNED, REASON_PENDING_TO_OPEN, Monitor,
)

ME = 999
WATCHED = 1

MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)
SATURDAY = date(2026, 9, 12)
SUNDAY = date(2026, 9, 13)

_tmp = tempfile.TemporaryDirectory()
monitor_module.state_path = lambda: Path(_tmp.name) / "state.json"
auth_module.tokens_path = lambda: Path(_tmp.name) / "tokens.json"

_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  (got {!r}, expected {!r})".format(label, actual, expected))
        _failures.append(label)


def ticket(tid: int, status: str, assignee=None, group=WATCHED) -> dict:
    return {"id": tid, "status": status, "assignee_id": assignee,
            "group_id": group, "subject": "t{}".format(tid)}


class ExplodingClient:
    """Any attribute touched means we made a Zendesk call we should not have."""

    def __init__(self):
        self.touched: list[str] = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError("Zendesk was contacted on an off day: .{}()".format(name))


def make_monitor(**overrides) -> Monitor:
    cfg = Config(subdomain="example", watched_group_ids=[WATCHED])
    for key, value in overrides.items():
        setattr(cfg, key, value)
    tokens = TokenStore(base_url="https://example.zendesk.com")
    tokens._refresh_token = "rt"
    tokens.user = SignedInUser(id=ME, name="T", email="t@x", role="agent")
    mon = Monitor(cfg, tokens)
    mon._groups = {WATCHED: "Watched group"}
    return mon


def reasons(mon: Monitor) -> dict[int, str]:
    return {tid: a.reason for tid, a in mon._alerts.items()}


def run() -> None:
    print("\n1. Fixed modes resolve to themselves")
    check("helpdesk", modes.resolve(modes.HELPDESK, {}, MONDAY), modes.HELPDESK)
    check("focus", modes.resolve(modes.FOCUS, {}, MONDAY), modes.FOCUS)
    check("an unknown mode falls back to helpdesk",
          modes.resolve("nonsense", {}, MONDAY), modes.HELPDESK)

    print("\n2. Schedule mode reads the weekday plan")
    plan = modes.default_schedule()
    check("Monday is a helpdesk day by default",
          modes.resolve(modes.SCHEDULE, plan, MONDAY), modes.HELPDESK)
    check("Saturday is off by default",
          modes.resolve(modes.SCHEDULE, plan, SATURDAY), modes.OFF)
    check("Sunday is off by default",
          modes.resolve(modes.SCHEDULE, plan, SUNDAY), modes.OFF)
    plan["tue"] = modes.FOCUS
    check("Tuesday follows the plan", modes.resolve(modes.SCHEDULE, plan, TUESDAY), modes.FOCUS)
    check("a bogus plan value falls back to helpdesk",
          modes.resolve(modes.SCHEDULE, {"mon": "banana"}, MONDAY), modes.HELPDESK)

    print("\n3. Weekday keys line up with date.weekday()")
    check("Monday", modes.weekday_key(MONDAY), "mon")
    check("Saturday", modes.weekday_key(SATURDAY), "sat")
    check("Sunday", modes.weekday_key(SUNDAY), "sun")

    print("\n4. sanitise_schedule repairs a partial or corrupt plan")
    fixed = modes.sanitise_schedule({"mon": modes.FOCUS, "junk": modes.OFF, "tue": "bad"})
    check("all seven days present", sorted(fixed) == sorted(modes.WEEKDAY_KEYS), True)
    check("valid entry kept", fixed["mon"], modes.FOCUS)
    check("invalid entry defaulted", fixed["tue"], modes.HELPDESK)
    check("unknown key dropped", "junk" in fixed, False)

    print("\n5. The rule mask per mode")
    check("helpdesk allows all three",
          {r for r in modes.ALL_RULES if modes.rule_allowed(modes.HELPDESK, r)},
          set(modes.ALL_RULES))
    check("focus allows only the reopen rule",
          {r for r in modes.ALL_RULES if modes.rule_allowed(modes.FOCUS, r)},
          {modes.RULE_PENDING_TO_OPEN})
    check("off allows nothing",
          {r for r in modes.ALL_RULES if modes.rule_allowed(modes.OFF, r)}, set())

    print("\n6. Config.rule_enabled masks ticks with the mode")
    cfg = Config(mode=modes.HELPDESK)
    check("helpdesk + all ticked -> all on",
          [cfg.rule_enabled(r) for r in modes.ALL_RULES], [True, True, True])
    cfg.mode = modes.FOCUS
    check("focus suppresses the queue rules even when ticked",
          [cfg.rule_enabled(r) for r in modes.ALL_RULES], [False, False, True])
    cfg.alert_on_pending_to_open = False
    check("a mode never widens a rule you untick",
          cfg.rule_enabled(modes.RULE_PENDING_TO_OPEN), False)

    print("\n7. Off days report themselves as inactive")
    cfg = Config(mode=modes.SCHEDULE, schedule={k: modes.OFF for k in modes.WEEKDAY_KEYS})
    check("is_off_day", cfg.is_off_day(), True)
    check("is_active is False", cfg.is_active(), False)
    check("label names the source", cfg.mode_label(), "Schedule → Off Day")
    cfg.mode = modes.FOCUS
    check("a fixed mode labels plainly", cfg.mode_label(), "Focus Day")
    check("and is active again", cfg.is_active(), True)

    print("\n8. Defaults: a fresh install is a Helpdesk Day")
    fresh = Config()
    check("mode", fresh.mode, modes.HELPDESK)
    check("effective", fresh.effective_mode(), modes.HELPDESK)
    check("schedule pre-filled Mon-Fri helpdesk",
          [fresh.schedule[k] for k in ("mon", "tue", "wed", "thu", "fri")],
          [modes.HELPDESK] * 5)

    print("\n9. Focus Day: queue alerts suppressed, reopen still fires")
    mon = make_monitor(mode=modes.FOCUS)
    mon._process_ticket(ticket(1, "new"), silent=False)
    check("new unassigned stays silent", reasons(mon), {})
    mon._process_ticket(ticket(2, "open", assignee=123), silent=False)
    mon._process_ticket(ticket(2, "open", assignee=None), silent=False)
    check("hand-back stays silent", reasons(mon), {})
    mon._process_ticket(ticket(3, "pending", assignee=ME), silent=False)
    mon._process_ticket(ticket(3, "open", assignee=ME), silent=False)
    check("my reopen still fires", reasons(mon), {3: REASON_PENDING_TO_OPEN})

    print("\n10. Helpdesk Day: all three fire")
    mon = make_monitor(mode=modes.HELPDESK)
    mon._process_ticket(ticket(1, "new"), silent=False)
    mon._process_ticket(ticket(2, "open", assignee=123), silent=False)
    mon._process_ticket(ticket(2, "open", assignee=None), silent=False)
    mon._process_ticket(ticket(3, "pending", assignee=ME), silent=False)
    mon._process_ticket(ticket(3, "open", assignee=ME), silent=False)
    check("all three raised", reasons(mon),
          {1: REASON_NEW_UNASSIGNED, 2: REASON_BECAME_UNASSIGNED, 3: REASON_PENDING_TO_OPEN})

    print("\n11. An off day makes no Zendesk calls at all")
    mon = make_monitor(mode=modes.SCHEDULE,
                       schedule={k: modes.OFF for k in modes.WEEKDAY_KEYS})
    exploding = ExplodingClient()
    mon._client = exploding
    statuses: list[str] = []
    mon.status_changed.connect(statuses.append)
    mon._tick()
    check("no API surface was touched", exploding.touched, [])
    check("status says so", statuses[-1], "Off Day - not polling")

    print("\n12. An off day starting mid-alert clears the warning")
    mon = make_monitor(mode=modes.HELPDESK)
    mon._process_ticket(ticket(4, "new"), silent=False)
    check("alert is up", len(mon._alerts), 1)
    mon._config.mode = modes.SCHEDULE
    mon._config.schedule = {k: modes.OFF for k in modes.WEEKDAY_KEYS}
    mon._client = ExplodingClient()
    mon._tick()
    check("cleared once the off day applies", reasons(mon), {})

    print("\n13. Switching to Focus Day drops a queue alert already showing")
    mon = make_monitor(mode=modes.HELPDESK)
    mon._process_ticket(ticket(5, "new"), silent=False)
    mon._process_ticket(ticket(6, "pending", assignee=ME), silent=False)
    mon._process_ticket(ticket(6, "open", assignee=ME), silent=False)
    check("two alerts up", sorted(reasons(mon)), [5, 6])
    mon._config.mode = modes.FOCUS
    mon._prune_alerts_outside_scope()
    check("only the reopen survives", reasons(mon), {6: REASON_PENDING_TO_OPEN})

    print("\n14. Mode and schedule survive a config round trip")
    cfg = Config(mode=modes.SCHEDULE)
    cfg.schedule["wed"] = modes.FOCUS
    cfg.schedule["thu"] = modes.OFF
    revived = Config.from_dict(cfg.to_dict())
    check("mode kept", revived.mode, modes.SCHEDULE)
    check("wednesday kept", revived.schedule["wed"], modes.FOCUS)
    check("thursday kept", revived.schedule["thu"], modes.OFF)

    print("\n15. A v1/v2 config without mode keys loads as Helpdesk")
    old = Config.from_dict({"subdomain": "x", "watched_group_ids": [1]})
    check("mode defaulted", old.mode, modes.HELPDESK)
    check("schedule filled in", sorted(old.schedule) == sorted(modes.WEEKDAY_KEYS), True)


if __name__ == "__main__":
    QCoreApplication([])
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
