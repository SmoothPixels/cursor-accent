#!/usr/bin/env python3
"""Generate the extra cursor styles beyond Bibata's own modern/original.

For each style in STYLES, writes svg/groups/<style>/ and
config/build.<style>.toml (build.toml with hotspots moved to match the new
shapes; recolor.py picks it up automatically), plus a pointer preview at
assets/previews/<style>.svg for the settings window.

Two kinds of style:
  full sets    every cursor drawn here around one arrow shape
               (macos, macos-tailless, dart, retro)
  pointer-only a full set's group plus a small group of their own that
               overrides just the plain pointers (crosshair, dot); composed
               in svg/symlink.toml, where later groups win

Colors follow Bibata's keys so recolor.py can theme them:
  #00FF00 body, #0000FF outline (accent), #FF0000 watch.
Shapes are drawn "layered": every part is first painted fat in the outline
color, then painted again at true size in the body color, so overlapping
parts merge into one silhouette with a uniform outline around it.

Usage: tools/gen-macos-cursors.py   (run from anywhere; paths are relative to the plugin)
"""
import math
import re
import shutil
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
GROUPS = PLUGIN / "svg/groups"
PREVIEWS = PLUGIN / "assets/previews"

BODY, LINE = "#00FF00", "#0000FF"
OUT = 16  # outline thickness added around each shape (8 each side)
WATCH_FRAMES = 54

# Arrows in unit coords, tip at (0,0), y down: left edge, notch, (tail,) wing.
ARROW_TAILLESS = [(0, 0), (0, 15.4), (4.3, 11.4), (10.9, 11.1)]
ARROW_MACOS = [(x * 0.9, y * 0.9) for x, y in
               [(0, 0), (0, 16.2), (3.9, 12.6), (6.5, 18.4), (9.2, 17.2), (6.7, 11.6), (11.5, 11.5)]]
ARROW_DART = [(0, 0), (0, 17.6), (3.3, 13.9), (8.6, 14.6)]
# 1-bit pixel arrow, one character per pixel ("X" filled).
RETRO_ROWS = [
    "X", "XX", "XXX", "XXXX", "XXXXX", "XXXXXX", "XXXXXXX", "XXXXXXXX",
    "XXXXXXXXX", "XXXXXXXXXX", "XXXXXXXXXXX", "XXXXXXX", "XXX.XXX",
    "XX...XXX", "X....XXX", "......XXX", "......XXX", ".......X",
]
TIP = (59, 22)  # body tip; the outline reaches ~(55,17), which is the hotspot
CENTER = (128, 128)

hotspots = {}  # cursor name -> (x, y) overrides for the current style's build toml
arrow = ARROW_TAILLESS  # the current style's arrow: a polygon, or "retro"


# ---------------------------------------------------------------- primitives

def svg(*parts, defs=""):
    body = "\n".join(parts)
    defs = f"<defs>\n{defs}\n</defs>\n" if defs else ""
    return (f'<svg width="256" height="256" viewBox="0 0 256 256" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">\n{defs}{body}\n</svg>\n')


def poly_d(pts):
    return "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + " Z"


def layered(shapes, lines=(), extra_out=OUT, join="round"):
    """shapes: list of (tag, attrs) filled solids; lines: list of (d, width, cap)."""
    outline, body = [], []
    for tag, attrs in shapes:
        outline.append(f'<{tag} {attrs} fill="{LINE}" stroke="{LINE}" stroke-width="{extra_out}" stroke-linejoin="{join}"/>')
        body.append(f'<{tag} {attrs} fill="{BODY}"/>')
    for d, w, cap in lines:
        outline.append(f'<path d="{d}" stroke="{LINE}" stroke-width="{w + extra_out}" stroke-linecap="{cap}" stroke-linejoin="round"/>')
        body.append(f'<path d="{d}" stroke="{BODY}" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="round"/>')
    return "<g>\n" + "\n".join(outline + body) + "\n</g>"


