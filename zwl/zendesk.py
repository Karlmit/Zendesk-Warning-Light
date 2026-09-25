"""Zendesk REST client that authenticates as the signed-in user.

All requests carry a bearer token from :class:`zwl.auth.TokenStore`. A 401 means the
access token died early, so we force one refresh and retry; if the refresh itself
fails the store raises :class:`zwl.auth.AuthExpired` and the app asks the user to
sign in again.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

import requests

from .auth import AuthError, TokenStore

log = logging.getLogger(__name__)

USER_AGENT = "ZendeskWarningLight/2.0"
MAX_GROUP_PAGES = 10


class ZendeskError(RuntimeError):
    """An API call failed for a reason worth showing the user."""


class ZendeskClient:
    def __init__(self, tokens: TokenStore, timeout: int = 20):
        self._tokens = tokens
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT

    @property
    def base_url(self) -> str:
        return self._tokens.base_url.rstrip("/")

    @property
    def user(self):
        return self._tokens.user

    # --- plumbing ---------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None,
            _retry: bool = True) -> dict[str, Any]:
        url = path if path.startswith("http") else self.base_url + path
        try:
            token = self._tokens.access_token()
        except AuthError:
            raise                       # AuthExpired must reach the app unchanged

        try:
            resp = self._session.get(
                url, headers={"Authorization": "Bearer " + token},
                params=params, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ZendeskError("Request to {} failed: {}".format(path, exc)) from exc

        if resp.status_code == 401 and _retry:
            log.info("got 401 on %s - forcing a token refresh", path)
            self._tokens.access_token(force_refresh=True)
            return self.get(path, params, _retry=False)

        if resp.status_code == 429:
            wait = min(int(resp.headers.get("Retry-After", "10")), 60)
            log.warning("rate limited on %s, sleeping %ss", path, wait)
            time.sleep(wait)
            if _retry:
                return self.get(path, params, _retry=False)

        if resp.status_code == 403:
            raise ZendeskError(
                "Your Zendesk account is not allowed to call {} (403).".format(path))
        if not resp.ok:
            raise ZendeskError("GET {} failed ({}): {}".format(
                path, resp.status_code, resp.text[:300]))
        return resp.json()

    def probe(self, path: str, params: dict[str, Any] | None = None) -> int:
        """HTTP status for a call we expect might be forbidden. Never raises on 4xx."""
        url = path if path.startswith("http") else self.base_url + path
        token = self._tokens.access_token()
        try:
            resp = self._session.get(
                url, headers={"Authorization": "Bearer " + token},
                params=params, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ZendeskError("Request to {} failed: {}".format(path, exc)) from exc
        return resp.status_code

    # --- endpoints --------------------------------------------------------

    def me(self) -> dict[str, Any]:
        return self.get("/api/v2/users/me.json")["user"]

    def groups(self) -> list[dict[str, Any]]:
        """Every group in the account. NOT filtered by the caller's membership."""
        out: list[dict[str, Any]] = []
        page = self.get("/api/v2/groups.json", {"per_page": 100})
        for _ in range(MAX_GROUP_PAGES):
            out.extend(g for g in page.get("groups", []) if not g.get("deleted"))
            nxt = page.get("next_page")
            if not nxt:
                break
            page = self.get(nxt)
        out.sort(key=lambda g: (g.get("name") or "").lower())
        return out

    def my_group_ids(self, user_id: int) -> set[int] | None:
        """IDs of the groups this user belongs to, or None if we cannot tell.

        Three endpoints are tried because what a non-admin agent may read varies:
        the convenience endpoint sometimes answers 200 with an empty list even for
        an agent who demonstrably has memberships. ``None`` means "unknown" and is
        emphatically *not* the same as "belongs to nothing" - callers must not use
        it to narrow a list down to nothing.
        """
        uid = int(user_id)
        attempts = (
            ("/api/v2/users/{}/groups.json".format(uid),
             lambda d: {int(g["id"]) for g in d.get("groups", []) if not g.get("deleted")}),
            ("/api/v2/users/{}/group_memberships.json".format(uid),
             lambda d: {int(m["group_id"]) for m in d.get("group_memberships", [])}),
            ("/api/v2/group_memberships.json",
             lambda d: {int(m["group_id"]) for m in d.get("group_memberships", [])
                        if int(m.get("user_id", 0)) == uid}),
        )
        for path, extract in attempts:
            try:
                ids = extract(self.get(path, {"per_page": 100}))
            except ZendeskError as exc:
                log.warning("%s unreadable: %s", path, exc)
                continue
            except (KeyError, TypeError, ValueError):
                log.warning("%s returned an unexpected shape", path, exc_info=True)
                continue
            if ids:
                log.info("resolved %d group membership(s) via %s", len(ids), path)
                return ids
            log.info("%s returned no memberships; trying the next endpoint", path)
        log.warning("could not determine group membership for user %s", uid)
        return None

    def incremental_tickets(self, cursor: str | None = None,
                            start_time: int | None = None
                            ) -> tuple[list[dict[str, Any]], str, bool]:
        """Cursor-based incremental export. Admins only - agents get a 403."""
        params = {"cursor": cursor} if cursor else {"start_time": start_time or int(time.time())}
        data = self.get("/api/v2/incremental/tickets/cursor.json", params)
        return (
            data.get("tickets", []),
            data.get("after_cursor") or cursor or "",
            bool(data.get("end_of_stream", True)),
        )

    def list_tickets_by_update(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        """Most-recently-updated tickets first. Allowed for agents."""
        data = self.get("/api/v2/tickets.json", {
            "sort_by": "updated_at",
            "sort_order": "desc",
            "per_page": per_page,
            "page": page,
        })
        return data.get("tickets", [])

    def tickets_by_id(self, ids: Iterable[int]) -> list[dict[str, Any]]:
        """Current state of specific tickets, used to reconcile live alerts."""
        wanted = [int(i) for i in ids]
        out: list[dict[str, Any]] = []
        for i in range(0, len(wanted), 100):
            chunk = wanted[i:i + 100]
            data = self.get("/api/v2/tickets/show_many.json",
                            {"ids": ",".join(str(t) for t in chunk)})
            out.extend(data.get("tickets", []))
        return out

    def users_by_id(self, ids: Iterable[int]) -> dict[int, str]:
        """Names for specific users, for showing who asked.

        Returns what it could find rather than raising on a partial answer: a
        missing name must never hold up a warning. Deleted users simply drop out
        of the response, and Zendesk allows 100 ids per request.
        """
        wanted = sorted({int(i) for i in ids if i})
        names: dict[int, str] = {}
        for i in range(0, len(wanted), 100):
            chunk = wanted[i:i + 100]
            data = self.get("/api/v2/users/show_many.json",
                            {"ids": ",".join(str(u) for u in chunk)})
            for user in data.get("users", []):
                name = (user.get("name") or "").strip()
                if name:
                    names[int(user["id"])] = name
        return names

    def ticket_url(self, ticket_id: int) -> str:
        return "{}/agent/tickets/{}".format(self.base_url, int(ticket_id))
