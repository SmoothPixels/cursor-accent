#!/usr/bin/env python3
"""Builds one recolored Bibata theme as hyprcursor plus Xcursor, quickly.

Reads the same config the vendored cursor_utils.py does (render.json,
build.toml, svg/), and must run with the same cwd layout, but renders every
(source SVG, size) pair exactly once and writes both formats from that one
render:

  - In-process through librsvg and cairo (python-gobject + python-cairo,
    both in Omarchy's base install): about 0.3 ms an image, pixel for pixel
    what `rsvg-convert` produces.
  - Otherwise through `rsvg-convert`, one process per image, all of them in
    a single thread pool.

hyprcursor shapes are either PNGs at --hypr-sizes, with resize_algorithm
none (hyprcursor 0.1.13 crops PNGs it scales down), or the recolored SVGs
themselves when --hypr-sizes is not given.

Usage: build_theme.py --theme NAME --out-dir DIR --x11-sizes 24,36,48
                      [--hypr-sizes 24,30,...]
"""
import argparse
import io
import logging
import os
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import xcursor
from cursor_utils import CursorBuilder, HyprManifest, XManifest

XCURSOR_DEFAULT_DELAY = 50  # what xcursorgen uses when a line has no delay


def in_process_renderer():
    """render(svg_bytes, size) -> (png_bytes, argb_bytes), or None."""
    try:
        import gi
        gi.require_version("Rsvg", "2.0")
        from gi.repository import Rsvg
        import cairo
    except (ImportError, ValueError):
        return None

    def render(svg, size):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        viewport = Rsvg.Rectangle()
        viewport.x = viewport.y = 0
        viewport.width = viewport.height = size
        Rsvg.Handle.new_from_data(svg).render_document(cairo.Context(surface), viewport)
        surface.flush()
        png = io.BytesIO()
        surface.write_to_png(png)
        # cairo's ARGB32 is premultiplied, native-endian, stride == size * 4:
        # exactly the pixel layout an Xcursor image chunk holds.
        return png.getvalue(), bytes(surface.get_data())

    return render


def rsvg_convert_renderer(tmpdir):
    """Fallback: one `rsvg-convert` per image. argb is decoded on demand."""
    counter = iter(range(1 << 30))

    def render(svg, size):
        n = next(counter)
        src, dst = Path(tmpdir, f"{n}.svg"), Path(tmpdir, f"{n}.png")
        src.write_bytes(svg)
        subprocess.run(
            ["rsvg-convert", "-a", "-w", str(size), "-h", str(size), "-f", "png",
             "-o", str(dst), str(src)],
            check=True,
        )
        return dst.read_bytes(), None

    return render


def argb_from_png(png):
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png)
        f.flush()
        _, _, rgba = xcursor.decode_png(Path(f.name))
    return xcursor.rgba_to_argb_premul(rgba)


def recolor(src, color_maps):
    text = Path(src).read_text()
    for cmap in color_maps:
        text = text.replace(cmap["match"], cmap["replace"])
    return text.encode()


def frames_for(cursor, render_dir, delay):
    """[(source svg, delay)] for one cursor, in frame order.

    Sorted by file name: cursor_utils.py takes frames in directory listing
    order, which is only name order on some filesystems.
    """
    cursor.scan_size_and_render(render_dir, [1], delay, "png")
    frames = [(src, (item + (0,))[2]) for (src, _, _), item in zip(cursor.renders, cursor.sizes)]
    return sorted(frames, key=lambda frame: Path(frame[0]).name)


