#!/usr/bin/env bash
# beyondMeetings installer.
#
# Prefers a usable system Python; falls back to uv, which ships its own
# CPython. The venv probe actually creates one — python3-venv can be missing
# on a perfectly modern Python, and a version check would not notice.
set -euo pipefail

MIN_MAJOR=3
MIN_MINOR=10
# Deliberately NOT ~/.local/share/beyondmeetings — that is the data directory
# holding recordings and transcripts. Keeping the venv out of it means an
# uninstall can remove the program without touching a user's meetings.
PREFIX="${BEYONDMEETINGS_HOME:-$HOME/.local/share/beyondmeetings-app}"
BIN_DIR="${BEYONDMEETINGS_BIN:-$HOME/.local/bin}"
REPO="${BEYONDMEETINGS_REPO:-https://github.com/nikhilm55/beyondmeetings}"

USE_UV=1
DRY_RUN=0

usage() {
  cat <<'EOF'
beyondMeetings installer

  --no-uv      Never download uv. If system Python is unusable, print the
               distro-specific fix and exit.
  --dry-run    Report what would be used, then stop.
  --help       Show this message.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-uv) USE_UV=0 ;;
    --dry-run) DRY_RUN=1 ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

say() { printf '  %s\n' "$1"; }

python_is_usable() {
  local py="$1" probe
  command -v "$py" >/dev/null 2>&1 || return 1
  "$py" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_MAJOR,$MIN_MINOR) else 1)" \
    >/dev/null 2>&1 || return 1

  # A version check does not prove venv works — build one and see.
  probe="$(mktemp -d)"
  if "$py" -m venv "$probe/v" >/dev/null 2>&1; then
    rm -rf "$probe"
    return 0
  fi
  rm -rf "$probe"
  return 1
}

OS="$(uname -s)"

venv_hint() {
  if [ "$OS" = "Darwin" ]; then
    echo "xcode-select --install   # or: brew install python"
  elif command -v apt-get >/dev/null 2>&1; then
    echo "sudo apt-get install -y python3-venv python3-pip"
  elif command -v dnf >/dev/null 2>&1; then
    echo "sudo dnf install -y python3 python3-pip"
  elif command -v pacman >/dev/null 2>&1; then
    echo "sudo pacman -S --noconfirm python python-pip"
  else
    echo "Install Python ${MIN_MAJOR}.${MIN_MINOR}+ including the venv module."
  fi
}

echo "beyondMeetings installer"
echo

INTERPRETER=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if python_is_usable "$candidate"; then
    INTERPRETER="$candidate"
    say "Using system Python: $("$candidate" --version 2>&1)"
    break
  fi
done

USING_UV=0
if [ -z "$INTERPRETER" ]; then
  say "No usable Python ${MIN_MAJOR}.${MIN_MINOR}+ with venv support found."
  if [ "$USE_UV" -eq 0 ]; then
    echo
    echo "Fix it with:" >&2
    echo "  $(venv_hint)" >&2
    echo "(python3-venv is a separate package on Debian/Ubuntu.)" >&2
    exit 1
  fi
  say "Falling back to uv, which installs its own Python."
  USING_UV=1
fi

if [ "$DRY_RUN" -eq 1 ]; then
  if [ "$USING_UV" -eq 1 ]; then
    echo "Dry run: would bootstrap uv and use its bundled python."
  else
    echo "Dry run: would use $INTERPRETER at $(command -v "$INTERPRETER")."
  fi
  exit 0
fi

mkdir -p "$PREFIX" "$BIN_DIR"

if [ "$USING_UV" -eq 1 ]; then
  if ! command -v uv >/dev/null 2>&1; then
    say "Downloading uv from astral.sh…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uv python install "${MIN_MAJOR}.${MIN_MINOR}"
  # --seed puts pip in the venv. Without it `uv venv` produces an environment
  # with no pip at all, and the install below dies on "No module named pip".
  uv venv --seed --python "${MIN_MAJOR}.${MIN_MINOR}" "$PREFIX/venv"
else
  # Linux desktop bindings (PyGObject/WebKit) are normally supplied by the
  # distribution rather than pip. Let the isolated app environment see those
  # read-only system packages; packages installed into the venv still win.
  if [ "$OS" = "Linux" ]; then
    "$INTERPRETER" -m venv --system-site-packages "$PREFIX/venv"
  else
    "$INTERPRETER" -m venv "$PREFIX/venv"
  fi
fi

say "Installing beyondMeetings…"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip

# ${BASH_SOURCE[0]} is unset when this script is piped into bash
# (curl … | bash), and `set -u` makes that fatal. Default it so the
# curl path falls through to the git install instead of erroring.
SCRIPT_SRC="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [ -n "$SCRIPT_SRC" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SRC")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
  "$PREFIX/venv/bin/python" -m pip install --quiet "$SCRIPT_DIR[desktop]"
