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

### What the box says

Beside the animation sits an information box naming the ticket, so you can judge it
without opening anything:

```
New unassigned ticket
#45231 · Cannot print payslips
From Malin Westerlund · Switchboard
Open ticket #45231 →
```

Clicking the box opens that ticket in Zendesk and dismisses the warning; clicking the
animation just dismisses it. The grey line carries whoever **asked** and the group it
landed in, and either half is dropped if it is not known — a requester whose name
cannot be looked up costs you the name, never the warning. Long names are shortened
rather than stretching the box. Turn the whole box off in **Appearance** if you would
rather the screen gave nothing away.

Those three rules, and the groups they apply to, belong to a **mode** — see below.
The reopen rule deliberately ignores the group selection: it is about your tickets
wherever they live.

Everyone signs in with their own Zendesk account, so the app only ever sees the tickets
that person is allowed to see. Two people running it can legitimately get different
warnings from the same settings.

On top of those tickboxes sits the **day mode**, which decides how much is allowed to
interrupt you today. A mode can only ever *narrow* what you ticked, never widen it.

## Day modes

A **mode** is a named bundle of *what may interrupt me* and *which groups that applies
to*. Switch mode from the tray — **Mode › …** — and the submenu title always names the
one in force, e.g. `Mode: Schedule → Switchboard morning`.

Because each mode carries its own group selection, you can watch the switchboard queue
on Mondays and only billing on Thursdays, without touching anything else.

You start with two modes, and they are ordinary editable modes — rename, retune or
delete them like any other:

| Mode | Rules | Groups |
|---|---|---|
| **Helpdesk Day** *(default after install)* | All three | Whatever you pick |
| **Focus Day** | Reopen only — the queue stays quiet while someone else covers it | Not used |

**Off Day** is the one reserved mode. It has nothing to configure: it fires nothing and
makes **no Zendesk API calls at all**. Because the app deliberately lets its ticket
history go stale while off, the next working day begins with a silent catch-up rather
than a wall of alerts for everything that happened while you were away.

### Making your own

**Settings → Modes** edits one mode at a time: pick it from the dropdown, set its rules,
tick its groups. **New**, **Duplicate**, **Rename** and **Delete** are alongside.

- A new mode starts from your own group memberships, which is a far better default than
  every group in the account.
- If a mode has neither queue rule ticked, the group list is greyed out and says why —
  the reopen rule is not tied to a group, so there would be nothing for it to do.
- A line at the bottom summarises the mode in plain words, e.g.
  *"Switchboard morning warns about the queue in 1 group + my reopened tickets"*, and
  tells you when that mode is the one currently in force.
- Deleting a mode that a weekday points at reassigns that day rather than breaking it,
  and says so before you confirm.

### Schedule mode

Pick **Follow the weekly schedule** on the **Schedule** tab and each of Monday to Sunday
gets its own mode — any of yours, or Off. The default plan is Monday to Friday on
Helpdesk Day, Saturday and Sunday off.

The tab shows what today resolves to as you edit it. Midnight rollover is handled while
the app runs, so Friday's mode becomes Saturday's without a restart.

Changing mode takes effect immediately. A warning the new mode no longer permits —
including one for a group the new mode does not watch — is dismissed rather than left
stranded on screen.

## Where the warning appears

**Settings → Appearance** decides which monitor, and which corner of it.

| Screen | Effect |
|---|---|
| **Primary screen** *(default)* | One warning, on whichever monitor Windows calls primary |
| A named monitor | One warning, always on that monitor |
| **All screens** | A copy on every monitor — **clicking any copy dismisses them all**, because they describe the same tickets |

Below that, **Corner** sets the default position, and each connected monitor gets its
own row to override it. So the game monitor can put the cat top-left out of the way
while the work monitor keeps it bottom-right. A monitor with no override follows the
default, which is what a newly connected screen does until you say otherwise.

Overrides are remembered per monitor **by name**, and unplugging a screen does not
forget its setting — undock a laptop and redock it and the placement comes back. The
settings window only ever speaks for the monitors it can see, so editing at your desk
cannot disturb how the warning sits at home.

### Full-screen apps and games

The warning is a topmost, frameless window that never takes focus, and it re-asserts
itself every four seconds because some apps grab the top of the z-order when they go
full screen. In practice that covers nearly everything, including borderless
full-screen games and video:

