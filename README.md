# Zendesk Warning Light

A small Windows tray app that puts an animated warning in the corner of your main
monitor when a Zendesk ticket needs someone's attention. Click the animation to
dismiss it; it also disappears on its own as soon as the underlying reason goes away.

## What sets it off

| Rule | Fires when | Clears when |
|---|---|---|
| **New unassigned ticket** | A ticket appears in a watched group with no assignee and status `new`/`open` | It gets an assignee, is solved, or leaves the watched groups |
| **Handed back to the queue** | An already-known ticket in a watched group loses its assignee | Same as above |
| **Your ticket reopened** | A ticket assigned to *you* goes from `pending` back to `open` | It leaves `open`, or is reassigned away from you |

Each rule can be switched off independently in **Settings → Alerts**. The reopen rule
deliberately ignores the group filter — it is about your tickets wherever they live.

Everyone signs in with their own Zendesk account, so the app only ever sees the tickets
that person is allowed to see. Two people running it can legitimately get different
warnings from the same settings.

On top of those tickboxes sits the **day mode**, which decides how much is allowed to
interrupt you today. A mode can only ever *narrow* what you ticked, never widen it.

## Day modes

Switch mode from the tray: **Mode › Helpdesk Day / Focus Day / Schedule**. The tray
menu title always shows what is in force, e.g. `Mode: Schedule → Off Day`.

| Mode | What fires | Zendesk polled? |
|---|---|---|
| **Helpdesk Day** | Every rule you have ticked: new unassigned tickets, hand-backs, and your own reopens | Yes |
| **Focus Day** | Only **your own tickets reopening**. Queue tickets stay silent because someone else is covering | Yes |
| **Off Day** | Nothing | **No — no API calls at all** |

**Helpdesk Day is the default** after installation.

**Focus Day** still polls, so the moment the day ends nothing has been missed — the app
already knows the current state of every ticket and simply stops suppressing the queue
rules.

**Off Day** is genuinely idle: no requests are made, so it costs nothing against your
Zendesk rate limit. Because the app deliberately lets its ticket history go stale while
off, the next working day begins with a silent catch-up rather than a wall of alerts for
everything that happened while you were away.

### Schedule mode

Pick **Schedule** and the app follows a weekly plan you set in
**Settings → Schedule**: each of Monday to Sunday is a Helpdesk, Focus or Off day. The
default plan is Monday to Friday on the queue, Saturday and Sunday off.

The Schedule tab shows what today resolves to as you edit it, and the same tab explains
what each mode means. Midnight rollover is handled while the app is running — Friday's
Helpdesk Day becomes Saturday's Off Day without a restart.

Changing mode takes effect immediately. If a warning is showing that the new mode no
longer permits, it is dismissed rather than left stranded on screen.

## Installing

Run **`dist\ZendeskWarningLight-Setup.exe`** and click through the wizard. It installs
per-user into `%LOCALAPPDATA%\Programs\ZendeskWarningLight`, so there is **no UAC prompt
and no administrator rights needed**. The wizard offers two checkboxes — start with
Windows (on by default) and a desktop shortcut (off by default) — then registers the app
under **Settings → Apps → Installed apps** with a proper uninstaller.

Re-running setup upgrades in place: it closes the running tray app, replaces the files
and restarts it. Your settings in `%APPDATA%\ZendeskWarningLight` are never touched.

### Silent install

Switches can be combined freely. Setup returns exit code **0** on success and non-zero on
failure, so it is safe to script.

