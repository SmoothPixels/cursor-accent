#!/usr/bin/env python3
"""Asks libhyprcursor for cursor images the way Hyprland asks for them.

Runs in its own process: hyprcursor finds themes through HOME and
XDG_DATA_DIRS, so each theme under test gets its own environment.

Usage: hcprobe.py REQUEST.json RESULT.json

REQUEST: {"theme": "Omarchy-Accent" or null for "first theme found",
          "queries": [{"shapes": [...], "size": 24, "load": true,
                       "chain": false}]}

"load" calls hyprcursor_load_theme_style first, as Hyprland does whenever
cursor:enable_hyprcursor is on. Without it the query sees the state
Omarchy 4.5's startup cursor leaves Hyprland 0.56 in (cursor-accent#3).
"chain" follows Hyprland 0.56's setCursorFromName: the name, the name
with '-' turned into '_', then default / left_ptr / left-ptr.

A NULL surface is reported, never touched: handing one to cairo is the
crash this exists to catch.
"""
import ctypes
import hashlib
import json
import sys


class StyleInfo(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint)]


class ImageData(ctypes.Structure):
    _fields_ = [
        ("surface", ctypes.c_void_p),
        ("size", ctypes.c_int),
        ("delay", ctypes.c_int),
        ("hotspotX", ctypes.c_int),
        ("hotspotY", ctypes.c_int),
    ]


hc = ctypes.CDLL("libhyprcursor.so.0")
hc.hyprcursor_manager_create.restype = ctypes.c_void_p
hc.hyprcursor_manager_create.argtypes = [ctypes.c_char_p]
hc.hyprcursor_manager_valid.restype = ctypes.c_int
hc.hyprcursor_manager_valid.argtypes = [ctypes.c_void_p]
hc.hyprcursor_load_theme_style.restype = ctypes.c_int
hc.hyprcursor_load_theme_style.argtypes = [ctypes.c_void_p, StyleInfo]
hc.hyprcursor_get_cursor_image_data.restype = ctypes.POINTER(ctypes.POINTER(ImageData))
hc.hyprcursor_get_cursor_image_data.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, StyleInfo, ctypes.POINTER(ctypes.c_int)]
hc.hyprcursor_cursor_image_data_free.restype = None
hc.hyprcursor_cursor_image_data_free.argtypes = [
    ctypes.POINTER(ctypes.POINTER(ImageData)), ctypes.c_int]

cairo = ctypes.CDLL("libcairo.so.2")
for name in ("cairo_image_surface_get_width", "cairo_image_surface_get_height",
             "cairo_image_surface_get_stride", "cairo_image_surface_get_format",
             "cairo_surface_status"):
    getattr(cairo, name).restype = ctypes.c_int
    getattr(cairo, name).argtypes = [ctypes.c_void_p]
cairo.cairo_image_surface_get_data.restype = ctypes.c_void_p
cairo.cairo_image_surface_get_data.argtypes = [ctypes.c_void_p]
cairo.cairo_surface_flush.restype = None
cairo.cairo_surface_flush.argtypes = [ctypes.c_void_p]

CAIRO_FORMAT_ARGB32 = 0
HYPRLAND_FALLBACKS = ("default", "left_ptr", "left-ptr")


def describe(image):
    out = {"null": not image.surface, "size": image.size, "delay": image.delay,
           "hotspot": [image.hotspotX, image.hotspotY]}
    if not image.surface:
        return out
    s = image.surface
    cairo.cairo_surface_flush(s)
    w, h = cairo.cairo_image_surface_get_width(s), cairo.cairo_image_surface_get_height(s)
    stride = cairo.cairo_image_surface_get_stride(s)
    out.update(status=cairo.cairo_surface_status(s), width=w, height=h,
               format=cairo.cairo_image_surface_get_format(s))
    data = cairo.cairo_image_surface_get_data(s)
    if data and out["status"] == 0 and out["format"] == CAIRO_FORMAT_ARGB32:
        rows = hashlib.sha256()
        for y in range(h):
            rows.update(ctypes.string_at(data + y * stride, w * 4))
        out["sha256"] = rows.hexdigest()
        # Anything drawn at all? A blank image would also pass the checks above.
        raw = ctypes.string_at(data, stride * h)
        out["opaque"] = any(raw[y * stride + x * 4 + 3] for y in range(h) for x in range(w))
    return out


def images_for(manager, shape, size):
    count = ctypes.c_int(0)
    arr = hc.hyprcursor_get_cursor_image_data(manager, shape.encode(), StyleInfo(size), ctypes.byref(count))
    try:
        return [describe(arr[i].contents) for i in range(count.value)]
    finally:
        if arr:
            hc.hyprcursor_cursor_image_data_free(arr, count.value)


def lookup(manager, shape, size, chain):
    if not chain:
        return shape, images_for(manager, shape, size)
    for candidate in (shape, shape.replace("-", "_")) + HYPRLAND_FALLBACKS:
        images = images_for(manager, candidate, size)
        if images:
            return candidate, images
    return None, []


def main(request_path, result_path):
    request = json.load(open(request_path))
    theme = request.get("theme")
    manager = hc.hyprcursor_manager_create(theme.encode() if theme else None)
    result = {"valid": bool(manager and hc.hyprcursor_manager_valid(manager)), "queries": []}
    loaded = set()
    if result["valid"]:
        for query in request["queries"]:
            size = query["size"]
            if query.get("load") and size not in loaded:
                hc.hyprcursor_load_theme_style(manager, StyleInfo(size))
                loaded.add(size)
            shapes = {}
            for shape in query["shapes"]:
                resolved, images = lookup(manager, shape, size, query.get("chain", False))
                shapes[shape] = {"resolved": resolved, "images": images}
            result["queries"].append(shapes)
    json.dump(result, open(result_path, "w"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