else
  "$PREFIX/venv/bin/python" -m pip install --quiet "beyondmeetings[desktop] @ git+$REPO"
fi

# Ubuntu ships the AppIndicator runtime and GNOME extension by default, but
# the tiny GI typelib that Python needs is a separate package. Install that
# one file privately when it is missing: this avoids sudo/password prompts and
# lets the global REC indicator work immediately after a normal user install.
if [ "$OS" = "Linux" ] && ! "$PREFIX/venv/bin/python" -c "
from beyondmeetings.tray import _ayatana_available
raise SystemExit(0 if _ayatana_available() else 1)
" >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1 && command -v dpkg-deb >/dev/null 2>&1; then
    INDICATOR_TMP="$(mktemp -d)"
    say "Adding the GNOME top-panel recording indicator…"
    if (cd "$INDICATOR_TMP" && apt-get download \
        gir1.2-ayatanaappindicator3-0.1 >/dev/null 2>&1); then
      INDICATOR_DEB="$(find "$INDICATOR_TMP" -maxdepth 1 -type f -name '*.deb' -print -quit)"
      if [ -n "$INDICATOR_DEB" ]; then
        mkdir -p "$PREFIX/indicator"
        dpkg-deb -x "$INDICATOR_DEB" "$PREFIX/indicator"
        say "Top-panel indicator enabled"
      fi
    else
      say "Could not download the optional GNOME indicator binding."
      say "Install gir1.2-ayatanaappindicator3-0.1 later to enable it."
    fi
    rm -rf "$INDICATOR_TMP"
  fi
fi

ln -sf "$PREFIX/venv/bin/beyondmeetings" "$BIN_DIR/beyondmeetings"
say "Installed to $BIN_DIR/beyondmeetings"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on your PATH — add it to your shell profile." ;;
esac

if [ "$OS" = "Darwin" ]; then
  # macOS keys privacy permissions per bundle identifier, so recording needs a
  # real .app — a bare command in ~/.local/bin has no identity of its own and
  # its grants would attach to the terminal instead.
  SWIFT_SRC="$("$PREFIX/venv/bin/python" -c "
from pathlib import Path
import beyondmeetings
print(Path(beyondmeetings.__file__).parent / 'native' / 'bmcapture.swift')
")"

  HELPER=""
  if ! command -v swiftc >/dev/null 2>&1; then
    say "Xcode command line tools not found — skipping the capture helper."
    say "Run 'xcode-select --install', then re-run this installer to record."
  elif [ ! -f "$SWIFT_SRC" ]; then
    say "Capture helper source missing from the install — skipping."
  else
    say "Building the audio capture helper…"
    if swiftc -O "$SWIFT_SRC" -o "$PREFIX/bmcapture" \
        -framework ScreenCaptureKit \
        -framework AVFoundation \
        -framework CoreMedia 2>"$PREFIX/bmcapture-build.log"; then
      HELPER="$PREFIX/bmcapture"
      say "Capture helper built"
    else
      say "Capture helper failed to build — see $PREFIX/bmcapture-build.log"
      say "Everything except recording will still work."
    fi
  fi

  "$PREFIX/venv/bin/python" -c "
import sys
from pathlib import Path
from beyondmeetings.desktop_macos import install_app_bundle
helper = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
bundle = install_app_bundle(helper=Path(helper) if helper else None)
print(bundle)
" "$HELPER" >/dev/null 2>&1 && say "App installed to ~/Applications/beyondMeetings.app"

  if [ -n "$HELPER" ]; then
    echo
    say "One-time permissions: open the app, then allow beyondMeetings under"
    say "System Settings → Privacy & Security → Screen Recording (this is how"
    say "macOS delivers the other participants' audio) and → Microphone."
    say "macOS needs the app reopened after granting screen recording."
  fi
else
  # Install the app icon so beyondMeetings appears in the applications menu.
  "$PREFIX/venv/bin/python" -c "
from beyondmeetings.desktop import install_desktop_entry
install_desktop_entry()
" >/dev/null 2>&1 && say "App icon added to your applications"
  "$PREFIX/venv/bin/python" -c "
from beyondmeetings.doctor.autostart import refresh_installed_autostart
refresh_installed_autostart()
" >/dev/null 2>&1 && say "Login startup updated for the top-panel indicator"
fi

echo
if "$PREFIX/venv/bin/python" -c "
import sys
from beyondmeetings.desktop import server_is_running
sys.exit(0 if server_is_running() else 1)
" 2>/dev/null; then
  say "beyondMeetings is already running — open http://127.0.0.1:7788/setup"
  exit 0
fi

say "Opening the desktop app…"
exec "$BIN_DIR/beyondmeetings" app --setup
