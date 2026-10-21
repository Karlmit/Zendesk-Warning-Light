r"""Prove out the V2 sign-in flow before any of it is wired into the app.

Runs the real authorization-code + PKCE flow against a PUBLIC Zendesk OAuth client
(no client secret anywhere), then reports what the resulting token can actually do.

    .\.venv\Scripts\python.exe tools\verify_oauth.py

Anyone can run it - hand it to a colleague who is a plain agent and it will show
whether the agent-safe ticket source is really needed for them.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import http.server
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

import requests

SUBDOMAIN = "yourcompany"
CLIENT_ID = "warning_light_desktop"
SCOPE = "read"
PORTS = (47821, 47822, 47823)
CALLBACK_PATH = "/callback"
CODE_TIMEOUT = 180          # Zendesk's code is valid 120s; allow time to sign in

# The classic path. The newer docs also show /oauth/authorize, but on this instance
# that redirects to /hc/restricted instead of starting the agent sign-in.
AUTHORIZE_PATH = "/oauth/authorizations/new"
TOKEN_PATH = "/oauth/tokens"


# ---------------------------------------------------------------------- #
# PKCE
# ---------------------------------------------------------------------- #

def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_pkce() -> tuple[str, str]:
    verifier = b64url(os.urandom(32))                     # 43 chars, within 43-128
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ---------------------------------------------------------------------- #
# loopback listener
# ---------------------------------------------------------------------- #

class _Catcher(http.server.BaseHTTPRequestHandler):
    result: dict = {}
    timeout = 10                        # an idle connection must not wedge the listener

    def do_GET(self) -> None:          # noqa: N802 - required name
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        _Catcher.result = {k: v[0] for k, v in query.items()}

        ok = "code" in _Catcher.result
        body = (
            "<h2>Signed in.</h2><p>You can close this tab and go back to the terminal.</p>"
            if ok else
            "<h2>Sign-in failed.</h2><pre>{}</pre>".format(html.escape(str(_Catcher.result)))
        )
        payload = ("<html><body style='font-family:system-ui;padding:40px'>"
                   + body + "</body></html>").encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass                            # keep the console clean


def start_listener() -> tuple[http.server.HTTPServer, int]:
    last_error: OSError | None = None
    for port in PORTS:
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), _Catcher)
        except OSError as exc:
            last_error = exc
            print("   port {} busy, trying the next one".format(port))
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, port
    raise SystemExit("None of the registered ports {} are free: {}".format(PORTS, last_error))


# ---------------------------------------------------------------------- #
# flow
# ---------------------------------------------------------------------- #

def sign_in(base: str, port: int) -> dict:
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    redirect_uri = "http://127.0.0.1:{}{}".format(port, CALLBACK_PATH)

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = "{}{}?{}".format(base, AUTHORIZE_PATH, urllib.parse.urlencode(params))

    print("\n2. Opening your browser to sign in as yourself...")
    print("   (if nothing opens, paste this URL manually)\n   {}\n".format(url))
    webbrowser.open(url)

    deadline = time.time() + CODE_TIMEOUT
    while not _Catcher.result and time.time() < deadline:
        time.sleep(0.3)
    if not _Catcher.result:
        raise SystemExit("Timed out waiting for the browser redirect.")

    result = _Catcher.result
    if "error" in result:
        raise SystemExit("Zendesk returned an error: {} - {}".format(
            result.get("error"), result.get("error_description", "")))
    if result.get("state") != state:
        raise SystemExit("State mismatch - possible CSRF. Aborting.")
    print("   got an authorization code, state verified")

    print("\n3. Exchanging the code for a token (no client_secret sent)...")
    resp = requests.post(
        base + TOKEN_PATH,
        json={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "scope": SCOPE,
        },
        timeout=30,
        allow_redirects=False,
    )
    if not resp.ok:
        raise SystemExit("Token exchange failed ({}): {}".format(resp.status_code, resp.text[:400]))

    token = resp.json()
    print("   access token issued, expires_in={}s".format(token.get("expires_in")))
    print("   refresh token: {}".format("yes" if token.get("refresh_token") else "NO - would mean re-signing in every 30 min"))
    return token


def try_refresh(base: str, refresh_token: str) -> None:
    print("\n5. Testing the silent refresh (this is what keeps you signed in)...")
    resp = requests.post(
        base + TOKEN_PATH,
        json={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30,
        allow_redirects=False,
    )
    if not resp.ok:
        print("   FAILED ({}): {}".format(resp.status_code, resp.text[:300]))
        return
    fresh = resp.json()
    rotated = fresh.get("refresh_token") and fresh["refresh_token"] != refresh_token
    print("   refresh worked, new access token expires_in={}s".format(fresh.get("expires_in")))
    print("   refresh token rotated: {}".format(
        "yes - the app must store the new one each time" if rotated else "no"))


def check_capabilities(base: str, access_token: str) -> None:
    headers = {"Authorization": "Bearer " + access_token}

    print("\n4. Who am I, and what can this token read?")
    me = requests.get(base + "/api/v2/users/me.json", headers=headers, timeout=30)
    if not me.ok:
        print("   /users/me failed ({}): {}".format(me.status_code, me.text[:200]))
        return
    user = me.json()["user"]
    print("   signed in as : {} <{}>".format(user.get("name"), user.get("email")))
    print("   role         : {}".format(user.get("role")))

    # This is the field V2 uses to decide whether to narrow the group checklist.
    # False = this user can see every ticket in the account, so all groups are
    # meaningful. True = they only see tickets in groups they belong to.
    restricted = user.get("restricted_agent")
    print("   restricted   : {}{}".format(
        restricted,
        "  -> group list should be limited to their own groups" if restricted
        else "  -> sees all tickets, whole group list is usable"))

    # The Settings dialog builds its checklist from /groups.json and pre-ticks using
    # one of three membership endpoints. Report the status of every one, because a
    # plain agent account came up with an empty group list and only the status codes
    # say which call is the problem.
    uid = user["id"]
    endpoints = (
        ("all groups", "/api/v2/groups.json", "groups", None),
        ("my groups", "/api/v2/users/{}/groups.json".format(uid), "groups", None),
        ("my memberships", "/api/v2/users/{}/group_memberships.json".format(uid),
         "group_memberships", None),
        ("all memberships", "/api/v2/group_memberships.json", "group_memberships", uid),
    )

    total: list[dict] = []
    mine_ids: set = set()
    print("\n   group endpoints (the app tries these in order):")
    for label, path, key, filter_uid in endpoints:
        resp = requests.get(base + path, headers=headers,
                            params={"per_page": 100}, timeout=30)
        if not resp.ok:
            print("     {:<16} HTTP {}  <-- REFUSED  {}".format(
                label, resp.status_code, resp.text[:70].replace("\n", " ")))
            continue
        rows = resp.json().get(key) or []
        if filter_uid is not None:
            rows = [r for r in rows if int(r.get("user_id", 0)) == int(filter_uid)]
        print("     {:<16} HTTP {}  -> {} row(s)".format(label, resp.status_code, len(rows)))
        if label == "all groups":
            total = [g for g in rows if not g.get("deleted")]
        elif not mine_ids:
            mine_ids = {int(r["id"] if "id" in r and key == "groups" else r["group_id"])
                        for r in rows}

    if not total:
        print("\n     The Settings group list would be EMPTY. Leaving every group"
              "\n     unticked still works - it then watches whatever you can see.")
    else:
        print("\n   what the Settings list would show ({} groups, {} pre-ticked):".format(
            len(total), len(mine_ids)))
        for g in sorted(total, key=lambda g: (g.get("name") or "").lower()):
            print("      [{}] {}".format("x" if int(g["id"]) in mine_ids else " ",
                                         g.get("name")))

    print("\n   ticket sources:")
    inc = requests.get(
        base + "/api/v2/incremental/tickets/cursor.json",
        headers=headers, params={"start_time": int(time.time()) - 3600}, timeout=30)
    if inc.ok:
        print("     incremental export  HTTP {}  -> {} tickets (admin-only endpoint)".format(
            inc.status_code, len(inc.json().get("tickets", []))))
    else:
        print("     incremental export  HTTP {}  -> NOT AVAILABLE to this user".format(inc.status_code))

    sweep = requests.get(
        base + "/api/v2/tickets.json", headers=headers,
        params={"sort_by": "updated_at", "sort_order": "desc", "per_page": 5}, timeout=30)
    if sweep.ok:
        tickets = sweep.json().get("tickets", [])
        print("     tickets.json sweep  HTTP {}  -> {} tickets (agent-safe fallback)".format(
            sweep.status_code, len(tickets)))
        for t in tickets[:3]:
            print("        #{} {:<8} assignee={} group={}".format(
                t["id"], t["status"], t.get("assignee_id"), t.get("group_id")))
    else:
        print("     tickets.json sweep  HTTP {}  -> {}".format(sweep.status_code, sweep.text[:150]))


def main() -> int:
    global CLIENT_ID

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subdomain", default=SUBDOMAIN)
    parser.add_argument("--client-id", default=CLIENT_ID,
                        help="override the OAuth client identifier")
    args = parser.parse_args()

    CLIENT_ID = args.client_id
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.subdomain):
        raise SystemExit("--subdomain must be just the part before .zendesk.com")
    base = "https://{}.zendesk.com".format(args.subdomain)

    print("=" * 68)
    print("Zendesk Warning Light - V2 sign-in check")
    print("=" * 68)
    print("instance  : {}".format(base))
    print("client id : {}  (public client, no secret)".format(CLIENT_ID))

    print("\n1. Starting the loopback listener...")
    server, port = start_listener()
    print("   listening on http://127.0.0.1:{}{}".format(port, CALLBACK_PATH))

    try:
        token = sign_in(base, port)
        check_capabilities(base, token["access_token"])
        if token.get("refresh_token"):
            try_refresh(base, token["refresh_token"])
    finally:
        server.shutdown()
        server.server_close()

    print("\n" + "=" * 68)
    print("If every step above succeeded, the V2 auth design is sound.")
    print("Nothing was stored on disk - this check is throwaway.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
