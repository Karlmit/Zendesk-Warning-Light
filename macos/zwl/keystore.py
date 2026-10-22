"""Store the Zendesk refresh token in the macOS Keychain.

The Windows build encrypts the token with DPAPI and keeps the ciphertext inside
``tokens.json``. macOS has a better home for it: the login Keychain, which is already
unlocked with the user's account and encrypted at rest with FileVault.

So on this platform ``tokens.json`` holds no secret at all - only the marker
:data:`MARKER`, telling us the real value lives in the Keychain. That keeps
:mod:`zwl.auth` identical to the Windows version: it still calls ``encrypt`` and
``decrypt`` and treats the result as an opaque string.

We shell out to ``/usr/bin/security`` rather than binding Security.framework
through ctypes: the CLI is on every Mac and needs no extra dependency. The token is
written through ``security -i`` on stdin, never as a command-line argument, so it
does not show up in ``ps`` while the command runs. Items made by the CLI trust the
CLI, so another process running as the same user could read this one back; on a
per-user laptop that process could read tokens.json and the log too.
"""

from __future__ import annotations

import base64
import logging
import shutil
import subprocess

log = logging.getLogger(__name__)

SECURITY = "/usr/bin/security"
SERVICE = "com.yourcompany.zendeskwarninglight"
ACCOUNT = "zendesk-refresh-token"

#: What we write into tokens.json in place of the secret.
MARKER = "keychain:v1"

_TIMEOUT = 15


def _security_available() -> bool:
    # Only the system copy: a "security" found on PATH could be anything.
    return bool(shutil.which(SECURITY))


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [SECURITY] + args,
        capture_output=True, text=True, timeout=_TIMEOUT, check=False,
    )


def _store(secret: str) -> bool:
    # Interactive mode reads the command from stdin, which keeps the secret out of
    # argv. Its line parser splits on spaces and honours double quotes, so a value
    # that could break out of the quotes is refused rather than escaped.
    if not secret or any(c in secret for c in '"\\\n\r'):
        log.error("refresh token has characters the Keychain command cannot carry")
        return False
    command = (
        'add-generic-password -s {} -a {} -D "application password" '
        '-j "Zendesk Warning Light sign-in" -U -w "{}"\n'
    ).format(SERVICE, ACCOUNT, secret)
    try:
        result = subprocess.run(
            [SECURITY, "-i"], input=command,
            capture_output=True, text=True, timeout=_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("could not run %s: %s", SECURITY, exc)
        return False
    # security -i exits 0 even when the command inside it failed, so read the
    # value back rather than trusting the exit code.
    if result.returncode != 0 or _fetch() != secret:
        log.error("could not write to the Keychain (%s): %s",
                  result.returncode, (result.stderr or "").strip()[:200])
        return False
    return True


def _fetch() -> str:
    result = _run(["find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"])
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        # A missing item is normal on first run, not an error worth shouting about.
        if "could not be found" not in stderr:
            log.error("could not read from the Keychain (%s): %s",
                      result.returncode, stderr[:200])
        return ""
    return (result.stdout or "").rstrip("\n")


def _delete() -> None:
    _run(["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT])


# ---------------------------------------------------------------------- #
# the interface zwl.auth uses
# ---------------------------------------------------------------------- #

def encrypt(plaintext: str) -> str:
    """Put ``plaintext`` in the Keychain and return the marker to persist."""
    if not plaintext:
        if _security_available():
            _delete()
        return ""

    if not _security_available():
        # Not a Mac (or a stripped-down one). Keep the app working, but make it
        # obvious in the file that the value is merely obfuscated.
        log.warning("no Keychain available; storing the token obfuscated only")
        return "plain:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    if _store(plaintext):
        return MARKER
    # The Keychain is there but refused (locked, denied...). Do not quietly drop the
    # token into tokens.json instead: keep it in memory only, so this session works
    # and the next start asks for a fresh sign-in.
    log.warning("refresh token not persisted; you will need to sign in again next start")
    return ""


def decrypt(stored: str) -> str:
    """Inverse of :func:`encrypt`."""
    if not stored:
        return ""
    if stored == MARKER:
        return _fetch()
    if stored.startswith("plain:"):
        try:
            return base64.b64decode(stored[6:]).decode("utf-8")
        except Exception:
            return ""
    # A value written by some other build; treat it as opaque plaintext.
    return stored


def forget() -> None:
    """Remove the token from the Keychain entirely (used when signing out)."""
    if _security_available():
        _delete()


def describe() -> str:
    """One line for the preflight check and the settings About text."""
    if not _security_available():
        return "Keychain unavailable - the token would be obfuscated, not encrypted"
    return "macOS login Keychain ({} / {})".format(SERVICE, ACCOUNT)
