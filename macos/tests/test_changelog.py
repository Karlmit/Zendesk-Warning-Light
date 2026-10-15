"""The changelog: ordering, completeness, and that it keeps up with the version.

The check that earns its keep is `latest entry matches __version__`. Releasing
without writing down what changed is the failure mode this catches.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zwl import __version__, changelog    # noqa: E402

CHECKS = []


def check(label: str, got, want) -> None:
    CHECKS.append((label, got == want, got, want))


def as_tuple(version: str) -> tuple[int, ...]:
    parts = [int(p) for p in version.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


# --- the changelog must keep up with the app -----------------------------

check("there are releases", bool(changelog.RELEASES), True)
check("latest entry matches __version__", changelog.latest_version(), __version__)
check("the running version is findable", bool(changelog.find(__version__)), True)
check("an unknown version is not invented", changelog.find("9.9.9"), None)

# --- every entry says something ------------------------------------------

for release in changelog.RELEASES:
    label = release.version
    check("{}: has a version".format(label), bool(release.version.strip()), True)
    check("{}: has a headline".format(label), bool(release.headline.strip()), True)
    check(
        "{}: says what changed".format(label),
        bool(release.changes) or bool(release.fixes),
        True,
    )
    check(
        "{}: headline is a phrase, not a paragraph".format(label),
        len(release.headline) <= 60,
        True,
    )
    if release.date:
        check(
            "{}: date is ISO-8601".format(label),
            bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", release.date)),
            True,
        )

# --- ordering -------------------------------------------------------------

versions = [r.version for r in changelog.RELEASES]
check("no version listed twice", len(set(versions)), len(versions))
check(
    "newest first",
    versions,
    sorted(versions, key=as_tuple, reverse=True),
)

dated = [r.date for r in changelog.RELEASES if r.date]
check("dates run newest to oldest", dated, sorted(dated, reverse=True))

# --- rendering ------------------------------------------------------------

html = changelog.to_html(__version__)
check("every version appears", all(v in html for v in versions), True)
check("every headline appears",
      all(r.headline in html for r in changelog.RELEASES), True)
check("the running version is badged", "you are running this" in html, True)
check("badge appears exactly once", html.count("you are running this"), 1)
check("a release separator between entries",
      html.count("<hr>"), len(changelog.RELEASES) - 1)

plain = changelog.to_html("")
check("no badge when the version is unknown", "you are running this" in plain, False)
check("unknown version still renders every release",
      all(v in plain for v in versions), True)

# Body text colour is deliberately left to the widget so it stays readable in a
# light Windows theme; only accents and greys are set.
check("body text colour is not forced", "color:#fff" in html.lower(), False)
check("no stray unescaped ampersand", "& " in html.replace("&amp; ", "").replace(
    "&nbsp; ", ""), False)

# --- the release notes are real prose, not commit subjects ----------------

for release in changelog.RELEASES:
    for item in release.changes + release.fixes:
        check(
            "{}: '{}' ends in a full stop".format(release.version, item[:28]),
            item.rstrip().endswith((".", "!", "?")),
            True,
        )


# --- report ---------------------------------------------------------------

failed = [c for c in CHECKS if not c[1]]
for label, ok, got, want in CHECKS:
    if not ok:
        print("FAIL  {}: got {!r}, want {!r}".format(label, got, want))
print("{}/{} checks passed".format(len(CHECKS) - len(failed), len(CHECKS)))
sys.exit(1 if failed else 0)
