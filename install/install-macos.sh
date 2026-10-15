#!/usr/bin/env bash
#
# One-step installer: downloads Zendesk Warning Light from GitHub, builds it, and
# installs it for the current user. No sudo, no admin rights.
#
#   curl -fsSL https://raw.githubusercontent.com/Karlmit/Zendesk-Warning-Light/main/install/install-macos.sh | bash
#
# Options go after `-s --`, for example:
#
#   curl -fsSL .../install-macos.sh | bash -s -- --no-autostart
#
#   --no-autostart   do not start the app at login
#   --no-launch      install but do not start it now
#   --keep           keep the downloaded source in ~/Library/Caches/ZendeskWarningLight
#
# Environment: ZWL_REF picks a branch, tag or commit (default: main).
#
# Run it again at any time to update: it always downloads the latest source and
# replaces the installed app. Your settings and sign-in are kept.

set -euo pipefail

REPO="Karlmit/Zendesk-Warning-Light"
REF="${ZWL_REF:-main}"
CACHE="$HOME/Library/Caches/ZendeskWarningLight"

KEEP=0
PASS=()
for arg in "$@"; do
  case "$arg" in
    --keep)      KEEP=1 ;;
    -h|--help)   sed -n '2,19p' "$0" 2>/dev/null || true; exit 0 ;;
    *)           PASS+=("$arg") ;;
  esac
done

say()  { printf '\033[36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "This installer is for macOS."
[[ "$(id -u)" != "0" ]] || die "Do not run this with sudo - it installs for one user."
command -v curl >/dev/null || die "curl is missing."
command -v tar  >/dev/null || die "tar is missing."

# --- 1. Xcode command line tools (iconutil and codesign live there) ---------

if ! xcode-select -p >/dev/null 2>&1; then
  warn "The Xcode command line tools are not installed."
  warn "A window should appear asking to install them - accept it, wait for it to"
  warn "finish, then run this command again."
  xcode-select --install >/dev/null 2>&1 || true
  exit 1
fi

# --- 2. a suitable Python: 3.10-3.13, native for this Mac -------------------

ARCH="$(uname -m)"

python_ok() {
  local py="$1" ver arch
  command -v "$py" >/dev/null 2>&1 || [[ -x "$py" ]] || return 1
  ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || return 1
  arch="$("$py" -c 'import platform; print(platform.machine())' 2>/dev/null)" || return 1
  case "$ver" in 3.10|3.11|3.12|3.13) ;; *) return 1 ;; esac
  [[ "$arch" == "$ARCH" ]]
}

find_python() {
  local candidate
  for candidate in \
      python3.13 python3.12 python3.11 python3.10 \
      /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
      /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
      /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
      /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
      /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
      python3; do
    if python_ok "$candidate"; then
      command -v "$candidate" 2>/dev/null || echo "$candidate"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"

if [[ -z "$PY" ]] && command -v brew >/dev/null 2>&1; then
  say "No suitable Python found - installing Python 3.12 with Homebrew..."
  brew install python@3.12
  PY="$(find_python || true)"
fi

if [[ -z "$PY" ]]; then
  die "No suitable Python found.

The app needs Python 3.10-3.13 built for this Mac ($ARCH). macOS itself ships 3.9,
which is too old. Install Python 3.12 from
  https://www.python.org/downloads/macos/
(the normal double-click installer), then run this command again."
fi
say "Using $PY"

# --- 3. download the source -------------------------------------------------

WORK="$(mktemp -d "${TMPDIR:-/tmp}/zwl.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

URL="https://github.com/$REPO/archive/$REF.tar.gz"
say "Downloading $REPO ($REF)..."
curl -fsSL "$URL" -o "$WORK/src.tar.gz" \
  || die "Could not download $URL
Check your internet connection, and that '$REF' exists."

tar -xzf "$WORK/src.tar.gz" -C "$WORK"
SRC="$(find "$WORK" -mindepth 2 -maxdepth 2 -type d -name macos | head -n 1)"
[[ -n "$SRC" && -f "$SRC/build.sh" ]] || die "The download does not contain the macOS app."

if [[ "$KEEP" == "1" ]]; then
  rm -rf "$CACHE"
  mkdir -p "$CACHE"
  cp -R "$SRC/." "$CACHE/"
  SRC="$CACHE"
  say "Source kept in $CACHE"
fi

# --- 4. build and install ---------------------------------------------------

cd "$SRC"
chmod +x build.sh install.sh uninstall.sh 2>/dev/null || true
say "Building and installing (this takes a few minutes the first time)..."
PYTHON="$PY" ./install.sh --force ${PASS[@]+"${PASS[@]}"}

echo
ok "Done. To update later, run the same command again."