def P(pts):
    return ("path", f'd="{poly_d(pts)}"')


def rrect(x, y, w, h, r, rot=0, cx=None, cy=None):
    t = f' transform="rotate({rot} {cx} {cy})"' if rot else ""
    return ("rect", f'x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"{t}')


def xform(pts, angle=0.0, origin=(0, 0), scale=1.0, offset=(0, 0), mirror=False):
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for x, y in pts:
        x, y = (-x if mirror else x) * scale, y * scale
        x, y = x * ca - y * sa, x * sa + y * ca
        out.append((x + origin[0] + offset[0], y + origin[1] + offset[1]))
    return out


def arrow_g(tip=TIP, scale=11.5, mirror=False, angle=0.0):
    """The current style's arrow, outlined, as one layered group."""
    if arrow == "retro":
        px = scale * 0.92
        cells = [[(m.start(), r), (m.end(), r), (m.end(), r + 1.08), (m.start(), r + 1.08)]
                 for r, row in enumerate(RETRO_ROWS) for m in re.finditer("X+", row)]
        return layered([P(xform(cell, angle=angle, origin=tip, scale=px, mirror=mirror)) for cell in cells],
                       join="miter")
    return layered([P(xform(arrow, angle=angle, origin=tip, scale=scale, mirror=mirror))])


# ---------------------------------------------------------------- pointer + badges

def badge(fill, glyph, cx=180, cy=188, r=40, ring=LINE):
    return (f'<circle cx="{cx}" cy="{cy}" r="{r + OUT // 2}" fill="{ring}"/>\n'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}"/>\n{glyph}')


def g_plus(cx=180, cy=188):
    return (f'<path d="M{cx} {cy - 22} V{cy + 22} M{cx - 22} {cy} H{cx + 22}" '
            f'stroke="white" stroke-width="11" stroke-linecap="round"/>')


def g_forbid(cx=180, cy=188):
    return (f'<circle cx="{cx}" cy="{cy}" r="22" stroke="white" stroke-width="9"/>\n'
            f'<path d="M{cx - 15} {cy + 15} L{cx + 15} {cy - 15}" stroke="white" stroke-width="9"/>')


def g_question(cx=180, cy=188):
    return (f'<path d="M{cx - 13} {cy - 10} C{cx - 13} {cy - 30} {cx + 14} {cy - 30} {cx + 14} {cy - 12} '
            f'C{cx + 14} {cy - 1} {cx} {cy} {cx} {cy + 9}" stroke="white" stroke-width="10" '
            f'stroke-linecap="round" fill="none"/>\n'
            f'<circle cx="{cx}" cy="{cy + 23}" r="6" fill="white"/>')


def g_alias(cx=180, cy=188):
    # macOS alias badge: a curved arrow sweeping up and to the right
    return (f'<path d="M{cx - 18} {cy + 18} C{cx - 18} {cy - 4} {cx - 6} {cy - 10} {cx + 8} {cy - 10}" '
            f'stroke="white" stroke-width="9" stroke-linecap="round" fill="none"/>\n'
            f'<path d="M{cx + 2} {cy - 26} L{cx + 22} {cy - 10} L{cx + 2} {cy + 6} Z" fill="white" '
            f'stroke="white" stroke-width="3" stroke-linejoin="round"/>')


def g_menu(cx=180, cy=188):
    return (f'<rect x="{cx - 20}" y="{cy - 20}" width="40" height="40" rx="6" fill="white"/>\n'
            + "\n".join(f'<path d="M{cx - 12} {cy + dy} H{cx + 12}" stroke="#555555" stroke-width="5" '
                        f'stroke-linecap="round"/>' for dy in (-9, 0, 9)))


def bibata_glyph(name, cx=180, cy=188, r=40):
    """Reuse the white glyph from Bibata's badge, rescaled into our badge."""
    text = (GROUPS / "original" / f"{name}.svg").read_text()
    m = re.search(r'<circle cx="118" cy="162" r="70.5" fill="(#[0-9A-Fa-f]+)"[^>]*/>\n(.*?)\n</g>', text, re.S)
    fill, glyph = m[1], m[2]
    s = r / 70.5
    return fill, f'<g transform="translate({cx} {cy}) scale({s:.4f}) translate(-118 -162)">\n{glyph}\n</g>'


