#!/usr/bin/env python3
"""Recolors a Bibata cursor theme, installs it, and applies it live.

Colors come from one of three modes, read from config.json:
  "theme" (default): follow the active Omarchy theme's colors.toml
    body   <- dark_background / background
    accent <- accent
    watch  <- darker_background / background
  "fixed": always use config.json's fixed_color for the outline, ignoring
    whatever the active theme is.
  "off": revert to the system's own default cursor (skips the whole build).

Shape comes from config.json's "shape": "modern" (default, rounded) or
"original" (classic sharp-edged pointer). Both are pre-defined render
targets in the vendored bibata_cursor's config/render.json.

The theme is built in both formats: hyprcursor shapes (SVGs on Hyprland
0.57+, PNGs on anything older, see hypr_format), plus an Xcursor `cursors/`
folder for XWayland apps and for Hyprland whenever hyprcursor is off.

Usage: recolor.py [theme-name]   (theme-name is cosmetic/logging only; theme
mode always reads whatever is currently staged, since that's what
omarchy-theme-set has already switched to by the time its hook runs.)

Paths are resolved relative to this file, not hardcoded, so this works
whether it's run from a git checkout or from an installed
~/.config/omarchy/plugins/<id>/ copy. User-editable state (config.json)
lives outside that directory, in ~/.local/state, so `omarchy plugin update`
(which re-syncs the plugin's own folder from git) never touches it.
"""
import ctypes
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".local/state/cursor-accent"
CONFIG_PATH = STATE_DIR / "config.json"
COLORS_PATH = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
CURSOR_NAME = "Omarchy-Accent"
CURSOR_SIZE = os.environ.get("HYPRCURSOR_SIZE", "24")
INSTALL_DIR = Path.home() / f".local/share/icons/{CURSOR_NAME}"
# Staging lives outside every icons/ folder: hyprcursor treats any directory
# there with a manifest, hidden ones included, as a theme it may pick up.
STAGING_DIR = Path.home() / ".local/share/cursor-accent/staging"
STAMP_NAME = ".cursor-accent-stamp"
# Bump when the installed theme's layout changes, so existing installs with
# unchanged colors still get rebuilt after `omarchy plugin update`.
BUILD_FORMAT = 3

SHAPE_TARGETS = {
    "modern": "Bibata-Modern-Classic",
    "original": "Bibata-Original-Classic",
}

DEFAULT_CONFIG = {"mode": "theme", "shape": "modern", "fixed_color": "#F25623"}


def load_config():
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_CONFIG)


def load_theme_colors():
    with COLORS_PATH.open("rb") as f:
        c = tomllib.load(f)
    accent = c.get("accent", "#F25623")
    body = c.get("dark_background") or c.get("background") or "#171717"
    watch = c.get("darker_background") or c.get("background") or body
    return body, accent, watch


# Monitor scales to render hyprcursor PNGs for. Hyprland asks for
# round(cursor size * highest monitor scale) pixels; at these scales that is
# an exact render, pixel for pixel what hyprcursor would draw from the SVG.
# Any other scale gets the nearest rendered size, sharp but a little off.
HYPR_SCALES = (1, 1.25, 1.5, 1.75, 2, 2.5, 3)
# Xcursor only matters for XWayland apps and the fallback. These three are
# also PNG sizes, so the PNG build renders nothing extra for them.
X11_SCALES = (1, 1.5, 2)
# First Hyprland that rejects an empty hyprcursor image instead of handing
# it to cairo (hyprwm/Hyprland 9f3facf, #16439).
SVG_SAFE_HYPRLAND = (0, 57, 0)


def parse_version(text):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else None


