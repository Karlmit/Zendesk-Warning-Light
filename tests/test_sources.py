"""Covers the ticket sources: the agent-safe sweep and the admin/agent selection.

No network - a fake client stands in for Zendesk.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zwl import sources  # noqa: E402
from zwl.zendesk import ZendeskError  # noqa: E402

_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print("  PASS  {}".format(label))
    else:
        print("  FAIL  {}  (got {!r}, expected {!r})".format(label, actual, expected))
        _failures.append(label)


def ticket(tid: int, updated: str) -> dict:
    return {"id": tid, "status": "open", "assignee_id": None,
            "group_id": 1, "subject": "t{}".format(tid), "updated_at": updated}


class FakeClient:
    """Serves a fixed newest-first ticket list, paginated."""

    def __init__(self, tickets: list[dict], probe_status: int = 200):
        self.tickets = tickets
        self.probe_status = probe_status
        self.pages_served: list[int] = []
        self.probe_calls = 0

    def list_tickets_by_update(self, page: int = 1, per_page: int = 100) -> list[dict]:
        self.pages_served.append(page)
        start = (page - 1) * per_page
        return self.tickets[start:start + per_page]

    def incremental_tickets(self, cursor=None, start_time=None):
        return list(self.tickets), "cursor-1", True

    def probe(self, path, params=None) -> int:
        self.probe_calls += 1
        if self.probe_status == 0:
            raise ZendeskError("boom")
        return self.probe_status


def run() -> None:
    # Keep the page sizes small so the tests stay readable.
    sources.SWEEP_PER_PAGE = 3
    sources.SWEEP_MAX_PAGES = 2
    sources.SWEEP_SEED_PAGES = 4

    print("\n1. A cold sweep takes everything and records a watermark")
    rows = [ticket(i, "2026-09-02T10:{:02d}:00Z".format(30 - i)) for i in range(1, 8)]
    client = FakeClient(rows)
    src = sources.SweepSource(client)
    check("not primed before the first fetch", src.is_primed, False)
    got = src.fetch(cold=True)
    check("returned every ticket", len(got), 7)
    check("primed afterwards", src.is_primed, True)
    check("watermark is the newest updated_at", src.state()["watermark"],
          "2026-09-02T10:29:00Z")

    print("\n2. A warm sweep stops as soon as it reaches known ground")
    client.pages_served.clear()
    got = src.fetch(cold=False)
    check("nothing new returned", [t["id"] for t in got], [1])   # equal timestamp, re-seen
    check("only read one page", client.pages_served, [1])

    print("\n3. A newly updated ticket is picked up")
    rows.insert(0, ticket(99, "2026-09-02T11:00:00Z"))
    got = src.fetch(cold=False)
    # #1 sits exactly on the old watermark, so it is deliberately re-examined
    # rather than risked being skipped. Reprocessing is a no-op for the rules.
    check("the new ticket came back, plus the boundary one",
          [t["id"] for t in got], [99, 1])
    check("stopped before anything older", 2 in [t["id"] for t in got], False)
    check("watermark advanced", src.state()["watermark"], "2026-09-02T11:00:00Z")

    print("\n4. Tickets sharing one second are not skipped")
    same = [ticket(1, "2026-09-02T12:00:00Z"), ticket(2, "2026-09-02T12:00:00Z"),
            ticket(3, "2026-09-02T12:00:00Z")]
    src2 = sources.SweepSource(FakeClient(same))
    first = src2.fetch(cold=True)
    check("all three on the cold pass", sorted(t["id"] for t in first), [1, 2, 3])
    again = src2.fetch(cold=False)
    check("re-seen rather than lost (>= watermark)",
          sorted(t["id"] for t in again), [1, 2, 3])

    print("\n5. State round-trips through a dict")
    revived = sources.SweepSource(FakeClient(rows), src.state())
    check("watermark restored", revived.state()["watermark"], src.state()["watermark"])
    check("restored source is primed", revived.is_primed, True)

    print("\n6. An admin whose probe succeeds gets the incremental export")
    client = FakeClient(rows, probe_status=200)
    src = sources.build(client, prefer_incremental=True)
    check("chose incremental", src.name, "incremental")
    check("probed once", client.probe_calls, 1)

    print("\n7. An admin whose probe is forbidden falls back to the sweep")
    client = FakeClient(rows, probe_status=403)
    src = sources.build(client, prefer_incremental=True)
    check("fell back to sweep", src.name, "sweep")

    print("\n8. A probe that errors outright also falls back")
    client = FakeClient(rows, probe_status=0)
    check("fell back to sweep", sources.build(client, prefer_incremental=True).name, "sweep")

    print("\n9. A non-admin goes straight to the sweep without probing")
    client = FakeClient(rows, probe_status=200)
    src = sources.build(client, prefer_incremental=False)
    check("chose sweep", src.name, "sweep")
    check("did not waste a probe call", client.probe_calls, 0)

    print("\n10. Saved state from the other source kind is discarded")
    client = FakeClient(rows, probe_status=200)
    src = sources.build(client, prefer_incremental=True,
                        saved={"kind": "sweep", "watermark": "2026-01-01T00:00:00Z"})
    check("incremental ignored the sweep watermark", src.state()["cursor"], "")
    check("so a cold seed is due", src.is_primed, False)

    client = FakeClient(rows, probe_status=403)
    src = sources.build(client, prefer_incremental=True,
                        saved={"kind": "sweep", "watermark": "2026-01-01T00:00:00Z"})
    check("but matching state is reused", src.state()["watermark"], "2026-01-01T00:00:00Z")


if __name__ == "__main__":
    run()
    print("\n" + "=" * 60)
    if _failures:
        print("{} FAILING CHECK(S): {}".format(len(_failures), ", ".join(_failures)))
        sys.exit(1)
    print("All checks passed.")
