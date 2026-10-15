"""What changed in each version, for the Changelog tab.

Written for the person using the app rather than the person who wrote it: what is
different now, and why they might care. The git history is the engineering record.

Newest first. Everything before 2.0.0 predates version control, so 1.0 is a single
summary rather than a release-by-release account.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Release:
    version: str
    date: str                       # ISO-8601, or "" when it was never tagged
    headline: str
    changes: tuple[str, ...] = ()
    fixes: tuple[str, ...] = ()
    note: str = ""                  # one line of context, shown in grey


RELEASES: tuple[Release, ...] = (
    Release(
        version="2.9.0",
        date="2026-10-08",
        headline="When it came in",
        changes=(
            "The information box now shows <b>when the ticket came in</b> — just the "
            "time for today's tickets, with the date added for older ones.",
        ),
        note="Shown in your local time. If Zendesk gives no time it is simply left out.",
    ),
    Release(
        version="2.8.0",
        date="2026-10-05",
        headline="A sound to go with it",
        changes=(
            "<b>Appearance → Play a sound when a warning appears</b> adds an optional "
            "alert sound. It is <b>off by default</b>.",
            "It plays once when the warning appears, not on every check. Pick the macOS "
            "default or a church bell, pan flute or singing bowl, and press <b>Test</b> "
            "to hear it.",
            "Each <b>mode</b> has its own <b>Play a sound</b> tick, so a day mode "
            "(and therefore the weekday schedule) can warn you silently while other "
            "days make a sound. Sound still has to be switched on in Appearance.",
        ),
        note="<b>Preview</b> plays the sound too when the option is ticked.",
    ),
    Release(
        version="2.7.0",
        date="2026-09-25",
        headline="Who asked",
        changes=(
            "The information box now names the <b>requester</b> as well as the group, "
            "so you can tell whose problem it is without opening the ticket.",
        ),
        note="If the name cannot be looked up it is simply left out — the warning "
             "itself is never delayed or lost over it.",
    ),
    Release(
        version="2.6.0",
        date="2026-09-15",
        headline="This tab",
        changes=(
            "A <b>Changelog</b> tab, so what changed in each version is in the app "
            "rather than somewhere you have to be told about.",
        ),
        note="Scroll down for everything back to the first version.",
    ),
    Release(
        version="2.5.0",
        date="2026-09-15",
        headline="Be seen past a full-screen game",
        changes=(
            "<b>Appearance → Screen</b> can now be <b>All screens</b>: a copy of the "
            "warning on every monitor. Clicking any copy dismisses them all, because they "
            "are describing the same tickets.",
            "<b>Corner</b> can now be set <b>per monitor</b>. The screen with a game on it "
            "can push the warning into a corner you are not looking at, while your other "
            "monitors keep it where it was.",
            "A monitor's placement is remembered by name and survives unplugging, so "
            "undocking a laptop and docking it again brings the same layout back.",
            "<b>Preview</b> now appears on every screen it would really use, instead of "
            "quietly disagreeing with the setting.",
        ),
        fixes=(
            "Placement is now correct when monitors run at different display scaling.",
        ),
        note="An app in exclusive full screen owns the monitor it is on and nothing can "
             "draw over it — but it cannot own the others. That is what “all "
             "screens” is for.",
    ),
    Release(
        version="2.2.0",
        date="2026-09-09",
        headline="Make your own modes",
        changes=(
            "A mode now owns <b>its own groups</b> as well as its own rules. You can watch "
            "the switchboard queue on Mondays and only billing on Thursdays.",
            "Create, duplicate, rename and delete modes on the <b>Modes</b> tab, and pick "
            "any of them for any weekday in the schedule.",
            "A new mode starts from the groups you are actually a member of, which is a "
            "better starting point than every group in the account.",
        ),
        fixes=(
            "Deleting a mode that a weekday points at reassigns that day instead of "
            "leaving the schedule broken, and says so first.",
        ),
    ),
    Release(
        version="2.1.0",
        date="2026-09-08",
        headline="Day modes and a weekly schedule",
        changes=(
            "<b>Helpdesk Day</b> and <b>Focus Day</b>, switchable straight from the tray "
            "icon. Focus Day only warns about your own tickets being reopened, so the "
            "queue stays quiet while somebody else covers it.",
            "<b>Off Day</b> makes no Zendesk calls at all — not quieter, genuinely off.",
            "A <b>Schedule</b> tab to set a mode for each day of the week.",
        ),
        note="Coming back from an off day begins with a silent catch-up, rather than a "
             "wall of warnings for everything that happened while you were away.",
    ),
    Release(
        version="2.0.0",
        date="2026-09-07",
        headline="Everyone signs in with their own Zendesk account",
        changes=(
            "Sign in through your browser, with your normal sign-in and MFA. "
            "No API key or secret to share, and none stored in the app.",
            "The app only ever sees what your own Zendesk role allows, so the group list "
            "shows what you can really watch.",
            "Read-only access is requested, so the app can never change a ticket.",
        ),
        note="This is what made the app shareable with colleagues.",
    ),
    Release(
        version="1.0",
        date="",
        headline="The original app",
        changes=(
            "An animated warning in the corner of the screen, always on top, when a "
            "ticket needs attention: a new unassigned ticket, a ticket handed back to the "
            "queue, or one of your own going from pending back to open.",
            "Click the warning to dismiss it; it also goes away by itself as soon as the "
            "reason does.",
            "A tray icon for settings, the groups to watch, the animation to show, and "
            "pausing it for a while.",
            "Starting at login.",
        ),
        note="Before this project used version control, so there is no exact date.",
    ),
)


def latest_version() -> str:
    return RELEASES[0].version if RELEASES else ""


def find(version: str) -> Release | None:
    return next((r for r in RELEASES if r.version == version), None)


def to_html(current_version: str = "") -> str:
    """Render the whole history as one scrollable document.

    Only accent and muted colours are set, so the surrounding widget's own palette
    keeps body text readable in both a light and a dark macOS appearance.
    """
    parts: list[str] = [
        "<style>"
        "h2 { color:#ffb020; margin-bottom:2px; }"
        "  .date { color:#8a8f98; font-size:11px; }"
        "  .badge { color:#6fb2ff; font-size:11px; }"
        "  .note { color:#8a8f98; }"
        "  .label { color:#8a8f98; font-size:11px; letter-spacing:1px; }"
        "  li { margin-bottom:5px; }"
        "  hr { border:none; border-top:1px solid rgba(138,143,152,0.35); }"
        "</style>"
    ]

    for index, release in enumerate(RELEASES):
        if index:
            parts.append("<hr>")

        heading = "<h2>{} &nbsp;<span style='font-weight:normal'>{}</span></h2>".format(
            _escape(release.version), _escape(release.headline))
        parts.append(heading)

        meta = []
        if release.date:
            meta.append("<span class='date'>{}</span>".format(_escape(release.date)))
        if current_version and release.version == current_version:
            meta.append("<span class='badge'>← you are running this</span>")
        if meta:
            parts.append("<p>{}</p>".format(" &nbsp; ".join(meta)))

        if release.changes:
            parts.append("<ul>")
            parts.extend("<li>{}</li>".format(item) for item in release.changes)
            parts.append("</ul>")

        if release.fixes:
            parts.append("<p class='label'>FIXED</p><ul>")
            parts.extend("<li>{}</li>".format(item) for item in release.fixes)
            parts.append("</ul>")

        if release.note:
            parts.append("<p class='note'><i>{}</i></p>".format(release.note))

    return "".join(parts)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
