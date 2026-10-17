#!/usr/bin/env python3
"""Recolors a Bibata hyprcursor theme, installs it, and applies it live.

Colors come from one of three modes, read from config.json:
  "theme" (default): follow the active Omarchy theme's colors.toml
    body   <- dark_background / background
    accent <- accent
    watch  <- darker_background / background
  "fixed": always use config.json's fixed_color for the outline, ignoring
    whatever the active theme is.
  "off": revert to the system's own default cursor (skips the whole build).

Shape comes from config.json's "shape": "modern" (default, rounded) or
"original" (classic sharp-edged pointer), Bibata's own, or one of the styles
drawn by tools/gen-cursor-styles.py (see SHAPE_TARGETS). Each is a render
target in config/render.json; a style that moves hotspots ships its own
config/build.<shape>.toml.

Usage: recolor.py [theme-name]   (theme-name is cosmetic/logging only; theme
mode always reads whatever is currently staged, since that's what
omarchy-theme-set has already switched to by the time its hook runs.)
       recolor.py --list-shapes   (print the valid shapes, one per line)

Paths are resolved relative to this file, not hardcoded, so this works
whether it's run from a git checkout or from an installed
~/.config/omarchy/plugins/<id>/ copy. User-editable state (config.json)
lives outside that directory, in ~/.local/state, so `omarchy plugin update`
(which re-syncs the plugin's own folder from git) never touches it.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".local/state/cursor-accent"
CONFIG_PATH = STATE_DIR / "config.json"
COLORS_PATH = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
CURSOR_NAME = "Omarchy-Accent"
CURSOR_SIZE = os.environ.get("HYPRCURSOR_SIZE", "24")

SHAPE_TARGETS = {
    "modern": "Bibata-Modern-Classic",
    "original": "Bibata-Original-Classic",
    "macos": "Bibata-MacOS-Classic",
    "macos-tailless": "Bibata-MacOS-Tailless-Classic",
    "dart": "Bibata-Dart-Classic",
    "retro": "Bibata-Retro-Classic",
    "crosshair": "Bibata-Crosshair-Classic",
    "dot": "Bibata-Dot-Classic",
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


def main():
    if sys.argv[1:2] == ["--list-shapes"]:
        print("\n".join(SHAPE_TARGETS))
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
    # scratch build dir and the install dir, and each run starts by wiping
    # both. A full build is ~0.2s, so the loser just redoes the same work.
    with (STATE_DIR / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Start from the plugin's copy every time: a copy cached by an older
        # version would lack the targets of shapes added since.
        render_path = STATE_DIR / "render.json"
        render = json.loads((PLUGIN_DIR / "config/render.json").read_text())
        render[target]["colors"][0]["replace"] = body
        render[target]["colors"][1]["replace"] = accent
        render[target]["colors"][2]["replace"] = watch
        render_path.write_text(json.dumps(render, indent=2))

        build_dir = STATE_DIR / "build"
        shutil.rmtree(build_dir, ignore_errors=True)
        build_dir.mkdir(parents=True)
        (build_dir / "src").symlink_to(PLUGIN_DIR / "src")
        (build_dir / "svg").symlink_to(PLUGIN_DIR / "svg")
        (build_dir / "config").mkdir()
        (build_dir / "config/render.json").symlink_to(render_path)
        # Generated styles move hotspots, so they ship their own build toml.
        build_toml = PLUGIN_DIR / f"config/build.{shape}.toml"
        if not build_toml.exists():
            build_toml = PLUGIN_DIR / "config/build.toml"
        (build_dir / "config/build.toml").symlink_to(build_toml)
        (build_dir / "config/build.right.toml").symlink_to(PLUGIN_DIR / "config/build.right.toml")

        # cursor_utils.py resolves its own source paths relative to cwd, and
        # mixes those with --out-dir internally (Path.relative_to), so passing
        # an absolute --out-dir while cwd is build_dir raises "different
        # anchors". Keep it relative, matched to cwd=build_dir, to avoid that.
        subprocess.run(
            ["./src/cursor_utils.py", "--hypr", "--theme", target,
             "--out-dir", "out", "--log-level", "error"],
            cwd=build_dir, check=True,
        )

        install_dir = Path.home() / f".local/share/icons/{CURSOR_NAME}"
        shutil.rmtree(install_dir, ignore_errors=True)
        shutil.copytree(build_dir / "out" / target, install_dir)
        (install_dir / "index.theme").write_text(
            "[Icon Theme]\n"
            f"Name={CURSOR_NAME}\n"
            "Comment=Bibata cursor recolored to the active Omarchy theme\n"
            "Inherits=Adwaita\n"
        )
        shutil.rmtree(build_dir, ignore_errors=True)

        # Runtime-only: Hyprland forgets this on restart, and with no
        # HYPRCURSOR_THEME set it boots with whichever theme directory
        # hyprcursor finds first. The post-boot hook re-runs this script.
        subprocess.run(["hyprctl", "setcursor", CURSOR_NAME, CURSOR_SIZE], check=True)
        print(f"cursor-accent: applied {CURSOR_NAME} ({target}) at size {CURSOR_SIZE}")


if __name__ == "__main__":
    main()
