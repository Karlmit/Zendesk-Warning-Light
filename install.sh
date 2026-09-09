#!/usr/bin/env bash
#
# Installs Zendesk Warning Light for the current user. No sudo, no admin rights.
#
#   ./install.sh                  # build if needed, install, start at login, launch
#   ./install.sh --no-autostart   # skip the login item
#   ./install.sh --no-launch      # do not start it now
#   ./install.sh --system         # /Applications instead of ~/Applications (needs sudo)
#   ./install.sh --force          # rebuild even if dist/ is current
#
# This is the scripted equivalent of dragging the app out of the .dmg. Either is
# fine; the .dmg is what you hand to a colleague.

set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="ZendeskWarningLight"
DISPLAY_NAME="Zendesk Warning Light"

AUTOSTART=1
LAUNCH=1
FORCE=0
DEST="$HOME/Applications"

for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    --no-launch)    LAUNCH=0 ;;
    --force)        FORCE=1 ;;
    --system)       DEST="/Applications" ;;
    -h|--help)      sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "macOS only."

# Running this under sudo would write the login item into root's home and leave
# root-owned files in your Applications folder, so the app would never start at
# login and you could not update it without sudo again.
if [[ "$(id -u)" == "0" ]]; then
  die "Do not run this with sudo - it installs for one user.
Run it as yourself; the default target (~/Applications) needs no admin rights."
fi

# --- 1. make sure there is something to install ----------------------------

BUILT="dist/$APP_NAME.app"
if [[ "$FORCE" == "1" || ! -d "$BUILT" ]]; then
  say "Building first..."
  ./build.sh --app-only
fi
[[ -d "$BUILT" ]] || die "No app at $BUILT."

# --- 2. stop a running copy ------------------------------------------------

if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
  say "Closing the running copy..."
  pkill -x "$APP_NAME" || true
  sleep 2
fi

# --- 3. copy it into place -------------------------------------------------

TARGET="$DEST/$APP_NAME.app"
mkdir -p "$DEST" 2>/dev/null || true
if [[ ! -w "$DEST" ]]; then
  die "$DEST is not writable. Re-run without --system, or use sudo."
fi

say "Installing to $TARGET"
rm -rf "$TARGET"
cp -R "$BUILT" "$TARGET"

# A local copy was never downloaded, so it should carry no quarantine flag -
# but strip it anyway in case the app arrived via a .dmg or AirDrop.
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null || true

# --- 4. login item ---------------------------------------------------------

PLIST="$HOME/Library/LaunchAgents/com.yourcompany.zendeskwarninglight.plist"
if [[ "$AUTOSTART" == "1" ]]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>com.yourcompany.zendeskwarninglight</string>
	<key>ProgramArguments</key>
	<array>
		<string>$TARGET/Contents/MacOS/$APP_NAME</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<false/>
	<key>ProcessType</key>
	<string>Interactive</string>
	<key>LimitLoadToSessionType</key>
	<string>Aqua</string>
</dict>
</plist>
PLISTEOF
  plutil -lint "$PLIST" >/dev/null || die "the generated login item is not valid plist"
  say "Will start when you log in."
else
  launchctl bootout "gui/$(id -u)" com.yourcompany.zendeskwarninglight 2>/dev/null || true
  rm -f "$PLIST"
  say "Login item left off."
fi

# --- 5. launch -------------------------------------------------------------

if [[ "$LAUNCH" == "1" ]]; then
  open "$TARGET"
  sleep 3
  if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
    ok "$DISPLAY_NAME is running - look for the cat in your menu bar."
  else
    warn "Installed, but it did not stay running."
    warn "Check ~/Library/Application Support/$APP_NAME/warning-light.log"
  fi
else
  ok "Installed to $TARGET (not started)."
fi

echo
echo "Uninstall with: ./uninstall.sh"
