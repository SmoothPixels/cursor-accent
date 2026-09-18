#!/bin/bash
# Opt-in: adds (or updates) a "Style > Cursor" submenu in the Omarchy menu by
# splicing extensions/omarchy-menu.snippet.jsonc into the user's own
# ~/.config/omarchy/extensions/omarchy-menu.jsonc. Run this yourself,
# including again after updating the plugin; nothing in this plugin does it
# automatically (see README.md).
set -euo pipefail

PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SNIPPET="$PLUGIN_DIR/extensions/omarchy-menu.snippet.jsonc"
TARGET="$HOME/.config/omarchy/extensions/omarchy-menu.jsonc"
MARKER='"style.cursor'

[[ -f $SNIPPET ]] || { echo "Missing $SNIPPET" >&2; exit 1; }

mkdir -p "$(dirname "$TARGET")"
if [[ ! -f $TARGET ]]; then
  printf '{\n}\n' > "$TARGET"
fi

tmp=$(mktemp)
trap 'rm -f "$tmp" "$tmp.stripped"' EXIT

grep -vF "$MARKER" "$TARGET" > "$tmp.stripped"
awk -v snippet="$SNIPPET" '
  /^}[[:space:]]*$/ && !done {
    while ((getline line < snippet) > 0) print line
    done = 1
  }
  { print }
' "$tmp.stripped" > "$tmp"

mv "$tmp" "$TARGET"
trap - EXIT
chmod +x "$PLUGIN_DIR/cursor-accent" "$PLUGIN_DIR/tools/set-fixed-color.sh"

echo "Synced Style > Cursor in $TARGET"
echo "The shell watches this file, so it should pick it up within a second or two."
