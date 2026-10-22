# Installing Zendesk Warning Light on a Mac

Step by step, in order. Everything is per-user — **no admin password needed at any
point**. Total time is about ten minutes, most of it waiting for downloads.

There are two different jobs here:

- **[Part A](#part-a--build-it-once)** — build the app. Done once, on one Mac, by you.
- **[Part B](#part-b--give-it-to-a-colleague)** — hand the result to colleagues. They
  never open a terminal.

---

## Before you start

| Need | Check | If it is wrong |
|---|---|---|
| Apple Silicon Mac | Apple menu → About This Mac says **M1/M2/M3/M4** | An Intel Mac works, but the app it builds will only run on Intel Macs |
| macOS 12 Monterey or newer | Same window | Older macOS is untested |
| Xcode command line tools | `xcode-select -p` prints a path | Run `xcode-select --install` and accept the prompt |
| Python 3.10–3.13, **arm64** | see below | Install from [python.org](https://www.python.org/downloads/macos/) |

### The Python trap — check this properly

macOS ships Python **3.9**, which is too old: `pip` will fail to find PySide6 and the
build will stop. Check what you actually have:

```bash
python3 --version
python3 -c 'import platform; print(platform.machine())'
```

You want a version in the 3.10–3.13 range and the word **`arm64`**.

- If the version is 3.9.x → install Python 3.12 from python.org (the normal
  double-click installer), then use `python3.12` in place of `python3` everywhere below.
- If it says **`x86_64`** on an M-series Mac, your Python is running under Rosetta and
  would produce an Intel app. Install the arm64 build from python.org.

`build.sh` refuses to run in the Rosetta case rather than quietly building the wrong
thing, so you cannot get this wrong silently.

### Nothing to do in Zendesk

The OAuth client already exists and its redirect URLs already cover macOS. Each person
signs in as themselves the first time they run the app.

---

## Part A — build it once

### 1. Get this folder onto the Mac

Copy the whole `Zendesk-Warning-Light-macOS` folder over — OneDrive, a USB stick, or
`git clone` if you put it on a server. Then open Terminal and go into it:

```bash
cd ~/Downloads/Zendesk-Warning-Light-macOS     # wherever you put it
```

### 2. Make the scripts executable

Only needed if the folder arrived by OneDrive or USB — copying from Windows loses the
executable flag. Harmless to run either way:

```bash
chmod +x build.sh install.sh uninstall.sh run.command
```

### 3. Set up Python and check the Mac can run it

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install --require-hashes -r requirements-build.txt
./.venv/bin/python tools/preflight.py
```

*(use `python3.12 -m venv .venv` if that is your working Python)*

**Do not skip the preflight.** This port was written on Windows, so the Mac-specific
parts — the Keychain, the login item, the menu-bar icon, the overlay window — had never
been executed anywhere until now. The preflight exercises all of them for real: it
writes and reads back a throwaway Keychain item, validates the login-item plist with
`plutil`, loads Qt's Cocoa plugin, decodes both animations, and puts the overlay on
screen briefly. It changes nothing permanent.

It should end with a line like:

```
All 30 checks passed - the macOS layer works on this Mac.
```

Every line above it should read `ok`. The exact count varies slightly with what it
finds; what matters is that none say `FAIL`.

If anything fails it names the failing check. Fix that before building — see
[Troubleshooting](#troubleshooting).

### 4. Build

```bash
./build.sh
```

Takes a few minutes. It creates the virtual environment if needed, generates the icon,
runs PyInstaller, patches `Info.plist`, ad-hoc signs the app (**mandatory** on Apple
Silicon — arm64 macOS refuses to run unsigned code), and packages a disk image.

It finishes with the file to hand out:

```
Give this file to colleagues:
  /Users/you/.../dist/ZendeskWarningLight-2.2.0.dmg  (33M)
```

### 5. Install it on this Mac

```bash
./install.sh
```

Installs to `~/Applications`, sets it to start at login, and launches it. The cat
appears in your menu bar, top right.

**Run this as yourself — never with `sudo`.** It installs for one user; under sudo the
login item would land in root's home and never start. The script refuses to run as root.

Options:

| Command | Effect |
|---|---|
| `./install.sh --no-autostart` | Do not start at login |
| `./install.sh --no-launch` | Install but do not start it now |
| `./install.sh --force` | Rebuild first, then install |
| `./install.sh --system` | Install to `/Applications` instead (needs that folder writable) |

### 6. Sign in

Settings opens by itself the first time. On the **Connection** tab press
**Sign in with Zendesk** — your browser opens, you sign in with Microsoft exactly as
normal, MFA included. The app never sees your password.

Then on the **Modes** tab pick which groups each mode should watch. Your own groups are
pre-ticked.

To confirm the Zendesk side independently:

```bash
./.venv/bin/python tools/verify_oauth.py
```

That does a complete sign-in and reports what your account can read. Safe to run while
the app is running — it uses its own token.

---

## Part B — give it to a colleague

Send them **one file**: `dist/ZendeskWarningLight-2.2.0.dmg`. Nothing else, no terminal,
no Python, no admin rights.

The one thing they must be told in advance is the Gatekeeper warning, or it looks like
the file is broken or unsafe. Here is a message you can paste into Teams or email:

> **Zendesk Warning Light — install (about a minute)**
>
> 1. Open the `.dmg` I sent, then drag **Zendesk Warning Light** onto the **Applications**
>    folder in the same window.
> 2. Open your Applications folder, **right-click** Zendesk Warning Light and choose
>    **Open** — then **Open** again in the box that appears.
>    You must right-click the first time. Double-clicking gives *"cannot be opened
>    because the developer cannot be verified"*, which just means the app is not
>    registered with Apple. It is safe; it is only used inside our company.
> 3. A cat appears in your menu bar, top right, and a settings window opens.
> 4. Press **Sign in with Zendesk**, sign in with your normal Microsoft account.
> 5. On the **Modes** tab, tick the groups you want to be warned about.
>
> After that it runs by itself and starts when you log in. Click the cat in the menu bar
> for settings, to pause it, or to switch mode.

### Why the warning appears

The app is ad-hoc signed but not *notarised* by Apple. Notarisation needs an Apple
Developer ID at $99/year. If you get one, set it before building and the warning
disappears completely:

```bash
CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" ./build.sh
```

---

## Updating to a new version

Rebuild and reinstall — settings, modes and the sign-in are all kept:

```bash
./build.sh --clean
./install.sh --force
```

For colleagues, send the new `.dmg` and have them drag it over the old app, replacing it.
They do **not** need to sign in again.

---

## Uninstalling

```bash
./uninstall.sh                    # remove app + login item, keep settings
./uninstall.sh --remove-settings  # also delete settings, logs and the Keychain item
```

---

## Running without building

To try it straight from source — no app bundle, no installer:

```bash
./run.command
```

Or double-click `run.command` in Finder. It sets up the environment on first use. Quit it
from the menu-bar cat.

---

## Where things end up

| What | Where |
|---|---|
| The app | `~/Applications/ZendeskWarningLight.app` |
| Settings, modes, schedule | `~/Library/Application Support/ZendeskWarningLight/config.json` |
| Ticket history | `…/ZendeskWarningLight/state.json` |
| Log file | `…/ZendeskWarningLight/warning-light.log` |
| Sign-in token | your **login Keychain** (not a file) |
| Start-at-login entry | `~/Library/LaunchAgents/com.yourcompany.zendeskwarninglight.plist` |

Nothing is written outside your home folder.

---

## Troubleshooting

Start with the log — menu-bar cat → **Settings → General → Open log file**, or:

```bash
tail -40 ~/Library/Application\ Support/ZendeskWarningLight/warning-light.log
```

| Symptom | Cause and fix |
|---|---|
| `pip` cannot find PySide6 | Python is 3.9 or under Rosetta. See [the Python trap](#the-python-trap--check-this-properly) |
| `./build.sh: Permission denied` | Run step 2: `chmod +x build.sh install.sh uninstall.sh run.command` |
| `bad interpreter` | The file arrived with Windows line endings. `sed -i '' 's/\r$//' *.sh run.command` |
| `iconutil: command not found` | `xcode-select --install` |
| "cannot be opened because the developer cannot be verified" | Expected. Right-click the app → **Open**, once |
| "is damaged and can't be opened" | Quarantine flag survived the copy: `xattr -dr com.apple.quarantine ~/Applications/ZendeskWarningLight.app` |
| No cat in the menu bar after building | Check the log. If it is empty the app never started — try `./run.command` to see errors in the terminal |
| No cat after logging in | Login item missing or the app moved. Re-run `./install.sh` |
| Sign-in never finishes in the browser | Ports 47821–47823 all in use. `lsof -nP -iTCP:47821-47823 \| grep LISTEN` |
| Menu bar shows a red cat | Not signed in, sign-in expired, or a Zendesk error — hover it for the reason |
| Warning never appears | Check the mode in force (menu-bar cat → **Mode**). An Off Day is silent by design |
| Warning hides behind a full-screen app | Known limitation — see the README |

To re-run the automated checks at any point:

```bash
./.venv/bin/python tools/preflight.py                          # the macOS layer
for t in rules sources modes groups_tab; do \
  ./.venv/bin/python tests/test_$t.py; done                    # the 128 logic checks
```
