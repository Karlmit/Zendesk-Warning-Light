# Security Report — Zendesk Warning Light

**Date:** 2026-10-21
**Scope:** Whole repository: `windows/` and `macos/` app code (`zwl/*`), tools, build and install scripts, installers (Inno Setup, Intune, PowerShell, shell), dependency manifests, and full git history.
**Method:** Manual review, split across four parallel reviewers (auth/secrets, app/API/UI, macOS packaging, Windows packaging), then cross-checked and merged. A second pass on the same day re-read the app code, installers and the first pass's fixes, and added M7, L22 and I15. A follow-up fixed every open item that could be fixed and checked here: L20, L21, I11, I12 and I15.

## Summary

| Severity | Found | Fixed | Open (recommendation only) |
|---|---|---|---|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 7 | 6 | 1 |
| Low | 22 | 21 | 1 |
| Info | 15 | 9 | 6 |

Nothing was found that a remote attacker could exploit on its own. The most important fixes:

- The Zendesk subdomain is now validated, so OAuth codes, refresh tokens and access tokens can't be sent to another host.
- The bearer token is now only ever sent to the configured Zendesk host. The second pass closed a bypass of this check through relative paths (M7).
- A silent machine-wide install no longer starts the app as SYSTEM.
- The `curl | bash` installer can no longer run halfway if the download is cut off.
- The installer's downloads can no longer be downgraded to plain HTTP (man-in-the-middle).

**Git history:** I searched all 28 commits for secrets and found none. The repo contains only the public OAuth client id (`warning_light_desktop`), the `yourcompany` placeholder and test dummies.

**Verification:**
- All 9 macOS and 10 Windows test scripts pass, run with PySide6 and offscreen Qt. They were re-run after the second-pass and follow-up fixes, and `shellcheck` passes on `macos/install.sh`.
- The M7 and L22 fixes were also checked with targeted cases on both platforms (see those entries).
- `python -m py_compile` passes on every changed Python file.
- `bash -n` and `shellcheck` pass on all shell scripts.
- PowerShell 7.6 was installed on the Linux host. All three `.ps1` scripts parse, and PSScriptAnalyzer reports only style warnings (`Write-Host`, `ShouldProcess`), no errors.
- Inno Setup 6.7.3 was run under Wine 9.0. `ZendeskWarningLight.iss` and `Launcher.iss` both compile, using placeholder files in place of the PyInstaller build. The resulting `Setup.exe /S` installed per user (files, HKCU Run value) and `Setup.exe /S /uninstall` removed it, both with exit code 0.
- Still not tested: the real PyInstaller build on Windows, the `.cmd` Intune wrappers, machine-wide `/ALLUSERS` installs as SYSTEM, and the macOS installer. **Please test these on real Windows and macOS machines before you release.**

---

## Medium

### M1. Zendesk subdomain not validated: tokens could be sent to any host — FIXED
- **Files:** `{macos,windows}/zwl/config.py`, `zwl/auth.py`, `zwl/settings_ui.py`
- **Issue:** The subdomain was pasted into `https://{}.zendesk.com` with no check. A value like `evil.com#`, `a.evil.com/` or `x@evil.com/` moves the real host off zendesk.com. Sign-in (the code and PKCE verifier), token refresh (the refresh token) and every API call (the bearer token) would then go to the attacker's host. Someone has to type the value, perhaps after being tricked by fake "setup instructions", or edit `config.json`.
- **Fix:** Three layers, all using one rule:
  - `config.normalise_subdomain()` accepts `Acme`, `acme.zendesk.com` or `https://acme.zendesk.com/` and returns `acme`. Anything that isn't a single DNS label becomes empty. `Config.from_dict` and `Config.base_url` both use it.
  - The Settings dialog uses the same function and shows an "Invalid subdomain" message.
  - `auth.check_base_url()` requires exactly `https://<label>.zendesk.com` in `sign_in()`, the token refresh and `access_token()`. No caller can get a token for a bad address.

