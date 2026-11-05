"""The installed theme as Hyprland's hyprcursor path sees it."""
import hashlib
import importlib
import json
import sys
import tempfile
import tomllib
import unittest

from tests.support import CURSOR_SHAPE_V1, LEGACY_NAMES, REPO, built

sys.path.insert(0, str(REPO / "src"))
build_theme = importlib.import_module("build_theme")
sys.path.remove(str(REPO / "src"))

PNG_SIZES = [24, 30, 36, 42, 48, 60, 72]  # cursor size 24 at 1x .. 3x
FRAMES = {"wait": 54, "left_ptr_watch": 54}


def all_images(result):
    for query in result["queries"]:
        for shape, entry in query.items():
            for image in entry["images"]:
                yield shape, image


class StartupState(unittest.TestCase):
    """Omarchy 4.5 turns hyprcursor off while Hyprland creates its cursor
    manager and back on without a theme reload, so Hyprland 0.56 asks for
    shapes at size 0 with no style loaded. An image with a NULL surface
    there is handed to cairo and aborts Hyprland (cursor-accent#3)."""

    def startup(self, box, theme):
        names = box.shapes() + sorted(box.overrides()) + CURSOR_SHAPE_V1 + LEGACY_NAMES
        return box.probe([{"shapes": names, "size": 0, "chain": True}], theme=theme)

    def test_png_theme_never_returns_a_null_surface(self):
        box = built("png")
        for theme in ("Omarchy-Accent", None):  # by name, and as the first theme found
            with self.subTest(theme=theme or "first found"):
                result = self.startup(box, theme)
                self.assertTrue(result["valid"])
                nulls = sorted({shape for shape, image in all_images(result) if image["null"]})
                self.assertEqual(nulls, [], "these shapes would crash Hyprland 0.56 at login")
                broken = sorted({shape for shape, image in all_images(result)
                                 if image.get("status") != 0 or not image.get("opaque")})
                self.assertEqual(broken, [])

    def test_detector_catches_the_svg_theme(self):
        # The SVG theme is what 1.1.0 installed. If this stops finding NULL
        # surfaces, the test above proves nothing.
        result = self.startup(built("svg"), "Omarchy-Accent")
        self.assertTrue(any(image["null"] for _, image in all_images(result)))