def pointer(scale=11.5):
    return arrow_g(scale=scale)


def badged(fill, glyph):
    return svg(pointer(10.5), badge(fill, glyph))


def beachball(cx, cy, r, angle, uid):
    colors = ["#0A84FF", "#32D74B", "#FFD60A", "#FF9F0A", "#FF453A", "#BF5AF2", "#5E5CE6", "#64D2FF"]
    n = len(colors)
    wedges = []
    for i, c in enumerate(colors):
        a0 = math.radians(angle + i * 360 / n)
        a1 = math.radians(angle + (i + 1) * 360 / n)
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        # swirl: bend each edge with a control point rotated ahead of it
        k0 = (cx + 0.55 * r * math.cos(a0 - 0.9), cy + 0.55 * r * math.sin(a0 - 0.9))
        k1 = (cx + 0.55 * r * math.cos(a1 - 0.9), cy + 0.55 * r * math.sin(a1 - 0.9))
        wedges.append(
            f'<path d="M{cx} {cy} Q{k0[0]:.2f} {k0[1]:.2f} {p0[0]:.2f} {p0[1]:.2f} '
            f'A{r} {r} 0 0 1 {p1[0]:.2f} {p1[1]:.2f} Q{k1[0]:.2f} {k1[1]:.2f} {cx} {cy} Z" fill="{c}"/>')
    defs = (f'<radialGradient id="gloss{uid}" cx="{cx - r * 0.3}" cy="{cy - r * 0.35}" r="{r * 1.3}" '
            f'gradientUnits="userSpaceOnUse">\n<stop offset="0" stop-color="white" stop-opacity="0.75"/>\n'
            f'<stop offset="0.45" stop-color="white" stop-opacity="0.1"/>\n'
            f'<stop offset="1" stop-color="black" stop-opacity="0.25"/>\n</radialGradient>')
    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r + OUT // 2}" fill="{LINE}"/>', *wedges,
             f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#gloss{uid})"/>']
    return "\n".join(parts), defs


# ---------------------------------------------------------------- arrows / resize

def double_arrow(angle, L=78, head=40, hw=32, sw=9, c=(128, 128)):
    pts = [(-L, 0), (-L + head, -hw), (-L + head, -sw), (L - head, -sw), (L - head, -hw),
           (L, 0), (L - head, hw), (L - head, sw), (-L + head, sw), (-L + head, hw)]
    return P(xform(pts, angle=angle, origin=c))


def single_arrow(angle, L=78, head=44, hw=34, sw=10, c=(128, 128)):
    """Points along +x by default, with a bar at the tip (macOS resize-limit style)."""
    pts = [(-L, -sw), (L - head, -sw), (L - head, -hw), (L, 0), (L - head, hw), (L - head, sw), (-L, sw)]
    bar = [(L + 10, -42), (L + 24, -42), (L + 24, 42), (L + 10, 42)]
    return [P(xform(pts, angle=angle, origin=c, offset=_back(angle, 10))),
            P(xform(bar, angle=angle, origin=c, offset=_back(angle, 10)))]


def _back(angle, d):
    a = math.radians(angle)
    return (-d * math.cos(a), -d * math.sin(a))


# ---------------------------------------------------------------- hands

def finger_seps(xs, y0, y1):
    return "\n".join(f'<path d="M{x} {y0} V{y1}" stroke="{LINE}" stroke-width="6" stroke-linecap="round"/>'
                     for x in xs)