### M2. Bearer token sent to any absolute URL, such as `next_page` — FIXED
- **Files:** `{macos,windows}/zwl/zendesk.py` (`get`, `probe`, new `_url`)
- **Issue:** `get()` and `probe()` used any URL starting with `http` exactly as given and attached `Authorization: Bearer`. `groups()` follows the `next_page` link from the API response. A tampered response could send the token to another host or over plain http.
- **Fix:** `_url()` only allows an absolute URL whose scheme and host:port match `base_url`. Anything else raises `ZendeskError` before a request is sent. Tested against another host, an http downgrade, `acme.zendesk.com.evil.com` and `acme.zendesk.com@evil.com`.

### M3. Silent machine-wide install started the app as SYSTEM, and the interactive one ran it elevated — FIXED
- **Files:** `windows/installer/ZendeskWarningLight.iss` ([Run], `ShouldLaunchAfterSilent`), `windows/README.md`
- **Issue:** The Intune system-context install (`/ALLUSERS`) launched the network-facing tray app as LocalSystem in session 0. An interactive `/ALLUSERS` install launched it with the admin token. Any bug in the app would then run as SYSTEM or admin.
- **Fix:** `ShouldLaunchAfterSilent` returns False when running as SYSTEM, and both `[Run]` entries use `runasoriginaluser`. Users still get the app from the HKLM Run value at their next sign-in. The README is updated to match.

### M4. `curl | bash` installer could run half a script — FIXED
- **File:** `install/install-macos.sh`
- **Issue:** The script ran top to bottom while it streamed in, so a dropped connection could leave a partly run install.
- **Fix:** The body is wrapped in `main() { … }` and only called on the last line. The `rm -rf` in cleanup now checks that the temp folder variable is set.

### M6. Installer downloads could be downgraded to plain HTTP (man-in-the-middle) — FIXED
- **Files:** `install/install-macos.sh`, `README.md`, `macos/README.md`
- **Issue:** The installer fetched the source tarball with `curl -fsSL`. The `-L` flag follows redirects, and curl allows a redirect from `https://` to `http://` by default. GitHub's archive URL redirects (to `codeload.github.com`). Anyone positioned to tamper with that redirect, or able to force an HTTPS→HTTP downgrade, could serve a modified tarball over plain HTTP. The installer would then build and run that code as the user. TLS 1.0/1.1 were also not ruled out.
- **Fix:**
  - The tarball download now uses `curl --proto '=https' --proto-redir '=https' --tlsv1.2 -fsSL`, so every hop must be HTTPS with TLS 1.2 or later; otherwise the install stops.
  - The documented one-liner (both READMEs and the script header) now starts with `curl --proto '=https' --tlsv1.2 -fsSL`.
- **Still relevant:** See M5. A checksum or signature check would also protect against a compromised source, not just a compromised network path.

### M5. Installer builds whatever is on `main`, with no pin or checksum — OPEN
- **File:** `install/install-macos.sh`
- **Issue:** The installer downloads the `main` branch and builds and runs it. Anyone who can push to `main`, including through a compromised account, reaches every new install and update.
- **Already in place:** HTTPS only, `curl -f`, `set -euo pipefail`, and a `ZWL_REF` override. The script header now explains how to pin to a tag or commit.
- **Not changed because:** "always latest" is the advertised way to update, so changing it is the owner's call.
- **Recommendation:**
  - Publish tagged releases and point the README one-liner at a tag.
  - Optionally publish a SHA-256 of the download and check it in the script.

### M7. The M2 host check could be bypassed by a value without a scheme — FIXED (second pass)
- **Files:** `{macos,windows}/zwl/zendesk.py` (`_url`)
- **Issue:** `_url()` only checked the host when the value started with `http://` or `https://`. Anything else was pasted straight after the base URL, so the host could still be moved:
  - `@evil.com/x` became `https://acme.zendesk.com@evil.com/x`, and the real host is `evil.com`. The Zendesk part is just the userinfo.
  - `.evil.com/x` became `https://acme.zendesk.com.evil.com/x`.
  - `:443@evil.com/x` also went to `evil.com`.
  
  `groups()` passes the response's `next_page` to `get()`, so a tampered response with a `next_page` like this one sent the bearer token off-host. That is exactly what M2 was meant to stop. It needs the same tampered API response as M2 to exploit, so it has the same rating.
