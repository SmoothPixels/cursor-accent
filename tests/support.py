"""Shared helpers: a throwaway home with stand-in system commands, and the
libhyprcursor / libXcursor probes.

Nothing here talks to a real compositor or touches the real home: every
run gets HOME, PATH and the plugin's state inside a temporary directory,
with `hyprctl`, `pacman` and `Hyprland` replaced by small scripts whose
answers each test chooses.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
CURSOR_NAME = "Omarchy-Accent"

# Default answers: Omarchy's stable channel today (Hyprland 0.56, PNG build).
DEFAULT_COLORS = {"accent": "#7d82d9", "background": "#060B1E",
                  "dark_background": "#040816", "darker_background": "#030610"}

# cursor-shape-v1, which Wayland clients use through Hyprland.
CURSOR_SHAPE_V1 = [
    "default", "context-menu", "help", "pointer", "progress", "wait", "cell",
    "crosshair", "text", "vertical-text", "alias", "copy", "move", "no-drop",
    "not-allowed", "grab", "grabbing", "e-resize", "n-resize", "ne-resize",
    "nw-resize", "s-resize", "se-resize", "sw-resize", "w-resize", "ew-resize",
    "ns-resize", "nesw-resize", "nwse-resize", "col-resize", "row-resize",
    "all-scroll", "zoom-in", "zoom-out",
]
# Legacy X11 names that XWayland apps and Hyprland itself still ask for.
LEGACY_NAMES = ["left_ptr", "top_left_arrow", "hand1", "hand2", "xterm", "watch",
                "fleur", "question_arrow", "sb_h_double_arrow", "sb_v_double_arrow"]

HYPRCTL = """#!/bin/bash
D="{dir}"
printf '%s\\n' "$*" >> "$D/hyprctl.log"
case "$1" in
  getoption)
    if [[ -f $D/hyprcursor-off ]]; then b=false; else b=true; fi
    printf '{{"option": "%s", "bool": %s, "set": true }}\\n' "$2" "$b" ;;
  version)
    [[ -f $D/running ]] || exit 1
    printf '{{"version": "%s"}}\\n' "$(cat "$D/running")" ;;
  setcursor) echo ok ;;