```bat
ZendeskWarningLight-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

| Switch | Effect |
|---|---|
| `/VERYSILENT` | No UI whatsoever |
| `/SILENT` | Progress window only, no prompts |
| `/SUPPRESSMSGBOXES` | Suppress any message box that would otherwise block |
| `/NOAUTOSTART` | Do **not** register the Windows startup entry |
| `/DESKTOPICON` | Also create a desktop shortcut |
| `/NOLAUNCH` | Do not start the app once installed |
| `/DIR="C:\path"` | Install somewhere other than the default |
| `/LOG="C:\file.log"` | Write a detailed install log |
| `/NORESTART` | Never reboot (nothing here needs one) |

A plain `/VERYSILENT` installs, enables autostart, creates no desktop icon, and launches
the app. The switches are absolute — the result never depends on what a previous install
selected.

The three app-specific switches also accept an explicit value, e.g. `/NOLAUNCH=1` or
`/NOLAUNCH=0`. Inno's own `/TASKS` and `/MERGETASKS` deliberately do **not** control them
in silent mode: Inno reuses the task selection recorded by a previous install (and
`dontinheritcheck` does not prevent it), which made repeat silent installs depend on
history. See the `[Tasks]` comment in the `.iss` for the detail.

### Uninstalling

**Settings → Apps → Installed apps → Zendesk Warning Light → Uninstall**, the Start-menu
shortcut, or silently:

```bat
"%LOCALAPPDATA%\Programs\ZendeskWarningLight\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES
```

That removes the program, shortcuts, startup entry and the Apps registration. Your
settings and logs in `%APPDATA%\ZendeskWarningLight` are deliberately kept, so
reinstalling picks up where you left off — delete that folder by hand for a truly clean
slate.

### Starting with Windows

The installer sets this up. Change it any time from **Settings → General → Start
automatically when I sign in to Windows** — that checkbox reads and writes the same
`HKCU\...\CurrentVersion\Run` entry the installer uses, so the two never disagree.

Re-running setup re-applies the installer's default, so if you turn autostart off in the
app and later upgrade, pass `/NOAUTOSTART` (or untick the wizard box) to keep it off.

### Building it yourself

```bash
.\build.ps1 -Installer   # app + dist\ZendeskWarningLight-Setup.exe
.\build.ps1              # app only -> dist\ZendeskWarningLight\
.\build.ps1 -OneFile     # single self-contained app exe (slower to start)
```

`-Installer` needs [Inno Setup 6](https://jrsoftware.org/isdl.php). A per-user install of
it is fine — `build.ps1` looks in `%LOCALAPPDATA%\Programs\Inno Setup 6` as well as the
Program Files locations.

`install.ps1` remains as a no-tooling PowerShell fallback that does the same job. The two
are interchangeable: if you previously installed with the script, the wizard removes its
Add/Remove entry and loose shortcut so the app is never listed twice. To run straight from
source without building anything, double-click `Run Warning Light.bat`.

## First run

On first launch the Settings window opens on the **Connection** tab.

1. Press **Sign in with Zendesk**. Your browser opens, you sign in the way you normally
   do — including Microsoft SSO and MFA — and approve the app. Nothing is typed into
   the app itself.
2. **Groups** – the list loads automatically, pre-ticked with your own groups. Adjust it
   if you want. *Nothing ticked means every group you can see.*
3. **Schedule** – optional. Leave it on *Always a Helpdesk Day*, or set a weekly plan.
4. **Appearance** – pick the animation, size, screen and corner. **Preview** shows it for
   four seconds without waiting for a real ticket.

There is no user ID to look up and no secret to paste: signing in tells the app who you
are, so the reopen rule configures itself.

### Which groups you can pick

The Groups list depends on what your Zendesk role allows, because `/groups.json` returns
every group in the account regardless of who asks:

- **If your role can see all tickets**, every group is listed. Groups you are not a
  member of are greyed out but still selectable — they work for you.
- **If your role limits you to your own groups** (`restricted_agent` is true on your
  Zendesk user), only those groups are listed, so you cannot tick one that would never
  fire.

**Only my groups** re-ticks the list to your own memberships. If Zendesk will not tell
the app which groups you belong to, it says so rather than guessing.

## Sharing it with colleagues

Hand them `ZendeskWarningLight-Setup.exe`. There is nothing to configure and no
credential to pass around — the app ships only the OAuth client *identifier*, which is
not sensitive, and each person signs in as themselves. If someone leaves, revoking their
Zendesk account is enough; there is no shared secret to rotate.

## Tray menu

- **Enabled** – master on/off switch, remembered across restarts.
- **Mode** – Helpdesk Day, Focus Day, or Schedule, plus a shortcut to edit the weekly
  plan. The submenu title names the mode currently in force.
- **Pause** – 30 minutes, 1 hour, 4 hours, or the rest of today. The tray icon greys out
  and the tooltip tells you when it comes back. Pauses survive a restart and expire on
  their own.
- **Check Zendesk now**, **Dismiss warning**, **Preview the warning**.
- **Open Zendesk**, **Settings…**, **Quit**.

Left-clicking the tray icon dismisses an active warning, or opens Settings when there is
nothing to dismiss.

### Clicking the warning

The warning has two click targets:

- **The animation** – dismisses the warning.
- **The information panel underneath** – opens that ticket in your browser *and* dismisses
  it. The panel highlights on hover and names the ticket it will open.

Right-clicking anywhere on the warning gives a menu listing every active alert, so you can
open a specific one when several are stacked up.

### The icon

Both the program icon and the tray icon are the first frame of `Warning-Cat.gif`,
extracted at build time and trimmed to the cat. The tray icon layers state on top of it:

| Tray icon | Meaning |
|---|---|
| Cat | Watching, nothing to report |
| Cat + amber dot | A warning is active |
| Cat + red dot | Auth or network trouble; the tooltip has the error |
| Greyed-out cat | Disabled or paused |

Switching the animation in Settings does not change the icon — the cat stays the app's
identity, and the `.exe` icon is fixed at build time anyway. If the GIF ever goes missing
the icons fall back to a drawn warning triangle so the tray is never blank.

## Authentication

Each user signs in as themselves with the OAuth 2.0 **authorization code** grant plus
**PKCE**, against a Zendesk OAuth client of kind **Public**. A public client has no
secret at all, which is what makes the app safe to distribute as an `.exe`.

```
1. GET  /oauth/authorizations/new?response_type=code&client_id=...
        &redirect_uri=http://127.0.0.1:47821/callback&scope=read
        &code_challenge=...&code_challenge_method=S256&state=...