- **Fix:** `_url()` only treats a value as relative when it starts with a single `/`. Everything else is taken as a full URL. Either way, it compares the scheme and the full `netloc` (userinfo included) of the URL that will actually be requested against `base_url`. All of these are now refused before any request is sent: the three values above, `//evil.com/x`, `HTTPS://evil.com/x`, `https://u@acme.zendesk.com/x`, `http://acme.zendesk.com/x` and the bare `api/v2`. Normal relative paths and same-host `next_page` links still work.

---

## Low

| # | Issue | File(s) | Status / fix |
|---|---|---|---|
| L1 | Any request to the loopback `/callback` ended sign-in, whatever its `state`. A web page or local process could abort sign-in or show its own error text in the app | `zwl/auth.py` | **Fixed.** The listener only accepts a request with the expected state (constant-time compare). Others get a 400 and are ignored |
| L2 | An idle connection could block the loopback listener, and its socket was never closed | `zwl/auth.py`, `tools/verify_oauth.py` | **Fixed.** 10 s timeout per connection; `server_close()` |
| L3 | Windows: SO_REUSEADDR let another process bind the callback port | `zwl/auth.py` | **Fixed.** `allow_reuse_address` is off on Windows |
| L4 | When the Keychain or DPAPI refused to store the refresh token, it was written to `tokens.json` as plaintext base64 | `zwl/keystore.py` | **Fixed.** The token is kept in memory for that session only, and the user signs in again on next start |
| L5 | `tokens.json` and the macOS data directory were created with default permissions | `zwl/auth.py`, `macos/zwl/paths.py` | **Fixed.** File is 0600 (written atomically), directory 0700 |
| L6 | Token POSTs followed redirects; a 307/308 would re-send the refresh token or code in the body | `zwl/auth.py`, `tools/verify_oauth.py` | **Fixed.** `allow_redirects=False` |
| L7 | Reflected XSS on the `verify_oauth.py` callback error page | `tools/verify_oauth.py` | **Fixed.** Text is `html.escape`d |
| L8 | Wrong types in `config.json` crashed startup | `zwl/config.py` | **Fixed.** Falls back to defaults, as for unparsable JSON |
| L9 | Message boxes let Qt guess whether text was HTML, so Zendesk reply text and user names could render as rich text (spoofing) | `zwl/settings_ui.py` | **Fixed.** Plain-text message boxes (`_plain_message`) |
| L10 | A sound name could be a path, including a UNC path on Windows, which leaks NTLM credentials | `zwl/sound.py` | **Fixed.** Only bundled sounds can play (second layer behind the config check) |
| L11 | A ticket id restored from `state.json` wasn't forced to an integer but went unescaped into the overlay's HTML | `zwl/monitor.py` | **Fixed.** `int()` on load; bad entries are skipped |
| L12 | A malformed or negative `Retry-After` header crashed the poll | `zwl/zendesk.py` | **Fixed.** Falls back to 10 s, capped at 0–60 s |
| L13 | Inno Setup called `taskkill` through `cmd.exe`, which searches the current directory first, while elevated or SYSTEM | `ZendeskWarningLight.iss` | **Fixed.** Calls `{sys}\taskkill.exe` directly |
| L14 | Intune scripts running as SYSTEM called `whoami`, `find`, `reg` and `ping` by bare name | `Intune-Install.cmd`, `Intune-Uninstall.cmd` | **Fixed.** Full `%SystemRoot%\System32\…` paths |
| L15 | Unpinned dependencies; `requests>=2.31` allowed versions affected by CVE-2024-35195 and CVE-2024-47081; PyInstaller had no version | `{macos,windows}/requirements.txt`, `build.ps1`, `build.sh` | **Fixed.** `PySide6>=6.6,<7`, `requests>=2.32.4,<3`, `pyinstaller>=6.10,<7` (Windows) / `>=6,<7` (macOS) |
| L16 | Uninstaller copied itself to a predictable `%TEMP%` path and never deleted it | `windows/installer/uninstall.ps1` | **Fixed.** Random (GUID) name; the copy deletes itself |
| L17 | The LaunchAgent plist was built by pasting `$HOME` into the XML, so `&` or `<` in the path broke it | `macos/install.sh` | **Fixed.** Fixed template; path written with `plutil -replace`; `chmod 644` |
| L18 | `run.command` carried on after errors | `macos/run.command` | **Fixed.** `set -euo pipefail` |
| L19 | macOS Keychain: the refresh token briefly appears in the `security … -w <token>` command line, and items made by the `security` tool can be read by any process of the same user | `macos/zwl/keystore.py` | **Open.** Couldn't be tested here, and a change could break token storage. Recommendation: use `SecItemAdd`/`SecItemCopyMatching` via ctypes or pyobjc |
| L20 | Uninstall deletes the whole `{app}` folder; if a user picked an existing folder, its contents are lost | `ZendeskWarningLight.iss` | **Fixed.** `DisableDirPage=yes`, so the installer always uses its own `{autopf}\ZendeskWarningLight` folder. An admin can still pass `/DIR=` on the command line, and the uninstaller deletes that folder too |
| L21 | Windows build uses Python 3.10, which reaches end of life in October 2026 | `windows/build.ps1` | **Fixed.** `build.ps1` now uses `py -3.12`; the top-level README says so. Build machines need Python 3.12 installed |
| L22 | The animation setting accepted any absolute path, including a UNC path such as `\\host\share\x.gif`. On Windows, just checking whether it exists (at startup and on every settings change) makes Windows connect to that host over SMB and send the user's NTLM hash. This is the same leak as L10, through the animation setting instead of the sound. It needs a crafted `config.json` or a user picking a network file. Found in the second pass | `{macos,windows}/zwl/config.py` | **Fixed.** New `config.is_network_path()` matches any path starting with two slashes or backslashes (`\\host`, `//host`, `\\?\UNC\…`). `Config.from_dict` resets such a value to the bundled animation, and `animation_path()` never returns one, as a second layer. Local absolute paths still work |
| — | Hash-pinned lock files | both platforms | **Open.** Recommendation: `pip-compile --generate-hashes` plus `--require-hashes` for reproducible builds that show tampering |

