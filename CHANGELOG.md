# Changelog

## 1.2.0 (2026-10-17)

- Six new pointer styles: macOS (the classic arrow with its tail), macOS
  Tailless, Dart, Retro, Crosshair, and Dot, drawn by
  `tools/gen-cursor-styles.py`. Each recolors like the Bibata shapes.
- A settings window (`cursor-accent settings`, or Style > Cursor > Cursor
  Style Settings…) to pick the color mode and style, with previews in your
  colors.
- `install-cursor-hook.sh` also installs the Style > Cursor menu, and the
  plugin keeps that menu up to date across updates once it's installed.
- Fixed: `install-menu-entries.sh` could leave the user's
  `omarchy-menu.jsonc` invalid (no comma before the spliced block), which
  hides every custom menu entry; it also piled up a copy of its header
  comments on each run and reset the file to mode 600.
- Fixed: a `render.json` cached by an older version stopped new shapes from
  building; it's now refreshed on every run.

## 1.1.0 (2026-09-22)

- The cursor is re-applied at every login. A post-boot hook joins the
  theme-set hook, because a cursor set with `hyprctl setcursor` lasts only
  for the running compositor and Omarchy sets no `HYPRCURSOR_THEME`, so a
  fresh boot could come up with whatever theme hyprcursor found first. The
  two hooks and the shell service take a lock so they cannot race on the
  shared build and install folders.
- The README documents the optional Style > Cursor menu picker with a
  screenshot, and its Remove section names the hook files that exist.

## 1.0.0 (2026-09-18)

- First listing. Recolors the system cursor to the active Omarchy theme's
  accent on every theme switch, using Hyprland's own `hyprcursor-util`,
  with a fixed-color or system-default option and a choice of pointer
  shape.
