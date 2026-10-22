"""Fuzz the checks that decide where a Zendesk token may be sent (M1, M2, M7).

Invariants, for any input at all:

1. normalise_subdomain() returns "" or a single DNS label, and the address built
   from a non-empty result passes check_base_url().
2. Whatever check_base_url() accepts is https://<label>.zendesk.com: no userinfo,
   no port, no path.
3. ZendeskClient._url() either refuses, or returns a URL that requests sends to
   exactly the account's host over https. The host is read with urllib3's parser,
   which is what requests uses on the wire, not with the urlsplit() that _url()
   itself uses, so a disagreement between the two parsers counts as a failure.

    python fuzz/fuzz_token_hosts.py -max_total_time=300

Runs on the Windows copy of zwl. config.py and zendesk.py are identical on macOS,
which tests.yml checks.
"""

import re
import sys
from pathlib import Path

import atheris

with atheris.instrument_imports():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))
    import requests
    from urllib3.util import parse_url
    from zwl import auth, config
    from zwl.zendesk import ZendeskClient, ZendeskError

LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
BASE = "https://acme.zendesk.com"


class Tokens:
    base_url = BASE
    user = None


CLIENT = ZendeskClient(Tokens())


def sent_to(url: str):
    """(scheme, host, port, auth) that requests would actually connect with."""
    prepared = requests.Request("GET", url).prepare()
    parsed = parse_url(prepared.url)
    return parsed.scheme, parsed.host, parsed.port, parsed.auth


def check_subdomain(text: str) -> None:
    sub = config.normalise_subdomain(text)
    if not sub:
        return
    assert LABEL.fullmatch(sub), sub
    assert auth.check_base_url("https://{}.zendesk.com".format(sub))


def check_base(text: str) -> None:
    try:
        base = auth.check_base_url(text)
    except auth.AuthError:
        return
    scheme, host, port, userinfo = sent_to(base + "/x")
    assert scheme == "https", base
    assert host and host.endswith(".zendesk.com") and host.count(".") == 2, base
    assert port is None and userinfo is None, base


def check_url(text: str) -> None:
    try:
        url = CLIENT._url(text)
    except ZendeskError:
        return
    try:
        scheme, host, port, userinfo = sent_to(url)
    except (requests.exceptions.RequestException, ValueError):
        return                      # requests would refuse to send it at all
    assert (scheme, host, port, userinfo) == ("https", "acme.zendesk.com", None, None), \
        "{!r} -> {!r} would go to {}".format(text, url, (scheme, host, port, userinfo))


def one_input(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    which = fdp.ConsumeIntInRange(0, 2)
    text = fdp.ConsumeUnicodeNoSurrogates(256)
    if which == 0:
        check_subdomain(text)
    elif which == 1:
        check_base(text)
    else:
        # Bias towards the shapes that matter: relative paths and absolute URLs.
        prefix = ("", "/", "https://", "https://acme.zendesk.com", "@", "//")[len(text) % 6]
        check_url(prefix + text)


if __name__ == "__main__":
    atheris.Setup(sys.argv, one_input)
    atheris.Fuzz()
