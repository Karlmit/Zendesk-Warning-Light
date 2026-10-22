# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue:

- **GitHub:** open the repository's **Security** tab and choose **Report a vulnerability**. Only the maintainer sees it.
- Include what you found, how to reproduce it, and which version or commit you tested.

You will get a reply within 5 working days. Fixes are released as soon as they are ready, and the reporter is credited unless they ask not to be.

## Supported versions

Only the latest release and the current `main` branch get security fixes.

## What is in scope

- The Windows and macOS apps (`windows/zwl`, `macos/zwl`)
- The installers and install scripts (`windows/installer`, `windows/*.ps1`, `macos/*.sh`, `install/install-macos.sh`)
- The build scripts and GitHub workflows

Zendesk itself and the OAuth client configured in your Zendesk account are out of scope; report those to Zendesk.

## How this project is checked

See [SECURITY_REPORT.md](SECURITY_REPORT.md) for the latest security review, every finding and how it was fixed. On every push, GitHub Actions runs the security regression tests on Windows and macOS, CodeQL static analysis and OpenSSF Scorecard. Dependabot watches the pinned dependencies.
