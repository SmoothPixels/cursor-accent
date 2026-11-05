"""The installed theme's Xcursor half: Hyprland's fallback and XWayland."""
import unittest

from tests.support import CURSOR_NAME, CURSOR_SHAPE_V1, LEGACY_NAMES, built

X11_SIZES = [24, 36, 48]  # cursor size 24 at 1x, 1.5x, 2x
FRAMES = {"wait": 54, "left_ptr_watch": 54}


class XcursorFiles(unittest.TestCase):

    def test_every_cursor_file_loads_with_all_sizes(self):
        for kind in ("png", "svg"):
            box = built(kind)
            files = sorted(p for p in (box.theme / "cursors").iterdir() if not p.is_symlink())
            self.assertEqual(sorted(f.name for f in files), box.shapes(), kind)
            loaded = box.xcursor(files=files)["files"]
            for path in files:
                with self.subTest(kind=kind, cursor=path.name):
                    images = loaded[str(path)]
                    self.assertIsNotNone(images, "libXcursor could not read it")
                    frames = FRAMES.get(path.name, 1)
                    self.assertEqual(len(images), frames * len(X11_SIZES))
                    self.assertEqual(sorted({i["size"] for i in images}), X11_SIZES)
                    for image in images:
                        self.assertEqual((image["width"], image["height"]), (image["size"],) * 2)
                        x, y = image["hotspot"]
                        self.assertTrue(0 <= x < image["width"] and 0 <= y < image["height"])
                        self.assertEqual(image["delay"], 40 if frames > 1 else 50)

    def test_aliases_all_point_at_real_cursors(self):
        box = built("png")
        for link in (box.theme / "cursors").iterdir():
            if link.is_symlink():
                self.assertTrue(link.exists(), f"broken alias {link.name}")
                self.assertNotIn("/", str(link.readlink()), f"{link.name} should be relative")

    def test_xcursor_pixels_match_the_hyprcursor_images(self):
        # Same render, two formats: an Xcursor fallback that looks different
        # from the hyprcursor cursor would be a bug.
        box = built("png")
        shapes = ["left_ptr", "hand2", "text", "wait"]
        hyprcursor = box.probe([{"shapes": shapes, "size": s, "load": True} for s in X11_SIZES])
        files = [box.theme / "cursors" / s for s in shapes]
        xcursor = box.xcursor(files=files)["files"]
        for shape, path in zip(shapes, files):
            for size, query in zip(X11_SIZES, hyprcursor["queries"]):
                expected = [i["sha256"] for i in query[shape]["images"]]
                actual = [i["sha256"] for i in xcursor[str(path)] if i["size"] == size]
                self.assertEqual(actual, expected, (shape, size))


class XcursorLookup(unittest.TestCase):

    def test_names_resolve_through_libxcursor_by_theme(self):
        box = built("png")
        names = CURSOR_SHAPE_V1 + LEGACY_NAMES
        result = box.xcursor(lookups=[{"theme": CURSOR_NAME, "shape": n, "size": 24} for n in names])
        for name, images in zip(names, result["lookups"]):
            with self.subTest(name=name):
                self.assertIsNotNone(images, "not found in the theme")
                self.assertEqual(images[0]["size"], 24)

    def test_index_theme(self):
        text = (built("png").theme / "index.theme").read_text()
        self.assertIn(f"Name={CURSOR_NAME}", text)
        self.assertIn("Inherits=Adwaita", text)


if __name__ == "__main__":
    unittest.main()
