"""Per-user Zendesk sign-in: authorization code + PKCE against a public OAuth client.

Why this shape
--------------
The app is distributed as an .exe, so it is a *public* client - there is no way to
keep a secret in it. Zendesk's public client kind requires PKCE and accepts the
token exchange with no ``client_secret`` at all, so the only value we ship is the
client identifier, which is not sensitive.

Tokens
------
Access tokens live 30 minutes; refresh tokens live 30 days and **rotate on every
use**, so the new refresh token must be stored or the next refresh fails. Only the
refresh token is persisted (DPAPI-encrypted); the access token is kept in memory and
re-minted on startup.

Threading
---------
:class:`TokenStore` is shared between the Qt UI thread and the monitor worker
thread, so every read-modify-write goes through one lock. Because refresh tokens
rotate, two concurrent refreshes would invalidate each other - the lock plus an
expiry re-check inside it means only one ever runs.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from typing import Any

import requests

from . import keystore
from .paths import tokens_path

log = logging.getLogger(__name__)

CLIENT_ID = "warning_light_desktop"
SCOPE = "read"

# Registered on the OAuth client as redirect URLs, in this order.
CALLBACK_PORTS = (47821, 47822, 47823)
CALLBACK_PATH = "/callback"
CALLBACK_HOST = "127.0.0.1"

# The classic authorize path. The newer docs also show /oauth/authorize, but that
# redirects to /hc/restricted instead of starting the agent sign-in.
AUTHORIZE_PATH = "/oauth/authorizations/new"
TOKEN_PATH = "/oauth/tokens"

SIGN_IN_TIMEOUT = 240          # Zendesk's code is valid 120s; allow time for SSO
REFRESH_MARGIN = 120           # refresh this long before the access token expires
REQUEST_TIMEOUT = 30


class AuthError(RuntimeError):
    """Sign-in or refresh failed for a reason the user may be able to fix."""


class AuthExpired(AuthError):
    """No usable token and no way to get one without the user signing in again."""


# ---------------------------------------------------------------------- #
# PKCE
# ---------------------------------------------------------------------- #

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 using S256."""
    verifier = _b64url(os.urandom(32))          # 43 chars, inside the 43-128 range
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ---------------------------------------------------------------------- #
# stored identity
# ---------------------------------------------------------------------- #