| Situation | What happens |
|---|---|
| Borderless / windowed full screen | Appears on top — verified over a full-screen game |
| An app that grabs the z-order | Covered briefly, then the re-raise brings it back |
| **Exclusive** full screen (older DirectX games) | May not appear on *that* monitor: the GPU is flipping the app's own swap chain, which is also why Windows suppresses its own notifications |
| Lock screen, UAC prompt, Ctrl+Alt+Del | Hidden — a separate secure desktop that nothing can draw on |

**"All screens" is the answer to that third row.** An exclusive full-screen app owns the
monitor it is on and nothing composites over it — but it cannot own the others, so a
copy on a second monitor is still seen. Pair it with a per-monitor corner and the
warning stays out of the way of what you are actually doing.

> **It appears during screen sharing.** The app draws its own window rather than using
> Windows notifications, so Focus Assist and presentation mode do not suppress it: in a
> Teams share or a projected slide deck, the animation *and* the ticket subject go out
> to everyone watching. Pause it from the tray, switch to a quieter mode, or turn the
> caption off in Appearance to at least keep the subject private.

## Installing

Run **`dist\ZendeskWarningLight-Setup-<version>.exe`** and click through the wizard. It installs
per-user into `%LOCALAPPDATA%\Programs\ZendeskWarningLight`, so there is **no UAC prompt
and no administrator rights needed**. The wizard offers two checkboxes — start with
Windows (on by default) and a desktop shortcut (off by default) — then registers the app
under **Settings → Apps → Installed apps** with a proper uninstaller.

Re-running setup upgrades in place: it closes the running tray app, replaces the files
and restarts it. Your settings in `%APPDATA%\ZendeskWarningLight` are never touched.

### Silent install

```bat
ZendeskWarningLight-Setup-2.7.0.exe /S                REM silent install
ZendeskWarningLight-Setup-2.7.0.exe /S /uninstall     REM silent uninstall
```

`/S` picks the install mode from the account running it: **SYSTEM installs machine-wide**,
anyone else gets a per-user install. `/S /uninstall` removes whichever copy is installed,
machine-wide or per-user, and waits until it is genuinely gone before exiting.

Inno's own switches work too, and take precedence when you want to be explicit:

| Switch | Effect |
|---|---|
| `/S` | Silent install, mode auto-detected *(NSIS-style, for packaging tools)* |
| `/S /uninstall` | Silent uninstall of whichever copy is installed |
| `/uninstall` | The same, interactively |
| `/VERYSILENT` | Silent, Inno's own switch |
| `/SILENT` | Progress window only |
| `/ALLUSERS` | Force machine-wide: `Program Files`, `HKLM`, every user |
| `/CURRENTUSER` | Force per-user: `%LOCALAPPDATA%\Programs`, `HKCU` |
| `/SUPPRESSMSGBOXES` | Suppress blocking message boxes |
| `/NOAUTOSTART` | Do not start at login — removes any existing entry too |
| `/DESKTOPICON` | Also create a desktop shortcut |
| `/NOLAUNCH` | Do not start the app after installing (it is never started when Setup runs as SYSTEM, e.g. Intune system context — users get it at their next sign-in) |
| `/DIR="C:\path"` | Install somewhere else |
| `/LOG="C:\file.log"` | Write an install log |
| `/NORESTART` | Never reboot |

Every switch is absolute: the result never depends on what a previous install chose.
`/NOAUTOSTART` deletes a login entry an earlier install left behind rather than merely
skipping it, and the wizard's task checkboxes are ignored in silent mode for the same
reason — see the `[Tasks]` comment in the `.iss`.

With `/LOG`, the launcher writes to the file you named and the install itself writes to
`<yourfile>.install.log` beside it. Two files, because the launcher still holds the first
one open when the installer starts.

**Setup never asks anyone anything.** Install-mode overrides are restricted to the command
line, so an elevated launch cannot raise a "Select install mode" prompt. A plain
double-click installs per-user with no prompt and no UAC.

### How `/S` works, and why it needs a launcher

The shipped exe is a thin **launcher** that carries the real Inno installer inside it. It
translates the command line, runs the right thing, waits, and exits with that thing's exact
exit code. Three findings forced this, each from testing rather than assumption:

1. **Inno fixes silent mode in its own parser** before any script runs, and nothing in the
   script can change it. `/S` alone could never be made to mean silent.