def pointing_hand():
    # index finger tip sits on build.toml's hand2 hotspot (114, 18)
    shapes = [
        rrect(100, 22, 30, 124, 15),            # index
        rrect(129, 90, 28, 66, 14),             # middle (curled)
        rrect(156, 100, 26, 62, 13),            # ring
        rrect(181, 112, 24, 54, 12),            # pinky
        rrect(98, 126, 107, 92, 32),            # palm
        rrect(66, 120, 30, 76, 15, -42, 81, 158),  # thumb
        rrect(112, 196, 82, 40, 10),            # wrist
    ]
    seps = finger_seps([129, 156, 181], 104, 140)
    return svg(layered(shapes), seps)


def open_hand():
    shapes = [
        rrect(92, 56, 28, 110, 14, -10, 106, 160),   # index
        rrect(122, 34, 28, 126, 14),                 # middle
        rrect(152, 44, 27, 118, 13.5, 6, 165, 160),   # ring
        rrect(180, 72, 24, 96, 12, 14, 192, 160),     # pinky
        rrect(92, 130, 112, 92, 34),                 # palm
        rrect(52, 116, 30, 84, 15, -48, 70, 158),    # thumb
        rrect(112, 200, 82, 38, 10),                 # wrist
    ]
    seps = (f'<path d="M121 128 L120 150" stroke="{LINE}" stroke-width="6" stroke-linecap="round"/>\n'
            f'<path d="M151 128 L152 152" stroke="{LINE}" stroke-width="6" stroke-linecap="round"/>\n'
            f'<path d="M180 132 L182 154" stroke="{LINE}" stroke-width="6" stroke-linecap="round"/>')
    hotspots["hand1"] = (148, 140)
    return svg(layered(shapes), seps)


def closed_hand():
    shapes = [
        rrect(92, 86, 30, 60, 15),      # knuckles
        rrect(121, 80, 30, 64, 15),
        rrect(150, 84, 29, 62, 14.5),
        rrect(178, 94, 26, 56, 13),
        rrect(90, 116, 114, 104, 34),   # palm
        rrect(70, 134, 28, 58, 14, -30, 84, 163),  # thumb, tucked
        rrect(112, 200, 82, 38, 10),
    ]
    seps = finger_seps([121, 150, 178], 100, 134)
    hotspots["grabbing"] = (148, 150)
    return svg(layered(shapes), seps)


# ---------------------------------------------------------------- text / precision

def ibeam(vertical=False):
    d = ("M100 52 C112 52 122 56 128 66 C134 56 144 52 156 52 "
         "M128 66 V190 "
         "M100 204 C112 204 122 200 128 190 C134 200 144 204 156 204")
    g = layered([], [(d, 9, "round")], extra_out=14)
    if vertical:
        g = f'<g transform="rotate(90 128 128)">{g}</g>'
    return svg(g)


def crosshair(arm=82, w=8, gap=0):
    c = 128
    if gap:
        d = (f"M{c} {c - arm} V{c - gap} M{c} {c + gap} V{c + arm} "
             f"M{c - arm} {c} H{c - gap} M{c + gap} {c} H{c + arm}")
    else:
        d = f"M{c} {c - arm} V{c + arm} M{c - arm} {c} H{c + arm}"
    return svg(layered([], [(d, w, "butt")], extra_out=14))


def thick_plus():
    a, w = 70, 14
    pts = [(-w, -a), (w, -a), (w, -w), (a, -w), (a, w), (w, w), (w, a), (-w, a), (-w, w), (-a, w), (-a, -w), (-w, -w)]
    return svg(layered([P(xform(pts, origin=(128, 128)))]))


def x_cursor():
    d = "M70 70 L186 186 M186 70 L70 186"
    return svg(layered([], [(d, 22, "round")]))


def magnifier(minus=False):
    lens = ("circle", 'cx="110" cy="110" r="56"')
    handle = (f"M150 150 L204 204", 26, "round")
    glyph = "M86 110 H134" if minus else "M86 110 H134 M110 86 V134"
    return svg(layered([lens], [handle]),
               f'<path d="{glyph}" stroke="{LINE}" stroke-width="12" stroke-linecap="round"/>')


