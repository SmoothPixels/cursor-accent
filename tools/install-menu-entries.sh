#!/bin/bash
# Adds (or updates) a "Style > Cursor" submenu in the Omarchy menu by
# splicing extensions/omarchy-menu.snippet.jsonc into the user's own
# ~/.config/omarchy/extensions/omarchy-menu.jsonc. install-cursor-hook.sh runs
# this as part of setup; once the entries exist, Service.qml re-runs it when
# a plugin update changes them (see README.md).
#
# The block is written between ">>> cursor-accent" / "<<< cursor-accent"
# marker comments so a re-run replaces it whole. Rows and header comments
# left by older versions, which had no markers, are removed too.
set -euo pipefail

PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SNIPPET="$PLUGIN_DIR/extensions/omarchy-menu.snippet.jsonc"
TARGET="$HOME/.config/omarchy/extensions/omarchy-menu.jsonc"

[[ -f $SNIPPET ]] || { echo "Missing $SNIPPET" >&2; exit 1; }

mkdir -p "$(dirname "$TARGET")"
if [[ ! -f $TARGET ]]; then
  printf '{\n}\n' > "$TARGET"
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

python3 - "$SNIPPET" "$TARGET" "$tmp" <<'EOF'
import sys
from pathlib import Path

snippet, target, out = (Path(p) for p in sys.argv[1:])
BEGIN, END = "  // >>> cursor-accent >>>", "  // <<< cursor-accent <<<"
snippet_lines = snippet.read_text().splitlines()
legacy_comments = {l for l in snippet_lines if l.lstrip().startswith("//")}

kept, inside = [], False
for line in target.read_text().splitlines():
    if line.strip() == BEGIN.strip():
        inside = True
    elif line.strip() == END.strip():
        inside = False
    elif not inside and '"style.cursor' not in line and line not in legacy_comments:
        kept.append(line)

close = max((i for i, l in enumerate(kept) if l.strip() == "}"), default=None)
if close is None:
    sys.exit(f"Couldn't find the closing brace in {target}; not touching it.")

# The block goes in as more members of the top-level object, so the member
# before it needs a trailing comma (the user's last entry often has none).
for i in range(close - 1, -1, -1):
    s = kept[i].strip()
    if not s or s.startswith("//"):
        continue
    if not s.endswith((",", "{")):
        kept[i] = kept[i].rstrip() + ","
    break

block = [BEGIN, *("  " + l.strip() if l.lstrip().startswith("//") else l for l in snippet_lines), END]
out.write_text("\n".join(kept[:close] + block + kept[close:]) + "\n")
EOF

cat "$tmp" > "$TARGET"
rm -f "$tmp"
trap - EXIT
chmod +x "$PLUGIN_DIR/cursor-accent" "$PLUGIN_DIR/tools/set-fixed-color.sh"

echo "Synced Style > Cursor in $TARGET"
echo "The shell watches this file, so it should pick it up within a second or two."