2. **Script cannot set the exit code.** Aborting always reports `1`, which every deployment
   tool reads as failure — so an installer cannot relay a command *and* report the real
   result. The launcher calls `ExitProcess` from `kernel32` to return the true code.
3. **A running Inno installer holds its own .exe open** against both executing *and*
   reading it, so it cannot relaunch or even copy itself. Only a separate exe can start it.

The launcher itself installs nothing, creates no folder and leaves no Add/Remove entry — it
is invisible in every way except the command line it accepts.

### Exit codes

| Code | Meaning |
|---|---|
| **0** | Installed successfully |
| **1** | Failed to initialize — **a bad switch lands here**; read the `/LOG` |
| 2 | Cancelled before installing started |
| 3 | Fatal error while preparing to install |
| 4 | Fatal error during installation |
| 5 | Cancelled during installation |
| 6 | Terminated by the debugger |
| 7 / 8 | Preparing-to-install decided it cannot continue (8 wants a restart) |

## Deploying with Intune

`build.ps1 -Installer` stages two wrappers next to the installer in `dist\`, so you can
point `IntuneWinAppUtil` at that folder and be done:

```
dist\
  ZendeskWarningLight-Setup-2.7.0.exe
  Intune-Install.cmd
  Intune-Uninstall.cmd
```

Since 2.4.0 the setup exe does the same job on its own, so the wrappers are a
convenience rather than a requirement — use whichever suits the tool:

```bat
ZendeskWarningLight-Setup-2.7.0.exe /S
ZendeskWarningLight-Setup-2.7.0.exe /S /uninstall
```

Both the wrapper and `/S` pick the install mode from the account running them — SYSTEM
gets `/ALLUSERS`, anyone else `/CURRENTUSER` — and both exit with the installer's own
exit code, so Intune reports success and failure correctly. The wrapper still has one
advantage on uninstall: nothing else to ship alongside it if you would rather not carry
the 35 MB setup exe just to remove something.

| Intune field | Value |
|---|---|
| Install command | `Intune-Install.cmd` — or `ZendeskWarningLight-Setup-2.7.0.exe /S` |
| Uninstall command | `Intune-Uninstall.cmd` — or `ZendeskWarningLight-Setup-2.7.0.exe /S /uninstall` |
| Install behaviour | **System** for all users, **User** for per-user |
| Device restart behaviour | No specific action |

Add `/LOG="%TEMP%\zwl-install.log"` to the install command if you want a trace; anything
you pass to the wrapper is forwarded to Setup. The launcher writes that file and the
install itself writes `zwl-install.log.install.log` beside it.

Prefer the explicit switches over either if you would rather be unambiguous:

```bat
ZendeskWarningLight-Setup-2.7.0.exe /VERYSILENT /ALLUSERS /SUPPRESSMSGBOXES /NORESTART
```

### Detection rules

Either works. The registry rule is the one Patch My PC-style version comparison uses:

**Registry** — machine-wide (system context):

```
Key    HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{8F3A1C6E-5B27-4E19-9C4D-7A2E6B0D9F31}_is1
Value  DisplayVersion
Rule   Version comparison, greater than or equal to, 2.7.0
```

For a per-user deployment the same key sits under `HKEY_CURRENT_USER`.

**File** — machine-wide:

```
Path     C:\Program Files\ZendeskWarningLight
File     ZendeskWarningLight.exe
Rule     Version, greater than or equal to, 2.7.0
```

Per-user: `%LOCALAPPDATA%\Programs\ZendeskWarningLight`.

### What stays per-user either way

A machine-wide install shares only the **program files**. Everything personal stays in
each user's own profile, which is what you want — every person signs in to Zendesk as
themselves:

| Per user, always | Where |
|---|---|
| Settings, modes, schedule | `%APPDATA%\ZendeskWarningLight\config.json` |
| Sign-in token | `%APPDATA%\ZendeskWarningLight\tokens.json`, DPAPI-encrypted to that account |
| Ticket history and log | same folder |

So a machine-wide install gives every user the app and starts it at login, and each of
them signs in once on first run. Uninstalling leaves those folders behind; the app's own
`--purge` equivalent is documented under Uninstalling.

### Version information

The version is written where Windows inventory and patching tools expect it, from the
single source of truth in `zwl/__init__.py`:

| Location | Field | Value |
|---|---|---|
| Add/Remove Programs | `DisplayVersion` | `2.7.0` |
| | `DisplayName`, `Publisher`, `InstallLocation`, `DisplayIcon`, `UninstallString`, `QuietUninstallString`, `EstimatedSize`, `VersionMajor`, `VersionMinor` | all populated |
| `ZendeskWarningLight.exe` | `FileVersion` / `ProductVersion` | `2.7.0` |
| `…-Setup-2.7.0.exe` | `FileVersion` / `ProductVersion` | `2.7.0` |

So a tool that compares either the ARP `DisplayVersion` or the installed exe's file
version will see the real version and detect an upgrade normally. The version also appears
in the installer's filename.

### Uninstalling

**Settings → Apps → Installed apps → Zendesk Warning Light → Uninstall**, the Start-menu
shortcut, or from a command line.

For Intune, Patch My PC, ConfigMgr or anything else that takes a command line, either of
these finds whichever install is present — machine-wide or per-user — and, importantly,
waits for the removal to actually finish:

```bat
ZendeskWarningLight-Setup-2.7.0.exe /S /uninstall
Intune-Uninstall.cmd
```

Both are idempotent: removing something already gone exits 0 rather than failing. (The
wrapper's name says Intune, but it is tool-agnostic — plain `cmd` with correct exit codes.)

> **An installer normally cannot uninstall**, which is why this needed building. Inno
> writes a *separate* `unins000.exe` at install time and silently ignores switches it does
> not know — so `Setup.exe /VERYSILENT /UNINSTALL` once **installed the app and exited 0**,
> meaning a patching tool configured that way would reinstall on every uninstall attempt
> and report success. The launcher now runs the real uninstaller instead. The payload
> inside still refuses those switches outright, in case anyone runs it directly.

The explicit commands, if you prefer them:

```bat
REM machine-wide install (needs admin)
"%ProgramFiles%\ZendeskWarningLight\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

