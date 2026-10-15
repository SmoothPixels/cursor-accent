# Changelog

## Unreleased

- Fixed a Hyprland crash at login (abort in `CCursorBuffer` / cairo,
  followed by a restart in safe mode). The theme is no longer rebuilt when
  its shape and colors have not changed, and a rebuild swaps the new theme
  in with one atomic `renameat2(RENAME_EXCHANGE)`, so Hyprland never sees
  a missing or half-written theme folder.

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
