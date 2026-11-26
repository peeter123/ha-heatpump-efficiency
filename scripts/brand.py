"""Draw the integration's brand images with the Python standard library only.

Usage: python scripts/brand.py [output-folder]

Writes icon.png (256 px) and icon@2x.png (512 px) into the integration's brand/ folder, or into the folder given as
the first argument. The geometry below, in a 256 by 256 grid of design units, is the source of the icon; the PNG
files are generated from it. Shapes are rasterised with signed distance functions and one pixel of anti-aliasing.
"""

import math
from pathlib import Path
import struct
import sys
import zlib

DESIGN = 256.0
TILE_COLOUR = (0x44, 0x88, 0x2E)
LINE_WIDTH = 12.0
CUTOUT_WIDTH = 26.0

Point = tuple[float, float]
Segment = tuple[Point, Point]

TILE = (
    128.0,
    128.0,
    128.0,
    128.0,
    56.0,
)  # centre x, centre y, half width, half height, radius
CABINET = (128.0, 126.0, 96.0, 64.0, 20.0)  # x 32..224, y 62..190
GRILLE: tuple[Segment, ...] = (
    ((152.0, 102.0), (200.0, 102.0)),
    ((152.0, 126.0), (200.0, 126.0)),
    ((152.0, 150.0), (200.0, 150.0)),
)
RING_CENTRE: Point = (88.0, 126.0)
RING_RADIUS = 32.0
ARROW: tuple[Segment, ...] = (
    ((58.0, 156.0), (116.0, 98.0)),
    ((98.0, 98.0), (116.0, 98.0)),
    ((116.0, 98.0), (116.0, 116.0)),
)
FEET = (
    (75.0, 200.0, 17.0, 8.0, 5.0),  # x 58..92, y 192..208
    (181.0, 200.0, 17.0, 8.0, 5.0),  # x 164..198
)

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def box_distance(
    px: float, py: float, box: tuple[float, float, float, float, float]
) -> float:
    """Signed distance from a point to a filled rounded box."""
    cx, cy, hw, hh, r = box
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def box_outline_distance(
    px: float, py: float, box: tuple[float, float, float, float, float], width: float
) -> float:
    """Signed distance to the outline of a rounded box."""
    return abs(box_distance(px, py, box)) - width / 2


def capsule_distance(px: float, py: float, segment: Segment, width: float) -> float:
    """Signed distance to a line segment with round caps."""
    (ax, ay), (bx, by) = segment
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = min(max(t, 0.0), 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) - width / 2


def ring_distance(
    px: float, py: float, centre: Point, radius: float, width: float
) -> float:
    """Signed distance to a circle outline."""
    return abs(math.hypot(px - centre[0], py - centre[1]) - radius) - width / 2


def coverage(distance: float, size: int) -> float:
    """Pixel coverage from a signed distance in design units."""
    return min(max(0.5 - distance * size / DESIGN, 0.0), 1.0)


def pixel_colour(
    tile: float,
    cabinet: float,
    grille: float,
    ring: float,
    feet: float,
    arrow: float,
    cutout: float,
    tile_colour: tuple[int, int, int] = TILE_COLOUR,
) -> tuple[int, int, int, int]:
    """Composite the shape coverages into one non-premultiplied RGBA pixel."""
    white = max(arrow, max(cabinet, grille, ring, feet) * (1.0 - cutout))
    rgb = tuple(round(c + (255 - c) * white) for c in tile_colour)
    return (rgb[0], rgb[1], rgb[2], round(255 * tile))


def pixel(i: int, j: int, size: int) -> tuple[int, int, int, int]:
    """The RGBA pixel in column i, row j of a size by size icon."""
    px = (i + 0.5) * DESIGN / size
    py = (j + 0.5) * DESIGN / size
    cov = lambda d: coverage(d, size)  # noqa: E731
    return pixel_colour(
        tile=cov(box_distance(px, py, TILE)),
        cabinet=cov(box_outline_distance(px, py, CABINET, LINE_WIDTH)),
        grille=cov(min(capsule_distance(px, py, s, LINE_WIDTH) for s in GRILLE)),
        ring=cov(ring_distance(px, py, RING_CENTRE, RING_RADIUS, LINE_WIDTH)),
        feet=cov(min(box_distance(px, py, f) for f in FEET)),
        arrow=cov(min(capsule_distance(px, py, s, LINE_WIDTH) for s in ARROW)),
        cutout=cov(min(capsule_distance(px, py, s, CUTOUT_WIDTH) for s in ARROW)),
    )


def draw(size: int) -> list[bytes]:
    """Draw the icon at size by size pixels; one bytes row of RGBA per scanline."""
    return [
        bytes(v for i in range(size) for v in pixel(i, j, size)) for j in range(size)
    ]


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


def png_bytes(width: int, height: int, rows: list[bytes]) -> bytes:
    """Encode 8-bit RGBA rows as a PNG file."""
    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    """Write icon.png and icon@2x.png."""
    root = Path(__file__).resolve().parents[1]
    folder = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else root / "custom_components" / "heatpump_efficiency" / "brand"
    )
    folder.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        data = png_bytes(size, size, draw(size))
        (folder / name).write_bytes(data)
        print(f"wrote {folder / name} ({size} x {size}, {len(data)} bytes)")


if __name__ == "__main__":
    main()