def build(theme, out_dir, hypr_sizes, x11_sizes):
    builder = CursorBuilder()
    builder.outDir = out_dir
    builder.renderList = [theme]
    render = next(builder.get_renders())

    # get_cursors() fills in names, hotspots, aliases and the frame delay
    # from build.toml; rescan each cursor at our own sizes afterwards.
    cursors = []
    for cursor in builder.get_cursors(render, "x11"):
        delay = max(((item + (0,))[2] for item in cursor.sizes), default=0)
        cursors.append((cursor, delay))

    sizes = sorted(set(hypr_sizes) | set(x11_sizes))
    frames = {}  # cursor name -> [(src, delay)]
    jobs = {}  # (src, size) -> None, filled with (png, argb)
    for cursor, delay in cursors:
        frames[cursor.name] = frames_for(cursor, render.dir, delay)
        for src, _ in frames[cursor.name]:
            for size in sizes:
                jobs[src, size] = None

    svgs = {src: recolor(src, render.color_maps) for frame in frames.values() for src, _ in frame}

    with tempfile.TemporaryDirectory(prefix="cursor-accent-") as tmpdir:
        renderer = in_process_renderer()
        if renderer is None:
            logging.info("python-gobject/python-cairo missing, using rsvg-convert")
            renderer = rsvg_convert_renderer(tmpdir)
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            keys = list(jobs)
            for key, result in zip(keys, pool.map(lambda k: renderer(svgs[k[0]], k[1]), keys)):
                jobs[key] = result

    theme_dir = Path(out_dir, theme)
    hypr = HyprManifest(name=render.name, description=render.desc)
    hypr.write(str(theme_dir))
    xman = XManifest(name=render.name, description=render.desc)
    xman.write(str(theme_dir))
    hypr_dir, x11_dir = theme_dir / hypr.directory, theme_dir / xman.directory

    for cursor, _ in cursors:
        write_hlc(hypr_dir / f"{cursor.name}.hlc", cursor, frames[cursor.name], svgs, jobs, hypr_sizes)
        write_xcursor(x11_dir, cursor, frames[cursor.name], jobs, x11_sizes)


def write_hlc(path, cursor, frames, svgs, jobs, hypr_sizes):
    """One .hlc, named and laid out the way cursor_utils.py --hypr does it."""
    files = []
    cursor.sizes = []
    # Size 0 means "SVG, any size" to hyprcursor.
    for size in hypr_sizes or [0]:
        for seq, (src, delay) in enumerate(frames):
            name = f"{cursor.name}_{size}" if size else cursor.name
            if len(frames) > 1:
                name += f"_{seq:02}"
            name += ".png" if size else ".svg"
            cursor.sizes.append((size, name, delay) if delay else (size, name))
            files.append((name, jobs[src, size][0] if size else svgs[src]))
    cursor.resize = "none"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("meta.hl", cursor.dumps(), compress_type=zipfile.ZIP_DEFLATED)
        for name, data in files:
            # PNGs are already compressed; SVG text is not.
            kind = zipfile.ZIP_STORED if name.endswith(".png") else zipfile.ZIP_DEFLATED
            zf.writestr(name, data, compress_type=kind)


def write_xcursor(x11_dir, cursor, frames, jobs, x11_sizes):
    images = []
    for size in x11_sizes:
        for src, frame_delay in frames:
            png, argb = jobs[src, size]
            if argb is None:
                argb = argb_from_png(png)
            images.append((size, size, size, int(size * cursor.hotX), int(size * cursor.hotY),
                           frame_delay or XCURSOR_DEFAULT_DELAY, argb))
    xcursor.write_xcursor(images, x11_dir / cursor.name)
    for alias in cursor.overrides:
        link = x11_dir / alias
        if not link.exists() and not link.is_symlink():
            link.symlink_to(cursor.name)


def main(argv):
    parser = argparse.ArgumentParser(prog="build_theme")
    parser.add_argument("--theme", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--x11-sizes", required=True)
    parser.add_argument("--hypr-sizes", default="", help="PNG sizes; SVG shapes if empty")
    args = parser.parse_args(argv)

    def sizes(text):
        return [int(x) for x in text.split(",") if x.strip()]

    # cursor_utils logs to the root logger, a line per symlink at info level.
    logging.basicConfig(level=logging.ERROR, format="build_theme: %(message)s")
    if Path(args.out_dir).exists():
        sys.exit(f"build_theme: output dir {args.out_dir} already exists")
    build(args.theme, args.out_dir, sizes(args.hypr_sizes), sizes(args.x11_sizes))


if __name__ == "__main__":
    main(sys.argv[1:])
