# Security Report — Zendesk Warning Light

**Date:** 2026-10-21, updated 2026-10-22
**Scope:** Whole repository: `windows/` and `macos/` app code (`zwl/*`), tools, build and install scripts, installers (Inno Setup, Intune, PowerShell, shell), dependency manifests, and full git history.
**Method:** Manual review, split across four parallel reviewers (auth/secrets, app/API/UI, macOS packaging, Windows packaging), then cross-checked and merged. A second pass on the same day re-read the app code, installers and the first pass's fixes, and added M7, L22 and I15. A follow-up fixed every open item that could be fixed and checked here: L20, L21, I11, I12 and I15. On 2026-10-22, automated scanners were added on top (see Tool scans), plus permanent security regression tests, CI on real Windows and macOS machines, and hash-pinned dependencies; L19 and the lock-file item were closed.

## Context and focus (decided 2026-10-22)

This is an internal app for a small team. The macOS install command (`install/install-macos.sh`) is run by one employee, and the Windows app is installed by hand or through Intune. **Hardening therefore focuses on the installed app**: what runs on people's machines, the data it holds and logs, and what it talks to.

Given that context, the owner **accepted** the repository-process items: M5 (the installer builds from `main`) and Scorecard's Branch-Protection, Code-Review, Signed-Releases/Packaging, License and CII-Best-Practices. They add process without reducing real risk for a team this size. **Code signing (I9) is also accepted**, because no signing certificate is available. Everything that protects the installed build stays in place: the security tests, CI on real Windows and macOS, hash-pinned dependencies and Dependabot.

## Summary

| Severity | Found | Fixed | Open (recommendation only) |
|---|---|---|---|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 7 | 6 | 1 accepted (M5) |
| Low | 22 | 22 | 0 (L19 has an accepted residual part) |
| Info | 15 | 11 | 4 accepted (I9, I10, I13, I14) |
| Tool scans, fuzzing and app review (S1–S6) | 6 | 6 | 0 |

Nothing was found that a remote attacker could exploit on its own. The most important fixes:

- The Zendesk subdomain is now validated, so OAuth codes, refresh tokens and access tokens can't be sent to another host.
- The bearer token is now only ever sent to the configured Zendesk host. The second pass closed a bypass of this check through relative paths (M7).
- A silent machine-wide install no longer starts the app as SYSTEM.
- The `curl | bash` installer can no longer run halfway if the download is cut off.
- The installer's downloads can no longer be downgraded to plain HTTP (man-in-the-middle).

**Git history:** I searched all 28 commits for secrets and found none; gitleaks confirmed this on 2026-10-22 across all 31 commits. The repo contains only the public OAuth client id (`warning_light_desktop`), the `yourcompany` placeholder and test dummies.

**Verification:**
- All 10 macOS and 11 Windows test scripts pass (originally 9 and 10; the new security tests added the rest), run with PySide6 and offscreen Qt. They were re-run after the second-pass and follow-up fixes, and `shellcheck` passes on `macos/install.sh`.
- The M7 and L22 fixes were also checked with targeted cases on both platforms (see those entries).
- `python -m py_compile` passes on every changed Python file.
- `bash -n` and `shellcheck` pass on all shell scripts.
- PowerShell 7.6 was installed on the Linux host. All three `.ps1` scripts parse, and PSScriptAnalyzer reports only style warnings (`Write-Host`, `ShouldProcess`), no errors.
- **Full Windows build under Wine 9.0**, following `build.ps1` step by step. Windows PowerShell and the `py` launcher don't run under Wine, so each step was run directly:
  - Windows Python 3.12.10 (64-bit), a fresh venv, and `pip install -r requirements.txt "pyinstaller>=6.10,<7"`.
  - All 10 Windows test scripts pass on Windows Python, including `test_autostart.py`, which writes to the real (Wine) registry.
  - PyInstaller 6.22.3 built `dist\ZendeskWarningLight\ZendeskWarningLight.exe` with the version stamped (2.9.0).
  - Inno Setup 6.7.3 compiled `ZendeskWarningLight.iss` and `Launcher.iss` around that build into `ZendeskWarningLight-Setup-2.9.0.exe` (38 MB).
  - `Setup.exe /S` installed per user with the HKCU Run value and started the app. Launched again on its own, the app showed its tray icon and the first-run Settings dialog. `Setup.exe /S /uninstall` removed the app folder, the Run value and the uninstall entry. All exit codes were 0.
  - **One difference from a real build:** PySide6 6.12 (the newest version `requirements.txt` allows) needs Windows' own `icuuc.dll`, which Wine 9 doesn't have, so this build used PySide6 6.8.3, which is also in range. A real Windows build will pick up 6.12.
