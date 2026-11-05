#!/usr/bin/env python3
"""Minimal pure-Python replacement for xcursorgen (stdlib only).

Reads the same config format xcursorgen does, one image per line:

    <nominal-size> <xhot> <yhot> <png-file> [<delay-ms>]

and writes an Xcursor file. PNGs must be 8-bit, non-interlaced, as
rsvg-convert produces (RGBA, color type 6); RGB, gray and gray+alpha are
accepted too. Pixels are stored as premultiplied ARGB32 with the same
rounding (div_255), default delay (50 ms) and image order xcursorgen uses,
so the output should match it byte for byte.

CLI is xcursorgen-compatible:  xcursor.py [-p prefix] config [out]
"""
import struct
import sys
import zlib
from pathlib import Path

XCURSOR_MAGIC = b'Xcur'
XCURSOR_FILE_HEADER_LEN = 16
XCURSOR_FILE_VERSION = 0x00010000
XCURSOR_IMAGE_TYPE = 0xFFFD0002
XCURSOR_IMAGE_HEADER_LEN = 36
XCURSOR_IMAGE_VERSION = 1
XCURSOR_IMAGE_MAX_SIZE = 0x7FFF

_CHANNELS = {6: 4, 2: 3, 4: 2, 0: 1}  # PNG color type -> samples per pixel


def _paeth_row(cur: bytearray, prev: bytes, bpp: int) -> None:
    for i in range(len(cur)):
        a = cur[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        p = a + b - c
        pa = p - a if p > a else a - p
        pb = p - b if p > b else b - p
        pc = p - c if p > c else c - p
        if pa <= pb and pa <= pc:
            pr = a
        elif pb <= pc:
            pr = b
        else:
            pr = c
        cur[i] = (cur[i] + pr) & 0xFF


def decode_png(path: Path) -> tuple[int, int, bytes]:
    """Return (width, height, RGBA bytes) for an 8-bit non-interlaced PNG."""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'{path}: not a PNG')
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        length, ctype = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', body)
        elif ctype == b'IDAT':
            idat.append(body)
        elif ctype == b'IEND':
            break
        pos += 12 + length
    if ihdr is None:
        raise ValueError(f'{path}: missing IHDR')
    w, h, depth, color, _comp, _filt, interlace = ihdr
    if depth != 8 or color not in _CHANNELS or interlace:
        raise ValueError(f'{path}: unsupported PNG (depth={depth} color={color} '
                         f'interlace={interlace})')
    bpp = _CHANNELS[color]
    stride = w * bpp
    raw = zlib.decompress(b''.join(idat))
    out = bytearray(stride * h)
    prev = bytes(stride)
    mask = (1 << (8 * stride)) - 1
    hi = int.from_bytes(b'\x80' * stride, 'little')
    lo = int.from_bytes(b'\x7f' * stride, 'little')
    for y in range(h):
        off = y * (stride + 1)
        ftype = raw[off]
        cur = bytearray(raw[off + 1:off + 1 + stride])
        if ftype == 1:  # Sub
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ftype == 2:  # Up: bytewise add without carries (SWAR on a big int)
            a = int.from_bytes(cur, 'little')
            b = int.from_bytes(prev, 'little')
            s = ((a & lo) + (b & lo)) ^ ((a ^ b) & hi)
            cur = bytearray((s & mask).to_bytes(stride, 'little'))
        elif ftype == 3:  # Average
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            _paeth_row(cur, prev, bpp)
        elif ftype != 0:
            raise ValueError(f'{path}: bad filter type {ftype}')
        out[y * stride:(y + 1) * stride] = cur
        prev = cur
    if color == 6:
        return w, h, bytes(out)
    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        if color == 2:
            r, g, b = out[3 * i:3 * i + 3]
            a = 255
        elif color == 4:
            r = g = b = out[2 * i]
            a = out[2 * i + 1]
        else:
            r = g = b = out[i]
            a = 255
        rgba[4 * i:4 * i + 4] = (r, g, b, a)
    return w, h, bytes(rgba)


def _mul(alpha: int, color: int) -> int:
    # Same rounding as xcursorgen's multiply_alpha().
    t = alpha * color + 0x80
    return (t + (t >> 8)) >> 8