class LoadedSizes(unittest.TestCase):
    """After `hyprctl setcursor`, Hyprland loads a style at
    round(cursor size * highest monitor scale) and draws what it gets."""

    def test_png_shapes_are_rendered_at_every_scale_size(self):
        box = built("png")
        for shape in box.shapes():
            self.assertEqual(box.defined_sizes(shape), PNG_SIZES, shape)
            self.assertIn("resize_algorithm = none", box.meta(shape), shape)

    def test_each_scale_size_is_returned_exactly(self):
        box = built("png")
        shapes = box.shapes()
        result = box.probe([{"shapes": shapes, "size": s, "load": True} for s in PNG_SIZES])
        for size, query in zip(PNG_SIZES, result["queries"]):
            for shape in shapes:
                images = query[shape]["images"]
                self.assertEqual(len(images), FRAMES.get(shape, 1), (shape, size))
                for image in images:
                    self.assertFalse(image["null"], (shape, size))
                    self.assertEqual((image["width"], image["height"]), (size, size), (shape, size))
                    self.assertTrue(image["opaque"], (shape, size))

    def test_in_between_sizes_get_a_whole_rendered_image(self):
        # hyprcursor 0.1.13 crops PNGs it scales down; resize none must
        # hand back one of the rendered sizes untouched instead.
        box = built("png")
        shapes = ["left_ptr", "hand2", "text", "wait"]
        between = [26, 33, 40, 54, 66, 90]
        exact = box.probe([{"shapes": shapes, "size": s, "load": True} for s in PNG_SIZES])
        exact_hashes = {(shape, img["width"], i): img["sha256"]
                        for q in exact["queries"] for shape in shapes
                        for i, img in enumerate(q[shape]["images"])}
        result = box.probe([{"shapes": shapes, "size": s, "load": True} for s in between])
        for size, query in zip(between, result["queries"]):
            for shape in shapes:
                for i, image in enumerate(query[shape]["images"]):
                    self.assertIn(image["width"], PNG_SIZES, (shape, size))
                    self.assertEqual(image["sha256"], exact_hashes[shape, image["width"], i], (shape, size))

    def test_png_pixels_match_hyprcursors_own_svg_raster(self):
        # The whole point of rendering PNGs ourselves: no visible change
        # from the SVG theme at the sizes Hyprland asks for.
        png, svg = built("png"), built("svg")
        shapes = png.shapes()
        self.assertEqual(shapes, svg.shapes())
        queries = [{"shapes": shapes, "size": s, "load": True} for s in PNG_SIZES]
        a, b = png.probe(queries), svg.probe(queries)
        for size, qa, qb in zip(PNG_SIZES, a["queries"], b["queries"]):
            for shape in shapes:
                ia, ib = qa[shape]["images"], qb[shape]["images"]
                self.assertEqual(len(ia), len(ib), (shape, size))
                for x, y in zip(ia, ib):
                    self.assertEqual(x["sha256"], y["sha256"], (shape, size))
                    self.assertEqual(x["hotspot"], y["hotspot"], (shape, size))
                    self.assertEqual(x["delay"], y["delay"], (shape, size))

    def test_animations_keep_their_frames_and_timing(self):
        box = built("png")
        result = box.probe([{"shapes": list(FRAMES), "size": 24, "load": True}])
        for shape, count in FRAMES.items():
            images = result["queries"][0][shape]["images"]
            self.assertEqual(len(images), count, shape)
            self.assertEqual({image["delay"] for image in images}, {40}, shape)
            self.assertEqual(len({image["sha256"] for image in images}), count, f"{shape}: repeated frames")

    def test_animation_frames_play_in_file_order(self):
        # Rendered straight from the source frames, independent of the
        # builder, so a frame-order bug cannot hide behind a comparison of
        # two builds made by the same code.
        box = built("png")
        render = json.loads((box.home / ".local/state/cursor-accent/render.json").read_text())
        color_maps = render["Bibata-Modern-Classic"]["colors"]
        result = box.probe([{"shapes": list(FRAMES), "size": 24, "load": True}])
        with tempfile.TemporaryDirectory() as tmp:
            renderer = build_theme.in_process_renderer() or build_theme.rsvg_convert_renderer(tmp)
            groups = tomllib.loads((REPO / "svg/symlink.toml").read_text())["modern"]
            for shape, count in FRAMES.items():
                sources = sorted(p for g in groups for p in (REPO / "svg" / g).rglob(f"{shape}-[0-9][0-9].svg"))
                self.assertEqual(len(sources), count, shape)
                images = result["queries"][0][shape]["images"]
                for index in (0, 1, count - 1):
                    png, argb = renderer(build_theme.recolor(sources[index], color_maps), 24)
                    argb = argb or build_theme.argb_from_png(png)
                    self.assertEqual(images[index]["sha256"], hashlib.sha256(argb).hexdigest(),
                                     f"{shape} frame {index} is not {sources[index].name}")

    def test_hotspots_lie_inside_the_image(self):
        box = built("png")
        result = box.probe([{"shapes": box.shapes(), "size": s, "load": True} for s in (24, 48)])
        for shape, image in all_images(result):
            x, y = image["hotspot"]
            self.assertTrue(0 <= x < image["width"] and 0 <= y < image["height"], shape)


class ShapeNames(unittest.TestCase):

    def test_every_cursor_shape_v1_name_resolves_without_falling_back(self):
        for kind in ("png", "svg"):
            box = built(kind)
            result = box.probe([{"shapes": CURSOR_SHAPE_V1 + LEGACY_NAMES, "size": 24,
                                 "load": True, "chain": True}])
            for name, entry in result["queries"][0].items():
                with self.subTest(kind=kind, name=name):
                    self.assertIn(entry["resolved"], (name, name.replace("-", "_")),
                                  "Hyprland would show the default arrow instead")

    def test_manifest_names_the_theme_and_its_folder(self):
        for kind in ("png", "svg"):
            manifest = (built(kind).theme / "manifest.hl").read_text()
            self.assertIn("cursors_directory = hyprcursors", manifest)


class SvgOnNewHyprland(unittest.TestCase):

    def test_svg_build_ships_svg_shapes(self):
        box = built("svg")
        for shape in box.shapes():
            members = box.hlc_members(shape)
            self.assertTrue(all(n == "meta.hl" or n.endswith(".svg") for n in members), shape)
            self.assertEqual(box.defined_sizes(shape), [0], shape)

    def test_svg_shapes_carry_the_theme_colors(self):
        svg = built("svg").hlc_members("left_ptr")["left_ptr.svg"].decode().lower()
        self.assertIn("#7d82d9", svg)


if __name__ == "__main__":
    unittest.main()
