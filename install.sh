#!/usr/bin/env bash
# beyondMeetings installer.
#
# Prefers a usable system Python; falls back to uv, which ships its own
# CPython. The venv probe actually creates one — python3-venv can be missing
# on a perfectly modern Python, and a version check would not notice.
set -euo pipefail

MIN_MAJOR=3
MIN_MINOR=10
PREFIX="${BEYONDMEETINGS_HOME:-$HOME/.local/share/beyondmeetings}"
BIN_DIR="$HOME/.local/bin"
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

venv_hint() {
  if command -v apt-get >/dev/null 2>&1; then
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
  uv venv --python "${MIN_MAJOR}.${MIN_MINOR}" "$PREFIX/venv"
else
  "$INTERPRETER" -m venv "$PREFIX/venv"
fi

say "Installing beyondMeetings…"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
  "$PREFIX/venv/bin/python" -m pip install --quiet "$SCRIPT_DIR"
else
  "$PREFIX/venv/bin/python" -m pip install --quiet "beyondmeetings @ git+$REPO"
fi

ln -sf "$PREFIX/venv/bin/beyondmeetings" "$BIN_DIR/beyondmeetings"
say "Installed to $BIN_DIR/beyondmeetings"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "Note: $BIN_DIR is not on your PATH — add it to your shell profile." ;;
esac

echo
say "Opening the setup wizard…"
exec "$BIN_DIR/beyondmeetings" setup
