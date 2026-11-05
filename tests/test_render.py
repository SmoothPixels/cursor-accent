"""The two render paths and the bundled Xcursor writer."""
import importlib
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from tests.support import REPO, Sandbox, built, has_gi_cairo

sys.path.insert(0, str(REPO / "src"))
build_theme = importlib.import_module("build_theme")
xcursor = importlib.import_module("xcursor")
sys.path.remove(str(REPO / "src"))

SAMPLES = ["left_ptr.svg", "hand2.svg", "xterm.svg", "wait-01.svg"]


def sample_svgs():
    found = {p.name: p for p in (REPO / "svg").rglob("*.svg")}
    return [found[name] for name in SAMPLES]


class RenderPaths(unittest.TestCase):

    @unittest.skipUnless(has_gi_cairo(), "python-gobject and python-cairo not installed")
    def test_in_process_render_matches_rsvg_convert(self):
        fast = build_theme.in_process_renderer()
        with tempfile.TemporaryDirectory() as tmp:
            slow = build_theme.rsvg_convert_renderer(tmp)
            for path in sample_svgs():
                for size in (24, 30, 36, 48, 72):
                    with self.subTest(svg=path.name, size=size):
                        png_fast, argb = fast(path.read_bytes(), size)
                        png_slow, _ = slow(path.read_bytes(), size)
                        self.assertEqual(png_fast, png_slow)
                        self.assertEqual(argb, build_theme.argb_from_png(png_slow))

    def test_fallback_build_is_identical(self):
        # Without python-gobject/python-cairo the build falls back to
        # rsvg-convert; users must get the same theme either way.
        reference = built("png")
        box = Sandbox()
        self.addCleanup(box.close)
        fake_gi = Path(box.root, "no-gi/gi")
        fake_gi.mkdir(parents=True)
        (fake_gi / "__init__.py").write_text("raise ImportError('gi disabled for this test')\n")
        box.run(env={"PYTHONPATH": str(fake_gi.parent)})
        self.assertEqual(box.shapes(), reference.shapes())
        for shape in reference.shapes():
            self.assertEqual(box.hlc_members(shape), reference.hlc_members(shape), shape)
            a = (box.theme / "cursors" / shape).read_bytes()
            b = (reference.theme / "cursors" / shape).read_bytes()
            self.assertEqual(a, b, shape)


def encode_png(width, height, rgba, filters):
    """A PNG using the given filter type per row, to exercise decode_png."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    stride, bpp, raw, prev = width * 4, 4, b"", bytes(width * 4)
    for y in range(height):
        row = rgba[y * stride:(y + 1) * stride]
        f = filters[y % len(filters)]
        out = bytearray(stride)
        for i in range(stride):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 0:
                pred = 0
            elif f == 1:
                pred = a
            elif f == 2:
                pred = b
            elif f == 3:
                pred = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            out[i] = (row[i] - pred) & 0xFF
        raw += bytes([f]) + bytes(out)
        prev = row
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


class XcursorWriter(unittest.TestCase):

    def test_decode_png_handles_every_filter_type(self):
        w, h = 7, 10
        rgba = bytes((x * 37 + y * 11 + c * 53) & 0xFF for y in range(h) for x in range(w) for c in range(4))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "f.png")
            path.write_bytes(encode_png(w, h, rgba, [0, 1, 2, 3, 4]))
            self.assertEqual(xcursor.decode_png(path), (w, h, rgba))

    def test_premultiply_matches_xcursorgen(self):
        # xcursorgen's multiply_alpha: t = a * c + 0x80; (t + (t >> 8)) >> 8
        for a in (0, 1, 127, 128, 254, 255):
            for c in (0, 1, 100, 200, 255):
                t = a * c + 0x80
                expected = 0 if a == 0 else (c if a == 255 else (t + (t >> 8)) >> 8)
                got = xcursor.rgba_to_argb_premul(bytes([c, c, c, a]))
                self.assertEqual(got, bytes([expected, expected, expected, a]), (a, c))

    def test_written_file_reads_back(self):
        box = Sandbox()
        self.addCleanup(box.close)
        pixels = bytes(range(256)) * 16  # 4096 bytes: a 32x32 ARGB image
        target = Path(box.root, "cursor")
        xcursor.write_xcursor([(32, 32, 32, 3, 4, 70, pixels), (16, 16, 16, 1, 2, 70, pixels[:1024])], target)
        images = box.xcursor(files=[target])["files"][str(target)]
        self.assertEqual([(i["size"], i["width"], i["hotspot"], i["delay"]) for i in images],
                         [(32, 32, [3, 4], 70), (16, 16, [1, 2], 70)])


if __name__ == "__main__":
    unittest.main()
