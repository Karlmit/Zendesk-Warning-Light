"""A reply that should be JSON but is not must say what it was, not 'Expecting value'."""

import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zwl.zendesk import ZendeskClient, ZendeskError   # noqa: E402

CHECKS = []


def check(label, got, want):
    CHECKS.append((label, got == want, got, want))


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/v2/empty"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/api/v2/redirect"):
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
        elif self.path.startswith("/login"):
            body = b"<html><body>Please sign in</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"groups": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *a):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:{}".format(server.server_port)


class FakeTokens:
    base_url = base
    user = None

    def access_token(self, force_refresh=False):
        return "t"


client = ZendeskClient(FakeTokens())


def failure(path):
    try:
        client.get(path)
    except ZendeskError as exc:
        return str(exc)
    return ""


empty = failure("/api/v2/empty.json")
check("empty body is a ZendeskError, not a bare parser error", "did not answer with JSON" in empty, True)
check("empty body is described as empty", "(empty)" in empty, True)
check("status is included", "HTTP 200" in empty, True)

redirected = failure("/api/v2/redirect.json")
check("redirect: reports the final address", "/login" in redirected, True)
check("redirect: reports that it was redirected", "redirect" in redirected, True)
check("redirect: shows the page text", "Please sign in" in redirected, True)

check("a good reply still parses", client.get("/api/v2/groups.json"), {"groups": []})

server.shutdown()

failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
