# Zendesk Warning Light — macOS

The Apple Silicon port. A menu-bar app that puts an animated warning in the corner of
your screen when a Zendesk ticket needs someone's attention. Click the animation to
dismiss it; click the panel underneath to open the ticket. It disappears on its own as
soon as the underlying reason goes away.

**Every feature matches the Windows build** — the same three alert rules, user-defined
modes owning their own rules and groups, the weekly schedule with Off Days, per-user
Zendesk sign-in, pause options, and the cat.

> ⚠️ **This port was written on Windows and has not yet been run on a Mac.** PyInstaller
> cannot cross-compile, so the `.app` and `.dmg` must be built on the Mac itself. The
> shared logic is covered by the same 128 automated checks as the Windows build, and
> `tools/preflight.py` verifies the macOS-specific layer in one command. Run that first.

## Requirements

| | |
|---|---|
| Mac | Apple Silicon (M1 or later), macOS 12 Monterey or newer |
| Python | 3.10–3.13, **arm64 native** — `python3 -c 'import platform; print(platform.machine())'` must say `arm64` |
| To build | Xcode command line tools (`xcode-select --install`) for `iconutil` and `codesign` |

macOS ships Python 3.9, which is too old for PySide6 wheels. Install a current one from
[python.org](https://www.python.org/downloads/macos/) or `brew install python@3.12`.

If Python reports `x86_64` on an M-series Mac it is running under Rosetta, and the app
would be built for the wrong architecture. `build.sh` refuses to continue in that case.

## First: check the Mac can run it

```bash
python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python tools/preflight.py
```

It checks the architecture, Python, Qt and its Cocoa plugin, that both animations decode,
that the overlay window actually appears, a real Keychain write/read/delete round trip,
that the LaunchAgent plist we generate passes `plutil -lint`, the settings folder, and
that a sign-in callback port is free. Nothing permanent is changed.

If that passes, the platform layer works and the build is worth trusting.

## Build

```bash
./build.sh              # .app + dist/ZendeskWarningLight-<version>.dmg
./build.sh --app-only   # skip the disk image
./build.sh --clean      # discard previous output first
```

Hand `dist/ZendeskWarningLight-<version>.dmg` to colleagues. They drag the app to
Applications — the image contains an Applications symlink so the window works as a
drag-and-drop target.

## Install

Either drag it out of the `.dmg`, or script it:

```bash
./install.sh                  # build if needed, install, start at login, launch
./install.sh --no-autostart   # skip the login item
./install.sh --no-launch      # do not start it now
./install.sh --system         # /Applications rather than ~/Applications
./install.sh --force          # rebuild first
```

It installs to `~/Applications` by default, so **no sudo and no admin rights**.

### Gatekeeper: the first launch

The app is **ad-hoc signed but not notarised**, so the first time anyone opens it macOS
says *"Zendesk Warning Light cannot be opened because the developer cannot be verified."*
That is expected. Get past it once:

- **Right-click the app → Open**, then confirm — or
- **System Settings → Privacy & Security**, scroll down, **Open Anyway**

After that it launches normally forever. Tell colleagues in advance, or it looks alarming.

Ad-hoc signing is not optional on Apple Silicon: arm64 macOS refuses to run code with no
signature at all. Proper notarisation needs an Apple Developer ID ($99/year); if you get
one, set `CODESIGN_IDENTITY="Developer ID Application: …"` before `./build.sh` and the
warning goes away entirely.

## Uninstall

```bash
./uninstall.sh                    # remove the app and login item, keep settings
./uninstall.sh --remove-settings  # also delete settings, logs and the Keychain item
```

## First run

The Settings window opens on the **Connection** tab. Press **Sign in with Zendesk** —
your browser opens, you sign in with Microsoft as usual, and the app never sees your
password. Then pick your groups per mode on the **Modes** tab.

There is no Dock icon by design (`LSUIElement`), the same as the Windows build having no
taskbar button. Everything is reached from the cat in the menu bar.

## How this differs from the Windows build

The application logic is byte-for-byte identical. Only the platform layer changes:

| Concern | Windows | macOS |
|---|---|---|
| Sign-in token | DPAPI-encrypted inside `tokens.json` | **login Keychain**; `tokens.json` holds only a marker |
| Start at login | `HKCU\…\CurrentVersion\Run` | **LaunchAgent** at `~/Library/LaunchAgents/com.yourcompany.zendeskwarninglight.plist` |
| Settings, state, log | `%APPDATA%\ZendeskWarningLight` | `~/Library/Application Support/ZendeskWarningLight` |
| Reveal a file | `os.startfile` | `/usr/bin/open` |
| No taskbar/Dock entry | `Qt.Tool` window flag | `LSUIElement` in `Info.plist` |
| App icon | `.ico` | `.icns` via `iconutil` |
| Installer | Inno Setup `.exe` | `.dmg` + `install.sh` |
| Signing | unsigned, SmartScreen warns | ad-hoc signed (mandatory on arm64), Gatekeeper warns |

Only five files differ: `zwl/paths.py`, `zwl/keystore.py`, `zwl/autostart.py`, and small
patches to `zwl/settings_ui.py` and `zwl/auth.py`. Everything else — `monitor.py`,
`modes.py`, `config.py`, `sources.py`, `zendesk.py`, `overlay.py`, `icons.py` — is the
Windows code unchanged.

The OAuth setup needs **no changes in Zendesk**: the loopback redirect URLs already
registered (`http://127.0.0.1:47821-47823/callback`) work identically on macOS.

## Known limitations

- **Full-screen apps.** The overlay is a topmost window, which floats above normal and
  maximised windows but not above a true full-screen Space. Fixing that needs an
  `NSWindow` level change through pyobjc, which this port deliberately avoids to stay
  dependency-light. Windows has the same limitation with exclusive-fullscreen apps.
- **The menu-bar icon is in colour.** macOS convention is a monochrome template image
  that adapts to light/dark menu bars. The colour cat is deliberate — it is the app's
  identity — but it will not invert in dark mode like system icons do.
- **`security` CLI for the Keychain.** The token appears in this process's argv for the
  moment the command runs, so a local user running `ps` at exactly the wrong time could
  see it. Acceptable for a per-user read-only token on a single-user laptop; the fix, if
  ever needed, is `SecItemAdd` through ctypes. See the note at the top of `keystore.py`.
- **The 1024px icon is upscaled** from the 480px GIF frame, so it is slightly soft in
  Finder's largest preview. Every size macOS actually uses is at or below native.

## Files

```
main.py                  entry point
zwl/app.py               menu bar icon, menus, wiring
zwl/auth.py              sign-in (PKCE), token store, rotating refresh
zwl/keystore.py          macOS Keychain  <- platform layer
zwl/autostart.py         LaunchAgent     <- platform layer
zwl/paths.py             ~/Library paths <- platform layer
zwl/monitor.py           polling loop and the transition rules
zwl/modes.py             the DayMode type, seeding and the weekday plan
zwl/sources.py           the two ticket sources and how one is chosen
zwl/zendesk.py           REST client, authenticated as the signed-in user
zwl/overlay.py           the always-on-top animated window
zwl/settings_ui.py       settings dialog
zwl/config.py            settings model and persistence
zwl/icons.py             icons built from the cat GIF's first frame

build.sh                 .app + .dmg
install.sh               per-user install, login item
uninstall.sh             reverses it
run.command              double-click to run from source, no build

tools/preflight.py       verifies the macOS layer on a real Mac  <- run this first
tools/verify_oauth.py    standalone Zendesk sign-in check
tools/make_iconset.py    generates the .iconset for iconutil
tests/                   the same 128 platform-independent checks as Windows
```

## Troubleshooting

The log is at `~/Library/Application Support/ZendeskWarningLight/warning-light.log`, or
**Settings → General → Open log file**.

| Symptom | Cause |
|---|---|
| "cannot be opened because the developer cannot be verified" | Not notarised — right-click → Open, once |
| "is damaged and can't be opened" | The signature did not survive the copy. Re-run `./build.sh`, or `xattr -dr com.apple.quarantine` on the app |
| No menu-bar icon after login | Login item missing or pointing at a moved app. Re-run `./install.sh` |
| Sign-in never completes | Ports 47821-47823 all busy, or a redirect URL missing from the Zendesk OAuth client |
| `pip` cannot find PySide6 | Python outside 3.10–3.13, or an x86_64 Python under Rosetta |
| Warning hides behind a full-screen app | Known limitation, see above |

Run the shared logic tests any time:

```bash
for t in rules sources modes groups_tab; do ./.venv/bin/python tests/test_$t.py; done
```