def command_output(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def hyprland_versions():
    """(running, installed) Hyprland versions; None where unknown."""
    running = None
    out = command_output(["hyprctl", "version", "-j"])
    if out:
        try:
            running = parse_version(json.loads(out).get("version"))
        except (ValueError, AttributeError):
            pass
    # The installed package is what the next login runs. Without a package
    # named hyprland (hyprland-git, a local build), ask the binary itself.
    installed = parse_version(command_output(["pacman", "-Q", "hyprland"]))
    if installed is None:
        installed = parse_version(command_output(["Hyprland", "--version"]))
    return running, installed


def hypr_format():
    """"svg" only when both the running and the installed Hyprland are safe.

    An SVG theme on disk crashes Hyprland 0.56 at the next login (see
    build_theme), before this script runs again. Checking the installed
    package too means a downgrade made during the session is caught by the
    next theme switch or shell reload, not only by the compositor that is
    already running. Anything unknown counts as unsafe.
    """
    versions = hyprland_versions()
    if all(v is not None and v >= SVG_SAFE_HYPRLAND for v in versions):
        return "svg"
    return "png"


def build_sizes(scales):
    try:
        base = max(8, int(CURSOR_SIZE))
    except ValueError:
        base = 24
    return sorted({round(base * s) for s in scales})


def build_stamp(target, render_spec, layout):
    """Hash of everything that shapes the installed theme.

    Colors alone are not enough: a plugin update can change the vendored
    sources or the output format while the theme colors stay the same.
    """
    h = hashlib.sha256()
    h.update(json.dumps([BUILD_FORMAT, target, render_spec, layout], sort_keys=True).encode())
    for sub in ("src", "svg", "config"):
        for path in sorted((PLUGIN_DIR / sub).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                h.update(str(path.relative_to(PLUGIN_DIR)).encode() + b"\0")
                h.update(path.read_bytes())
    return h.hexdigest() + "\n"


def theme_is_current(stamp):
    stamp_path = INSTALL_DIR / STAMP_NAME
    return (
        stamp_path.is_file()
        and stamp_path.read_text() == stamp
        and (INSTALL_DIR / "manifest.hl").is_file()
        and (INSTALL_DIR / "cursors/left_ptr").exists()
    )


def exchange_dirs(a, b):
    """Atomically swap two paths with renameat2(RENAME_EXCHANGE)."""
    libc = ctypes.CDLL(None, use_errno=True)
    AT_FDCWD, RENAME_EXCHANGE = -100, 2
    if libc.renameat2(AT_FDCWD, os.fsencode(a), AT_FDCWD, os.fsencode(b), RENAME_EXCHANGE) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(a))


def replace_dir(new, live):
    """Move new into live's place without live ever being half-written."""
    live.parent.mkdir(parents=True, exist_ok=True)
    if not live.exists():
        new.rename(live)
        return
    try:
        exchange_dirs(new, live)
    except (OSError, AttributeError):
        # No RENAME_EXCHANGE on this filesystem or libc: two renames, so the
        # theme is only missing for the instant between them.
        old = new.with_name(new.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        live.rename(old)
        new.rename(live)
        new = old
    shutil.rmtree(new, ignore_errors=True)


def remove_leftovers():
    # A staging dir from an interrupted run, and the one an earlier patch
    # (cursor-accent#4) kept inside icons/, where hyprcursor can pick it up
    # as a theme.
    for path in (STAGING_DIR, STAGING_DIR.with_name(STAGING_DIR.name + ".old"),
                 INSTALL_DIR.with_name(f".{CURSOR_NAME}.new")):
        shutil.rmtree(path, ignore_errors=True)


def hyprcursor_enabled():
    """cursor:enable_hyprcursor, or None if Hyprland can't be asked."""
    try:
        out = subprocess.run(
            ["hyprctl", "getoption", "cursor:enable_hyprcursor", "-j"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        option = json.loads(out)
        return bool(option.get("bool", option.get("int")))
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None


def apply_theme():
    subprocess.run(["hyprctl", "setcursor", CURSOR_NAME, CURSOR_SIZE], check=True)
    # Omarchy 4.5 turns hyprcursor off while the session starts and turns it
    # back on at the shell's reveal without another `setcursor`, so a setcursor
    # made in that window only reloads Xcursor and the hyprcursor theme never
    # gets loaded at the right size. Re-apply once hyprcursor is back on.
    if hyprcursor_enabled() is False:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--reapply-when-hyprcursor-on"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        print("cursor-accent: hyprcursor is off for now, will re-apply once it is back on")


def reapply_when_hyprcursor_on(timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        enabled = hyprcursor_enabled()
        if enabled is None:
            return
        if enabled:
            subprocess.run(["hyprctl", "setcursor", CURSOR_NAME, CURSOR_SIZE], check=False)
            return
        time.sleep(0.5)


def build_theme(target, fmt, sizes, stamp):
    """Build the recolored theme in a scratch dir and swap it into place."""
    build_dir = STATE_DIR / "build"
    shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True)
    (build_dir / "src").symlink_to(PLUGIN_DIR / "src")
    (build_dir / "svg").symlink_to(PLUGIN_DIR / "svg")
    (build_dir / "config").mkdir()
    (build_dir / "config/render.json").symlink_to(STATE_DIR / "render.json")
    (build_dir / "config/build.toml").symlink_to(PLUGIN_DIR / "config/build.toml")
    (build_dir / "config/build.right.toml").symlink_to(PLUGIN_DIR / "config/build.right.toml")

    # build_theme.py reuses cursor_utils.py, which resolves its own source
    # paths relative to cwd and mixes those with --out-dir internally
    # (Path.relative_to), so an absolute --out-dir while cwd is build_dir
    # raises "different anchors". Keep it relative, matched to cwd.
    #
    # On Hyprland 0.56 the hyprcursor shapes must be PNGs. An SVG shape has
    # no image at all until hyprcursor loads a style for it, and 0.56 hands
    # that missing image straight to cairo (NULL surface, crash) when
    # hyprcursor is switched on without a theme reload, which is what
    # Omarchy 4.5's startup cursor does at every login. A PNG shape always
    # has a real image, so the worst case there is a nearest-size cursor.
    hypr_sizes = ",".join(str(s) for s in sizes["hypr"]) if fmt == "png" else ""
    x11_sizes = ",".join(str(s) for s in sizes["x11"])
    subprocess.run(
        ["./src/build_theme.py", "--theme", target, "--out-dir", "out",
         "--hypr-sizes", hypr_sizes, "--x11-sizes", x11_sizes],
        # No __pycache__ inside the plugin dir (src/ is symlinked from it).
        cwd=build_dir, check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    shutil.copytree(build_dir / "out" / target, STAGING_DIR, symlinks=True)
    (STAGING_DIR / "index.theme").write_text(
        "[Icon Theme]\n"
        f"Name={CURSOR_NAME}\n"
        "Comment=Bibata cursor recolored to the active Omarchy theme\n"
        "Inherits=Adwaita\n"
    )
    (STAGING_DIR / STAMP_NAME).write_text(stamp)
    replace_dir(STAGING_DIR, INSTALL_DIR)
    shutil.rmtree(build_dir, ignore_errors=True)


def main():
    if sys.argv[1:] == ["--reapply-when-hyprcursor-on"]:
        reapply_when_hyprcursor_on()
        return

    theme_name = sys.argv[1] if len(sys.argv) > 1 else "(unknown)"
    config = load_config()

    if config.get("mode") == "off":
        subprocess.run(["hyprctl", "setcursor", "default", CURSOR_SIZE], check=True)
        print("cursor-accent: mode=off, reverted to the system default cursor")
        return

    shape = config.get("shape", "modern")
    if shape not in SHAPE_TARGETS:
        print(f"cursor-accent: unknown shape '{shape}', falling back to modern", file=sys.stderr)
        shape = "modern"
    target = SHAPE_TARGETS[shape]

    if config.get("mode") == "fixed":
        accent = config.get("fixed_color", "#F25623")
        body = watch = "#171717"
        print(f"cursor-accent: mode=fixed shape={shape} accent={accent}")
    else:
        body, accent, watch = load_theme_colors()
        print(f"cursor-accent: mode=theme theme={theme_name} shape={shape} "
              f"body={body} accent={accent} watch={watch}")

    # Work in a scratch copy of config/, not the plugin's own tracked copy:
    # an `omarchy plugin update` mid-run shouldn't race a half-written
    # render.json, and the plugin directory should stay pristine anyway.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # The theme-set hook, the post-boot hook, and the shell service can all
    # fire within the same second at login. Serialize them: they share the
    # scratch build, staging and install dirs. The loser usually finds the
    # theme already built and only re-applies it.
    with (STATE_DIR / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        remove_leftovers()

        # Start from the plugin's own render.json every time, so a plugin
        # update that changes it is picked up.
        render = json.loads((PLUGIN_DIR / "config/render.json").read_text())
        render[target]["colors"][0]["replace"] = body
        render[target]["colors"][1]["replace"] = accent
        render[target]["colors"][2]["replace"] = watch
        (STATE_DIR / "render.json").write_text(json.dumps(render, indent=2))

        fmt = hypr_format()
        sizes = {"hypr": build_sizes(HYPR_SCALES), "x11": build_sizes(X11_SCALES)}
        stamp = build_stamp(target, render[target], [fmt, sizes])
        if theme_is_current(stamp):
            # A normal login: same theme, same plugin. Leave the installed
            # theme alone and only re-apply it.
            apply_theme()
            print(f"cursor-accent: {CURSOR_NAME} already up to date, re-applied")
            return

        build_theme(target, fmt, sizes, stamp)

        # Runtime-only: Hyprland forgets this on restart, and with no
        # HYPRCURSOR_THEME set it boots with whichever theme directory
        # hyprcursor finds first. The post-boot hook re-runs this script.
        apply_theme()
        print(f"cursor-accent: applied {CURSOR_NAME} ({target}, {fmt}) at size {CURSOR_SIZE}")


if __name__ == "__main__":
    main()