- **Since 2026-10-22, CI on real machines** (see Continuous checks): every test passes on real Windows and macOS with PySide6 6.12. The Windows build and installer, the Intune wrappers as SYSTEM, the machine-wide install and the macOS `.app` build are all checked on every push.
- **Still not tested:**
  - signing in against a real Zendesk account (it needs an account and a browser);
  - the app's windows and tray on a real desktop with a person using it (CI runs offscreen);
  - Intel Macs (the CI Mac is Apple silicon);
  - `install/install-macos.sh` end to end, which builds from GitHub and registers a login item.
  
  **Please do a manual smoke test of these before a release.**

---

## Tool scans (2026-10-22)

Automated scanners, run on top of the manual review. Every tool was downloaded from its official release and checked against the published SHA-256 checksum where one exists.

| Tool | What it checks | Result |
|---|---|---|
| gitleaks 8.30.1 | Secrets in all 31 commits and in the working tree | **No leaks found** |
| GitHub secret scanning + push protection | Secrets on every push (server side) | Already enabled on the repo |
| pip-audit 2.10.1 | Known CVEs in every pinned dependency (`{windows,macos}/requirements-build.txt`) | **No known vulnerabilities** |
| Bandit 1.9.4 | Python security anti-patterns, 9,100 lines | 0 high, 0 medium, 36 low. Triage below |
| Semgrep 1.182.1 (`p/python`, `p/security-audit`, `p/secrets`, `p/command-injection`) | Broader security rules, 69 files | 4 results. Triage below |
| ShellCheck | All shell scripts | Clean |
| PSScriptAnalyzer | All three `.ps1` scripts | No errors; style warnings only (`Write-Host`, `ShouldProcess`) |
| OpenSSF Scorecard 5.6.0 | Repository security practices | **2.1 → 5.8 / 10** after this work. See Scorecard below |
| atheris 3.1.0 (coverage-guided fuzzer) | The token host checks (M1, M2, M7) with random input | **Found S5** within seconds; after the fix, 6.4 million inputs in 5 minutes with no failures |
| actionlint 1.7.12, zizmor 1.31.1 | The new GitHub workflows | No findings |

**Bandit triage (36 low):**
- **Fixed (S1):** `explorer` started by bare name in `windows/zwl/settings_ui.py` (B607); it is looked up in the current directory first. Now the full path from `GetSystemWindowsDirectoryW`.
- **Fixed (S2):** `assert` used as a check in `{windows,macos}/zwl/modes.py` (B101); `python -O` drops asserts. Now an explicit `ValueError`.
- **Fixed (S3, found while triaging):** `macos/zwl/keystore.py` fell back to whatever `security` was first on `PATH` when `/usr/bin/security` was missing. Now only `/usr/bin/security` is used.
- **False positives (33):**
  - B105 (×12) flags `TOKEN_PATH = "/oauth/tokens"` and empty-string resets as "hardcoded passwords".
  - B404/B603 (×14) flag subprocess calls that all use a fixed absolute binary (`/usr/bin/security`, `/bin/launchctl`, `/usr/bin/afplay`, `/usr/bin/open`, `/usr/bin/plutil`) with an argument list and no shell.
  - B606 (×2) flags `os.startfile` on the app's own data folder and log.
  - B112 (×2) flags `except Exception: continue` when skipping malformed `state.json` entries.
  - B404 (×3) flags `import subprocess` itself.