2. browser signs in (Microsoft SSO applies), redirects back with ?code=...
3. POST /oauth/tokens
        {"grant_type":"authorization_code","client_id":...,"code":...,
         "code_verifier":...,"redirect_uri":...}      <- no client_secret
```

Notes that matter in practice:

- The authorize path is `/oauth/authorizations/new`. Some Zendesk docs show
  `/oauth/authorize`, which redirects to the restricted help-centre page instead.
- The redirect is a **loopback listener** on 127.0.0.1, using the first free port of
  47821/47822/47823. All six spellings (both hostnames × three ports) must be registered
  on the OAuth client, because Zendesk matches the redirect URI exactly.
- The `state` parameter is generated per sign-in and checked on the way back.
- Sign-in opens the **system browser**, not an embedded webview, so SSO, MFA and
  conditional access all behave normally.
- Only the `read` scope is requested, so the app can never modify a ticket.

### Staying signed in

Access tokens last 30 minutes and refresh tokens 30 days, and **refresh tokens rotate on
every use** — the replacement must be stored or the next refresh fails. Only the refresh
token is persisted, encrypted with Windows DPAPI under your account, in `tokens.json`;
the access token is kept in memory and re-minted at startup.

In practice, anyone using the app regularly never signs in again: the token rotates every
half hour while it runs. Expiry only bites after roughly 30 days of not running it.

**If the sign-in does expire, the app says so rather than looking idle**: the tray icon
turns red, a notification appears, the tooltip reads "Zendesk sign-in expired", and the
warning overlay is suppressed so a stale alert can never imply all is well. **Sign in to
Zendesk…** appears in the tray menu.

### Setting up the OAuth client

Admin Center → Apps and integrations → APIs → Zendesk API → OAuth Clients →
**Add OAuth client**:

| Field | Value |
|---|---|
| Client kind | **Public** |
| Identifier | `warning_light_desktop` |
| Scopes | `read` |
| Redirect URLs | `http://127.0.0.1:47821/callback` … `47822` … `47823`, plus the same three with `localhost` |

There is no secret to copy. `tools\verify_oauth.py` runs the whole flow standalone and
reports what the resulting token can do — useful for checking a colleague's access
without installing anything.

## How polling works

Every 30 seconds by default, the app asks a *ticket source* what changed. There are two,
because the endpoint this was originally built on is admin-only:

| Source | Endpoint | Allowed for | Used when |
|---|---|---|---|
| Incremental export | `/api/v2/incremental/tickets/cursor.json` | **Admins** | The signed-in user is an admin *and* a probe returns 200 |
| Sweep | `/api/v2/tickets.json?sort_by=updated_at&sort_order=desc` | **Agents** | Everyone else, or if the probe is refused |

