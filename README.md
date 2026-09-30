# Zendesk Warning Light

A desktop tray/menu-bar app that puts an animated warning on screen when a Zendesk
ticket needs someone's attention — a new unassigned ticket lands in a watched queue,
a ticket gets handed back to the queue, or one of your own tickets gets reopened.
Click the animation to dismiss it, or click the information box to jump straight to
the ticket. The warning clears itself as soon as the underlying reason goes away, and
everyone signs in with their own Zendesk account so each person only ever sees what
they're allowed to see.

On top of the alert rules sits a **day mode**: a named bundle of "what may interrupt
me today" and "which groups that applies to." Switch modes from the tray, or let a
weekly schedule do it for you. **Off Day** silences everything and makes no Zendesk
API calls at all.

Full behavior — the alert rules, day modes, tray menu, authentication, troubleshooting
— is documented per platform, since installation and packaging differ:

| Platform | Docs |
|---|---|
| **Windows** | [`windows/README.md`](windows/README.md) |
| **macOS** (Apple Silicon) | [`macos/README.md`](macos/README.md) · [`macos/INSTALL.md`](macos/INSTALL.md) |

The two builds share the same rules, modes, and Zendesk auth flow — the macOS README
calls out anywhere it differs from Windows.

## Before you build or run this yourself

Both builds ship with a placeholder Zendesk subdomain (`yourcompany`) and, on macOS, a
placeholder bundle identifier (`com.yourcompany.zendeskwarninglight`). Before building:

1. Register an OAuth client in your Zendesk admin (**Admin Center → Apps and
   integrations → APIs → Zendesk API → OAuth Clients**) as a **public client**
   (authorization code + PKCE, no client secret). See the "Authentication" section
   in [`windows/README.md`](windows/README.md) for the exact settings.
2. Point the app at your subdomain — either edit the default in `zwl/config.py`, or
   just type it into **Settings → Connection** the first time you run it.
3. (macOS only) Pick your own bundle identifier in `zwl/paths.py`, `zwl/keystore.py`,
   `build.sh`, and `install.sh`/`uninstall.sh` if you want the Keychain entry and
   LaunchAgent to use your own reverse-DNS name instead of `com.yourcompany.*`.

No API keys, tokens, or client secrets are stored anywhere in this repo — refresh
tokens live only on the machine that signed in (Windows: DPAPI; macOS: login Keychain).

## Requirements

- Python 3.10+ (3.10–3.13 on macOS, arm64 native — see `macos/README.md`)
- `PySide6>=6.6`, `requests>=2.31` (see each platform's `requirements.txt`)

## Repository layout

```
windows/   Windows build — PyInstaller + Inno Setup installer, tray app
macos/     macOS (Apple Silicon) build — .app + .dmg, menu-bar app
```

Each platform folder is a self-contained project (its own `requirements.txt`, tests,
and build scripts) and keeps its own git history from before the two were combined
into this repository.