**Semgrep triage (4):**
- **Fixed (S4):** `python-logger-credential-disclosure` in `{windows,macos}/zwl/auth.py`. When a refresh was rejected, the raw Zendesk reply (up to 200 characters) went into `warning-light.log`, which people attach to support requests. No token was seen in practice, but the body isn't under our control. The first fix logged only the OAuth `error` code. CodeQL still traced that back to the reply of a request that carried the refresh token (`py/clear-text-logging-sensitive-data`), so the final fix logs only the HTTP status (`refresh token rejected (HTTP 400)`). CodeQL now reports no open alerts.
- **Fixed (S1, second rule):** `dangerous-subprocess-use-tainted-env-args` on the first version of the S1 fix, which built the path from `%SystemRoot%`. The environment can change that, so the fix asks Windows for the directory instead.
- **False positive:** `insecure-file-permissions` on `os.chmod(path, 0o700)` in `macos/zwl/paths.py`. 0700 is owner-only (this is the L5 fix); the rule flags any mode that includes the execute bit, which a directory needs.

**Fuzzing (S5):** `fuzz/fuzz_token_hosts.py` feeds random text to the three checks that decide where a token may go, and asserts these invariants:
- `normalise_subdomain` returns nothing or a single DNS label.
- `check_base_url` only accepts `https://<label>.zendesk.com`.
- `_url` either refuses, or produces a URL that `requests` really sends to `acme.zendesk.com` over https with no userinfo or port.

The last invariant reads the host with urllib3's parser, the one used on the wire, rather than the `urlsplit` that `_url` checks with, so any disagreement between the two parsers counts as a failure.
- **Fixed (S5, Low):** within seconds the fuzzer found that a malformed host such as `//[JJ` or `https://[::1/x` made `_url()` raise a bare `ValueError` instead of `ZendeskError`. A tampered `next_page` could use this to break callers that fall back on `ZendeskError`, such as the incremental-export to ticket-sweep fallback in `sources.py` and the groups list in Settings; the poll itself survives through the monitor's catch-all. `_url()` now turns it into `ZendeskError`, and both values are in `test_security.py`.
- The fuzzer runs for 2 minutes on every push in CI (`tests.yml`, job `fuzz`), with hash-pinned dependencies in `fuzz/requirements.txt`.

**Hash-pinned lock files (closes the open lock-file item):**
- New `{windows,macos}/requirements-build.in` list the version ranges, including PyInstaller. They are compiled with `uv pip compile --generate-hashes` into `requirements-build.txt`; the exact command is at the top of each lock.
- The Windows lock targets Windows x64 / Python 3.12. The macOS lock is universal for Python 3.10 and later, so it works on both Intel and Apple silicon.
- `build.ps1`, `build.sh` and `run.command` now install with `pip install --require-hashes -r requirements-build.txt`, so a tampered or swapped package fails the build.
- The unpinned `pip install --upgrade pip` steps are removed; the pip that ships with Python handles hashes fine.

---

## Security regression tests (2026-10-22)

The checks that were run once by hand during the review are now permanent test scripts, so a later change that reopens a hole fails the build:

