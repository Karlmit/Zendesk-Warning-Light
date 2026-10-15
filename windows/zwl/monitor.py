"""Polls Zendesk and decides when the warning light should be on.

Design notes
------------
* Changed tickets arrive from a :mod:`zwl.sources` TicketSource, so this module
  does not care whether they came from the admin-only incremental export or the
  agent-safe sweep. Neither uses the Search API, so there is no indexing lag.
* Alerts are driven by *transitions*, not by absolute state. To know a transition
  happened we keep the previously seen status/assignee/group of every ticket in
  ``state.json``. On a cold start (or after the app has been off for a while) we
  replay recent history in "silent" mode so the backlog seeds the state map
  without setting off a wall of alerts.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from . import modes, sources
from .auth import AuthError, AuthExpired, TokenStore
from .config import Config
from .paths import state_path
from .zendesk import ZendeskClient, ZendeskError

log = logging.getLogger(__name__)

ACTIONABLE_STATUSES = ("new", "open")
STALE_RESUME_SECONDS = 15 * 60   # if we are further behind than this, replay silently
STATE_RETENTION_DAYS = 30
MAX_TRACKED_TICKETS = 20000
GROUP_REFRESH_SECONDS = 3600

REASON_NEW_UNASSIGNED = modes.RULE_NEW_UNASSIGNED
REASON_BECAME_UNASSIGNED = modes.RULE_BECAME_UNASSIGNED
REASON_PENDING_TO_OPEN = modes.RULE_PENDING_TO_OPEN

REASON_TEXT = {
    REASON_NEW_UNASSIGNED: "New unassigned ticket",
    REASON_BECAME_UNASSIGNED: "Ticket became unassigned",
    REASON_PENDING_TO_OPEN: "Your ticket reopened",
}


@dataclass
class Alert:
    ticket_id: int
    reason: str
    subject: str
    group_id: int | None
    group_name: str
    raised_at: float
    # Who asked. Both default, so an alert saved by an older version still
    # restores, and so a name that cannot be looked up is simply absent rather
    # than holding up the warning.
    requester_id: int | None = None
    requester_name: str = ""
    # When the ticket came in (Zendesk's created_at, ISO-8601 UTC). Empty when
    # unknown, and defaulted so an alert saved by an older version still restores.
    created_at: str = ""

    @property
    def headline(self) -> str:
        return REASON_TEXT.get(self.reason, self.reason)


class Monitor(QObject):
    """Lives on a worker thread; owns all network I/O."""

    alerts_changed = Signal(list)          # list[Alert]
    status_changed = Signal(str)           # short human status for the tray tooltip
    error_occurred = Signal(str)
    auth_state_changed = Signal(bool, str)  # (signed in and working, message)

    def __init__(self, config: Config, tokens: TokenStore):
        super().__init__()
        self._config = config
        self._tokens = tokens
        self._client: ZendeskClient | None = None
        self._source: sources.TicketSource | None = None
        self._timer: QTimer | None = None
        self._groups: dict[int, str] = {}
        self._groups_fetched_at = 0.0
        # Requester names, kept for the life of the process. People are renamed
        # far less often than tickets arrive, and this is only ever read for
        # tickets that actually raised a warning.
        self._requesters: dict[int, str] = {}
        self._polling = False
        self._auth_ok = True
        self._off_day_announced = False

        self._source_state: dict[str, object] = {}
        self._last_poll_ts: float = 0.0
        self._tickets: dict[int, dict[str, Any]] = {}
        self._alerts: dict[int, Alert] = {}
        self._load_state()

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    @Slot()
    def start(self) -> None:
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._rebuild_client()
        QTimer.singleShot(0, self._tick)

    @Slot(object)
    def apply_config(self, config: Config) -> None:
        """Hot-swap settings without restarting the thread."""
        connection_changed = (
            config.base_url != self._config.base_url
            or config.client_id != self._config.client_id
        )
        self._config = config
        if connection_changed:
            self._rebuild_client()
            self._groups_fetched_at = 0.0
        self._prune_alerts_outside_scope()
        self._emit_alerts()
        QTimer.singleShot(0, self._tick)

    @Slot()
    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
        self._save_state()

    def _rebuild_client(self) -> None:
        self._source = None
        if not self._tokens.is_signed_in:
            self._client = None
            self.status_changed.emit("Not signed in")
            return
        self._tokens.base_url = self._config.base_url
        self._tokens.client_id = self._config.client_id
        self._client = ZendeskClient(self._tokens)

    def _schedule_next(self) -> None:
        if self._timer:
            self._timer.start(max(10, self._config.poll_seconds) * 1000)

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #

    def _load_state(self) -> None:
        path = state_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("state.json unreadable, starting clean")
            return
        self._source_state = data.get("source") or {}
        self._last_poll_ts = float(data.get("last_poll_ts", 0.0))
        self._tickets = {int(k): v for k, v in data.get("tickets", {}).items()}
        for raw in data.get("alerts", []):
            try:
                self._alerts[int(raw["ticket_id"])] = Alert(**raw)
            except Exception:
                continue
        log.info("restored %d tracked tickets and %d live alerts",
                 len(self._tickets), len(self._alerts))

    def _save_state(self) -> None:
        self._prune_tickets()
        payload = {
            "source": self._source.state() if self._source else self._source_state,
            "last_poll_ts": self._last_poll_ts,
            "tickets": {str(k): v for k, v in self._tickets.items()},
            "alerts": [asdict(a) for a in self._alerts.values()],
        }
        path = state_path()
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            log.exception("could not write %s", path)

    def _prune_tickets(self) -> None:
        cutoff = time.time() - STATE_RETENTION_DAYS * 86400
        keep = {k: v for k, v in self._tickets.items()
                if v.get("seen", 0) >= cutoff or k in self._alerts}
        if len(keep) > MAX_TRACKED_TICKETS:
            ordered = sorted(keep.items(), key=lambda kv: kv[1].get("seen", 0), reverse=True)
            keep = dict(ordered[:MAX_TRACKED_TICKETS])
        self._tickets = keep

    # ------------------------------------------------------------------ #
    # polling
    # ------------------------------------------------------------------ #

    @Slot()
    def _tick(self) -> None:
        if self._polling:
            return
        self._polling = True
        try:
            if self._config.is_off_day():
                self._handle_off_day()
            else:
                self._off_day_announced = False
                self._poll()
                self._set_auth_ok(True, "")
        except AuthExpired as exc:
            log.error("sign-in expired: %s", exc)
            self._set_auth_ok(False, str(exc))
        except AuthError as exc:
            # Network trouble during refresh: the sign-in may still be good.
            log.error("auth problem: %s", exc)
            self.status_changed.emit("Zendesk error")
            self.error_occurred.emit(str(exc))
        except ZendeskError as exc:
            log.error("poll failed: %s", exc)
            self.status_changed.emit("Zendesk error")
            self.error_occurred.emit(str(exc))
        except Exception as exc:  # keep the timer alive whatever happens
            log.exception("unexpected poll failure")
            self.status_changed.emit("Error")
            self.error_occurred.emit("Unexpected error: {}".format(exc))
        finally:
            self._polling = False
            self._schedule_next()

    def _handle_off_day(self) -> None:
        """An off day is genuinely idle: no requests, no warnings.

        We deliberately leave ``_last_poll_ts`` alone. By the next working day it is
        far enough in the past that the staleness check triggers a silent re-seed,
        so the backlog that built up while we were away never lands as alerts.
        """
        if not self._off_day_announced:
            log.info("%s - not polling Zendesk today", self._config.mode_label())
            self._off_day_announced = True
        if self._alerts:
            self._alerts.clear()
            self._save_state()
        self._emit_alerts()
        self.status_changed.emit("Off Day - not polling")

    def _poll(self) -> None:
        if self._client is None:
            self._rebuild_client()
        if self._client is None:
            return
        if self._source is None:
            self._build_source()

        self._refresh_groups()

        cold_start = not self._source.is_primed
        stale = not cold_start and (time.time() - self._last_poll_ts) > STALE_RESUME_SECONDS
        silent = cold_start or stale
        if silent:
            why = "first run" if cold_start else "app was asleep"
            log.info("seeding ticket state silently (%s)", why)
            self.status_changed.emit("Catching up...")

        tickets = self._source.fetch(cold=silent)
        for ticket in tickets:
            self._process_ticket(ticket, silent=silent)
        changed = len(tickets)

        self._last_poll_ts = time.time()
        self._resolve_requesters()
        self._reconcile_alerts()
        self._save_state()

        if changed:
            log.info("processed %d changed tickets via %s (silent=%s)",
                     changed, self._source.name, silent)
        self._emit_alerts()
        self._emit_status()

    def _build_source(self) -> None:
        """Pick the ticket source once per sign-in, then remember which it was."""
        user = self._tokens.user
        self._source = sources.build(
            self._client, prefer_incremental=user.is_admin, saved=self._source_state)
        if self._source_state.get("kind") not in (None, self._source.name):
            log.info("ticket source changed to %s; re-seeding", self._source.name)
        self._source_state = self._source.state()

    def _resolve_requesters(self) -> None:
        """Put a name to every live alert, in one request for the lot.

        Deliberately best-effort and deliberately after the rules have run: who
        asked is worth showing, but it is never worth delaying or losing a warning
        over. Anything unresolved just stays blank, and is retried next poll.
        """
        missing = {a.requester_id for a in self._alerts.values()
                   if a.requester_id and not a.requester_name}
        unknown = missing - self._requesters.keys()

        if unknown and self._client is not None:
            try:
                self._requesters.update(self._client.users_by_id(unknown))
            except ZendeskError:
                log.warning("could not look up %d requester name(s)", len(unknown),
                            exc_info=True)

        for alert in self._alerts.values():
            if alert.requester_id and not alert.requester_name:
                alert.requester_name = self._requesters.get(alert.requester_id, "")

        still_blank = sum(1 for a in self._alerts.values()
                          if a.requester_id and not a.requester_name)
        if unknown:
            log.info("looked up %d requester name(s); %d still unresolved",
                     len(unknown), still_blank)

    def _refresh_groups(self) -> None:
        if self._client is None:
            return
        if time.time() - self._groups_fetched_at < GROUP_REFRESH_SECONDS:
            return
        try:
            groups = self._client.groups()
        except ZendeskError:
            log.warning("could not refresh groups", exc_info=True)
            return
        self._groups = {int(g["id"]): g.get("name", "") for g in groups}
        self._groups_fetched_at = time.time()

    # ------------------------------------------------------------------ #
    # transition rules
    # ------------------------------------------------------------------ #

    def _is_watched_group(self, group_id: int | None) -> bool:
        watched = self._config.watched_group_ids
        if not watched:
            return True  # empty selection means "every group"
        return group_id is not None and int(group_id) in watched

    def _needs_owner(self, snapshot: dict[str, Any] | None) -> bool:
        """True when this snapshot is an unassigned ticket we care about."""
        if not snapshot:
            return False
        return (
            snapshot.get("assignee_id") is None
            and snapshot.get("status") in ACTIONABLE_STATUSES
            and self._is_watched_group(snapshot.get("group_id"))
        )

    def _is_my_reopened(self, snapshot: dict[str, Any] | None) -> bool:
        my_id = self._tokens.user.id
        if not (snapshot and my_id):
            return False
        return snapshot.get("status") == "open" and snapshot.get("assignee_id") == int(my_id)

    @staticmethod
    def _snapshot(ticket: dict[str, Any]) -> dict[str, Any]:
        assignee = ticket.get("assignee_id")
        group = ticket.get("group_id")
        requester = ticket.get("requester_id")
        return {
            "status": ticket.get("status"),
            "assignee_id": int(assignee) if assignee else None,
            "group_id": int(group) if group else None,
            "requester_id": int(requester) if requester else None,
            "subject": (ticket.get("subject") or "").strip(),
            "created_at": str(ticket.get("created_at") or ""),
            "seen": time.time(),
        }

    def _process_ticket(self, ticket: dict[str, Any], silent: bool) -> None:
        ticket_id = int(ticket["id"])
        prev = self._tickets.get(ticket_id)
        curr = self._snapshot(ticket)
        self._tickets[ticket_id] = curr

        if silent or not self._config.is_active():
            # Keep the state map current, but never raise while catching up or paused.
            self._drop_alert_if_resolved(ticket_id, curr)
            return

        cfg = self._config

        # --- rule 1: nobody owns this ticket ------------------------------
        if self._needs_owner(curr) and not self._needs_owner(prev):
            brand_new = prev is None
            reason = REASON_NEW_UNASSIGNED if brand_new else REASON_BECAME_UNASSIGNED
            if cfg.rule_enabled(reason):
                self._raise_alert(ticket_id, reason, curr)

        # --- rule 2: my ticket bounced from pending back to open ----------
        if (cfg.rule_enabled(REASON_PENDING_TO_OPEN)
                and prev is not None
                and prev.get("status") == "pending"
                and self._is_my_reopened(curr)):
            self._raise_alert(ticket_id, REASON_PENDING_TO_OPEN, curr)

        self._drop_alert_if_resolved(ticket_id, curr)

    def _raise_alert(self, ticket_id: int, reason: str, snapshot: dict[str, Any]) -> None:
        existing = self._alerts.get(ticket_id)
        if existing and existing.reason == reason:
            return
        group_id = snapshot.get("group_id")
        alert = Alert(
            ticket_id=ticket_id,
            reason=reason,
            subject=snapshot.get("subject") or "Ticket #{}".format(ticket_id),
            group_id=group_id,
            group_name=self._groups.get(group_id, "") if group_id else "",
            raised_at=time.time(),
            requester_id=snapshot.get("requester_id"),
            # Filled in afterwards, in one request for the whole batch.
            requester_name=self._requesters.get(snapshot.get("requester_id"), ""),
            created_at=snapshot.get("created_at") or "",
        )
        self._alerts[ticket_id] = alert
        log.info("ALERT %s: #%s %s", reason, ticket_id, alert.subject[:70])

    def _drop_alert_if_resolved(self, ticket_id: int, snapshot: dict[str, Any]) -> None:
        alert = self._alerts.get(ticket_id)
        if alert is None:
            return
        if alert.reason == REASON_PENDING_TO_OPEN:
            still_valid = self._is_my_reopened(snapshot)
        else:
            still_valid = self._needs_owner(snapshot)
        if not still_valid:
            log.info("cleared alert on #%s (%s)", ticket_id, alert.reason)
            del self._alerts[ticket_id]

    def _prune_alerts_outside_scope(self) -> None:
        """After a settings or mode change, drop alerts that no longer apply."""
        for ticket_id, alert in list(self._alerts.items()):
            if not self._config.rule_enabled(alert.reason):
                log.info("cleared alert on #%s (%s no longer active in %s)",
                         ticket_id, alert.reason, self._config.mode_label())
                del self._alerts[ticket_id]
                continue
            snapshot = self._tickets.get(ticket_id)
            if snapshot:
                self._drop_alert_if_resolved(ticket_id, snapshot)

    def _reconcile_alerts(self) -> None:
        """Re-read the tickets we are alerting on, in case we missed an update."""
        if not self._alerts or self._client is None:
            return
        try:
            tickets = self._client.tickets_by_id(list(self._alerts))
        except ZendeskError:
            log.warning("alert reconcile failed", exc_info=True)
            return
        seen = set()
        for ticket in tickets:
            ticket_id = int(ticket["id"])
            seen.add(ticket_id)
            snapshot = self._snapshot(ticket)
            self._tickets[ticket_id] = snapshot
            self._drop_alert_if_resolved(ticket_id, snapshot)
        for missing in set(self._alerts) - seen:  # deleted or no longer visible
            log.info("cleared alert on #%s (ticket no longer readable)", missing)
            del self._alerts[missing]

    # ------------------------------------------------------------------ #
    # outward signals & commands
    # ------------------------------------------------------------------ #

    def _emit_alerts(self) -> None:
        ordered = sorted(self._alerts.values(), key=lambda a: a.raised_at)
        self.alerts_changed.emit(ordered)

    def _set_auth_ok(self, ok: bool, message: str) -> None:
        if ok == self._auth_ok:
            return
        self._auth_ok = ok
        log.info("auth state -> %s", "ok" if ok else "needs sign-in")
        self.auth_state_changed.emit(ok, message)
        if not ok:
            self.status_changed.emit("Sign-in expired")

    def _emit_status(self) -> None:
        if not self._auth_ok:
            self.status_changed.emit("Sign-in expired")
            return
        if not self._config.enabled:
            self.status_changed.emit("Disabled")
        elif self._config.is_paused():
            self.status_changed.emit("Paused")
        elif self._config.is_off_day():
            self.status_changed.emit("Off Day - not polling")
        elif self._alerts:
            self.status_changed.emit("{} ticket(s) need attention".format(len(self._alerts)))
        else:
            self.status_changed.emit("Watching · {}".format(self._config.mode_label()))

    @Slot()
    def dismiss_all(self) -> None:
        """User clicked the warning: clear it until something new happens."""
        if self._alerts:
            log.info("user dismissed %d alert(s)", len(self._alerts))
            self._alerts.clear()
            self._save_state()
        self._emit_alerts()
        self._emit_status()

    @Slot(int)
    def dismiss_one(self, ticket_id: int) -> None:
        if self._alerts.pop(int(ticket_id), None) is not None:
            self._save_state()
        self._emit_alerts()
        self._emit_status()

    @Slot()
    def poll_now(self) -> None:
        if self._timer:
            self._timer.stop()
        self._tick()

    @Slot()
    def reset_sign_in(self) -> None:
        """Called after a fresh sign-in: rebuild everything against the new user."""
        self._source_state = {}
        self._auth_ok = True
        self._rebuild_client()
        self._alerts.clear()
        self._tickets.clear()
        self._save_state()
        self._emit_alerts()
        self.poll_now()
