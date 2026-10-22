"""Regression checks for the fixes in SECURITY_REPORT.md.

Each check names the finding it guards (M1, L22, ...). They try the actual attack
against the fixed code, so a later change that reopens a hole fails here.
"""

import http.server
import json
import logging
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zwl import auth, config, zendesk                  # noqa: E402
from zwl.auth import AuthError, AuthExpired, TokenStore  # noqa: E402
from zwl.zendesk import ZendeskClient, ZendeskError    # noqa: E402

CHECKS = []


def check(label, got, want):
    CHECKS.append((label, got == want, got, want))


def raises(fn, exc_type):
    try:
        fn()
    except exc_type:
        return True
    except Exception as exc:            # the wrong kind of failure
        return "raised {}: {}".format(type(exc).__name__, exc)
    return False


TMP = Path(tempfile.mkdtemp(prefix="zwl-security-"))
auth.tokens_path = lambda: TMP / "tokens.json"
auth.keystore.encrypt = lambda s: s
auth.keystore.decrypt = lambda s: s
if hasattr(auth.keystore, "forget"):
    auth.keystore.forget = lambda: None


# --------------------------------------------------------------------------- #
# M1 - the subdomain can never move tokens off *.zendesk.com
# --------------------------------------------------------------------------- #

for typed in ("evil.com#", "a.evil.com/", "x@evil.com/", "acme.zendesk.com.evil.com",
              "acme:443", "acme/..", "", " ", "-acme", "a" * 64):
    check("M1 subdomain {!r} is rejected".format(typed),
          config.normalise_subdomain(typed), "")
for typed, want in (("Acme", "acme"), ("acme.zendesk.com", "acme"),
                    ("https://acme.zendesk.com/", "acme")):
    check("M1 subdomain {!r} is accepted".format(typed),
          config.normalise_subdomain(typed), want)
check("M1 config with a bad subdomain gets no usable base URL",
      raises(lambda: auth.check_base_url(
          config.Config.from_dict({"subdomain": "evil.com#"}).base_url), AuthError), True)
for url in ("https://evil.com", "http://acme.zendesk.com", "https://acme.zendesk.com.evil.com",
            "https://x@acme.zendesk.com", "https://acme.zendesk.com:8443"):
    check("M1 check_base_url refuses {}".format(url),
          raises(lambda: auth.check_base_url(url), AuthError), True)
check("M1 sign_in refuses a bad address before opening anything",
      raises(lambda: TokenStore().sign_in("https://evil.com"), AuthError), True)
check("M1 access_token refuses a bad address",
      raises(lambda: TokenStore(base_url="https://evil.com",
                                _refresh_token="r").access_token(), AuthError), True)


# --------------------------------------------------------------------------- #
# M2 / M7 - the bearer token only goes to the account's own host
# --------------------------------------------------------------------------- #

class Recorder(http.server.BaseHTTPRequestHandler):
    """A server that remembers every Authorization header it was sent."""

    seen = None                         # set per server
    reply = b"{}"

    def do_GET(self):
        self.seen.append(self.headers.get("Authorization"))
        body = self.reply
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(reply: bytes):
    seen: list = []
    handler = type("H", (Recorder,), {"seen": seen, "reply": reply})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


evil, evil_seen = serve(b'{"groups": []}')
evil_addr = "127.0.0.1:{}".format(evil.server_port)


class FakeTokens:
    user = None

    def __init__(self, base_url):
        self.base_url = base_url

    def access_token(self, force_refresh=False):
        return "secret-token"


for next_page in ("http://{}/api/v2/groups.json".format(evil_addr),   # another host
                  "@{}/api/v2/groups.json".format(evil_addr),          # M7: userinfo trick
                  "//{}/api/v2/groups.json".format(evil_addr)):        # scheme-relative
    good, good_seen = serve(json.dumps({
        "groups": [{"id": 1, "name": "One"}], "next_page": next_page}).encode())
    client = ZendeskClient(FakeTokens("http://127.0.0.1:{}".format(good.server_port)))
    check("M2/M7 next_page {!r} is refused".format(next_page[:24]),
          raises(client.groups, ZendeskError), True)
    check("M2/M7 the real host got the token", good_seen, ["Bearer secret-token"])
    good.shutdown()
check("M2/M7 the other host never received a request", evil_seen, [])
evil.shutdown()

client = ZendeskClient(FakeTokens("https://acme.zendesk.com"))
for path in ("@evil.com/x", ".evil.com/x", ":443@evil.com/x", "//evil.com/x",
             "HTTPS://evil.com/x", "https://evil.com/", "http://acme.zendesk.com/x",
             "https://u@acme.zendesk.com/x", "api/v2",
             "//[JJ", "https://[::1/x"):                         # S5: malformed hosts
    check("M7 _url refuses {!r}".format(path), raises(lambda: client._url(path), ZendeskError), True)
check("M7 a normal path still works", client._url("/api/v2/groups.json"),
      "https://acme.zendesk.com/api/v2/groups.json")


# --------------------------------------------------------------------------- #
# L1 - only the redirect carrying our state can end the sign-in wait
# --------------------------------------------------------------------------- #

def callback(port, query):
    url = "http://127.0.0.1:{}{}?{}".format(port, auth.CALLBACK_PATH, query)
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


