"""recolor.py's decisions: when to build, in which format, and what it
leaves behind. Everything runs against a throwaway home."""
import errno
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.support import CURSOR_NAME, REPO, Sandbox, copy_plugin


def load_recolor():
    spec = importlib.util.spec_from_file_location("recolor_under_test", REPO / "recolor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recolor = load_recolor()


def hlc_format(box):
    members = box.hlc_members("left_ptr")
    return "svg" if "left_ptr.svg" in members else "png"


class Versions(unittest.TestCase):

    def test_parse_version(self):
        cases = {
            "0.56.2": (0, 56, 2), "hyprland 0.56.2-2": (0, 56, 2), "v0.57.1": (0, 57, 1),
            "Hyprland 0.57.0 built from branch v0.57.0 at commit abc": (0, 57, 0),
            "hyprland-git 0.57.0.r12.gdeadbee-1": (0, 57, 0), "": None, None: None, "garbage": None,
        }
        for text, expected in cases.items():
            self.assertEqual(recolor.parse_version(text), expected, text)

    def test_hypr_format_needs_both_running_and_installed_to_be_safe(self):
        cases = [
            ((0, 57, 1), (0, 57, 1), "svg"),
            ((0, 58, 0), (0, 57, 0), "svg"),
            ((0, 57, 1), (0, 56, 2), "png"),   # downgraded mid-session
            ((0, 56, 2), (0, 57, 1), "png"),   # upgraded, not restarted yet
            ((0, 56, 2), (0, 56, 2), "png"),
            (None, (0, 57, 1), "png"),         # compositor not reachable
            ((0, 57, 1), None, "png"),         # package unknown
            (None, None, "png"),
        ]
        for running, installed, expected in cases:
            with mock.patch.object(recolor, "hyprland_versions", return_value=(running, installed)):
                self.assertEqual(recolor.hypr_format(), expected, (running, installed))

    def test_installed_version_falls_back_to_the_binary(self):
        answers = {("hyprctl", "version", "-j"): '{"version": "0.57.1"}',
                   ("pacman", "-Q", "hyprland"): None,
                   ("Hyprland", "--version"): "Hyprland 0.56.2 built from branch v0.56.2"}
        with mock.patch.object(recolor, "command_output", side_effect=lambda cmd: answers[tuple(cmd)]):
            self.assertEqual(recolor.hyprland_versions(), ((0, 57, 1), (0, 56, 2)))
            self.assertEqual(recolor.hypr_format(), "png")

    def test_sizes_follow_the_cursor_size(self):
        for size, hypr, x11 in (("24", [24, 30, 36, 42, 48, 60, 72], [24, 36, 48]),
                                ("32", [32, 40, 48, 56, 64, 80, 96], [32, 48, 64]),
                                ("bogus", [24, 30, 36, 42, 48, 60, 72], [24, 36, 48])):
            with mock.patch.object(recolor, "CURSOR_SIZE", size):
                self.assertEqual(recolor.build_sizes(recolor.HYPR_SCALES), hypr, size)
                self.assertEqual(recolor.build_sizes(recolor.X11_SCALES), x11, size)
                self.assertTrue(set(recolor.build_sizes(recolor.X11_SCALES))
                                <= set(recolor.build_sizes(recolor.HYPR_SCALES)),
                                "Xcursor sizes should cost no extra renders")


class Swap(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.new, self.live = self.tmp / "staging", self.tmp / "icons/theme"
        self.new.mkdir()
        (self.new / "marker").write_text("new")

    def test_first_install_is_a_rename(self):
        recolor.replace_dir(self.new, self.live)
        self.assertEqual((self.live / "marker").read_text(), "new")
        self.assertFalse(self.new.exists())

    def test_replace_swaps_and_removes_the_old_copy(self):
        self.live.mkdir(parents=True)
        (self.live / "marker").write_text("old")
        recolor.replace_dir(self.new, self.live)
        self.assertEqual((self.live / "marker").read_text(), "new")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["icons"])

    def test_filesystems_without_rename_exchange_fall_back(self):
        self.live.mkdir(parents=True)
        (self.live / "marker").write_text("old")
        for error in (OSError(errno.EINVAL, "Invalid argument"), AttributeError("renameat2")):
            with self.subTest(error=type(error).__name__):
                if not self.new.exists():
                    self.new.mkdir()
                    (self.new / "marker").write_text("new")
                with mock.patch.object(recolor, "exchange_dirs", side_effect=error):
                    recolor.replace_dir(self.new, self.live)
                self.assertEqual((self.live / "marker").read_text(), "new")
                self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["icons"])


