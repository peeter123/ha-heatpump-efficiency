"""Tests of the brand images and of the script that draws them."""

import importlib.util
from pathlib import Path
import struct
import sys
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "heatpump_efficiency" / "brand"
_spec = importlib.util.spec_from_file_location(
    "brand_script", ROOT / "scripts" / "brand.py"
)
brand = importlib.util.module_from_spec(_spec)
sys.modules["brand_script"] = brand
_spec.loader.exec_module(brand)


def read_png(data: bytes) -> tuple[int, int, int, list[bytes]]:
    """Decode a PNG as the writer produces it: returns width, height, colour type and the RGBA rows."""
    if data[:8] != brand.SIGNATURE:
        raise ValueError("bad signature")
    pos = 8
    header = None
    idat = b""
    ended = False
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        if crc != zlib.crc32(kind + body):
            raise ValueError(f"bad CRC in {kind!r}")
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            ended = True
    if header is None or not ended:
        raise ValueError("missing IHDR or IEND")
    width, height, depth, colour, _compression, _filter, interlace = header
    if depth != 8 or colour != 6 or interlace != 0:
        raise ValueError("unsupported image format")
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    if len(raw) != stride * height:
        raise ValueError("bad data length")
    rows = []
    for j in range(height):
        line = raw[j * stride : (j + 1) * stride]
        if line[0] != 0:
            raise ValueError("unsupported filter type")
        rows.append(line[1:])
    return width, height, colour, rows


def pixel_at(rows: list[bytes], x: int, y: int) -> tuple[int, ...]:
    """Return the RGBA tuple of the pixel at x, y."""
    return tuple(rows[y][x * 4 : x * 4 + 4])


class TestBrandFiles:
    """The icon files of the brand folder."""

    def test_only_the_two_icons(self):
        """The folder holds the icon and its 2x variant and nothing else."""
        assert sorted(p.name for p in BRAND.iterdir()) == ["icon.png", "icon@2x.png"]

    def check_file(self, name: str, size: int):
        """Check the size, corner, tile colour and white arrow of one icon."""
        width, height, colour, rows = read_png((BRAND / name).read_bytes())
        assert (width, height, colour) == (size, size, 6)
        assert pixel_at(rows, 0, 0)[3] == 0
        x, y = int(128 * size / 256), int(40 * size / 256)
        assert pixel_at(rows, x, y) == (0x44, 0x88, 0x2E, 255)
        assert pixel_at(rows, int(128 * size / 256), int(62 * size / 256)) == (
            255,
            255,
            255,
            255,
        )

    def test_icon(self):
        """The 256 pixel icon is a valid image with the expected pixels."""
        self.check_file("icon.png", 256)

    def test_icon_2x(self):
        """The 512 pixel icon is a valid image with the expected pixels."""
        self.check_file("icon@2x.png", 512)

    def test_committed_icon_matches_the_script(self):
        """The committed icon equals the script drawing, within one level."""
        _w, _h, _c, committed = read_png((BRAND / "icon.png").read_bytes())
        drawn = brand.draw(256)
        for j, (a, b) in enumerate(zip(committed, drawn, strict=True)):
            worst = max(abs(x - y) for x, y in zip(a, b, strict=True))
            assert worst <= 1, f"row {j} differs by {worst}"


class TestCoverage:
    """The anti-aliasing coverage of a pixel from its distance to an edge."""

    def test_half_at_the_edge(self):
        """A pixel centred on the edge is half covered."""
        assert brand.coverage(0.0, 256) == 0.5

    def test_clamps(self):
        """Coverage is clamped between 0 and 1 far outside and far inside the shape."""
        assert brand.coverage(100.0, 256) == 0.0
        assert brand.coverage(-100.0, 256) == 1.0

    def test_distance_scales_with_size(self):
        """The same distance covers less of a pixel in a larger image."""
        assert brand.coverage(0.25, 256) == 0.25
        assert brand.coverage(0.25, 512) == 0.0


class TestPixelColour:
    """The colour of a pixel from the coverage of each shape."""

    def colour(self, **kwargs):
        """Return the pixel colour with every shape uncovered except those given."""
        shapes = {
            "tile": 0.0,
            "cabinet": 0.0,
            "grille": 0.0,
            "ring": 0.0,
            "feet": 0.0,
            "arrow": 0.0,
            "cutout": 0.0,
        }
        shapes.update(kwargs)
        return brand.pixel_colour(**shapes)

    def test_cutout_cancels_the_ring(self):
        """The cutout hides the ring and leaves the tile colour."""
        assert self.colour(tile=1.0, ring=1.0, cutout=1.0) == (0x44, 0x88, 0x2E, 255)

    def test_arrow_wins_over_the_cutout(self):
        """The arrow is drawn in white even where the cutout covers it."""
        assert self.colour(tile=1.0, arrow=1.0, cutout=1.0) == (255, 255, 255, 255)

    def test_alpha_comes_from_the_tile_alone(self):
        """Only the tile coverage sets the alpha channel."""
        assert self.colour(tile=0.0, cabinet=1.0, arrow=1.0)[3] == 0
        assert self.colour(tile=0.5)[3] == round(127.5)


class TestPngRoundTrip:
    """Writing and reading back a PNG."""

    def test_round_trip(self):
        """A PNG written by the script decodes to the same size and rows."""
        rows = [bytes(range(12)), bytes(range(100, 112))]
        data = brand.png_bytes(3, 2, rows)
        assert read_png(data) == (3, 2, 6, rows)

    def test_corrupt_crc_is_rejected(self):
        """A PNG with a corrupt chunk checksum is rejected."""
        data = bytearray(brand.png_bytes(1, 1, [bytes(4)]))
        data[-1] ^= 0xFF
        with pytest.raises(ValueError):
            read_png(bytes(data))