server, port = auth._start_listener("expected-state")
try:
    check("L1 a wrong state is refused", callback(port, "state=nope&code=x"), 400)
    check("L1 an error without our state is refused", callback(port, "error=access_denied"), 400)
    check("L1 nothing was accepted yet", auth._Callback.result, {})
    check("L1 the real redirect is accepted", callback(port, "state=expected-state&code=c"), 200)
    check("L1 and its code is kept", auth._Callback.result.get("code"), "c")
    check("L1 a second redirect cannot replace it", callback(port, "state=expected-state&code=d"), 400)
finally:
    server.shutdown()
    server.server_close()
    auth._Callback.result = {}
    auth._Callback.expected_state = ""


# --------------------------------------------------------------------------- #
# L5, L6, I15, S4 - the token store
# --------------------------------------------------------------------------- #

class Reply:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}
        self.history = []
        self.url = ""

    def json(self):
        return self._payload


posts = []
next_reply = [Reply(200, {"access_token": "AT", "expires_in": 1800, "refresh_token": "RT2"})]


def fake_post(url, **kwargs):
    posts.append((url, kwargs))
    return next_reply[0]


auth.requests.post = fake_post

(TMP / "tokens.json").write_text(json.dumps({"refresh_token_enc": "RT1", "user": {"id": 1}}))
store = TokenStore(base_url="https://acme.zendesk.com")
store.load()
check("I15 an old tokens.json is pinned to the account configured now",
      getattr(store, "_issued_for", None), "https://acme.zendesk.com")
check("refresh works", store.access_token(), "AT")
check("L6 the refresh does not follow redirects", posts[-1][1].get("allow_redirects"), False)
saved = json.loads((TMP / "tokens.json").read_text())
check("I15 tokens.json records the issuing account", saved.get("base_url"), "https://acme.zendesk.com")
check("tokens.json holds no access token", "AT" in json.dumps(saved), False)
if os.name != "nt":
    check("L5 tokens.json is private (0600)", (TMP / "tokens.json").stat().st_mode & 0o777, 0o600)

other = TokenStore(base_url="https://other.zendesk.com")
other.load()
before = len(posts)
check("I15 another account is refused", raises(other.access_token, AuthExpired), True)
check("I15 and nothing is sent to it", len(posts), before)

next_reply[0] = Reply(400, {"error": "invalid_grant", "error_description": "leak-me-not"})
records = []
handler = logging.Handler()
handler.emit = records.append
auth.log.addHandler(handler)
store._access_token = ""
check("a rejected refresh asks for a new sign-in", raises(store.access_token, AuthExpired), True)
auth.log.removeHandler(handler)
logged = " ".join(r.getMessage() for r in records)
check("S4 the log names the OAuth error", "invalid_grant" in logged, True)
check("S4 the log does not copy the reply body", "leak-me-not" in logged, False)

posts.clear()
next_reply[0] = Reply(200, {"access_token": "AT", "refresh_token": "RT"})
auth.TokenStore()._exchange_code("https://acme.zendesk.com", "cid", "code", "verifier",
                                 "http://127.0.0.1:47821/callback")
check("L6 the code exchange does not follow redirects", posts[-1][1].get("allow_redirects"), False)


# --------------------------------------------------------------------------- #
# L8, L10, L22 - config.json cannot be turned against the user
# --------------------------------------------------------------------------- #

for bad in ({"poll_seconds": "soon"}, {"day_modes": "x"}, {"corner_by_screen": [1]}):
    path = TMP / "config.json"
    path.write_text(json.dumps(bad))
    config.config_path = lambda: path
    check("L8 config {} falls back to defaults".format(bad),
          isinstance(config.load(), config.Config), True)

for name in (r"\\attacker\share\x.wav", "../../x.wav", "/etc/passwd"):
    check("L10 sound {!r} is replaced by the default".format(name),
          config.Config.from_dict({"sound_name": name}).sound_name, config.sound.DEFAULT)

for path in (r"\\attacker\share\x.gif", "//attacker/share/x.gif", r"\\?\UNC\attacker\x.gif"):
    cfg = config.Config.from_dict({"animation": path})
    check("L22 animation {!r} is replaced".format(path), cfg.animation, config.DEFAULT_ANIMATION)
    check("L22 animation_path never returns {!r}".format(path),
          config.Config(animation=path).animation_path()[:2] in ("\\\\", "//", "\\/", "/\\"), False)


# --------------------------------------------------------------------------- #
# L12 - a hostile Retry-After cannot crash or stall the poll
# --------------------------------------------------------------------------- #

class Limited(http.server.BaseHTTPRequestHandler):
    value = ""

    def do_GET(self):
        self.send_response(429)
        self.send_header("Retry-After", self.value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


slept = []
zendesk.time.sleep = slept.append
for value, want in (("junk", 10), ("-5", 0), ("99999", 60), ("Wed, 21 Oct 2026 07:28:00 GMT", 10)):
    handler_cls = type("L", (Limited,), {"value": value})
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    client = ZendeskClient(FakeTokens("http://127.0.0.1:{}".format(srv.server_port)))
    slept.clear()
    raises(lambda: client.get("/api/v2/x.json"), ZendeskError)
    check("L12 Retry-After {!r} waits {}s".format(value, want), slept[:1], [want])
    srv.shutdown()


failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
