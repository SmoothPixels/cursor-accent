#!/usr/bin/env python3
"""Loads Xcursor images through libXcursor.

Runs in its own process: libXcursor reads XCURSOR_PATH once and caches it,
so theme lookups by name need a fresh environment per theme.

Usage: xcprobe.py REQUEST.json RESULT.json

REQUEST: {"files": [paths], "lookups": [{"theme": "Omarchy-Accent",
          "shape": "left_ptr", "size": 24}]}
"""
import ctypes
import hashlib
import json
import sys


class Image(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint), ("size", ctypes.c_uint),
        ("width", ctypes.c_uint), ("height", ctypes.c_uint),
        ("xhot", ctypes.c_uint), ("yhot", ctypes.c_uint),
        ("delay", ctypes.c_uint), ("pixels", ctypes.c_void_p),
    ]


class Images(ctypes.Structure):
    _fields_ = [("nimage", ctypes.c_int), ("images", ctypes.POINTER(ctypes.POINTER(Image))),
                ("name", ctypes.c_char_p)]


xc = ctypes.CDLL("libXcursor.so.1")
xc.XcursorFilenameLoadAllImages.restype = ctypes.POINTER(Images)
xc.XcursorFilenameLoadAllImages.argtypes = [ctypes.c_char_p]
xc.XcursorLibraryLoadImages.restype = ctypes.POINTER(Images)
xc.XcursorLibraryLoadImages.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
xc.XcursorImagesDestroy.restype = None
xc.XcursorImagesDestroy.argtypes = [ctypes.POINTER(Images)]


def describe(ptr):
    if not ptr:
        return None
    images = []
    for i in range(ptr.contents.nimage):
        im = ptr.contents.images[i].contents
        pixels = ctypes.string_at(im.pixels, im.width * im.height * 4)
        images.append({"size": im.size, "width": im.width, "height": im.height,
                       "hotspot": [im.xhot, im.yhot], "delay": im.delay,
                       "sha256": hashlib.sha256(pixels).hexdigest()})
    xc.XcursorImagesDestroy(ptr)
    return images


def main(request_path, result_path):
    request = json.load(open(request_path))
    result = {
        "files": {f: describe(xc.XcursorFilenameLoadAllImages(f.encode()))
                  for f in request.get("files", [])},
        "lookups": [describe(xc.XcursorLibraryLoadImages(q["shape"].encode(), q["theme"].encode(), q["size"]))
                    for q in request.get("lookups", [])],
    }
    json.dump(result, open(result_path, "w"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
