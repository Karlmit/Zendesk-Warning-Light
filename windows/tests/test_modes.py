"""Covers day modes: each mode owns its rules AND its groups.

No network - an exploding client proves an off day never reaches Zendesk.
"""

from __future__ import annotations

import json
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
from zwl.modes import DayMode  # noqa: E402
from zwl.monitor import (  # noqa: E402
    REASON_NEW_UNASSIGNED, REASON_PENDING_TO_OPEN, Monitor,
)

ME = 999
QUEUE_A = 111
QUEUE_B = 222

MONDAY = date(2026, 9, 7)
TUESDAY = date(2026, 9, 8)
SATURDAY = date(2026, 9, 12)

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


def ticket(tid: int, status: str, assignee=None, group=QUEUE_A) -> dict:
    return {"id": tid, "status": status, "assignee_id": assignee,
            "group_id": group, "subject": "t{}".format(tid)}


class ExplodingClient:
    """Any attribute touched means a Zendesk call we should not have made."""

    def __init__(self):
        self.touched: list[str] = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError("Zendesk was contacted on an off day: .{}()".format(name))


def make_monitor(cfg: Config) -> Monitor:
    tokens = TokenStore(base_url="https://example.zendesk.com")
    tokens._refresh_token = "rt"
    tokens.user = SignedInUser(id=ME, name="T", email="t@x", role="agent")
    mon = Monitor(cfg, tokens)
    mon._groups = {QUEUE_A: "Queue A", QUEUE_B: "Queue B"}
    return mon


def reasons(mon: Monitor) -> dict[int, str]:
    return {tid: a.reason for tid, a in mon._alerts.items()}


def two_queue_config() -> Config:
    """Morning watches queue A, afternoon watches queue B."""
    return Config(
        subdomain="example",
        mode="morning",
        day_modes=[
            DayMode(id="morning", name="Switchboard", watched_group_ids=[QUEUE_A]),
            DayMode(id="afternoon", name="Billing", watched_group_ids=[QUEUE_B]),
        ],
        schedule={k: "morning" for k in modes.WEEKDAY_KEYS},
    )


