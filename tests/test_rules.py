"""Exercises the alert transition rules with synthetic tickets (no network)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from zwl import auth as auth_module  # noqa: E402
from zwl import monitor as monitor_module  # noqa: E402
from zwl.auth import SignedInUser, TokenStore  # noqa: E402
from zwl.config import Config  # noqa: E402
from zwl.monitor import (  # noqa: E402
    REASON_BECAME_UNASSIGNED, REASON_NEW_UNASSIGNED, REASON_PENDING_TO_OPEN, Monitor,
)

ME = 12059351301777
WATCHED = 15962684745105
OTHER_GROUP = 18564583439761

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


def ticket(tid: int, status: str, assignee=None, group=WATCHED, subject="Subject") -> dict:
    return {"id": tid, "status": status, "assignee_id": assignee,
            "group_id": group, "subject": subject}


def make_tokens(user_id: int = ME, role: str = "agent") -> TokenStore:
    """A signed-in store with no network behind it."""
    store = TokenStore(base_url="https://example.zendesk.com")
    store._refresh_token = "pretend-refresh-token"
    store.user = SignedInUser(id=user_id, name="Tester",
                              email="tester@example.com", role=role)
    return store


def make_monitor(**overrides) -> Monitor:
    cfg = Config(subdomain="example", watched_group_ids=[WATCHED])
    for key, value in overrides.items():
        setattr(cfg, key, value)
    mon = Monitor(cfg, make_tokens())
    mon._groups = {WATCHED: "Group - Example Co", OTHER_GROUP: "NL - Helpdesk"}
    return mon


def reasons(mon: Monitor) -> dict[int, str]:
    return {tid: a.reason for tid, a in mon._alerts.items()}


def run() -> None:
    print("\n1. A brand new unassigned ticket in a watched group raises an alert")
    mon = make_monitor()
    mon._process_ticket(ticket(1, "new"), silent=False)
    check("alert raised", reasons(mon), {1: REASON_NEW_UNASSIGNED})

    print("\n2. Assigning it clears the alert automatically")
    mon._process_ticket(ticket(1, "open", assignee=999), silent=False)
    check("alert cleared", reasons(mon), {})

    print("\n3. A new unassigned ticket in an unwatched group stays silent")
    mon = make_monitor()
    mon._process_ticket(ticket(2, "new", group=OTHER_GROUP), silent=False)
    check("no alert", reasons(mon), {})

    print("\n4. Handing an assigned ticket back to the queue raises 'became unassigned'")
    mon = make_monitor()
    mon._process_ticket(ticket(3, "open", assignee=999), silent=False)
    check("assigned ticket is quiet", reasons(mon), {})
    mon._process_ticket(ticket(3, "open", assignee=None), silent=False)
    check("alert on hand-back", reasons(mon), {3: REASON_BECAME_UNASSIGNED})

    print("\n5. That rule can be switched off independently")
    mon = make_monitor(alert_on_became_unassigned=False)
    mon._process_ticket(ticket(4, "open", assignee=999), silent=False)
    mon._process_ticket(ticket(4, "open", assignee=None), silent=False)
    check("no alert when rule disabled", reasons(mon), {})
    mon._process_ticket(ticket(5, "new"), silent=False)
    check("new-ticket rule still fires", reasons(mon), {5: REASON_NEW_UNASSIGNED})

    print("\n6. My ticket going pending -> open raises the reopen alert")
    mon = make_monitor()
    mon._process_ticket(ticket(6, "pending", assignee=ME), silent=False)
    check("pending is quiet", reasons(mon), {})
    mon._process_ticket(ticket(6, "open", assignee=ME), silent=False)
    check("reopen alert", reasons(mon), {6: REASON_PENDING_TO_OPEN})

    print("\n7. Solving it clears the reopen alert")
    mon._process_ticket(ticket(6, "solved", assignee=ME), silent=False)
    check("cleared on solve", reasons(mon), {})

    print("\n8. Someone else's ticket going pending -> open stays silent")
    mon = make_monitor()
    mon._process_ticket(ticket(7, "pending", assignee=999), silent=False)
    mon._process_ticket(ticket(7, "open", assignee=999), silent=False)
    check("no alert for other agents", reasons(mon), {})

    print("\n9. Silent seeding records state without alerting, then goes live")
    mon = make_monitor()
    mon._process_ticket(ticket(8, "new"), silent=True)
    check("backlog is silent", reasons(mon), {})
    mon._process_ticket(ticket(8, "new", subject="edited while still unassigned"), silent=False)
    check("no re-alert for a known unassigned ticket", reasons(mon), {})
    mon._process_ticket(ticket(9, "new"), silent=False)
    check("a genuinely new ticket still alerts", reasons(mon), {9: REASON_NEW_UNASSIGNED})

    print("\n10. While paused nothing is raised, but state keeps advancing")
    mon = make_monitor()
    mon._config.enabled = False
    mon._process_ticket(ticket(10, "new"), silent=False)
    check("paused means silent", reasons(mon), {})
    mon._config.enabled = True
    mon._process_ticket(ticket(10, "new", subject="still unassigned"), silent=False)
    check("no backlog dump on resume", reasons(mon), {})

    print("\n11. Dismissing clears alerts and they do not come back on their own")
    mon = make_monitor()
    mon._process_ticket(ticket(11, "new"), silent=False)
    mon.dismiss_all()
    check("dismissed", reasons(mon), {})
    mon._process_ticket(ticket(11, "open", subject="a public reply arrives"), silent=False)
    check("stays dismissed while unchanged", reasons(mon), {})
    mon._process_ticket(ticket(11, "open", assignee=999), silent=False)
    mon._process_ticket(ticket(11, "open", assignee=None), silent=False)
    check("re-alerts on a fresh transition", reasons(mon), {11: REASON_BECAME_UNASSIGNED})

    print("\n12. Moving an unassigned ticket into a watched group alerts")
    mon = make_monitor()
    mon._process_ticket(ticket(12, "new", group=OTHER_GROUP), silent=False)
    check("quiet in the other group", reasons(mon), {})
    mon._process_ticket(ticket(12, "new", group=WATCHED), silent=False)
    check("alerts once it lands in my group", reasons(mon), {12: REASON_BECAME_UNASSIGNED})

    print("\n13. An empty group selection watches every group")
    mon = make_monitor(watched_group_ids=[])
    mon._process_ticket(ticket(13, "new", group=OTHER_GROUP), silent=False)
    check("alerts anywhere", reasons(mon), {13: REASON_NEW_UNASSIGNED})

    print("\n14. Unassigned but solved/pending tickets are not 'needs an owner'")
    mon = make_monitor()
    mon._process_ticket(ticket(14, "pending", assignee=None), silent=False)
    check("pending unassigned is quiet", reasons(mon), {})
    mon._process_ticket(ticket(15, "solved", assignee=None), silent=False)
    check("solved unassigned is quiet", reasons(mon), {})

    print("\n15. State survives a save/load round trip")
    mon = make_monitor()
    mon._process_ticket(ticket(16, "new"), silent=False)
    mon._save_state()
    revived = make_monitor()
    check("alerts restored", reasons(revived), {16: REASON_NEW_UNASSIGNED})
    check("ticket history restored", 16 in revived._tickets, True)


if __name__ == "__main__":
    QCoreApplication([])
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