## Info

| # | Issue | Status |
|---|---|---|
| I1 | The "animation missing" message put the file name into HTML unescaped | **Fixed.** Escaped (`overlay.py`) |
| I2 | `Stop-Process` also hit other users' sessions and aborted install/uninstall on multi-user machines | **Fixed.** Limited to the current session |
| I3 | No top-level `.gitignore` | **Fixed.** Added (`__pycache__`, `.venv`, `build`, `dist`, `*.dmg`, `.env`, …) |
| I4 | `windows/.gitignore` didn't ignore install logs or Intune packages | **Fixed.** Added `*.log` and `*.intunewin` |
| I5 | Settings dialog and config had separate subdomain rules (Settings rejected `acme.zendesk.com`) | **Fixed.** Settings uses `config.normalise_subdomain()` |
| I6 | The README said a silent install starts the app | **Fixed.** Now says it never starts under SYSTEM |
| I7 | Ticket subjects and the agent's identity are written to the local log | Open. Kept on purpose for troubleshooting. If logs are collected centrally, drop the subject or log it only with `--verbose` |
| I8 | Responses are read with no size limit | Open. Low risk: page sizes are capped and the host is enforced (M2) |
| I9 | `xattr -dr com.apple.quarantine` / ad-hoc signing / `codesign --deep` | Open. Recommendation: Developer ID signing and notarization for distributed builds |
| I10 | Python is found on the user's PATH, and Homebrew may install Python without asking | Open. Crosses no privilege boundary |
| I11 | The `--system` error message says "or use sudo" although the script refuses to run as root | **Fixed.** Now says to re-run without `--system` or ask an administrator to make the folder writable (`macos/install.sh`) |
| I12 | `.cmd` files are stored with LF line endings, which cmd can mishandle around `goto` labels | **Fixed.** New `.gitattributes` with `*.cmd text eol=crlf` and `*.bat text eol=crlf`. Git still stores them with LF, so the diff shows no content change; any checkout, Windows included, gets CRLF. The local copies were converted to match |
| I13 | Launcher and Intune uninstall fall back to the HKCU uninstall entry | Open. No privilege boundary is crossed in supported flows |
| I14 | Per-user uninstall uses `ExecutionPolicy Bypass` on its own script | Open. ExecutionPolicy is not a security boundary |
| I15 | `tokens.json` doesn't record which Zendesk account issued the refresh token. The account comes from `config.json` alone. If `config.json` is changed to another subdomain while signed in (Settings blocks this, but hand-editing doesn't), the refresh token is sent to that other `*.zendesk.com` account. Only a process running as the same user can do this, and such a process can already decrypt the token | **Fixed** (`{macos,windows}/zwl/auth.py`). `tokens.json` now saves the account that issued the token (`base_url`). `access_token()` and the refresh refuse to run when the configured account differs; the error says to sign out and sign in again, and nothing is sent. The token is kept, so undoing the edit fixes it. An older `tokens.json` without the field is pinned to the account configured when it is first loaded. Tested on both platforms: a legacy file is pinned, a changed subdomain is refused with no request sent, undoing the change works again, and sign-out clears the binding |

