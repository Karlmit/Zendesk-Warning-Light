#!/usr/bin/env bash
#
# Removes Zendesk Warning Light for the current user.
#
#   ./uninstall.sh                   # remove the app and login item, keep settings
#   ./uninstall.sh --remove-settings # also delete settings, logs and the Keychain item
#
# Settings are kept by default so reinstalling picks up where you left off.

set -euo pipefail

APP_NAME="ZendeskWarningLight"
DISPLAY_NAME="Zendesk Warning Light"
BUNDLE_ID="com.yourcompany.zendeskwarninglight"
DATA_DIR="$HOME/Library/Application Support/$APP_NAME"
PLIST="$HOME/Library/LaunchAgents/$BUNDLE_ID.plist"

REMOVE_SETTINGS=0
for arg in "$@"; do
  case "$arg" in
    --remove-settings) REMOVE_SETTINGS=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[36m  %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS only." >&2; exit 1; }

echo "Uninstalling $DISPLAY_NAME..."

if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
  pkill -x "$APP_NAME" || true
  sleep 2
  say "stopped the running app"
fi

if [[ -f "$PLIST" ]]; then
  launchctl bootout "gui/$(id -u)" "$BUNDLE_ID" 2>/dev/null || true
  rm -f "$PLIST"
  say "removed the login item"
fi

for candidate in "$HOME/Applications/$APP_NAME.app" "/Applications/$APP_NAME.app"; do
  if [[ -d "$candidate" ]]; then
    if rm -rf "$candidate" 2>/dev/null; then
      say "deleted $candidate"
    else
      warn "  could not delete $candidate - try: sudo rm -rf \"$candidate\""
    fi
  fi
done

if [[ "$REMOVE_SETTINGS" == "1" ]]; then
  rm -rf "$DATA_DIR"
  say "deleted settings and logs"
  if security delete-generic-password -s "$BUNDLE_ID" -a zendesk-refresh-token \
       >/dev/null 2>&1; then
    say "removed the sign-in token from the Keychain"
  fi
else
  if [[ -d "$DATA_DIR" ]]; then
    echo
    warn "Settings and logs kept in $DATA_DIR"
    warn "The sign-in token is still in your Keychain."
    echo  "Re-run with --remove-settings to delete both."
  fi
fi

echo
ok "$DISPLAY_NAME has been removed."