def lines_svg(d, w=12):
    return svg(layered([], [(d, w, "square")], extra_out=14))


# ---------------------------------------------------------------- assemble

def full_set():
    """Every cursor, drawn around the current `arrow`. Returns name -> svg text."""
    out = {}

    # plain pointers
    out["left_ptr"] = svg(pointer())
    out["wayland-cursor"] = out["left_ptr"]
    hotspots["wayland-cursor"] = (55, 17)
    out["right_ptr"] = svg(arrow_g(tip=(256 - TIP[0], TIP[1]), mirror=True))
    out["center_ptr"] = svg(arrow_g(tip=(128, 22), angle=23))

    # arrow + badge
    out["copy"] = badged("#30C048", g_plus())
    out["link"] = badged(BODY, g_alias())
    out["context-menu"] = badged(BODY, g_menu())
    out["circle"] = badged(BODY, g_forbid())
    out["crossed_circle"] = out["circle"]
    out["question_arrow"] = badged(BODY, g_question())
    for n in ("person", "pin", "pointer-move"):
        out[n] = badged(*bibata_glyph(n))
    # macOS drags with the arrow, not a hand
    out["dnd-copy"], out["dnd-link"] = out["copy"], out["link"]
    out["dnd_no_drop"], out["dnd-ask"] = out["circle"], out["question_arrow"]
    for n in ("crossed_circle", "question_arrow", "dnd-copy", "dnd-link", "dnd_no_drop", "dnd-ask"):
        hotspots[n] = (55, 17)

    # hands
    out["hand2"] = pointing_hand()
    out["hand1"] = open_hand()
    out["grabbing"] = closed_hand()

    # resize: double arrows everywhere, centered like macOS
    h, v, d1, d2 = 0, 90, 45, -45
    for name, ang in {
        "sb_h_double_arrow": h, "left_side": h, "right_side": h,
        "sb_v_double_arrow": v, "top_side": v, "bottom_side": v,
        "bd_double_arrow": d1, "top_left_corner": d1, "bottom_right_corner": d1,
        "fd_double_arrow": d2, "top_right_corner": d2, "bottom_left_corner": d2,
    }.items():
        L = 70 if ang in (d1, d2) else 78
        out[name] = svg(layered([double_arrow(ang, L=L)]))
        hotspots[name] = CENTER
    for name, ang in {"sb_right_arrow": 0, "sb_down_arrow": 90, "sb_left_arrow": 180, "sb_up_arrow": 270}.items():
        out[name] = svg(layered(single_arrow(ang)))
        hotspots[name] = CENTER
    out["move"] = svg(layered([double_arrow(0, L=84, head=36, hw=26, sw=8),
                               double_arrow(90, L=84, head=36, hw=26, sw=8)]))

    # text and precision
    out["xterm"] = ibeam()
    out["vertical-text"] = ibeam(vertical=True)
    out["crosshair"] = crosshair(gap=0)
    out["cross"] = crosshair(arm=70)
    out["tcross"] = crosshair(arm=60, w=7)
    out["plus"] = thick_plus()
    out["X_cursor"] = x_cursor()
    out["zoom-in"] = magnifier()
    out["zoom-out"] = magnifier(minus=True)
    hotspots["zoom_in"] = hotspots["zoom_out"] = (110, 110)
    out["dotbox"] = svg(layered([], [("M72 72 H184 V184 H72 Z", 9, "square")], extra_out=14),
                        layered([("circle", 'cx="128" cy="128" r="11"')]))

    # tees and angles: thin lines meeting at the existing hotspot
    out["ul_angle"] = lines_svg("M33 160 V33 H160")
    out["ur_angle"] = lines_svg("M98 33 H225 V160")
    out["ll_angle"] = lines_svg("M30 96 V223 H157")
    out["lr_angle"] = lines_svg("M97 230 H224 V103")
    out["top_tee"] = lines_svg("M60 27 H196 M128 27 V170")
    out["bottom_tee"] = lines_svg("M60 230 H196 M128 230 V87")
    out["left_tee"] = lines_svg("M230 60 V196 M230 128 H87")
    out["right_tee"] = lines_svg("M29 60 V196 M29 128 H172")
    hotspots["wait"] = CENTER
    return out