Neither uses the Search API, so neither suffers indexing lag. The incremental export is
exact and cheap; the sweep pages from the most-recently-updated ticket and stops once it
reaches a timestamp it has already seen. That watermark comparison is deliberately
inclusive, so a ticket sharing the boundary second is re-examined rather than risked being
skipped — reprocessing is harmless because the rules compare against the stored snapshot.

The choice is made once per sign-in and remembered; signing in as someone else re-seeds
from scratch.

Alerts are driven by *transitions*, so the app remembers each ticket's last known status,
assignee and group in `state.json`. Two consequences worth knowing:

- **Cold start is silent.** On first run — or after the app has been closed for more than
  15 minutes — it replays the last seven days of ticket activity purely to seed that map,
  raising nothing. You do not get a wall of alerts every time you sign in.
- **Dismissing sticks.** Once dismissed, a ticket stays quiet until it genuinely changes
  state again, so an unrelated comment on the same ticket will not re-trigger it.

Every poll also re-reads the tickets currently being alerted on, so a warning still clears
even if an update is somehow missed.

## Files

```
main.py                 entry point
zwl/app.py              tray icon, menus, wiring
zwl/auth.py             sign-in (PKCE), token store, rotating refresh
zwl/monitor.py          polling loop and the transition rules
zwl/modes.py            day modes, the rule mask and the weekday plan
zwl/sources.py          the two ticket sources and how one is chosen
zwl/zendesk.py          REST client, authenticated as the signed-in user
zwl/overlay.py          the always-on-top animated window
zwl/settings_ui.py      settings dialog
zwl/config.py           settings model and persistence (holds no credentials)
zwl/keystore.py         DPAPI encryption for the refresh token
zwl/icons.py            app + tray icons, built from the cat GIF's first frame
zwl/autostart.py        Windows Run-key registration
assets/                 bundled animations and the generated app.ico
tests/test_rules.py     transition rules, no network needed
tests/test_sources.py   ticket sources and their selection, no network needed
tests/test_modes.py     day modes, the rule mask and the off-day silence
tools/make_icon.py      generates assets/app.ico for the build
tools/verify_oauth.py   standalone sign-in check, safe to hand to a colleague

build.ps1               PyInstaller build, optionally the setup wizard too
installer/*.iss         Inno Setup script -> ZendeskWarningLight-Setup.exe
install.ps1             no-tooling PowerShell installer (alternative to the wizard)
installer/uninstall.ps1 reverses install.ps1
```

Settings, tokens, state and logs live in `%APPDATA%\ZendeskWarningLight\`:
`config.json` (no credentials), `tokens.json` (DPAPI-encrypted refresh token),
`state.json` (ticket history) and `warning-light.log`.

## Troubleshooting

Run the rule tests to confirm the alert logic still behaves:

```bash
.\.venv\Scripts\python.exe tests\test_rules.py
```

For anything else, start with the log — **Settings → General → Open log file**, or
`%APPDATA%\ZendeskWarningLight\warning-light.log`.

| Symptom | Likely cause |
|---|---|
| Tray icon is red | Not signed in, sign-in expired, or a Zendesk error — the tooltip says which |
| "Zendesk sign-in expired" | Tray menu → **Sign in to Zendesk…**. Happens after ~30 days of not running the app |
| Sign-in never completes | Ports 47821-47823 all busy, or a redirect URL missing from the OAuth client |
| Nothing ever fires | Check the tray tooltip — it names the mode. An Off Day is silent by design, and a Focus Day only allows your own reopens |
| Queue alerts stopped but reopens still work | You are on a Focus Day. Tray › Mode › Helpdesk Day |
| No Zendesk traffic at all | An Off Day makes no API calls. Tray › Mode, or edit Settings → Schedule |
| Too many alerts | Groups tab is empty, so it is watching every group |
| Reopen rule never fires | Not signed in — the rule needs to know who you are |
| A ticked group never fires | Your Zendesk role cannot see that group's tickets; greyed-out rows warn about this |
| Warning hides behind a game | Exclusive-fullscreen apps sit above all topmost windows; borderless-window mode works |
| Setup says it is already running | A previous setup was killed and left a `*-Setup.tmp` process holding the mutex; end it in Task Manager |

To start over, use **Settings → General → Forget tracked tickets and re-seed**.
