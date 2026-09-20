# Cursor Accent

Recolors the system pointer to match the active Omarchy theme's accent
color, automatically, every time you switch themes. No matugen, no new
runtime dependencies: it uses Hyprland's own `hyprcursor-util` (already
installed, since `hyprcursor` is a hard dependency of Hyprland itself) to
compile a [Bibata](https://github.com/ful1e5/Bibata_Cursor) cursor recolored
on the fly from each theme's `colors.toml`.

Also supports locking to one fixed color regardless of theme, turning it off
entirely to use the system default cursor, and choosing between Bibata's
"Modern" (rounded) and "Original" (classic sharp-edged) pointer shapes.

## Install

```sh
omarchy plugin add https://github.com/SmoothPixels/cursor-accent.git --enable
```

Once enabled, the plugin's shell service applies the cursor once at startup
and re-applies it whenever the active theme's colors.toml changes, so
`omarchy theme set` recolors the pointer immediately — no shell restart and
no manual setup needed. Everything below is optional:

```sh
# Optional: a "Style > Cursor" menu, since there's no settings-form GUI yet
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/tools/install-menu-entries.sh
```

An older `theme-set` hook installer (`tools/install-cursor-hook.sh`) is still
supported for machines where the shell service isn't running (e.g. a theme
changed from outside the session). It's no longer required: the service
watches theme changes itself, and `recolor.py` skips a rebuild when the
colors it was asked for are already applied, so keeping the hook installed
alongside the service never builds the cursor twice.

## Settings

There's no settings-form GUI for plugins in Omarchy yet, and unlike
bar-widgets, `service`-kind plugins like this one have no `omarchy bar set`
equivalent at all. Configuration is the bundled `cursor-accent` command, or
the optional menu above:

```sh
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent follow
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent fixed '#39ff14'
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent default
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent shape modern
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent shape original
~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/cursor-accent status
```

| Command | Effect |
| --- | --- |
| `follow` | Recolor to the active theme's accent, and keep following it on every theme switch (default). |
| `fixed '#rrggbb'` | Lock to one color, ignoring theme switches. |
| `default` | Turn this off. Reverts to the system's own default cursor (the theme literally named `default`, inherited from Adwaita), and stays off through theme switches until you pick `follow` or `fixed` again. |
| `shape modern\|original` | Bibata's rounded "Modern" shape (default) or the classic sharp-edged "Original". |
| `status` | Print the current mode, shape, and fixed color as JSON. |

Your choice is stored in `~/.local/state/cursor-accent/config.json`, outside
the plugin's own directory, so `omarchy plugin update` never resets it.

## Remove

```sh
rm -f ~/.config/omarchy/hooks/theme-set.d/theme-set-hook.sh
rm -rf ~/.local/share/icons/Omarchy-Accent ~/.local/state/cursor-accent
hyprctl setcursor default 24               # or your preferred size
omarchy plugin remove io.github.smoothpixels.cursor-accent
```

Delete the `"style.cursor*"` block from
`~/.config/omarchy/extensions/omarchy-menu.jsonc` by hand if you installed
the menu.

## Development

`src/`, `svg/`, and `config/` are vendored from
[rtgiskard/bibata_cursor](https://github.com/rtgiskard/bibata_cursor) (see
NOTICE.md), pinned to a known-good commit rather than fetched at install
time, so there's no network access at runtime. `recolor.py` patches a
scratch copy of `config/render.json` with the current colors, symlinks the
vendored `src/`/`svg/` into a scratch build directory (to avoid copying
~1.5MB on every theme switch), and runs `cursor_utils.py --hypr` there.

Validate before publishing:

```sh
omarchy plugin validate ~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent
qmllint -I "$OMARCHY_PATH/shell" ~/.config/omarchy/plugins/io.github.smoothpixels.cursor-accent/Service.qml
```
