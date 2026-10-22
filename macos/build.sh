#!/usr/bin/env bash
#
# Builds Zendesk Warning Light.app and a .dmg to hand out, for Apple Silicon.
#
#   ./build.sh              # .app + dist/ZendeskWarningLight-<version>.dmg
#   ./build.sh --app-only   # skip the .dmg
#   ./build.sh --clean      # discard build/ and dist/ first
#
# Must run ON a Mac: PyInstaller cannot cross-compile, so the machine you build on
# decides the architecture of the result.

set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="ZendeskWarningLight"
DISPLAY_NAME="Zendesk Warning Light"
BUNDLE_ID="com.yourcompany.zendeskwarninglight"
MIN_MACOS="12.0"

APP_ONLY=0
CLEAN=0
for arg in "$@"; do
  case "$arg" in
    --app-only) APP_ONLY=1 ;;
    --clean)    CLEAN=1 ;;
    -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. sanity-check the machine -------------------------------------------

[[ "$(uname -s)" == "Darwin" ]] || die "This must be built on macOS."

ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
  warn "This Mac reports $ARCH, not arm64."
  warn "The result will only run on $ARCH Macs. Build on Apple Silicon for M-series."
fi

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null || die "No $PY on PATH. Install Python from python.org."

PY_VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_ARCH="$("$PY" -c 'import platform; print(platform.machine())')"
say "Using $PY  (Python $PY_VER, $PY_ARCH)"

case "$PY_VER" in
  3.10|3.11|3.12|3.13) ;;
  *) warn "Python $PY_VER is outside the 3.10-3.13 range PySide6 ships wheels for."
     warn "If pip cannot find PySide6, that is why." ;;
esac

if [[ "$ARCH" == "arm64" && "$PY_ARCH" != "arm64" ]]; then
  die "Python reports $PY_ARCH on an arm64 Mac - it is running under Rosetta.
The app would be x86_64. Install a native arm64 Python and retry."
fi

# --- 2. dependencies -------------------------------------------------------

VENV=".venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  say "Creating the virtual environment..."
  "$PY" -m venv "$VENV"
fi
PYV="$VENV/bin/python"

say "Installing dependencies..."
# Exact versions with SHA-256 hashes, so a tampered or swapped package fails the
# install. To change versions, edit requirements-build.in and regenerate with the
# command at the top of requirements-build.txt.
"$PYV" -m pip install --quiet --require-hashes -r requirements-build.txt

# zwl/__init__.py is the single source of truth for the version.
VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' zwl/__init__.py)"
[[ -n "$VERSION" ]] || die "Could not read __version__ from zwl/__init__.py"
say "Building $DISPLAY_NAME $VERSION"

if [[ "$CLEAN" == "1" ]]; then
  say "Cleaning previous output..."
  rm -rf build dist
fi

# --- 3. icon ---------------------------------------------------------------

say "Generating the icon..."
ICONSET="build/$APP_NAME.iconset"
rm -rf "$ICONSET"
QT_QPA_PLATFORM=offscreen "$PYV" tools/make_iconset.py "$ICONSET" >/dev/null
ICNS="build/$APP_NAME.icns"
iconutil -c icns "$ICONSET" -o "$ICNS"
[[ -f "$ICNS" ]] || die "iconutil did not produce $ICNS"

# --- 4. the app bundle -----------------------------------------------------

say "Running PyInstaller..."
"$PYV" -m PyInstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICNS" \
  --osx-bundle-identifier "$BUNDLE_ID" \
  --add-data "assets:assets" \
  --exclude-module tkinter \
  --exclude-module PySide6.QtWebEngineCore \
  --exclude-module PySide6.QtQuick \
  --exclude-module PySide6.Qt3DCore \
  --exclude-module PySide6.QtMultimedia \
  main.py

APP="dist/$APP_NAME.app"
[[ -d "$APP" ]] || die "PyInstaller finished but $APP is missing."

# --- 5. Info.plist ---------------------------------------------------------
# LSUIElement is the important one: it makes this a menu-bar-only app with no
# Dock icon and no app switcher entry, which is the macOS equivalent of the
# Windows tray app having no taskbar button.

say "Patching Info.plist..."
PLIST="$APP/Contents/Info.plist"
plutil -replace LSUIElement -bool true "$PLIST"
plutil -replace CFBundleName -string "$DISPLAY_NAME" "$PLIST"
plutil -replace CFBundleDisplayName -string "$DISPLAY_NAME" "$PLIST"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
plutil -replace LSMinimumSystemVersion -string "$MIN_MACOS" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "Karl Almqvist" "$PLIST"

# --- 6. signature ----------------------------------------------------------
# Apple Silicon refuses to run code with no signature at all, so an ad-hoc one is
# not optional. It is NOT the same as being notarised: Gatekeeper still warns the
# first time, which README-macOS.md explains how to get past.

say "Signing (ad-hoc)..."
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  say "  using identity: $CODESIGN_IDENTITY"
  codesign --force --deep --options runtime --timestamp \
           --sign "$CODESIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"
  warn "  ad-hoc signature only (set CODESIGN_IDENTITY to use a Developer ID)"
fi
codesign --verify --deep --strict "$APP" && ok "  signature verifies"

# --- 7. the disk image -----------------------------------------------------

if [[ "$APP_ONLY" == "1" ]]; then
  echo
  ok "Built $APP  (version $VERSION)"
  exit 0
fi

say "Building the disk image..."
DMG="dist/$APP_NAME-$VERSION.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
# The Applications symlink is what makes the window a drag-to-install target.
ln -s /Applications "$STAGE/Applications"

hdiutil create \
  -volname "$DISPLAY_NAME $VERSION" \
  -srcfolder "$STAGE" \
  -ov -format UDZO \
  "$DMG" >/dev/null

[[ -f "$DMG" ]] || die "hdiutil did not produce $DMG"
SIZE="$(du -h "$DMG" | cut -f1)"

echo
ok "Give this file to colleagues:"
ok "  $(pwd)/$DMG  ($SIZE)"
echo
echo "They drag the app to Applications, then right-click it and choose Open the"
echo "first time - see the Gatekeeper section in README-macOS.md."
echo
echo "To install it here instead: ./install.sh"
