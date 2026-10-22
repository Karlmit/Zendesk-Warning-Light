"""The refresh token must reach the Keychain without ever being a command-line
argument (SECURITY_REPORT.md L19), and must come back unchanged.

The argv check runs anywhere with a stand-in for subprocess.run. On a real Mac the
round trip runs against the login Keychain too, under a throwaway service name.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zwl import keystore  # noqa: E402

CHECKS = []


def check(label, got, want):
    CHECKS.append((label, got == want, got, want))


SECRET = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"

# --- argv never carries the secret (fake security binary) ------------------ #

calls = []
stored = {}
real_run = subprocess.run
real_which = keystore.shutil.which    # keystore.shutil is the shutil module itself


def fake_run(args, input=None, **kwargs):
    calls.append((list(args), input))
    if args[1:] == ["-i"]:
        stored["value"] = input.split('-w "', 1)[1].split('"', 1)[0]
        return subprocess.CompletedProcess(args, 0, "", "")
    if args[1] == "find-generic-password":
        return subprocess.CompletedProcess(args, 0, stored.get("value", "") + "\n", "")
    return subprocess.CompletedProcess(args, 0, "", "")


keystore.subprocess.run = fake_run
keystore.shutil.which = lambda name: name if name == keystore.SECURITY else None

check("encrypt returns the marker", keystore.encrypt(SECRET), keystore.MARKER)
check("the secret is never in argv", any(SECRET in " ".join(a) for a, _ in calls), False)
check("the secret went in on stdin", any(i and SECRET in i for _, i in calls), True)
check("only /usr/bin/security is run", {a[0] for a, _ in calls}, {keystore.SECURITY})
check("decrypt reads it back", keystore.decrypt(keystore.MARKER), SECRET)

calls.clear()
for bad in ('abc" -T "/tmp/evil', "abc\\", "abc\nxyz"):
    check("a value that could break the quoting is refused: {!r}".format(bad),
          keystore.encrypt(bad), "")
check("and no command ran for it", [a for a, _ in calls if a[1:] == ["-i"]], [])

keystore.shutil.which = lambda name: None
check("a security binary on PATH but not at /usr/bin is not used",
      keystore._security_available(), False)

# --- the real Keychain ------------------------------------------------------ #

keystore.subprocess.run = real_run
keystore.shutil.which = real_which

if sys.platform == "darwin":
    # On a Mac this must really run, never quietly skip.
    check("Keychain: /usr/bin/security exists", bool(real_which(keystore.SECURITY)), True)
    keystore.SERVICE = "com.yourcompany.zendeskwarninglight.selftest"
    try:
        check("Keychain: store", keystore.encrypt(SECRET), keystore.MARKER)
        check("Keychain: read back", keystore.decrypt(keystore.MARKER), SECRET)
        check("Keychain: update in place", keystore.encrypt(SECRET[::-1]), keystore.MARKER)
        check("Keychain: read the update", keystore.decrypt(keystore.MARKER), SECRET[::-1])
    finally:
        keystore.forget()
    check("Keychain: forget removes it", keystore.decrypt(keystore.MARKER), "")
else:
    print("not a Mac: skipped the real Keychain round trip")

failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
