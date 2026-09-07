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

    def my_groups(self, user_id: int) -> list[dict[str, Any]] | None:
        """Groups this user belongs to, or None if Zendesk will not say."""
        try:
            data = self.get("/api/v2/users/{}/groups.json".format(int(user_id)),
                            {"per_page": 100})
        except ZendeskError:
            log.warning("could not read own group memberships", exc_info=True)
            return None
        groups = [g for g in data.get("groups", []) if not g.get("deleted")]
        groups.sort(key=lambda g: (g.get("name") or "").lower())
        return groups

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

    def ticket_url(self, ticket_id: int) -> str:
        return "{}/agent/tickets/{}".format(self.base_url, int(ticket_id))