@dataclass
class SignedInUser:
    id: int = 0
    name: str = ""
    email: str = ""
    role: str = ""
    restricted_agent: bool = False

    @classmethod
    def from_api(cls, user: dict[str, Any]) -> "SignedInUser":
        return cls(
            id=int(user["id"]),
            name=user.get("name") or "",
            email=user.get("email") or "",
            role=user.get("role") or "",
            restricted_agent=bool(user.get("restricted_agent")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "role": self.role, "restricted_agent": self.restricted_agent,
        }

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def describe(self) -> str:
        if not self.id:
            return "not signed in"
        return "{} <{}> ({})".format(self.name, self.email, self.role)


# ---------------------------------------------------------------------- #
# token store
# ---------------------------------------------------------------------- #

@dataclass
class TokenStore:
    """Holds the rotating refresh token and mints access tokens on demand."""

    base_url: str = ""
    client_id: str = CLIENT_ID
    _refresh_token: str = ""
    _access_token: str = ""
    _expires_at: float = 0.0
    user: SignedInUser = field(default_factory=SignedInUser)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # --- persistence --------------------------------------------------- #

    def load(self) -> None:
        path = tokens_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("tokens.json unreadable; sign-in will be required")
            return
        with self._lock:
            self._refresh_token = keystore.decrypt(data.get("refresh_token_enc", ""))
            self.user = SignedInUser(**{
                k: v for k, v in (data.get("user") or {}).items()
                if k in SignedInUser.__dataclass_fields__
            })
            # Access tokens are not persisted - they only last 30 minutes.
            self._access_token = ""
            self._expires_at = 0.0
        if self._refresh_token:
            log.info("restored Zendesk sign-in for %s", self.user.describe())

    def save(self) -> None:
        path = tokens_path()
        with self._lock:
            payload = {
                "refresh_token_enc": keystore.encrypt(self._refresh_token),
                "user": self.user.to_dict(),
                "saved_at": time.time(),
            }
        try:
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            log.exception("could not write %s", path)

    def clear(self) -> None:
        with self._lock:
            self._refresh_token = ""
            self._access_token = ""
            self._expires_at = 0.0
            self.user = SignedInUser()
        try:
            tokens_path().unlink(missing_ok=True)
        except OSError:
            log.exception("could not delete tokens.json")
        log.info("signed out")

    # --- state --------------------------------------------------------- #

    @property
    def is_signed_in(self) -> bool:
        with self._lock:
            return bool(self._refresh_token)

    def _apply(self, payload: dict[str, Any]) -> None:
        """Adopt a token response. Caller must hold the lock."""
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 1800))
        rotated = payload.get("refresh_token")
        if rotated:
            self._refresh_token = rotated       # the old one is now dead

    def _adopt_rotated_token_locked(self, already_tried: str) -> bool:
        """Re-read tokens.json; adopt a refresh token newer than the one that failed.

        Caller must hold the lock. Returns True when a different token was found.
        """
        path = tokens_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            log.warning("could not re-read %s while recovering a refresh", path)
            return False
        stored = keystore.decrypt(data.get("refresh_token_enc", ""))
        if not stored or stored == already_tried:
            return False
        self._refresh_token = stored
        return True

    # --- getting a usable token ---------------------------------------- #

    def access_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            fresh_enough = (
                self._access_token
                and time.time() < self._expires_at - REFRESH_MARGIN
            )
            if fresh_enough and not force_refresh:
                return self._access_token
            if not self._refresh_token:
                raise AuthExpired("You need to sign in to Zendesk.")
            self._refresh_locked()
            return self._access_token

    def _refresh_locked(self, allow_reload: bool = True) -> None:
        log.info("refreshing the Zendesk access token")
        attempted = self._refresh_token
        try:
            resp = requests.post(
                self.base_url.rstrip("/") + TOKEN_PATH,
                json={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": attempted,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            # Network trouble is not an expired sign-in - keep the refresh token.
            raise AuthError("Could not reach Zendesk to refresh the token: {}".format(exc)) from exc

        if resp.status_code in (400, 401, 403):
            # Refresh tokens rotate, so another process that refreshed against the
            # same tokens.json has already invalidated the copy we just tried. Before
            # declaring the sign-in dead, re-read the file: if it now holds a newer
            # token, adopt that and try once more.
            if allow_reload and self._adopt_rotated_token_locked(attempted):
                log.info("another process had rotated the refresh token; retrying")
                self._refresh_locked(allow_reload=False)
                return
            self._refresh_token = ""
            self._access_token = ""
            self._expires_at = 0.0
            self.save()
            log.error("refresh token rejected (%s): %s", resp.status_code, resp.text[:200])
            raise AuthExpired(
                "Your Zendesk sign-in has expired. Open Settings and sign in again."
            )
        if not resp.ok:
            raise AuthError("Token refresh failed ({}): {}".format(resp.status_code, resp.text[:200]))

        self._apply(resp.json())
        self.save()
        log.info("token refreshed; next expiry in %ds", int(self._expires_at - time.time()))

    # --- interactive sign-in ------------------------------------------- #

    def sign_in(self, base_url: str, client_id: str = CLIENT_ID) -> SignedInUser:
        """Run the browser flow. Blocking - call from a worker thread."""
        base = base_url.rstrip("/")
        verifier, challenge = make_pkce()
        state = secrets.token_urlsafe(24)

        server, port = _start_listener()
        redirect_uri = "http://{}:{}{}".format(CALLBACK_HOST, port, CALLBACK_PATH)
        try:
            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            url = "{}{}?{}".format(base, AUTHORIZE_PATH, urllib.parse.urlencode(params))
            log.info("opening the browser for Zendesk sign-in on port %d", port)
            webbrowser.open(url)

            deadline = time.time() + SIGN_IN_TIMEOUT
            while not _Callback.result and time.time() < deadline:
                time.sleep(0.2)
            result = dict(_Callback.result)
        finally:
            server.shutdown()
            _Callback.result = {}

        if not result:
            raise AuthError(
                "Timed out waiting for the browser. If no browser opened, check that "
                "one of ports {} is free.".format(", ".join(str(p) for p in CALLBACK_PORTS))
            )
        if "error" in result:
            raise AuthError("Zendesk refused the sign-in: {} {}".format(
                result.get("error"), result.get("error_description", "")))
        if result.get("state") != state:
            raise AuthError("Sign-in state mismatch - aborted as a precaution.")

        payload = self._exchange_code(base, client_id, result["code"], verifier, redirect_uri)

        with self._lock:
            self.base_url = base
            self.client_id = client_id
            self._apply(payload)
            if not self._refresh_token:
                raise AuthError(
                    "Zendesk issued no refresh token, so the app could not stay signed in. "
                    "Check that 'Expire tokens' is enabled on the OAuth client."
                )
            token = self._access_token

        user = self._fetch_user(base, token)
        with self._lock:
            self.user = user
        self.save()
        log.info("signed in as %s", user.describe())
        return user

    def _exchange_code(self, base: str, client_id: str, code: str,
                       verifier: str, redirect_uri: str) -> dict[str, Any]:
        try:
            resp = requests.post(
                base + TOKEN_PATH,
                json={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "code_verifier": verifier,     # replaces the client secret
                    "redirect_uri": redirect_uri,
                    "scope": SCOPE,
                },
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise AuthError("Could not reach {}: {}".format(base, exc)) from exc

        if not resp.ok:
            raise AuthError(
                "Zendesk rejected the sign-in ({}).\n{}\n\n"
                "Check that the OAuth client is of kind 'Public' and that "
                "{} is one of its redirect URLs.".format(
                    resp.status_code, resp.text[:300], redirect_uri)
            )
        return resp.json()

    @staticmethod
    def _fetch_user(base: str, access_token: str) -> SignedInUser:
        resp = requests.get(
            base + "/api/v2/users/me.json",
            headers={"Authorization": "Bearer " + access_token},
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise AuthError("Signed in, but could not read your Zendesk profile "
                            "({}).".format(resp.status_code))
        return SignedInUser.from_api(resp.json()["user"])


# ---------------------------------------------------------------------- #
# loopback listener
# ---------------------------------------------------------------------- #

_PAGE = (
    "<html><head><meta charset='utf-8'><title>Zendesk Warning Light</title></head>"
    "<body style=\"font-family:system-ui,Segoe UI,sans-serif;background:#14161c;"
    "color:#f5f6f8;display:flex;align-items:center;justify-content:center;"
    "height:100vh;margin:0\"><div style='text-align:center;max-width:30rem'>"
    "<h2 style='color:{colour}'>{title}</h2><p style='color:#9aa0aa'>{body}</p>"
    "</div></body></html>"
)


class _Callback(http.server.BaseHTTPRequestHandler):
    result: dict[str, str] = {}

    def do_GET(self) -> None:          # noqa: N802 - name fixed by the framework
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        _Callback.result = {
            k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()
        }
        ok = "code" in _Callback.result
        page = _PAGE.format(
            colour="#ffb020" if ok else "#e0533d",
            title="Signed in" if ok else "Sign-in failed",
            body=("You can close this tab - the warning light is connected."
                  if ok else "Go back to the app and try again."),
        ).encode("utf-8")

        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args) -> None:
        pass                            # never write to stdout in a windowed app


def _start_listener() -> tuple[http.server.HTTPServer, int]:
    _Callback.result = {}
    last: OSError | None = None
    for port in CALLBACK_PORTS:
        try:
            server = http.server.HTTPServer((CALLBACK_HOST, port), _Callback)
        except OSError as exc:
            last = exc
            log.info("callback port %d busy, trying the next", port)
            continue
        threading.Thread(target=server.serve_forever, daemon=True,
                         name="oauth-callback").start()
        return server, port
    raise AuthError(
        "All callback ports ({}) are in use, so sign-in cannot complete: {}".format(
            ", ".join(str(p) for p in CALLBACK_PORTS), last)
    )
