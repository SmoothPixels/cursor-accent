# Changelog

## Unreleased

- Added a test suite (`tests/`) and a `tests` workflow that runs it on every
  push and pull request, and weekly against current Arch packages. It checks
  the built theme the way Hyprland and XWayland read it, including the
  startup state behind #3.

## 1.2.0 (2026-11-04)

- Fixed Hyprland crashing at login on Omarchy 4.5 (abort in
  `CCursorBuffer` / cairo, then a restart in safe mode with a black screen;
  #3). Omarchy 4.5 turns hyprcursor off while the session starts and back on
  at the shell's reveal without reloading the cursor theme. Hyprland 0.56
  then asks hyprcursor for a shape at size 0, and for an SVG theme like
  ours that returns an image with no surface, which crashes cairo. The
  crash needed only the theme folder on disk, so disabling the plugin did
  not help. On Hyprland 0.56 the theme's hyprcursor shapes are now PNGs,
  rendered by the same librsvg from the same SVGs at the pixel sizes
  Hyprland asks for at 1x,
  1.25x, 1.5x, 1.75x, 2x, 2.5x and 3x, so at those scales the cursor is
  pixel for pixel what the SVG theme drew. A PNG shape always has an image,
  so the startup window gets a real cursor instead of a crash. Other scales
  get the nearest rendered size, kept sharp: the PNGs are marked
  `resize_algorithm = none`, because hyprcursor 0.1.13 crops the PNGs it
  scales down.
- Hyprland 0.57 and later reject an empty cursor image instead of crashing,
  so there the theme keeps SVG shapes. SVGs are used only when both the
  running Hyprland and the installed package (`pacman -Q hyprland`, or
  `Hyprland --version` without that package) are 0.57 or newer, so a
  downgrade made during a session is caught by the next theme switch or
  shell reload before it can crash a login. A version change in either
  direction rebuilds the theme.
- The theme now also ships Xcursor cursors (`cursors/`), so that fallback,
  XWayland apps, and anything else that only reads Xcursor show the accent
  cursor too. `xcursorgen` is not needed.
- Builds are fast again. A new builder (`src/build_theme.py`) renders each
  image once, inside Python through librsvg and cairo (python-gobject and
  python-cairo, both in Omarchy's base install), and writes the hyprcursor
  and Xcursor files from that one render. Measured on 4 cores: about 0.4 s
  for the PNG theme and 0.25 s for the SVG one, where running
  `rsvg-convert` once per image took 3.4 s. Without those Python modules it
  falls back to `rsvg-convert`, all images in one thread pool, with the same
  output byte for byte. Animation frames are now ordered by file name,
  not by directory listing order.
- When hyprcursor is off at the moment the cursor is applied (Omarchy 4.5's
  startup window), the cursor is applied again as soon as it is back on, so
  the session does not stay on the fallback cursor.
- A login no longer rebuilds the theme when nothing changed. The installed
  theme carries a stamp of the colors, the shape, the sizes, and the plugin's
  build sources, so a plugin update still triggers a rebuild. A rebuild is
  staged outside `~/.local/share/icons` and swapped in with one atomic
  rename. Leftovers from an interrupted run, and the hidden
  `.Omarchy-Accent.new` folder an earlier patch for #3 could leave in
  `~/.local/share/icons`, are removed on every run.
- `render.json` is taken from the plugin on every run instead of from a
  copy made once at first install, so plugin updates to it apply.

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