REM per-user install
"%LOCALAPPDATA%\Programs\ZendeskWarningLight\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

Both paths are also recorded in the registry as `UninstallString` and
`QuietUninstallString` under the uninstall key, so a management tool can read them rather
than assume a path.

> **Why not call `unins000.exe` directly?** Inno's uninstaller copies itself
> to `%TEMP%` and lets that copy finish the job, so it can delete its own folder. The
> process you launched therefore **returns exit code 0 while the program folder is still on
> disk** — measured here at about three seconds' lag. Intune evaluates its detection rule as
> soon as the command returns, so a bare `unins000.exe` call can be reported as a *failed*
> uninstall even though it succeeded. Both `/S /uninstall` and `Intune-Uninstall.cmd` poll
> until the registry key and the program folder are actually gone before exiting, so either
> kind of detection rule is accurate.

Uninstalling removes the program, shortcuts, startup entry and the Apps registration.
Settings and logs in `%APPDATA%\ZendeskWarningLight` are deliberately kept, so reinstalling
picks up where each user left off — including their Zendesk sign-in. Pass `--purge` to the
wrapper to delete those too, though that only clears the account running the command: every
user has their own folder and their own encrypted token.

Running the wrapper when nothing is installed is a no-op that exits 0, so it is safe for
Intune to retry.

### Starting with Windows

The installer sets this up. Change it any time from **Settings → General → Start
automatically when I sign in to Windows** — that checkbox reads and writes the same
`Run` entry the installer uses, so the two never disagree.

A **machine-wide** install writes it to `HKLM` instead, so it applies to everyone. The
app notices: the checkbox shows ticked, greys out, and says your administrator set it
for all users. That stops it from reading "off" while the app plainly does start at
login, and stops a tick from adding a duplicate `HKCU` entry that would launch the app
twice.

Re-running setup re-applies the installer's default, so if you turn autostart off in the
app and later upgrade, pass `/NOAUTOSTART` (or untick the wizard box) to keep it off.

### Building it yourself

