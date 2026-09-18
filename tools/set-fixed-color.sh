#!/bin/bash
# Launched from Style > Cursor > Fixed Color… inside a floating terminal.
set -euo pipefail
PLUGIN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Fixed cursor color (hex, e.g. #39ff14):"
if ! read -r color; then
  color=""
fi

if [[ ! $color =~ ^#[0-9a-fA-F]{6}$ ]]; then
  echo "Not a valid #rrggbb color, leaving the cursor unchanged." >&2
  exit 130
fi

"$PLUGIN_DIR/cursor-accent" fixed "$color"