class Building(unittest.TestCase):

    def setUp(self):
        self.box = Sandbox()

    def tearDown(self):
        self.box.close()

    def test_fresh_install_builds_and_applies(self):
        out = self.box.run().stdout
        self.assertIn(f"applied {CURSOR_NAME}", out)
        self.assertTrue((self.box.theme / ".cursor-accent-stamp").is_file())
        self.assertEqual(self.box.setcursor_calls(), [["setcursor", CURSOR_NAME, "24"]])
        self.assertEqual(hlc_format(self.box), "png")

    def test_unchanged_login_skips_the_build_but_still_applies(self):
        self.box.run()
        inode = self.box.theme.stat().st_ino
        self.box.clear_calls()
        out = self.box.run().stdout
        self.assertIn("already up to date", out)
        self.assertEqual(self.box.theme.stat().st_ino, inode)
        self.assertEqual(self.box.setcursor_calls(), [["setcursor", CURSOR_NAME, "24"]])

    def test_a_theme_switch_rebuilds_with_the_new_colors(self):
        self.box.run()
        before = self.box.hlc_members("left_ptr")
        self.box.colors(accent="#ff0000", background="#000000")
        self.assertIn(f"applied {CURSOR_NAME}", self.box.run().stdout)
        self.assertNotEqual(self.box.hlc_members("left_ptr"), before)
        render = json.loads((self.box.home / ".local/state/cursor-accent/render.json").read_text())
        self.assertEqual(render["Bibata-Modern-Classic"]["colors"][1]["replace"], "#ff0000")

    def test_a_hyprland_version_change_rebuilds_in_the_right_format(self):
        self.box.run()
        self.assertEqual(hlc_format(self.box), "png")
        self.box.hyprland(running="0.57.1", installed="0.57.1-2")
        self.box.run()
        self.assertEqual(hlc_format(self.box), "svg")
        self.box.hyprland(running="0.57.1", installed="0.56.2-2")  # downgrade
        self.box.run()
        self.assertEqual(hlc_format(self.box), "png")
        self.box.hyprland(running="0.57.1", installed=None, binary="0.57.0")  # hyprland-git
        self.box.run()
        self.assertEqual(hlc_format(self.box), "svg")

    def test_a_damaged_install_is_rebuilt(self):
        self.box.run()
        shutil.rmtree(self.box.theme / "cursors")
        self.assertIn(f"applied {CURSOR_NAME}", self.box.run().stdout)
        self.assertTrue((self.box.theme / "cursors/left_ptr").exists())

    def test_a_plugin_update_rebuilds_even_with_the_same_colors(self):
        plugin = copy_plugin()
        box = Sandbox(plugin)
        self.addCleanup(box.close)
        box.run()
        svg = next((plugin / "svg").rglob("left_ptr.svg"))
        svg.write_text(svg.read_text().replace("</svg>", "<!-- changed --></svg>"))
        self.assertIn(f"applied {CURSOR_NAME}", box.run().stdout)

    def test_cursor_size_comes_from_hyprcursor_size(self):
        self.box.run(env={"HYPRCURSOR_SIZE": "32"})
        self.assertEqual(self.box.defined_sizes("left_ptr"), [32, 40, 48, 56, 64, 80, 96])
        self.assertEqual(self.box.setcursor_calls()[-1], ["setcursor", CURSOR_NAME, "32"])

    def test_modes(self):
        self.box.config(mode="fixed", shape="original", fixed_color="#39ff14")
        out = self.box.run().stdout
        self.assertIn("Bibata-Original-Classic", out)
        render = json.loads((self.box.home / ".local/state/cursor-accent/render.json").read_text())
        self.assertEqual(render["Bibata-Original-Classic"]["colors"][1]["replace"], "#39ff14")
        self.box.clear_calls()
        self.box.config(mode="off")
        out = self.box.run().stdout
        self.assertIn("reverted to the system default", out)
        self.assertEqual(self.box.setcursor_calls(), [["setcursor", "default", "24"]])

    def test_an_unknown_shape_falls_back_to_modern(self):
        self.box.config(mode="theme", shape="squiggly")
        result = self.box.run()
        self.assertIn("unknown shape", result.stderr)
        self.assertIn("Bibata-Modern-Classic", result.stdout)

    def test_a_stale_render_json_copy_is_ignored(self):
        state = self.box.home / ".local/state/cursor-accent"
        state.mkdir(parents=True, exist_ok=True)
        (state / "render.json").write_text("{}")  # what an old version left behind
        self.box.run()

    def test_leftovers_are_cleaned_up(self):
        leftovers = [self.box.icons / f".{CURSOR_NAME}.new",  # cursor-accent#4's staging dir
                     self.box.home / ".local/share/cursor-accent/staging",
                     self.box.home / ".local/share/cursor-accent/staging.old"]
        for path in leftovers:
            (path / "hyprcursors").mkdir(parents=True)
            (path / "manifest.hl").write_text("name = stale\n")
        self.box.run()
        for path in leftovers:
            self.assertFalse(path.exists(), path)
        self.assertEqual(sorted(p.name for p in self.box.icons.iterdir()), [CURSOR_NAME])
        # The skip path cleans up too.
        (leftovers[0] / "hyprcursors").mkdir(parents=True)
        self.box.run()
        self.assertFalse(leftovers[0].exists())

    def test_no_staging_dir_inside_icons_ever(self):
        # hyprcursor picks up hidden dirs with a manifest as themes.
        self.box.run()
        self.box.colors(accent="#00ff00")
        self.box.run()
        self.assertEqual([p.name for p in self.box.icons.iterdir()], [CURSOR_NAME])

    def test_concurrent_runs_build_once_and_agree(self):
        env = self.box.env()
        procs = [subprocess.Popen([os.sys.executable, str(REPO / "recolor.py"), "x"], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(3)]
        outs = [p.communicate(timeout=300) for p in procs]
        self.assertTrue(all(p.returncode == 0 for p in procs), outs)
        built = sum(f"applied {CURSOR_NAME}" in out for out, _ in outs)
        skipped = sum("already up to date" in out for out, _ in outs)
        self.assertEqual((built, skipped), (1, 2))
        self.assertEqual(self.box.shapes(), Sandbox.shapes(self.box))
        self.assertEqual(len(self.box.setcursor_calls()), 3)

    def test_the_build_writes_nothing_into_the_plugin_dir(self):
        plugin = copy_plugin()
        box = Sandbox(plugin)
        self.addCleanup(box.close)
        before = sorted(str(p.relative_to(plugin)) for p in plugin.rglob("*"))
        box.run()
        after = sorted(str(p.relative_to(plugin)) for p in plugin.rglob("*"))
        self.assertEqual(after, before)

    def test_the_theme_is_never_missing_or_partial_during_a_rebuild(self):
        # Anything reading the theme while a theme switch rebuilds it (a
        # Hyprland starting up, an XWayland app) must see either the old
        # theme or the new one, whole.
        probe_new, probe_live = self.box.root / "x-new", self.box.root / "x-live"
        probe_new.mkdir()
        probe_live.mkdir()
        try:
            recolor.exchange_dirs(probe_new, probe_live)
        except (OSError, AttributeError):
            self.skipTest("this filesystem has no RENAME_EXCHANGE; the fallback has a brief gap")
        self.box.run()
        theme = self.box.theme
        misses, checks, stop = [], [0], threading.Event()

        def watch():
            while not stop.is_set():
                checks[0] += 1
                if not ((theme / "manifest.hl").is_file() and (theme / "cursors/left_ptr").exists()
                        and (theme / "hyprcursors/wait.hlc").is_file()):
                    misses.append(checks[0])

        watcher = threading.Thread(target=watch)
        watcher.start()
        try:
            for accent in ("#ff0000", "#00ff00", "#0000ff"):
                self.box.colors(accent=accent, background="#101010")
                self.assertIn(f"applied {CURSOR_NAME}", self.box.run().stdout)
        finally:
            stop.set()
            watcher.join()
        self.assertGreater(checks[0], 1000)
        self.assertEqual(misses, [], f"theme missing or partial in {len(misses)} of {checks[0]} checks")

    def test_a_failed_build_keeps_the_previous_theme(self):
        self.box.run()
        inode = self.box.theme.stat().st_ino
        plugin = copy_plugin()
        broken = Sandbox(plugin)
        self.addCleanup(broken.close)
        shutil.copytree(self.box.home, broken.home, dirs_exist_ok=True)
        (plugin / "src/build_theme.py").write_text("import sys\nsys.exit('boom')\n")
        broken.colors(accent="#123456")
        result = broken.run(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((broken.theme / "manifest.hl").is_file(), "the old theme should survive")
        self.assertEqual(self.box.theme.stat().st_ino, inode)


class ReapplyAfterStartup(unittest.TestCase):
    """While Omarchy 4.5's startup cursor has hyprcursor off, setcursor only
    reloads Xcursor; the plugin must apply the theme again once it is back on."""

    def test_reapplies_once_hyprcursor_is_back_on(self):
        box = Sandbox()
        self.addCleanup(box.close)
        box.hyprcursor(enabled=False)
        out = box.run().stdout
        self.assertIn("will re-apply once it is back on", out)
        time.sleep(1.2)
        self.assertEqual(len(box.setcursor_calls()), 1, "nothing while hyprcursor is still off")
        box.hyprcursor(enabled=True)
        deadline = time.monotonic() + 10
        while len(box.setcursor_calls()) < 2 and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertEqual(box.setcursor_calls()[-1], ["setcursor", CURSOR_NAME, "24"])
        time.sleep(1.2)
        self.assertEqual(len(box.setcursor_calls()), 2, "exactly one re-apply")

    def test_no_waiter_when_hyprcursor_is_on(self):
        box = Sandbox()
        self.addCleanup(box.close)
        self.assertNotIn("re-apply", box.run().stdout)


class Cli(unittest.TestCase):

    def setUp(self):
        if not shutil.which("jq"):
            self.skipTest("cursor-accent needs jq")
        self.box = Sandbox()
        self.addCleanup(self.box.close)

    def config(self):
        return json.loads((self.box.home / ".local/state/cursor-accent/config.json").read_text())

    def test_commands_update_the_config_and_apply(self):
        self.box.cli("fixed", "#39ff14")
        self.assertEqual(self.config()["mode"], "fixed")
        self.assertEqual(self.config()["fixed_color"], "#39ff14")
        self.box.cli("shape", "original")
        self.assertEqual(self.config()["shape"], "original")
        self.box.cli("follow")
        self.assertEqual(self.config()["mode"], "theme")
        self.box.cli("default")
        self.assertEqual(self.config()["mode"], "off")
        self.assertEqual(self.box.setcursor_calls()[-1], ["setcursor", "default", "24"])
        self.assertEqual(json.loads(self.box.cli("status").stdout)["mode"], "off")

    def test_bad_input_is_rejected(self):
        for args in (["fixed"], ["shape", "squiggly"], ["nonsense"]):
            self.assertNotEqual(self.box.cli(*args, check=False).returncode, 0, args)


if __name__ == "__main__":
    unittest.main()
