#!/usr/bin/env bash
# Remove beyondMeetings.
#
# Your meetings are never touched by default. Recordings and transcripts live in
# a separate directory from the program precisely so that uninstalling cannot
# destroy them — use --purge-data if you really want them gone.
set -euo pipefail

PREFIX="${BEYONDMEETINGS_HOME:-$HOME/.local/share/beyondmeetings-app}"
DATA_DIR="${BEYONDMEETINGS_DATA:-$HOME/.local/share/beyondmeetings}"
CONFIG_DIR="$HOME/.config/beyondmeetings"
BIN_LINK="$HOME/.local/bin/beyondmeetings"
AUTOSTART="$HOME/.config/autostart/beyondmeetings.desktop"
LAUNCHER="$HOME/.local/share/applications/beyondmeetings.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/beyondmeetings.svg"

PURGE_DATA=0
PURGE_KEYS=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Uninstall beyondMeetings

  --purge-data   Also delete recordings and transcripts. IRREVERSIBLE.
  --purge-keys   Also delete stored API keys from your keyring.
  --dry-run      Show what would be removed, change nothing.
  --help         Show this message.

Never removed: your Obsidian vault, your meeting notes, your task board.
Those are yours and this script does not know how to tell which notes
came from beyondMeetings.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --purge-data) PURGE_DATA=1 ;;
    --purge-keys) PURGE_KEYS=1 ;;
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

remove() {
  local path="$1" what="$2"
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    say "already gone: $what"
    return
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    say "would remove: $what ($path)"
    return
  fi
  rm -rf "$path"
  say "removed: $what"
}

echo "beyondMeetings uninstaller"
echo

# A recording in progress would otherwise leave an orphaned capture process
# and loaded PipeWire modules behind.
if command -v "$BIN_LINK" >/dev/null 2>&1 || [ -x "$PREFIX/venv/bin/beyondmeetings" ]; then
  BM="${BIN_LINK}"
  [ -x "$PREFIX/venv/bin/beyondmeetings" ] && BM="$PREFIX/venv/bin/beyondmeetings"
  if [ "$DRY_RUN" -eq 0 ]; then
    "$BM" stop >/dev/null 2>&1 || true
  fi
fi

remove "$BIN_LINK" "command symlink"
remove "$PREFIX" "program files"
remove "$AUTOSTART" "start-at-login entry"
remove "$LAUNCHER" "app icon"
remove "$ICON" "icon file"
remove "$CONFIG_DIR" "settings"

if [ "$PURGE_KEYS" -eq 1 ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    say "would remove: stored API keys"
  else
    for name in groq_api_key anthropic_api_key openai_api_key gemini_api_key; do
      python3 - "$name" <<'PY' 2>/dev/null || true
import sys
import keyring
try:
    keyring.delete_password("beyondmeetings", sys.argv[1])
except Exception:
    pass
PY
    done
    say "removed: stored API keys"
  fi
else
  say "kept: stored API keys (--purge-keys to remove)"
fi

if [ "$PURGE_DATA" -eq 1 ]; then
  remove "$DATA_DIR" "recordings and transcripts"
else
  if [ -d "$DATA_DIR" ]; then
    size="$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
    say "kept: recordings and transcripts in $DATA_DIR ($size)"
    say "      use --purge-data to delete them"
  fi
fi

echo
say "Done. Your Obsidian vault and meeting notes were not touched."

# A stale mix would make the next install's first recording misbehave.
if pgrep -x pw-record >/dev/null 2>&1; then
  echo
  say "NOTE: a pw-record process is still running:"
  pgrep -af pw-record | sed 's/^/      /'
  say "If you are not in a meeting, stop it with: kill <pid>"
fi