- **`{windows,macos}/tests/test_security.py`** (89 checks): each check names the finding it guards and tries the actual attack:
  - **M1:** 10 hostile subdomains are rejected, and `check_base_url`, `sign_in` and `access_token` refuse non-Zendesk addresses.
  - **M2/M7:** two real local HTTP servers, one playing Zendesk and one an attacker. A `next_page` pointing at the attacker (absolute, `@host` and `//host` forms) is refused, and the attacker server receives no request at all. `_url` refuses 11 crafted values, including the two S5 inputs.
  - **L1:** the real loopback listener refuses a wrong `state`, a bare `error=`, and a second redirect after the first.
  - **L5:** `tokens.json` is 0600 (macOS/Linux).
  - **L6:** the refresh and the code exchange don't follow redirects.
  - **I15:** another account's address is refused and nothing is sent.
  - **S4:** a rejected refresh logs the HTTP status and nothing from the reply.
  - **L8, L10, L22:** bad config types, path-like sound names and UNC animation paths are neutralised.
  - **L12:** hostile `Retry-After` values (junk, negative, huge, HTTP-date) give bounded waits.
  - **I8:** a real local server sends a normal reply (parsed), a reply over 32 MB with `Content-Length` (refused) and a 32 MB gzip bomb with no length (refused while it decompresses).
  - **I7:** the log label for the signed-in user has no name or email; no module logs `describe()`; ticket subjects are only logged at debug level.
  - **S6:** different users get different "already running" keys, the key doesn't contain the user name, and the server is restricted to the current user.
- **`macos/tests/test_keystore.py`** (10 checks, plus 6 on a real Mac): L19 and S3, described in the L19 row.

**The tests were checked against old code, to confirm they catch the holes:**
- On the commit before the second pass (`403df7a`), exactly the 19 checks for M7, I15, S4 and L22 fail. On that code, the attacker server really did receive the bearer token.
- On the commit before the first review (`bcaa05a`), the script stops with an error at the first check, because the subdomain validation did not exist yet. That still counts as a failed run.
- On the current code, all 74 checks pass on Linux, and in CI on real Windows and macOS (below).

## Continuous checks on GitHub (2026-10-22)

New files in `.github/`:

| Workflow / setting | What it does |
|---|---|
| `workflows/tests.yml` | On every push and PR, on real `windows-latest` and `macos-latest` runners: installs the hash-pinned dependencies and runs every test script, including the security tests. Then it checks the installers on those runners: <br>• **Windows:** builds with `build.ps1 -Installer` (PySide6 6.12, the version Wine could not run) and runs a per-user silent install and uninstall. It then runs **`Intune-Install.cmd` as SYSTEM through a scheduled task**, the way Intune does, and checks for a machine-wide install in Program Files with the HKLM Run value, with **no copy of the app running as SYSTEM (M3)**. Last, it uninstalls with `Intune-Uninstall.cmd` as SYSTEM. <br>• **macOS:** builds the `.app` with `build.sh` and checks its signature and `Info.plist`. |
| `workflows/tests.yml`, other jobs | `shared code is identical` fails the build if the files copied between `windows/` and `macos/` (including `config.py`, `zendesk.py`, `monitor.py` and `test_security.py`) drift apart, so a fix can't land on only one platform. `fuzz` runs the fuzzer above for 2 minutes |
| `workflows/codeql.yml` | CodeQL static analysis (`security-extended` queries) of the Python code and of the workflows themselves, on every push, every PR and weekly |
| `workflows/scorecard.yml` | OpenSSF Scorecard on every push and weekly; results go to Security > Code scanning |
| `dependabot.yml` | Weekly update PRs for both `requirements-build.txt` locks and for the pinned Actions |
| Repository settings (enabled through the API) | Private vulnerability reporting, Dependabot alerts, Dependabot security updates. Secret scanning and push protection were already on. Non-provider patterns and validity checks need a paid GitHub plan and stayed off |
| `SECURITY.md` | How to report a vulnerability privately, what is in scope, and what is checked |

**Hardening of the workflows themselves:**
- Every Action is pinned to a full commit SHA, choosing releases at least about two weeks old.
- Default token permissions are `contents: read`, with any extra permission granted per job and explained in a comment.
- `persist-credentials: false` on every checkout, and concurrency limits on each workflow.
- `actionlint` and `zizmor` (a security linter for GitHub Actions) report no findings.