# Lookup tables: _MUL[a][c] == _mul(a, c); built lazily per alpha.
_MUL_CACHE: dict[int, bytes] = {}


def _mul_table(alpha: int) -> bytes:
    tbl = _MUL_CACHE.get(alpha)
    if tbl is None:
        tbl = bytes(_mul(alpha, c) for c in range(256))
        _MUL_CACHE[alpha] = tbl
    return tbl


def rgba_to_argb_premul(rgba: bytes) -> bytes:
    """RGBA8 -> little-endian premultiplied ARGB32 (byte order B,G,R,A)."""
    n = len(rgba) // 4
    out = bytearray(len(rgba))
    # Swap R and B with slicing (fast), then fix partial-alpha pixels.
    out[0::4] = rgba[2::4]
    out[1::4] = rgba[1::4]
    out[2::4] = rgba[0::4]
    out[3::4] = rgba[3::4]
    alphas = rgba[3::4]
    for i in range(n):
        a = alphas[i]
        if a == 255:
            continue
        j = 4 * i
        if a == 0:
            out[j:j + 4] = b'\0\0\0\0'
        else:
            t = _mul_table(a)
            out[j] = t[out[j]]
            out[j + 1] = t[out[j + 1]]
            out[j + 2] = t[out[j + 2]]
    return bytes(out)


def parse_config(text: str) -> list[tuple[int, int, int, str, int]]:
    entries = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split()
        if len(parts) not in (4, 5):
            raise ValueError(f'config line {lineno}: expected '
                             '"size xhot yhot file [delay]", got {line!r}')
        size, xhot, yhot = (int(x) for x in parts[:3])
        delay = int(parts[4]) if len(parts) == 5 else 50  # xcursorgen's default
        entries.append((size, xhot, yhot, parts[3], delay))
    return entries


def write_xcursor(images: list[tuple[int, int, int, int, int, int, bytes]], out: Path) -> None:
    """images: (nominal size, width, height, xhot, yhot, delay, argb bytes)."""
    ntoc = len(images)
    header = struct.pack('<4sIII', XCURSOR_MAGIC, XCURSOR_FILE_HEADER_LEN,
                         XCURSOR_FILE_VERSION, ntoc)
    pos = XCURSOR_FILE_HEADER_LEN + 12 * ntoc
    toc, chunks = [], []
    for size, w, h, xhot, yhot, delay, pixels in images:
        if not (0 < w <= XCURSOR_IMAGE_MAX_SIZE and 0 < h <= XCURSOR_IMAGE_MAX_SIZE):
            raise ValueError(f'bad image size {w}x{h}')
        # Keep the hotspot inside the image; libXcursor rejects it otherwise.
        xhot, yhot = min(xhot, w), min(yhot, h)
        toc.append(struct.pack('<III', XCURSOR_IMAGE_TYPE, size, pos))
        chunk = struct.pack('<IIIIIIIII', XCURSOR_IMAGE_HEADER_LEN, XCURSOR_IMAGE_TYPE,
                            size, XCURSOR_IMAGE_VERSION, w, h, xhot, yhot, delay) + pixels
        chunks.append(chunk)
        pos += len(chunk)
    Path(out).write_bytes(header + b''.join(toc) + b''.join(chunks))


def xcursorgen(config: Path, out: Path, prefix: Path | None = None) -> None:
    base = Path(prefix) if prefix else Path('.')
    images = []
    for size, xhot, yhot, name, delay in parse_config(Path(config).read_text()):
        w, h, rgba = decode_png(base / name)
        images.append((size, w, h, xhot, yhot, delay, rgba_to_argb_premul(rgba)))
    write_xcursor(images, out)


def main(argv: list[str]) -> int:
    prefix = None
    args = list(argv)
    if len(args) >= 2 and args[0] == '-p':
        prefix = args[1]
        args = args[2:]
    elif args and args[0].startswith('--prefix='):
        prefix = args[0].split('=', 1)[1]
        args = args[1:]
    if len(args) != 2:
        print('usage: xcursor.py [-p prefix] config out', file=sys.stderr)
        return 1
    xcursorgen(Path(args[0]), Path(args[1]), prefix)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
