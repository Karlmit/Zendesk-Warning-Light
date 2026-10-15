"""Who asked: carrying the requester from Zendesk through to the caption.

The rule this pins down is that a name is a nicety, never a dependency. A
lookup that fails, a deleted user, an older saved alert - none of them may cost
you the warning itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication            # noqa: E402

from zwl import overlay                               # noqa: E402
from zwl.config import Config                         # noqa: E402
from zwl.monitor import Alert, Monitor                # noqa: E402
from zwl.zendesk import ZendeskError                  # noqa: E402

CHECKS = []


def check(label: str, got, want) -> None:
    CHECKS.append((label, got == want, got, want))


class FakeClient:
    """Stands in for ZendeskClient, counting calls and able to misbehave."""

    def __init__(self, names=None, explode=False):
        self._names = names or {}
        self._explode = explode
        self.calls = []

    def users_by_id(self, ids):
        ids = sorted(ids)
        self.calls.append(ids)
        if self._explode:
            raise ZendeskError("403 Forbidden")
        return {i: self._names[i] for i in ids if i in self._names}


def a_monitor(client) -> Monitor:
    """A Monitor with its network and timers left off; we drive it directly."""
    monitor = Monitor.__new__(Monitor)
    monitor._client = client
    monitor._alerts = {}
    monitor._requesters = {}
    return monitor


def an_alert(ticket_id=1, requester_id=None, requester_name="", group_name="Support"):
    return Alert(
        ticket_id=ticket_id,
        reason="new_unassigned",
        subject="Printer on fire",
        group_id=7,
        group_name=group_name,
        raised_at=0.0,
        requester_id=requester_id,
        requester_name=requester_name,
    )


# --- the snapshot keeps the requester id ----------------------------------

snap = Monitor._snapshot({
    "id": 5, "status": "new", "subject": " Help ",
    "assignee_id": None, "group_id": 7, "requester_id": 900,
})
check("snapshot keeps the requester", snap["requester_id"], 900)

check(
    "a ticket with no requester is not invented",
    Monitor._snapshot({"id": 5, "status": "new"}).get("requester_id"),
    None,
)
check(
    "requester 0 is treated as absent",
    Monitor._snapshot({"id": 5, "requester_id": 0}).get("requester_id"),
    None,
)

# --- names are resolved in one batched request ----------------------------

client = FakeClient({900: "Ada Lovelace", 901: "Grace Hopper"})
monitor = a_monitor(client)
monitor._alerts = {
    1: an_alert(1, 900),
    2: an_alert(2, 901),
    3: an_alert(3, 900),      # same requester as #1
}
monitor._resolve_requesters()

check("one request for the whole batch", len(client.calls), 1)
check("each requester asked for once", client.calls[0], [900, 901])
check("name reached alert 1", monitor._alerts[1].requester_name, "Ada Lovelace")
check("name reached alert 2", monitor._alerts[2].requester_name, "Grace Hopper")
check("repeat requester also named", monitor._alerts[3].requester_name, "Ada Lovelace")

# a second pass must not ask again
monitor._resolve_requesters()
check("already-known names are not re-fetched", len(client.calls), 1)

# a new alert for a known requester needs no request at all
monitor._alerts[4] = an_alert(4, 900)
monitor._resolve_requesters()
check("cached name needs no request", len(client.calls), 1)
check("cached name still applied", monitor._alerts[4].requester_name, "Ada Lovelace")

# --- failure must never cost the warning ----------------------------------

angry = FakeClient(explode=True)
survivor = a_monitor(angry)
survivor._alerts = {1: an_alert(1, 900)}
survivor._resolve_requesters()          # must not raise
check("a failed lookup leaves the alert intact", 1 in survivor._alerts, True)
check("a failed lookup leaves the name blank", survivor._alerts[1].requester_name, "")

# and it is retried on the next poll rather than giving up
recovered = a_monitor(FakeClient({900: "Ada Lovelace"}))
recovered._alerts = survivor._alerts
recovered._requesters = {}
recovered._resolve_requesters()
check("a later poll picks the name up", recovered._alerts[1].requester_name, "Ada Lovelace")

# a requester Zendesk does not return (deleted user) stays blank, quietly
missing = FakeClient({})
quiet = a_monitor(missing)
quiet._alerts = {1: an_alert(1, 12345)}
quiet._resolve_requesters()
check("an unknown user stays blank", quiet._alerts[1].requester_name, "")
check("the alert survives an unknown user", 1 in quiet._alerts, True)

# an alert with no requester at all asks for nothing
none_at_all = FakeClient({})
bare = a_monitor(none_at_all)
bare._alerts = {1: an_alert(1, None)}
bare._resolve_requesters()
check("no requester means no request", none_at_all.calls, [])

# --- an alert saved by an older version still loads -----------------------

old_shape = {
    "ticket_id": 8, "reason": "new_unassigned", "subject": "From before",
    "group_id": 7, "group_name": "Support", "raised_at": 0.0,
}
restored = Alert(**old_shape)
check("old saved alert restores", restored.ticket_id, 8)
check("old saved alert has no requester", restored.requester_id, None)
check("old saved alert has no name", restored.requester_name, "")

# --- the caption shows it ------------------------------------------------

app = QApplication.instance() or QApplication(sys.argv)
window = overlay.OverlayWindow(Config())


def caption_for(alert) -> str:
    window.set_alerts([alert])
    return window._caption.text()


text = caption_for(an_alert(1, 900, "Ada Lovelace", "Switchboard"))
check("caption names the requester", "Ada Lovelace" in text, True)
check("caption says who it is from", "From Ada Lovelace" in text, True)
check("caption still names the group", "Switchboard" in text, True)
check("requester comes before the group",
      text.index("Ada Lovelace") < text.index("Switchboard"), True)
check("caption still has the ticket number", "#1" in text, True)
check("caption still has the subject", "Printer on fire" in text, True)

# both halves of the grey line are optional, and neither leaves a stray separator
no_name = caption_for(an_alert(2, 900, "", "Switchboard"))
check("no name: group still shown", "Switchboard" in no_name, True)
check("no name: no dangling separator", "From" in no_name, False)

no_group = caption_for(an_alert(3, 900, "Ada Lovelace", ""))
check("no group: requester still shown", "From Ada Lovelace" in no_group, True)
check("no group: no trailing separator",
      no_group.rstrip().endswith("&middot; </span>"), False)

neither = caption_for(an_alert(4, None, "", ""))
check("neither: caption still renders", "#4" in neither, True)
check("neither: no empty grey line", "&middot;" in neither.split("<br>")[-1], False)

# a long name is clipped rather than stretching the box
long_name = "Wilhelmina Aloysia Fitzgerald-Montgomery of the Northern Office"
clipped = caption_for(an_alert(5, 900, long_name, "Support"))
check("a long name is clipped", long_name in clipped, False)
check("a clipped name is marked", "…" in clipped, True)
check("a clipped name still starts correctly", "Wilhelmina" in clipped, True)

# names are escaped, not interpreted
nasty = caption_for(an_alert(6, 900, "<b>Bold</b> & Co", "Support"))
check("a name cannot inject markup", "<b>Bold</b>" in nasty, False)
check("a name's ampersand is escaped", "&amp;" in nasty, True)

# the summary line for several alerts still names the newest requester
window.set_alerts([an_alert(7, 900, "Ada Lovelace"), an_alert(8, 901, "Grace Hopper")])
many = window._caption.text()
check("many alerts: counted", "2 tickets need attention" in many, True)
check("many alerts: newest requester shown", "Grace Hopper" in many, True)


# --- when the ticket came in ---------------------------------------------

from datetime import datetime, timedelta, timezone   # noqa: E402

fmt = overlay.format_received
now_utc = datetime.now(timezone.utc)
today_text = fmt(now_utc.isoformat())
check("today shows a bare clock time", len(today_text) == 5 and today_text[2] == ":", True)
old = (now_utc - timedelta(days=3)).isoformat().replace("+00:00", "Z")
check("older ticket adds the date (and parses a trailing Z)",
      len(fmt(old).split()) == 3, True)
check("missing time is blank", fmt(""), "")
check("garbage time is blank", fmt("not a date"), "")
check("snapshot keeps created_at", Monitor._snapshot(
    {"id": 1, "created_at": "2026-10-08T07:05:00Z"}).get("created_at"), "2026-10-08T07:05:00Z")
check("snapshot tolerates no created_at", Monitor._snapshot({"id": 1}).get("created_at"), "")
with_time = Alert(ticket_id=9, reason="new_unassigned", subject="s", group_id=None,
                  group_name="G", raised_at=0.0, requester_id=1, requester_name="Ada",
                  created_at=now_utc.isoformat())
w = overlay.OverlayWindow(Config())
w.set_alerts([with_time])
check("box shows 'Received'", "Received {}".format(today_text) in w._caption.text(), True)
w.set_alerts([Alert(**{**with_time.__dict__, "created_at": ""})])
check("no 'Received' without a time", "Received" in w._caption.text(), False)

# --- report ---------------------------------------------------------------

failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