```bash
.\build.ps1 -Installer   # app + dist\ZendeskWarningLight-Setup-<version>.exe
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
2. **Modes** – the group list loads automatically, pre-ticked with your own groups.
   Adjust the rules and groups for each mode. *Nothing ticked means every group you
   can see.*
3. **Schedule** – optional. Leave it on one mode every day, or set a weekly plan.
4. **Appearance** – pick the animation, size, and where it appears: one monitor or all
   of them, with a corner per monitor. **Preview** shows it for four seconds without
   waiting for a real ticket, on every screen it would really use.
5. **Changelog** – what changed in every version, newest first, with the one you are
   running marked. Nothing to configure; it is there so an upgrade explains itself.

There is no user ID to look up and no secret to paste: signing in tells the app who you
are, so the reopen rule configures itself.

### Which groups you can pick

The group list on the Modes tab depends on what your Zendesk role allows, because
`/groups.json` returns every group in the account regardless of who asks:

- **If your role can see all tickets**, every group is listed. Groups you are not a
  member of are greyed out but still selectable — they work for you.
- **If your role limits you to your own groups** (`restricted_agent` is true on your
  Zendesk user), only those groups are listed, so you cannot tick one that would never
  fire.

**Only my groups** re-ticks the list to your own memberships. If Zendesk will not tell
the app which groups you belong to, it says so rather than guessing.

## Sharing it with colleagues

Hand them `ZendeskWarningLight-Setup-<version>.exe`. There is nothing to configure and no
credential to pass around — the app ships only the OAuth client *identifier*, which is
not sensitive, and each person signs in as themselves. If someone leaves, revoking their
Zendesk account is enough; there is no shared secret to rotate.

## Tray menu

- **Enabled** – master on/off switch, remembered across restarts.
- **Mode** – every mode you have defined, plus Off Day and *Follow the weekly
  schedule*, with shortcuts to edit modes or the plan. The submenu title names the
  mode currently in force.
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
zwl/modes.py            the DayMode type, seeding/repair and the weekday plan
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
tests/test_modes.py     modes, per-mode groups and the off-day silence
tests/test_autostart.py start-at-login, including a machine-wide HKLM entry
tests/test_groups_tab.py the group picker, including per-mode independence
tools/make_icon.py      generates assets/app.ico for the build
tools/verify_oauth.py   standalone sign-in check, safe to hand to a colleague

build.ps1               PyInstaller build, optionally the setup wizard too
installer/*.iss         Inno Setup script -> ZendeskWarningLight-Setup-<version>.exe
installer/Intune-*.cmd  Intune wrappers; pick the install mode from the account
install.ps1             no-tooling PowerShell installer (alternative to the wizard)
installer/uninstall.ps1 reverses install.ps1
```

Settings, tokens, state and logs live in `%APPDATA%\ZendeskWarningLight\`:
`config.json` (no credentials — holds your modes and weekly plan), `tokens.json`
(DPAPI-encrypted refresh token), `state.json` (ticket history) and
`warning-light.log`.

Upgrading from 2.1 folds the old single set of rules and groups into the two seeded
modes, so behaviour carries over untouched.

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
| Queue alerts stopped but reopens still work | The mode in force has no queue rule (Focus Day does not). Tray › Mode |
| A group I ticked never fires | Check you ticked it on the *mode* that is in force — each mode has its own group list |
| No Zendesk traffic at all | An Off Day makes no API calls. Tray › Mode, or edit Settings → Schedule |
| Too many alerts | Groups tab is empty, so it is watching every group |
| Reopen rule never fires | Not signed in — the rule needs to know who you are |
| A ticked group never fires | Your Zendesk role cannot see that group's tickets; greyed-out rows warn about this |
| Warning hides behind a game | Only *exclusive* full screen can do this. Set Appearance → Screen to **All screens** so another monitor still shows it, or use the game's borderless mode |
| Warning sits where the game needs it | Appearance → Corner has a row per monitor; move that one screen's copy without disturbing the others |
| Setup says it is already running | A previous setup was killed and left a `*-Setup.tmp` process holding the mutex; end it in Task Manager |
| `/S` did nothing / the wizard opened | Fixed in 2.4.0 — `/S` installs silently. Older builds need `/VERYSILENT` |
| Silent install exits 1 with no install | Read the `/LOG`. Either a bad switch, or SYSTEM without `/ALLUSERS` |
| Installed as SYSTEM but no user sees it | It went to the service profile. Reinstall with `/ALLUSERS` |
| Listed twice in Settings → Apps | A per-user and a machine-wide copy are both installed; uninstall the one you do not want |
| Autostart checkbox is greyed out | A machine-wide install set it in `HKLM`; only an admin can change it |

To start over, use **Settings → General → Forget tracked tickets and re-seed**.