**Results on real machines.** All jobs pass on commit `ce09f1d`: [tests run](https://github.com/Karlmit/Zendesk-Warning-Light/actions/runs/39734820452), [CodeQL run](https://github.com/Karlmit/Zendesk-Warning-Light/actions/runs/39734820484). The parts that matter most for security:

- **Windows (`windows-latest`, PySide6 6.12, the version Wine couldn't load):**
  - all 11 test scripts pass, including `test_security.py`;
  - `build.ps1 -Installer` builds `ZendeskWarningLight.exe` (version 2.9.0) and the setup;
  - the per-user silent install and uninstall pass;
  - `Intune-Install.cmd` run as SYSTEM logs `Detected: SYSTEM - installing machine-wide for all users` and installs to Program Files with the HKLM Run value, and **no copy of the app is running as SYSTEM afterwards (M3 confirmed)**;
  - `Intune-Uninstall.cmd` as SYSTEM removes it, exit code 0.
- **macOS (`macos-latest`):**
  - all 10 test scripts pass;
  - `test_keystore.py` does **16/16 checks, including a real login-Keychain round trip through `security -i` (L19 confirmed on macOS)**;
  - `build.sh` builds `ZendeskWarningLight.app`, which passes `codesign --verify --strict` and `plutil -lint`.
- **Fuzzing in CI:** about 2.4 million inputs in 2 minutes per push, with no invariant broken.
- **CodeQL:** 0 open alerts. It found one (S4, above), which was fixed.
- **CI problems fixed along the way:**
  - the first run's per-user install step hung, because `Start-Process -Wait` waited for the app the installer starts; it now waits for the installer process only;
  - the first macOS run skipped the real Keychain check, because the test restored `shutil.which` wrongly; on a Mac it now fails instead of skipping.

## OpenSSF Scorecard (2026-10-22)

The score went from **2.1 to 6.7 / 10**. Every check that code or settings could fix is now 10/10: Dangerous-Workflow, Dependency-Update-Tool, Fuzzing, Pinned-Dependencies, SAST, Security-Policy, Token-Permissions, plus Binary-Artifacts and Vulnerabilities, which were already 10. What is left:

| Check | Score | What it would take | Status |
|---|---|---|---|
| Branch-Protection, Code-Review | 0 | Protect `main` so that changes go through a reviewed pull request with the CI checks passing | **Accepted** (internal project, small team; see Context). Direct pushes to `main` stay |
| License | 0 | Add a `LICENSE` file | **Accepted.** Internal code, not shared outside the team |
| Signed-Releases, Packaging | n/a | Publish tagged GitHub releases, ideally built by CI with signed artifacts or provenance | **Accepted** together with M5 |
| CII-Best-Practices | 0 | Fill in the OpenSSF Best Practices questionnaire at bestpractices.dev | **Accepted.** Not useful for an internal project |
| Maintained, Contributors | 0 | Time (the repository is under 90 days old) and outside contributors | Nothing to do |
| CI-Tests | n/a | Counts PRs that ran CI; none exist because changes go straight to `main` | Follows from Branch-Protection |

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

### M5. Installer builds whatever is on `main`, with no pin or checksum — ACCEPTED
- **File:** `install/install-macos.sh`
- **Issue:** The installer downloads the `main` branch and builds and runs it. Anyone who can push to `main`, including through a compromised account, reaches every new install and update.
- **Already in place:** HTTPS only, `curl -f`, `set -euo pipefail`, and a `ZWL_REF` override. The script header now explains how to pin to a tag or commit.
- **Not changed because:** "always latest" is the advertised way to update, so changing it is the owner's call.
- **Since 2026-10-22:** every push to `main` now runs the full test suite, including the security tests, and CodeQL in CI, so a bad push is at least caught quickly. CI can't stop a push, though; only branch protection can (see Scorecard).
- **Accepted (2026-10-22):** one employee runs this installer, for an internal tool, so the risk of a bad push reaching many machines doesn't apply. If that changes, publish tagged releases and point the one-liner at a tag (`ZWL_REF` already supports it).

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
| L19 | macOS Keychain: the refresh token briefly appears in the `security … -w <token>` command line, and items made by the `security` tool can be read by any process of the same user | `macos/zwl/keystore.py` | **Fixed (2026-10-22), with an accepted residual part.** The token is now written with `security -i` on stdin, so it is never a command-line argument. A value with `"`, `\` or a newline, which could break the command's quoting, is refused (Zendesk tokens are hex). Because `security -i` exits 0 even on failure, the value is read back to confirm it was stored. Only `/usr/bin/security` is ever run (S3). New `macos/tests/test_keystore.py` checks that the secret never appears in any argv and that malformed values are refused, and does a real Keychain round trip on the macOS CI runner. **Accepted:** items made by the `security` tool trust that tool, so another process running as the same user can read the item back. Closing that needs a signed app calling Security.framework directly, and such a process could read `tokens.json` and the log anyway |
| L20 | Uninstall deletes the whole `{app}` folder; if a user picked an existing folder, its contents are lost | `ZendeskWarningLight.iss` | **Fixed.** `DisableDirPage=yes`, so the installer always uses its own `{autopf}\ZendeskWarningLight` folder. An admin can still pass `/DIR=` on the command line, and the uninstaller deletes that folder too |
| L21 | Windows build uses Python 3.10, which reaches end of life in October 2026 | `windows/build.ps1` | **Fixed.** `build.ps1` now uses `py -3.12`; the top-level README says so. Build machines need Python 3.12 installed |
| L22 | The animation setting accepted any absolute path, including a UNC path such as `\\host\share\x.gif`. On Windows, just checking whether it exists (at startup and on every settings change) makes Windows connect to that host over SMB and send the user's NTLM hash. This is the same leak as L10, through the animation setting instead of the sound. It needs a crafted `config.json` or a user picking a network file. Found in the second pass | `{macos,windows}/zwl/config.py` | **Fixed.** New `config.is_network_path()` matches any path starting with two slashes or backslashes (`\\host`, `//host`, `\\?\UNC\…`). `Config.from_dict` resets such a value to the bundled animation, and `animation_path()` never returns one, as a second layer. Local absolute paths still work |
| — | Hash-pinned lock files | both platforms | **Fixed (2026-10-22).** `requirements-build.txt` with SHA-256 hashes, installed with `--require-hashes`. See Tool scans |

## Info

| # | Issue | Status |
|---|---|---|
| I1 | The "animation missing" message put the file name into HTML unescaped | **Fixed.** Escaped (`overlay.py`) |
| I2 | `Stop-Process` also hit other users' sessions and aborted install/uninstall on multi-user machines | **Fixed.** Limited to the current session |
| I3 | No top-level `.gitignore` | **Fixed.** Added (`__pycache__`, `.venv`, `build`, `dist`, `*.dmg`, `.env`, …) |
| I4 | `windows/.gitignore` didn't ignore install logs or Intune packages | **Fixed.** Added `*.log` and `*.intunewin` |
| I5 | Settings dialog and config had separate subdomain rules (Settings rejected `acme.zendesk.com`) | **Fixed.** Settings uses `config.normalise_subdomain()` |
| I6 | The README said a silent install starts the app | **Fixed.** Now says it never starts under SYSTEM |
| I7 | Ticket subjects and the agent's identity are written to the local log | **Fixed (2026-10-22).** The default log now has ticket numbers only, and identifies the signed-in user as `user <id> (<role>)` with no name or email (`SignedInUser.log_label()`, used in `auth.py` and `settings_ui.py`). Ticket subjects are logged only at debug level, which is on only with `--verbose`. Logs written before this version still contain the old lines until they rotate out; delete `warning-light.log*` to clear them now. Settings still shows the name and email on screen, which is fine |
| I8 | Responses are read with no size limit | **Fixed (2026-10-22).** Every request now streams its reply through `auth.read_limited()`, which stops once the reply passes a limit. The limit is counted after decompression, so a gzip bomb is caught. API replies are capped at 32 MB (100 tickets are a few MB); token and profile replies at 64 KB. `probe()` never reads the body. An oversized reply becomes the usual `ZendeskError`/`AuthError`, so the poll carries on |
| I9 | `xattr -dr com.apple.quarantine` / ad-hoc signing / `codesign --deep`; Windows exe unsigned | **Accepted (2026-10-22):** no signing certificate is available. Without one, a machine can't check that the installed app hasn't been changed since it was built. That's acceptable when the installer is built by the team and passed around internally. Builds come from hash-pinned dependencies, and CI checks the macOS bundle's ad-hoc signature |
| S6 | **Low, listed here with the other app-review items.** The Windows app's "already running" check used one fixed name (`ZendeskWarningLight.singleton`). On Windows that is a named pipe in a namespace shared by every session, so on a PC several people sign in to (shared desks, fast user switching, Remote Desktop), whoever started first stopped everyone else's copy from starting. Any local program could also hold the name to keep the app from running. Found in the 2026-10-22 app review | **Fixed (2026-10-22).** `app.instance_key()` derives the name from a hash of the user (domain\\user on Windows, uid on macOS), and the server uses `UserAccessOption`, so only that user can connect (pipe ACL on Windows, 0700 socket on macOS). Residual risk: another local user could still create a pipe with this user's predictable name to block their copy, a deliberate denial of service by someone already on the machine. Accepted |
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

**2026-10-22 (installed-app hardening):** `{windows,macos}/zwl/{app,auth,monitor,settings_ui,zendesk}.py` (I7, I8, S6), `{windows,macos}/tests/test_security.py`.

**2026-10-22 (tools, tests and CI):**
- **New:** `.github/workflows/{tests,codeql,scorecard}.yml`, `.github/dependabot.yml`, `.github/scripts/run-as-system.ps1`, `SECURITY.md`, `fuzz/{fuzz_token_hosts.py,requirements.in,requirements.txt}`, `{windows,macos}/requirements-build.{in,txt}`, `{windows,macos}/tests/test_security.py`, `macos/tests/test_keystore.py`.
- **Changed:** `{windows,macos}/zwl/{auth,modes,zendesk}.py`, `windows/zwl/settings_ui.py`, `macos/zwl/keystore.py`, `windows/build.ps1`, `macos/{build.sh,run.command,INSTALL.md,README.md}`.

**2026-10-21:**

`install/install-macos.sh`, `README.md`, `macos/README.md`, `macos/{build.sh,install.sh,run.command,requirements.txt}`, `macos/tools/verify_oauth.py`, `macos/zwl/{auth,config,keystore,monitor,overlay,paths,settings_ui,sound,zendesk}.py`, `windows/{.gitignore,README.md,build.ps1,install.ps1,requirements.txt}`, `windows/installer/{ZendeskWarningLight.iss,Intune-Install.cmd,Intune-Uninstall.cmd,uninstall.ps1}`, `windows/tools/verify_oauth.py`, `windows/zwl/{auth,config,keystore,monitor,overlay,settings_ui,sound,zendesk}.py`, new `.gitignore`, new `SECURITY_REPORT.md`.

Second pass and follow-up (left uncommitted for review):
- `{macos,windows}/zwl/zendesk.py` (M7)
- `{macos,windows}/zwl/config.py` (L22)
- `{macos,windows}/zwl/auth.py` (I15)
- `windows/installer/ZendeskWarningLight.iss` (L20)
- `windows/build.ps1` and `README.md` (L21; the README also lists the current dependency ranges)
- `macos/install.sh` (I11)
- new `.gitattributes`, plus the three `.cmd`/`.bat` files converted to CRLF (I12)