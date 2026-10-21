"""Encrypt the Zendesk client secret at rest with Windows DPAPI (current user scope).

The ciphertext is only decryptable by the same Windows account on the same machine,
so a copied config.json leaks nothing usable.
"""

from __future__ import annotations

import base64
import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _read(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


try:
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
except (OSError, AttributeError):  # pragma: no cover - non-Windows safety net
    _crypt32 = None
    _kernel32 = None

_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_ENTROPY = b"ZendeskWarningLight/v1"


def encrypt(plaintext: str) -> str:
    """Return a base64 DPAPI blob, or a plainly-marked fallback if DPAPI is unavailable."""
    if not plaintext:
        return ""
    if _crypt32 is None:
        return "plain:" + base64.b64encode(plaintext.encode("utf-8")).decode("ascii")

    out = _Blob()
    data_in = _blob(plaintext.encode("utf-8"))
    entropy = _blob(_ENTROPY)
    ok = _crypt32.CryptProtectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    )
    if not ok:
        # Never fall back to writing the secret readably: keep it in memory only, so
        # this session works and the next start asks for a fresh sign-in.
        log.warning("CryptProtectData failed (%s); secret not persisted", ctypes.get_last_error())
        return ""
    try:
        return "dpapi:" + base64.b64encode(_read(out)).decode("ascii")
    finally:
        _kernel32.LocalFree(out.pbData)


def decrypt(stored: str) -> str:
    """Inverse of :func:`encrypt`. Unrecognised values are treated as plaintext."""
    if not stored:
        return ""
    if stored.startswith("plain:"):
        try:
            return base64.b64decode(stored[6:]).decode("utf-8")
        except Exception:
            return ""
    if not stored.startswith("dpapi:") or _crypt32 is None:
        return stored  # legacy plaintext value written by hand

    try:
        raw = base64.b64decode(stored[6:])
    except Exception:
        return ""

    out = _Blob()
    data_in = _blob(raw)
    entropy = _blob(_ENTROPY)
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, ctypes.byref(entropy),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out),
    )
    if not ok:
        log.error("CryptUnprotectData failed (%s) - secret must be re-entered", ctypes.get_last_error())
        return ""
    try:
        return _read(out).decode("utf-8")
    finally:
        _kernel32.LocalFree(out.pbData)
