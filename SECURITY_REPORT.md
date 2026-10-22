# Security Report: Zendesk Warning Light

| | |
|---|---|
| **Application** | Zendesk Warning Light 2.9.0, for Windows and macOS |
| **Review period** | 21–22 October 2026 |
| **Source** | [github.com/Karlmit/Zendesk-Warning-Light](https://github.com/Karlmit/Zendesk-Warning-Light), `main` branch |
| **Latest verified build** | All automated checks passed on commit `ff83687` ([tests](https://github.com/Karlmit/Zendesk-Warning-Light/actions/runs/39739311976), [CodeQL](https://github.com/Karlmit/Zendesk-Warning-Light/actions/runs/39739311897)) |

## 1. Summary

Zendesk Warning Light is a small internal desktop app. It sits in the system tray and shows a warning animation when a Zendesk support ticket needs attention, for example a new ticket that nobody has picked up.

The review covered the whole project: the app on both platforms, its installers, its build scripts and the full history of the source code. It found **no critical or high-severity problems**, and nothing that an attacker on the internet could exploit on their own. Every problem that could be fixed has been fixed and tested. The few that remain have been knowingly accepted, with the reasons given in section 5.

| Severity | Found | Fixed | Accepted |
|---|---|---|---|
| Critical | 0 | 0 | 0 |
| High | 0 | 0 | 0 |
| Medium | 7 | 6 | 1 |
| Low | 28 | 28 | 0 (one has a small accepted remainder) |
| Informational | 15 | 11 | 4 |

**What the severities mean here:**
- **Medium:** could expose the user's Zendesk access or let someone tamper with the installed app, but only under specific conditions, such as tricking the user or controlling their network.
- **Low:** limited impact or hard to exploit. Usually it needs someone who already has access to the user's computer.
- **Informational:** a weakness in hardening or good practice, not a vulnerability in itself.

**The most important fixes:**
- The app can no longer be tricked into sending the user's Zendesk sign-in to any website other than the company's own Zendesk account (M1, M2, M7, I15).
- When IT installs the app for all users (for example through Intune), the app is no longer started with full system rights (M3).
- The macOS install script can no longer be downgraded to an unencrypted download, or run half-finished if the connection drops (M4, M6).
- Windows can no longer be made to send the user's Windows password hash to a network share named in the app's settings (L10, L22).
- The log file no longer contains ticket subjects or the agent's name and email (I7).

## 2. About the app

Knowing how the app works makes the findings easier to follow.

- **Sign-in.** Each user signs in with their own Zendesk account through their normal web browser, including single sign-on and MFA. The app uses the industry-standard OAuth method for desktop apps (authorization code with PKCE), so it never sees the user's password and contains no secret of its own.
- **Access.** The app asks Zendesk for **read-only** access. It cannot change, reply to or delete tickets.
- **What it stores.**
  - A *refresh token*, the credential that keeps the user signed in. On Windows it is encrypted with the user's Windows account (DPAPI); on macOS it is kept in the user's Keychain.
  - The short-lived *access token* is kept in memory only.
  - Settings and a local log file, in the user's own profile folder.
- **What it talks to.** Only the company's own Zendesk address (`https://<company>.zendesk.com`), over HTTPS. During sign-in it also listens briefly on the computer's own loopback address (127.0.0.1) to receive the answer from the browser. Nothing else on the network can reach it.
- **How it is installed.** On Windows, an installer for one user, or for all users through Intune. On macOS, a script run by the person installing it.

**Scope and focus.** The app is used internally by a small team, and one person installs the macOS version. The review therefore concentrates on the **installed app**: what runs on people's computers, what it stores and logs, and what it connects to. The project's development process was reviewed too, and the items accepted for an internal project of this size are listed in section 5.

## 3. How the review was done

Several independent methods were combined, so that each could catch what another might miss:

1. **Manual code review** of all app code, installers and scripts, done twice, plus a further pass focused on the installed app.
2. **Automated security scanners** (Appendix B):
   - two tools that search the code for known risky patterns (Bandit, Semgrep);
   - GitHub's own code analysis (CodeQL), which runs on every change;
   - a check of every third-party component against public vulnerability databases (pip-audit);
   - a search of the full code history for leaked passwords or keys (gitleaks).
3. **Fuzzing:** a tool that sends millions of random inputs to the checks that decide where the sign-in may be sent, to find inputs that slip through. It found one problem (S5), which was fixed.
4. **Security tests that try the real attacks.** For example, a test sets up a fake "attacker" server and checks that it never receives the user's sign-in. The tests were also run against the old code, to show that they really catch the problems that were fixed.
5. **Testing on real Windows and macOS computers** for every change to the code. This includes a full Windows installation run the same way Intune runs it, which checks that the app is never started with system rights.

## 4. Main findings and how they were fixed

This section explains the medium-severity findings in plain terms. Every finding, with technical detail, is listed in Appendix A.

**The sign-in could be sent to the wrong website (M1, M2, M7). Fixed.**
The user types their company's Zendesk name (for example `acme`) into the settings. A deliberately strange value, such as one suggested by fake "setup instructions", could make the app send the user's sign-in to a completely different website. Similarly, a page link inside a Zendesk reply could have pointed the app somewhere else. Now the name must be a plain company name. The app also checks the final web address of every request, and refuses to send the sign-in anywhere except `https://<company>.zendesk.com`. The second review pass found a way around the first version of this check (M7), which is now closed too. Tests and fuzzing confirm it.

**The app was started with full system rights during company-wide installs (M3). Fixed.**
When IT installs the app for all users, the installer runs with the highest rights on the computer (SYSTEM). It used to start the app with those same rights, so any flaw in the app would have had full control of the computer. The installer no longer starts the app in that case, and each user's own copy starts normally when they sign in to Windows. This is now tested automatically on a real Windows computer, the same way Intune runs it.

**The macOS install script could be tampered with or left half-run (M4, M6). Fixed.**
The script downloads the app's source code and builds it. A redirect could have quietly switched the download to unencrypted HTTP, where someone on the same network could swap in modified code. A dropped connection could also have run only part of the script. Now every step of the download must be encrypted (TLS 1.2 or newer), and the script only starts running once it has been downloaded completely.

**The macOS install script follows the latest code (M5). Accepted.** See section 5.

## 5. Accepted risks

These items were considered and consciously accepted for an internal app used by a small team.

| Item | Why it is accepted |
|---|---|
| **M5:** the macOS install script builds the latest version of the code, rather than a fixed, approved release | One person uses this script. Every change to the code is tested automatically (section 6), and the download is protected in transit (M6). If the app is rolled out more widely, installs should point to fixed release versions; the script already supports this |
| **I9:** the app is not signed with a company code-signing certificate | No certificate is available. Without signing, a computer can't check by itself that the installed app is the one that was built, and Windows and macOS show a warning the first time it opens. This is acceptable while the installer is built by the team and shared internally |
| **L19 (remainder):** on macOS, another program running as the same user can read the stored sign-in from the Keychain | Closing this fully needs a signed app (see I9). A program running as the user could read the user's other files anyway |
| **S6 (remainder):** another person signed in to the same Windows computer could deliberately stop someone else's copy of the app from starting | Only possible for someone who is already signed in to that computer, and the only effect is that the warning light doesn't start |
| **I10, I13, I14:** minor installer behaviours (details in Appendix A) | None of them gives anyone more rights than they already have |
| **Development process** (from the OpenSSF Scorecard, Appendix B): requiring reviewed pull requests, protected branches, signed releases, a licence file and an OpenSSF badge | They add process without reducing real risk for a small internal team. The automated checks in section 6 still run on every change |

## 6. Ongoing protection

These run automatically, so the fixes stay in place:

- **Every change to the code** is tested on real Windows and macOS computers:
  - all tests, including the attack tests in section 3;
  - a full build and installation, including the company-wide Intune install;
  - two minutes of fuzzing;
  - GitHub's CodeQL code analysis.
- **Third-party components** are pinned to exact, checksummed versions, so a tampered package fails the build instead of ending up in the app. Dependabot checks them every week and proposes updates when a security fix is published.
- **Leaked secrets:** GitHub blocks any push that contains a recognised password or key.
- **Reporting:** anyone can report a security problem privately through GitHub; see [SECURITY.md](SECURITY.md).

---

## Appendix A: All findings

Finding IDs (M1, L1 and so on) are used in the code's tests and history. S-numbered findings came from the automated scanners and the review of the installed app.

### Medium

**M1. The Zendesk subdomain was not validated. Fixed.**
- **Problem:** the subdomain was inserted into `https://{}.zendesk.com` without any check. Values such as `evil.com#`, `a.evil.com/` or `x@evil.com/` move the real host away from zendesk.com, so sign-in (the authorization code and PKCE verifier), token refresh (the refresh token) and API calls (the bearer token) would go to that host. It needs a user to type such a value, or an edited `config.json`.
- **Fix:** one rule, applied in three places. `config.normalise_subdomain()` accepts `Acme`, `acme.zendesk.com` or `https://acme.zendesk.com/`, turns them into `acme`, and rejects anything that isn't a single DNS label. The Settings dialog uses the same rule. `auth.check_base_url()` requires exactly `https://<label>.zendesk.com` before any token is issued, refreshed or used.
- **Files:** `{windows,macos}/zwl/config.py`, `auth.py`, `settings_ui.py`

**M2. The access token was attached to any link returned by the API. Fixed.**
- **Problem:** `get()` and `probe()` accepted any absolute URL and attached `Authorization: Bearer`. The group list follows the `next_page` link from Zendesk's reply, so a tampered reply could send the token to another host, or over plain HTTP.
- **Fix:** `_url()` only accepts a URL whose scheme and host match the configured account. Anything else is refused before any request is sent.
- **Files:** `{windows,macos}/zwl/zendesk.py`

**M3. A company-wide install started the app as SYSTEM. Fixed.**
- **Problem:** a silent all-users install (Intune system context) started the network-connected tray app as LocalSystem. An interactive all-users install started it with the administrator's rights.
- **Fix:** the installer never starts the app when it runs as SYSTEM, and otherwise starts it as the original, non-elevated user. Users get the app from the machine-wide autostart entry when they sign in. This is verified on every change on a real Windows computer: `Intune-Install.cmd` is run as SYSTEM, and the test checks that no copy of the app runs as SYSTEM.
- **Files:** `windows/installer/ZendeskWarningLight.iss`

**M4. The `curl | bash` installer could run partly. Fixed.**
- **Problem:** the shell runs the script while it is still downloading, so a dropped connection could leave a half-finished install.
- **Fix:** the whole script is wrapped in a function that is only called on the last line. The cleanup step checks its temporary folder variable before deleting.
- **Files:** `install/install-macos.sh`

**M5. The installer builds the latest code on `main`, with no fixed version or checksum. Accepted** (section 5).
- **Problem:** anyone able to push to `main`, including through a stolen account, would reach the next install or update.
- **In place:** HTTPS only, the protections from M4 and M6, automatic testing of every change, and a `ZWL_REF` setting to pin a tag or commit.

**M6. The installer's download could be downgraded to plain HTTP. Fixed.**
- **Problem:** `curl -L` follows redirects, and by default curl allows a redirect from HTTPS to HTTP. GitHub's archive links redirect, so an attacker on the network could have served a modified source archive, which the installer would then build and run. Old TLS versions were not ruled out either.
- **Fix:** the download uses `curl --proto '=https' --proto-redir '=https' --tlsv1.2`, so every hop must use HTTPS with TLS 1.2 or newer. The documented install command uses the same options.
- **Files:** `install/install-macos.sh`, `README.md`, `macos/README.md`

**M7. The M2 check could be bypassed with a link that has no scheme. Fixed.**
- **Problem:** the first version of the M2 fix only checked links that started with `http://` or `https://`; anything else was appended to the account's address. `@evil.com/x` then became `https://acme.zendesk.com@evil.com/x`, which actually goes to `evil.com`. Values like `.evil.com/x` and `:443@evil.com/x` worked the same way. A test against the old code confirmed that the token really was sent.
- **Fix:** only a value starting with a single `/` is treated as a path. In every case, the scheme and full host part of the final URL are compared with the account's address, and both cases are covered by tests and fuzzing.
- **Files:** `{windows,macos}/zwl/zendesk.py`

### Low

| ID | Problem | Fix |
|---|---|---|
| L1 | During sign-in, any request to the local callback address ended the sign-in, whatever it contained. A web page or local program could abort the sign-in or show its own message | Only the browser's answer carrying the expected random `state` value is accepted (constant-time comparison); everything else is refused |
| L2 | A connection that never sent anything could block the sign-in listener, and the listener's socket was never closed | 10-second timeout per connection; the socket is closed afterwards |
| L3 | On Windows, another program could bind the same callback port (`SO_REUSEADDR`) | Address reuse is turned off on Windows |
| L4 | If the Keychain or DPAPI refused to store the token, it was saved in `tokens.json` in readable form | The token is then kept in memory for that session only, and the user signs in again next time |
| L5 | `tokens.json` and the macOS data folder had default permissions | File readable by the user only (0600, written atomically); folder 0700 |
| L6 | Token requests followed redirects, so a 307/308 redirect would re-send the refresh token or the sign-in code | Redirects are not followed for token requests |
| L7 | Reflected cross-site scripting in the developer tool `verify_oauth.py` | Output is HTML-escaped |
| L8 | Wrong value types in `config.json` stopped the app from starting | Falls back to default settings |
| L9 | Message boxes let Qt decide whether text was HTML, so text from Zendesk could be shown as formatted content (spoofing) | Message boxes always show plain text |
| L10 | The alert sound setting could name a file path, including a Windows network path, which makes Windows send the user's NTLM password hash to that server | Only the sounds shipped with the app can be played |
| L11 | A ticket number read back from `state.json` was not forced to be a number, but was placed in the warning's HTML | Converted to an integer on load; invalid entries are skipped |
| L12 | A malformed or negative `Retry-After` header from the server crashed the check for new tickets | Falls back to 10 seconds, limited to 0–60 seconds |
| L13 | The installer started `taskkill` through `cmd.exe` while running with high rights; `cmd.exe` looks in the current folder first | Runs `taskkill.exe` from the Windows system folder directly |
| L14 | The Intune scripts, which run as SYSTEM, started `whoami`, `find`, `reg` and `ping` by name only | Full system paths are used |
| L15 | Dependencies had no upper version limits, and allowed versions of `requests` with known vulnerabilities (CVE-2024-35195, CVE-2024-47081) | Every dependency is now pinned to an exact version with a SHA-256 checksum (`requirements-build.txt`), and the builds refuse anything that doesn't match |
| L16 | The uninstaller copied itself to a predictable path in `%TEMP%` and left the copy behind | Random file name; the copy deletes itself |
| L17 | The macOS login item file was built by pasting the home folder path into XML, so special characters broke it | Fixed template; the path is set with `plutil` |
| L18 | `run.command` carried on after errors | Stops at the first error |
| L19 | On macOS, the token briefly appeared on the `security` tool's command line, where other processes can see it | The token is now passed through standard input, never on the command line, and is read back to confirm it was stored. Tested with the real Keychain on a Mac. The remaining part (other programs of the same user can read the Keychain item) is accepted, see section 5 |
| L20 | Uninstalling deletes the whole install folder; if a user had chosen an existing folder, its contents would be lost | The installer always uses its own folder |
| L21 | The Windows build used Python 3.10, which reaches end of life in October 2026 | Builds with Python 3.12 |
| L22 | The animation setting accepted network paths such as `\\host\share\x.gif`; just checking whether the file exists makes Windows send the user's NTLM hash to that server | Network paths are rejected, and the shipped animation is used instead |
| S1 | Windows Explorer was started by name only, which can pick up a file of the same name in the current folder | Full path, taken from Windows itself |
| S2 | A safety check used `assert`, which Python removes in optimised mode | Replaced with an explicit check |
| S3 | On macOS, a `security` program found elsewhere on the search path could be used instead of the system one | Only `/usr/bin/security` is ever used |
| S4 | When a sign-in refresh was rejected, part of Zendesk's reply was written to the log file, which is often shared for support | Only the HTTP status code is logged |
| S5 | A malformed web address in a Zendesk reply (found by fuzzing, for example `//[JJ`) caused an unexpected error type, which could break the app's fallback for reading tickets | Turned into the app's normal error, and covered by tests |
| S6 | On Windows, the "app is already running" check used one name for the whole computer. On a shared computer (shared desks, fast user switching, Remote Desktop), the first person to start the app stopped it from starting for everyone else | The name is now unique to each user, and only that user may connect to it. The remaining denial-of-service risk from another signed-in user is accepted, see section 5 |

### Informational

| ID | Observation | Status |
|---|---|---|
| I1 | A file name in the "animation missing" message was not HTML-escaped | Fixed |
| I2 | Closing the running app during install also tried to close other users' copies, which made the installer fail on multi-user computers | Fixed: only the current session |
| I3 | No top-level `.gitignore` | Fixed |
| I4 | Windows install logs and Intune packages were not excluded from version control | Fixed |
| I5 | The Settings dialog and the config file used different rules for the subdomain | Fixed: one shared rule |
| I6 | The documentation said a silent install starts the app | Fixed: it now says the app never starts as SYSTEM |
| I7 | The log file contained ticket subjects (customer text) and the agent's name and email | Fixed: the log now records ticket numbers and the user's Zendesk ID and role only. Subjects are logged only when the app runs with `--verbose`. Log files from older versions keep the old lines until they are rotated or deleted |
| I8 | Replies from the server were read with no size limit | Fixed: replies are capped at 32 MB (64 KB for sign-in replies), counted after decompression, so a "zip bomb" is stopped too |
| I9 | The app is not code-signed (macOS ad-hoc signature only; Windows unsigned) | Accepted, see section 5 |
| I10 | The macOS install script finds Python on the user's search path, and may install it with Homebrew | Accepted: no rights beyond the user's own |
| I11 | A macOS installer message suggested `sudo`, although the script refuses to run as root | Fixed |
| I12 | Windows batch files were stored with Unix line endings, which `cmd.exe` can misread | Fixed: always checked out with Windows line endings |
| I13 | The Windows launcher and Intune uninstall also look for a per-user installation | Accepted: no rights are gained in supported use |
| I14 | The per-user uninstaller runs its own script with `ExecutionPolicy Bypass` | Accepted: ExecutionPolicy is not a security boundary |
| I15 | The saved sign-in did not record which Zendesk account it belonged to, so editing `config.json` to another account would send it there | Fixed: the sign-in is tied to the account that issued it and is never sent anywhere else |

## Appendix B: Automated tools and results

| Tool | What it checks | Result |
|---|---|---|
| gitleaks 8.30.1 | Leaked passwords and keys in the code and its full history (31 commits) | Nothing found |
| GitHub secret scanning and push protection | Leaked secrets on every push | Enabled |
| pip-audit 2.10.1 | Every third-party component against public vulnerability databases | No known vulnerabilities |
| Bandit 1.9.4 | Risky patterns in Python code (9,100 lines) | 0 high, 0 medium, 36 low. 3 were real and fixed (S1–S3); the rest were checked and are false positives, such as the constant `TOKEN_PATH` mistaken for a password |
| Semgrep 1.182.1 | Broader security rules (Python, secrets, command injection) | 4 results: 2 fixed (S1, S4), 1 a false positive (owner-only folder permissions read as "insecure"), and 1 raised by the first version of the S1 fix itself |
| CodeQL (extended security queries) | GitHub's code analysis, run on every change | 0 open alerts. It found one issue, the log line in S4, which was fixed |
| atheris 3.1.0 (fuzzer) | Millions of random inputs against the checks that decide where the sign-in may go | Found S5; since the fix, no failures (6.4 million inputs in 5 minutes, and about 2.4 million on every change) |
| ShellCheck, PSScriptAnalyzer | Shell and PowerShell scripts | No errors |
| actionlint, zizmor | The automated GitHub workflows themselves | No findings |
| OpenSSF Scorecard 5.6.0 | Security practices of the code repository | 6.7 / 10, up from 2.1. All technical checks score 10/10: pinned dependencies, code analysis, fuzzing, least-privilege workflows, security policy and dependency updates. The remaining points are the development-process items accepted in section 5 |

**How the tests prove the fixes:**
- `test_security.py` makes 89 checks on each platform, each named after the finding it guards.
- On the code from before the second review pass, the checks for M7, I15, S4 and L22 fail, and the fake attacker server really receives the sign-in token. On the current code, every check passes on Windows, macOS and Linux.
- On a real Mac, `test_keystore.py` stores and reads back a sign-in through the Keychain, and confirms that the token never appears on a command line.

## Appendix C: Checked and found sound

- **Sign-in:**
  - PKCE with S256 and a 32-byte random verifier;
  - a 192-bit random `state` value, checked before the code is exchanged;
  - the callback listener accepts connections from the computer itself (127.0.0.1) only;
  - no client secret in the app;
  - access tokens are never saved to disk;
  - the Windows encryption (DPAPI) is tied to the user, with app-specific extra input (entropy).
- **Network:**
  - certificate checks are never turned off;
  - every request has a timeout;
  - tokens never appear in logs or error messages.
- **Display:**
  - all text from Zendesk is escaped before it is shown;
  - links that the app opens are built from the configured address and a ticket number only, never taken from a server reply.
- **Code:**
  - no `eval`, `pickle` or shell command strings;
  - other programs are started with fixed paths and argument lists.
- **Windows installation:**
  - autostart entries are quoted;
  - company-wide installs go to Program Files, which ordinary users can't modify;
  - the installer unpacks into a random temporary folder.
- **macOS installation:**
  - no administrator rights;
  - no world-writable files;
  - every deletion targets a fixed path inside the user's home folder.
- **Code repository:** no build output, credentials or token files are stored in it.