## Checked and fine

- **OAuth:**
  - PKCE uses S256 with a verifier from 32 random bytes.
  - `state` has 192 bits and is checked before the code is exchanged.
  - The listener binds `127.0.0.1` only.
  - No client secret is shipped.
  - Access tokens are never saved to disk.
  - DPAPI is scoped to the current user with app-specific entropy.
- **Network:**
  - TLS verification is never turned off.
  - Every request has a timeout.
  - Tokens never appear in logs or error text.
- **UI:**
  - The overlay caption and Settings labels escape all Zendesk data.
  - Opened URLs are built only from the configured base URL plus an integer ticket id, never taken from the API.
  - The changelog is static text.
- **No dangerous code paths:**
  - No `eval`, `pickle`, `yaml` or `shell=True`.
  - Subprocesses get argument lists, never a shell string.
- **Windows install:**
  - Run-key values are quoted.
  - Machine-wide installs go to Program Files, with no folders users can write to.
  - The launcher extracts into Inno's random `{tmp}`.
- **macOS install:**
  - No sudo and no `chmod 777`.
  - Every `rm -rf` target is built from fixed names plus `$HOME`.
  - `zwl/autostart.py` writes the plist with `plistlib`.
- **Repository:** `git ls-files` shows no build output, credentials or token files.

## Changed files

`install/install-macos.sh`, `README.md`, `macos/README.md`, `macos/{build.sh,install.sh,run.command,requirements.txt}`, `macos/tools/verify_oauth.py`, `macos/zwl/{auth,config,keystore,monitor,overlay,paths,settings_ui,sound,zendesk}.py`, `windows/{.gitignore,README.md,build.ps1,install.ps1,requirements.txt}`, `windows/installer/{ZendeskWarningLight.iss,Intune-Install.cmd,Intune-Uninstall.cmd,uninstall.ps1}`, `windows/tools/verify_oauth.py`, `windows/zwl/{auth,config,keystore,monitor,overlay,settings_ui,sound,zendesk}.py`, new `.gitignore`, new `SECURITY_REPORT.md`.

Second pass and follow-up (left uncommitted for review):
- `{macos,windows}/zwl/zendesk.py` (M7)
- `{macos,windows}/zwl/config.py` (L22)
- `{macos,windows}/zwl/auth.py` (I15)
- `windows/installer/ZendeskWarningLight.iss` (L20)
- `windows/build.ps1` and `README.md` (L21; the README also lists the current dependency ranges)
- `macos/install.sh` (I11)
- new `.gitattributes`, plus the three `.cmd`/`.bat` files converted to CRLF (I12)