def write_full(dst):
    out = full_set()
    # pencil has no macOS twin; keep Bibata's
    shutil.copy(GROUPS / "shared/pencil.svg", dst / "pencil.svg")
    for name, text in out.items():
        (dst / f"{name}.svg").write_text(text)

    # animated: beach ball, and arrow + small beach ball
    (dst / "wait").mkdir()
    (dst / "left_ptr_watch").mkdir()
    for i in range(1, WATCH_FRAMES + 1):
        ang = (i - 1) * 720 / WATCH_FRAMES  # two turns per loop
        ball, defs = beachball(128, 128, 64, ang, i)
        (dst / f"wait/wait-{i:02d}.svg").write_text(svg(ball, defs=defs))
        ball, defs = beachball(180, 188, 40, ang, i)
        (dst / f"left_ptr_watch/left_ptr_watch-{i:02d}.svg").write_text(svg(pointer(10.5), ball, defs=defs))
    return out["left_ptr"]


def crosshair_pointer():
    c = 128
    d = f"M{c} {c - 70} V{c - 20} M{c} {c + 20} V{c + 70} M{c - 70} {c} H{c - 20} M{c + 20} {c} H{c + 70}"
    return svg(layered([("circle", f'cx="{c}" cy="{c}" r="7"')], [(d, 10, "butt")], extra_out=14))


def dot_pointer():
    return svg(layered([("circle", 'cx="128" cy="128" r="40"')], extra_out=20))


def pointer_only(dst, draw):
    """Just the plain pointers, all centered on their hotspot."""
    text = draw()
    for name in ("left_ptr", "right_ptr", "center_ptr", "wayland-cursor"):
        (dst / f"{name}.svg").write_text(text)
        hotspots[name] = CENTER
    return text


# name -> full set around an arrow, or (base full set, pointer drawer)
STYLES = {
    "macos": ARROW_MACOS,
    "macos-tailless": ARROW_TAILLESS,
    "dart": ARROW_DART,
    "retro": "retro",
    "crosshair": ("macos-tailless", crosshair_pointer),
    "dot": ("macos-tailless", dot_pointer),
}


def main():
    global arrow
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    full_hotspots = {}
    for name, spec in STYLES.items():
        dst = GROUPS / name
        shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True)
        hotspots.clear()
        if isinstance(spec, tuple):
            base, draw = spec
            hotspots.update(full_hotspots[base])
            preview = pointer_only(dst, draw)
        else:
            arrow = spec
            preview = write_full(dst)
            full_hotspots[name] = dict(hotspots)
        write_build_toml(name)
        (PREVIEWS / f"{name}.svg").write_text(preview)
        print(f"wrote {name}")
    # Bibata's own shapes, for the settings window
    for name in ("modern", "original"):
        shutil.copy(GROUPS / name / "left_ptr.svg", PREVIEWS / f"{name}.svg")


def write_build_toml(style):
    text = (PLUGIN / "config/build.toml").read_text()
    sections = re.split(r"(?m)^(?=\[cursors\.)", text)
    result = []
    for sec in sections:
        m = re.match(r"\[cursors\.([^\]]+)\]", sec)
        if m and m[1] in hotspots:
            x, y = hotspots[m[1]]
            sec = re.sub(r"(?m)^[xy]_hotspot = .*\n", "", sec)
            sec = sec.replace(f"{m[0]}\n", f"{m[0]}\nx_hotspot = {x}\ny_hotspot = {y}\n", 1)
        result.append(sec)
    header = "# Generated by tools/gen-cursor-styles.py from build.toml; do not edit by hand.\n"
    (PLUGIN / f"config/build.{style}.toml").write_text(header + "".join(result))


if __name__ == "__main__":
    main()
