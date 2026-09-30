"""Where changed tickets come from.

Two implementations, because the endpoint the app was originally built on is
admin-only:

* :class:`IncrementalSource` - ``/api/v2/incremental/tickets/cursor.json``.
  Exact and cheap: it hands back precisely what changed since the last cursor.
  Documented as "Allowed For: Admins", so agents get a 403.
* :class:`SweepSource` - ``/api/v2/tickets.json?sort_by=updated_at&sort_order=desc``.
  "Allowed For: Agents". Reads the ticket database, so no search-index lag, but we
  have to page from the top and stop once we reach tickets we have already seen.

Both return plain ticket dicts, so ``monitor.py``'s transition rules never need to
know which one is in play.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .zendesk import ZendeskClient, ZendeskError

log = logging.getLogger(__name__)

SEED_LOOKBACK_DAYS = 7
INCREMENTAL_MAX_PAGES = 25

SWEEP_PER_PAGE = 100
SWEEP_MAX_PAGES = 3          # 300 most-recently-updated tickets per poll
SWEEP_SEED_PAGES = 8         # a wider first pass to seed state


class TicketSource:
    """Interface: hand back tickets that changed since last time."""

    name = "unknown"

    def fetch(self, cold: bool) -> list[dict[str, Any]]:
        raise NotImplementedError

    def state(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def is_primed(self) -> bool:
        """False when we have no idea where we left off (so a cold pass is due)."""
        raise NotImplementedError


class IncrementalSource(TicketSource):
    name = "incremental"

    def __init__(self, client: ZendeskClient, state: dict[str, Any] | None = None):
        self._client = client
        self._cursor: str = (state or {}).get("cursor", "")

    @property
    def is_primed(self) -> bool:
        return bool(self._cursor)

    def fetch(self, cold: bool) -> list[dict[str, Any]]:
        cursor = self._cursor or None
        start_time = None if cursor else int(time.time() - SEED_LOOKBACK_DAYS * 86400)

        collected: list[dict[str, Any]] = []
        for _ in range(INCREMENTAL_MAX_PAGES):
            tickets, cursor, end_of_stream = self._client.incremental_tickets(cursor, start_time)
            start_time = None
            collected.extend(tickets)
            self._cursor = cursor
            if end_of_stream:
                break
        return collected

    def state(self) -> dict[str, Any]:
        return {"kind": self.name, "cursor": self._cursor}


class SweepSource(TicketSource):
    """Pages the most-recently-updated tickets until it reaches familiar ground.

    The watermark comparison is ``>=`` rather than ``>``: several tickets can share
    an ``updated_at`` second, and re-examining one is harmless because the rules
    compare against the stored snapshot and a repeat yields no new alert.
    """

    name = "sweep"

    def __init__(self, client: ZendeskClient, state: dict[str, Any] | None = None):
        self._client = client
        self._watermark: str = (state or {}).get("watermark", "")

    @property
    def is_primed(self) -> bool:
        return bool(self._watermark)

    def fetch(self, cold: bool) -> list[dict[str, Any]]:
        max_pages = SWEEP_SEED_PAGES if cold or not self._watermark else SWEEP_MAX_PAGES
        watermark = self._watermark
        collected: list[dict[str, Any]] = []
        reached_known_ground = False

        for page in range(1, max_pages + 1):
            batch = self._client.list_tickets_by_update(page=page, per_page=SWEEP_PER_PAGE)
            if not batch:
                reached_known_ground = True
                break

            for ticket in batch:
                updated = ticket.get("updated_at") or ""
                if watermark and updated < watermark:
                    reached_known_ground = True
                    break
                collected.append(ticket)
            if reached_known_ground or len(batch) < SWEEP_PER_PAGE:
                reached_known_ground = True
                break

        if collected:
            newest = max((t.get("updated_at") or "") for t in collected)
            if newest:
                self._watermark = newest

        # A cold pass has no watermark to reach, so filling the page budget is the
        # intended behaviour - only a warm pass running out of pages means we may
        # genuinely have missed something.
        if watermark and not reached_known_ground:
            log.warning("sweep read %d pages without reaching the last known update; "
                        "some changes may be picked up on a later poll", max_pages)
        elif not watermark:
            log.info("sweep seeded %d tickets", len(collected))
        return collected

    def state(self) -> dict[str, Any]:
        return {"kind": self.name, "watermark": self._watermark}


# ---------------------------------------------------------------------- #
# selection
# ---------------------------------------------------------------------- #

def build(client: ZendeskClient, prefer_incremental: bool,
          saved: dict[str, Any] | None = None) -> TicketSource:
    """Pick a source, probing rather than trusting the user's role blindly.

    ``prefer_incremental`` comes from the signed-in user's role, but a probe is
    still cheaper than discovering the 403 mid-poll, and role alone does not
    guarantee the endpoint is enabled for the account.
    """
    saved = saved or {}
    saved_kind = saved.get("kind")

    if prefer_incremental:
        try:
            status = client.probe("/api/v2/incremental/tickets/cursor.json",
                                  {"start_time": int(time.time()) - 60})
        except ZendeskError:
            status = 0
        if status == 200:
            log.info("using the incremental export (admin)")
            return IncrementalSource(client, saved if saved_kind == "incremental" else None)
        log.info("incremental export unavailable (HTTP %s); falling back to the sweep", status)
    else:
        log.info("signed-in user is not an admin; using the agent-safe sweep")

    return SweepSource(client, saved if saved_kind == "sweep" else None)