esac
"""
PACMAN = """#!/bin/bash
D="{dir}"
[[ "$*" == "-Q hyprland" && -f $D/installed ]] || exit 1
echo "hyprland $(cat "$D/installed")"
"""
HYPRLAND = """#!/bin/bash
D="{dir}"
[[ $1 == --version && -f $D/binary ]] || exit 1
echo "Hyprland $(cat "$D/binary") built from branch test at commit 0000000 clean"
"""


class Sandbox:
    """A home directory plus stand-in commands, for running recolor.py."""

    def __init__(self, plugin_dir=REPO):
        self.root = Path(tempfile.mkdtemp(prefix="cursor-accent-test-"))
        self.plugin_dir = Path(plugin_dir)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True)
        for name, text in (("hyprctl", HYPRCTL), ("pacman", PACMAN), ("Hyprland", HYPRLAND)):
            path = self.bin / name
            path.write_text(text.format(dir=self.root))
            path.chmod(0o755)
        (self.home / ".local/state/omarchy/current/theme").mkdir(parents=True)
        self.colors(**DEFAULT_COLORS)
        self.hyprland(running="0.56.2", installed="0.56.2-2")
        atexit.register(self.close)

    # -- the system the plugin sees ------------------------------------------

    def colors(self, **values):
        text = "".join(f'{k} = "{v}"\n' for k, v in values.items())
        (self.home / ".local/state/omarchy/current/theme/colors.toml").write_text(text)

    def config(self, **values):
        path = self.home / ".local/state/cursor-accent/config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values))

    def hyprland(self, running=None, installed=None, binary=None):
        """Versions of the running compositor, the hyprland package and the binary."""
        for name, value in (("running", running), ("installed", installed), ("binary", binary)):
            path = self.root / name
            if value is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(value)

    def hyprcursor(self, enabled):
        flag = self.root / "hyprcursor-off"
        if enabled:
            flag.unlink(missing_ok=True)
        else:
            flag.touch()

    # -- running the plugin ----------------------------------------------------

    def env(self, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HYPRLAND_", "HYPRCURSOR_", "XCURSOR_", "XDG_"))}
        env.update(HOME=str(self.home), PATH=f"{self.bin}:{os.environ.get('PATH', '/usr/bin')}",
                   PYTHONDONTWRITEBYTECODE="1", XDG_DATA_DIRS=str(self.root / "no-system-data"))
        env.update(extra or {})
        return env

    def run(self, *args, env=None, check=True):
        args = args or ("test-theme",)
        result = subprocess.run([sys.executable, str(self.plugin_dir / "recolor.py"), *args],
                                env=self.env(env), capture_output=True, text=True, timeout=300)
        if check and result.returncode != 0:
            raise AssertionError(f"recolor.py failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
        return result

    def cli(self, *args, check=True):
        result = subprocess.run([str(self.plugin_dir / "cursor-accent"), *args], env=self.env(),
                                capture_output=True, text=True, timeout=300)
        if check and result.returncode != 0:
            raise AssertionError(f"cursor-accent failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
        return result

    def calls(self):
        log = self.root / "hyprctl.log"
        return [line.split() for line in log.read_text().splitlines()] if log.exists() else []

    def setcursor_calls(self):
        return [c for c in self.calls() if c and c[0] == "setcursor"]

    def clear_calls(self):
        (self.root / "hyprctl.log").unlink(missing_ok=True)

    # -- what it produced ----------------------------------------------------

    @property
    def icons(self):
        return self.home / ".local/share/icons"

    @property
    def theme(self):
        return self.icons / CURSOR_NAME

    def shapes(self):
        return sorted(p.stem for p in (self.theme / "hyprcursors").glob("*.hlc"))

    def meta(self, shape):
        with zipfile.ZipFile(self.theme / "hyprcursors" / f"{shape}.hlc") as z:
            return z.read("meta.hl").decode()

    def hlc_members(self, shape):
        with zipfile.ZipFile(self.theme / "hyprcursors" / f"{shape}.hlc") as z:
            return {name: z.read(name) for name in z.namelist()}

    def overrides(self):
        names = {}
        for shape in self.shapes():
            for line in self.meta(shape).splitlines():
                if line.startswith("define_override"):
                    names[line.split("=", 1)[1].strip()] = shape
        return names

    def defined_sizes(self, shape):
        sizes = []
        for line in self.meta(shape).splitlines():
            if line.startswith("define_size"):
                sizes.append(int(line.split("=", 1)[1].split(",")[0]))
        return sorted(set(sizes))

    def probe(self, queries, theme=CURSOR_NAME):
        """Run hcprobe.py against this home. theme=None: first theme found."""
        return _probe(TESTS / "hcprobe.py", {"theme": theme, "queries": queries},
                      self.env())

    def xcursor(self, files=(), lookups=()):
        return _probe(TESTS / "xcprobe.py", {"files": [str(f) for f in files], "lookups": list(lookups)},
                      self.env({"XCURSOR_PATH": str(self.icons)}))

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _probe(script, request, env):
    with tempfile.TemporaryDirectory() as tmp:
        req, res = Path(tmp, "request.json"), Path(tmp, "result.json")
        req.write_text(json.dumps(request))
        run = subprocess.run([sys.executable, str(script), str(req), str(res)], env=env,
                             capture_output=True, text=True, timeout=300)
        if run.returncode != 0 or not res.exists():
            raise AssertionError(f"{script.name} failed ({run.returncode}): {run.stderr[-2000:]}")
        return json.loads(res.read_text())


_built = {}


def built(kind):
    """One shared build per kind, reused across test modules.

    "png": Hyprland 0.56 everywhere, so PNG shapes.
    "svg": Hyprland 0.57 running and installed, so SVG shapes.
    Both use DEFAULT_COLORS, so their pixels can be compared.
    """
    if kind not in _built:
        box = Sandbox()
        if kind == "svg":
            box.hyprland(running="0.57.1", installed="0.57.1-2")
        box.run()
        _built[kind] = box
    return _built[kind]


def copy_plugin():
    """A copy of the plugin's tracked files, for tests that edit them."""
    dest = Path(tempfile.mkdtemp(prefix="cursor-accent-plugin-"))
    atexit.register(shutil.rmtree, dest, True)
    listing = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], capture_output=True)
    if listing.returncode == 0:
        names = [n.decode() for n in listing.stdout.split(b"\0") if n]
    else:  # not a git checkout (a release tarball, say)
        names = [str(p.relative_to(REPO)) for p in REPO.rglob("*")
                 if p.is_file() and not {".git", "__pycache__"} & set(p.relative_to(REPO).parts)]
    for name in names:
        src = REPO / name
        if src.is_file():
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target, follow_symlinks=False)
    return dest


def has_gi_cairo():
    try:
        import gi
        gi.require_version("Rsvg", "2.0")
        from gi.repository import Rsvg  # noqa: F401
        import cairo  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False