def run() -> None:
    print("\n1. A fresh install seeds two modes and runs Helpdesk Day")
    fresh = Config()
    check("mode", fresh.mode, modes.BUILTIN_HELPDESK)
    check("seeded ids", [m.id for m in fresh.day_modes],
          [modes.BUILTIN_HELPDESK, modes.BUILTIN_FOCUS])
    check("helpdesk allows all three",
          [fresh.find_mode("helpdesk").rule_enabled(r) for r in modes.ALL_RULES],
          [True, True, True])
    check("focus allows only the reopen rule",
          [fresh.find_mode("focus").rule_enabled(r) for r in modes.ALL_RULES],
          [False, False, True])
    check("weekend is off by default",
          [fresh.schedule[k] for k in ("sat", "sun")], [modes.OFF, modes.OFF])

    print("\n2. THE NEW BIT: groups are per mode")
    cfg = two_queue_config()
    check("morning watches queue A", cfg.watched_group_ids, [QUEUE_A])
    cfg.mode = "afternoon"
    check("afternoon watches queue B", cfg.watched_group_ids, [QUEUE_B])
    check("label follows the mode name", cfg.mode_label(), "Billing")

    print("\n3. A weekday can select a different mode, so groups change by day")
    cfg = two_queue_config()
    cfg.mode = modes.SCHEDULE
    cfg.schedule["mon"] = "morning"
    cfg.schedule["tue"] = "afternoon"
    check("Monday resolves to the queue-A mode", cfg.effective_mode(MONDAY), "morning")
    check("Tuesday resolves to the queue-B mode", cfg.effective_mode(TUESDAY), "afternoon")
    check("Monday's mode watches queue A",
          cfg.active_mode(MONDAY).watched_group_ids, [QUEUE_A])
    check("Tuesday's mode watches queue B",
          cfg.active_mode(TUESDAY).watched_group_ids, [QUEUE_B])

    print("\n4. Off resolves to no mode at all")
    cfg = two_queue_config()
    cfg.mode = modes.SCHEDULE
    cfg.schedule[modes.weekday_key(SATURDAY)] = modes.OFF
    check("effective is off", cfg.effective_mode(SATURDAY), modes.OFF)
    check("no active mode", cfg.active_mode(SATURDAY), None)
    cfg.mode = modes.OFF
    check("off can be picked directly", cfg.is_off_day(), True)
    check("not active", cfg.is_active(), False)
    check("no groups watched when off", cfg.watched_group_ids, [])
    check("label", cfg.mode_label(), modes.OFF_LABEL)

    print("\n5. Rules come from the mode in force")
    cfg = two_queue_config()
    cfg.find_mode("afternoon").alert_on_new_unassigned = False
    cfg.mode = "morning"
    check("morning allows the new-ticket rule",
          cfg.rule_enabled(modes.RULE_NEW_UNASSIGNED), True)
    cfg.mode = "afternoon"
    check("afternoon does not", cfg.rule_enabled(modes.RULE_NEW_UNASSIGNED), False)
    cfg.mode = modes.OFF
    check("off allows nothing",
          [cfg.rule_enabled(r) for r in modes.ALL_RULES], [False, False, False])

    print("\n6. A mode knows whether it needs a group list at all")
    reopen_only = DayMode(id="q", name="Quiet", alert_on_new_unassigned=False,
                          alert_on_became_unassigned=False)
    check("reopen-only does not watch the queue", reopen_only.watches_the_queue, False)
    check("but is not silent", reopen_only.is_silent, False)
    check("summary says so", reopen_only.summary(), "my reopened tickets")
    silent = DayMode(id="s", name="Silent", alert_on_new_unassigned=False,
                     alert_on_became_unassigned=False, alert_on_pending_to_open=False)
    check("all rules off is silent", silent.is_silent, True)
    queue = DayMode(id="k", name="Queue", watched_group_ids=[1, 2])
    check("group count appears in the summary",
          "2 groups" in queue.summary(), True)
    check("no groups reads as every visible group",
          "every visible group" in DayMode(id="z", name="Z").summary(), True)

    print("\n7. The monitor honours per-mode groups")
    cfg = two_queue_config()          # mode "morning", watches queue A only
    mon = make_monitor(cfg)
    mon._process_ticket(ticket(1, "new", group=QUEUE_A), silent=False)
    check("queue A alerts", reasons(mon), {1: REASON_NEW_UNASSIGNED})
    mon._process_ticket(ticket(2, "new", group=QUEUE_B), silent=False)
    check("queue B stays quiet", reasons(mon), {1: REASON_NEW_UNASSIGNED})

    print("\n8. Switching mode re-scopes live alerts to the new groups")
    mon._config.mode = "afternoon"    # now watches queue B instead
    mon._prune_alerts_outside_scope()
    check("the queue-A alert is dropped", reasons(mon), {})
    mon._process_ticket(ticket(3, "new", group=QUEUE_B), silent=False)
    check("queue B now alerts", reasons(mon), {3: REASON_NEW_UNASSIGNED})

    print("\n9. A reopen alert survives a group-only mode change")
    cfg = two_queue_config()
    mon = make_monitor(cfg)
    mon._process_ticket(ticket(4, "pending", assignee=ME, group=QUEUE_A), silent=False)
    mon._process_ticket(ticket(4, "open", assignee=ME, group=QUEUE_A), silent=False)
    check("reopen alert raised", reasons(mon), {4: REASON_PENDING_TO_OPEN})
    mon._config.mode = "afternoon"
    mon._prune_alerts_outside_scope()
    check("it survives, because reopen ignores groups",
          reasons(mon), {4: REASON_PENDING_TO_OPEN})

    print("\n10. An off day makes no Zendesk calls at all")
    cfg = two_queue_config()
    cfg.mode = modes.OFF
    mon = make_monitor(cfg)
    exploding = ExplodingClient()
    mon._client = exploding
    statuses: list[str] = []
    mon.status_changed.connect(statuses.append)
    mon._tick()
    check("no API surface touched", exploding.touched, [])
    check("status says so", statuses[-1], "Off Day - not polling")

    print("\n11. An off day starting mid-alert clears the warning")
    cfg = two_queue_config()
    mon = make_monitor(cfg)
    mon._process_ticket(ticket(5, "new", group=QUEUE_A), silent=False)
    check("alert is up", len(mon._alerts), 1)
    mon._config.mode = modes.OFF
    mon._client = ExplodingClient()
    mon._tick()
    check("cleared", reasons(mon), {})

    print("\n12. Deleting the mode a weekday points at is repaired on load")
    cfg = two_queue_config()
    cfg.mode = modes.SCHEDULE
    cfg.schedule["wed"] = "afternoon"
    raw = cfg.to_dict()
    raw["day_modes"] = [m for m in raw["day_modes"] if m["id"] != "afternoon"]
    revived = Config.from_dict(raw)
    check("the orphaned day falls back to a real mode",
          revived.schedule["wed"] in revived.mode_ids(), True)
    check("the surviving mode is untouched",
          revived.find_mode("morning").watched_group_ids, [QUEUE_A])

    print("\n13. A corrupt mode list never leaves you with none")
    check("garbage seeds the defaults",
          [m.id for m in Config.from_dict({"day_modes": ["nonsense", 42]}).day_modes],
          [modes.BUILTIN_HELPDESK, modes.BUILTIN_FOCUS])
    check("reserved ids are rejected",
          modes.DayMode.from_dict({"id": "off", "name": "Sneaky"}), None)
    check("a duplicate id is dropped",
          len(modes.sanitise_modes([{"id": "a", "name": "A"}, {"id": "a", "name": "B"}])), 1)

    print("\n14. Unknown selected mode falls back rather than breaking")
    cfg = Config.from_dict({"mode": "deleted-long-ago"})
    check("fell back to a real mode", cfg.mode, modes.BUILTIN_HELPDESK)

    print("\n15. New ids are unique and readable")
    taken = {"switchboard"}
    check("readable slug", modes.new_id("Switchboard morning", set()), "switchboard-morning")
    check("collision gets a suffix",
          modes.new_id("Switchboard", taken).startswith("switchboard-"), True)
    check("reserved words never become an id",
          modes.new_id("Off", set()) != modes.OFF, True)

    print("\n16. Modes survive a JSON round trip")
    cfg = two_queue_config()
    again = Config.from_dict(json.loads(json.dumps(cfg.to_dict())))
    check("identical", again.to_dict(), cfg.to_dict())
    check("groups intact", again.find_mode("afternoon").watched_group_ids, [QUEUE_B])

    print("\n17. A v2.1 config migrates into the seeded modes")
    v21 = {
        "mode": "schedule",
        "schedule": {"mon": "helpdesk", "tue": "focus", "wed": "helpdesk",
                     "thu": "helpdesk", "fri": "helpdesk", "sat": "off", "sun": "off"},
        "watched_group_ids": [QUEUE_A, QUEUE_B],
        "alert_on_new_unassigned": True,
        "alert_on_became_unassigned": False,
        "alert_on_pending_to_open": True,
    }
    migrated = Config.from_dict(v21)
    check("both modes created", sorted(migrated.mode_ids()), ["focus", "helpdesk"])
    check("old rules carried into helpdesk",
          [migrated.find_mode("helpdesk").rule_enabled(r) for r in modes.ALL_RULES],
          [True, False, True])
    check("old groups carried over",
          migrated.find_mode("helpdesk").watched_group_ids, [QUEUE_A, QUEUE_B])
    check("weekday plan unchanged", migrated.schedule["tue"], "focus")
    check("still on the schedule", migrated.mode, modes.SCHEDULE)


if __name__ == "__main__":
    QCoreApplication([])
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
