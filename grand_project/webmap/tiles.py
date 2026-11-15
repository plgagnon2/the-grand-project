"""webmap.tiles: the web map's coordinates, its raster tiles (the map image) and its vector tiles.

MapLibre only knows the Web Mercator world, so the atlas is laid on it as a flat picture: at the most detailed tile
level `zmax` one map image pixel is one world pixel, and the picture sits in the middle half of the world (a quarter
of the world from its top-left corner). The margin keeps every point, and the page's pan limits around the picture,
inside the latitudes MapLibre accepts (the world's own edge is at 85 degrees). Every point is placed through world
pixels; longitude / latitude (for the page) are only the exact Mercator names of those pixels, so the picture, the
dots and the lines always line up.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from .constants import WEBMAP_JPEG_QUALITY, WEBMAP_MVT_BUFFER, WEBMAP_MVT_EXTENT, WEBMAP_TILE
from .mvt import Layer, encode_tile


class Grid:
    """Atlas units <-> world pixels <-> longitude / latitude, for one map image."""

    def __init__(self, origin: tuple[float, float, float], width: int, height: int):
        """Set up the grid for a map image.

        Args:
            origin: (x0, y0, scale) of the map image: atlas (x, y) is image px ((x - x0) * scale, (y - y0) * scale).
            width: Map image width in px.
            height: Map image height in px.
        """
        self.x0, self.y0, self.scale = (float(v) for v in origin)
        self.width, self.height = int(width), int(height)
        # the smallest level whose world holds the picture in its middle half: world = WEBMAP_TILE * 2 ** zmax px
        self.zmax = max(0, math.ceil(math.log2(max(self.width, self.height, 1) / WEBMAP_TILE))) + 1
        self.world = WEBMAP_TILE * 2**self.zmax
        self.offset = self.world // 4  # world px of the picture's top-left corner (both axes); 64 * 2**z at level z

    def world_px(self, x: float, y: float) -> tuple[float, float]:
        """Convert an atlas point to world px at level zmax.

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            (wx, wy) world px.
        """
        return (x - self.x0) * self.scale + self.offset, (y - self.y0) * self.scale + self.offset

    def lnglat(self, x: float, y: float) -> list[float]:
        """Convert an atlas point to the longitude / latitude MapLibre uses for it.

        Args:
            x: Atlas x.
            y: Atlas y.

        Returns:
            [lng, lat] in degrees, rounded to 7 places (~1 cm on the equator: far below a pixel here).
        """
        wx, wy = self.world_px(x, y)
        lng = wx / self.world * 360.0 - 180.0
        lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy / self.world))))
        return [round(lng, 7), round(lat, 7)]

    def bounds(self) -> list[list[float]]:
        """Return the map image's corners as [[west, south], [east, north]] in degrees.

        Returns:
            The bounds MapLibre's fitBounds / maxBounds take.
        """
        to = lambda wx, wy: [  # noqa: E731
            wx / self.world * 360.0 - 180.0,
            math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * wy / self.world)))),
        ]
        o = self.offset
        (w, n), (e, s) = to(o, o), to(o + self.width, o + self.height)
        return [[w, s], [e, n]]


def write_raster_tiles(image: np.ndarray, grid: Grid, out: Path, progress: Callable[[str], None] | None = None) -> int:
    """Write the map image as JPEG tiles out/{z}/{x}/{y}.jpg for every level 0..zmax.

    Each level is the previous one halved (area averaging), placed at the grid's offset for that level. Tiles that
    are entirely black (no screenshot there) are not written; the page shows its background there.

    Args:
        image: The map image (BGR uint8), at the grid's offset at level zmax.
        grid: The grid of this map image.
        out: Folder for the tiles.
        progress: Called with a short status line now and then.

    Returns:
        The number of tiles written.
    """
    n = 0
    level = image
    T = WEBMAP_TILE
    for z in range(grid.zmax, -1, -1):
        h, w = level.shape[:2]
        off = grid.offset >> (grid.zmax - z)  # the picture's corner at this level (exact: 64 * 2**z px)
        for ty in range(off // T, (off + h - 1) // T + 1):
            for tx in range(off // T, (off + w - 1) // T + 1):
                # the part of the picture inside this tile, in picture px and in tile px
                x0, y0 = max(0, tx * T - off), max(0, ty * T - off)
                x1, y1 = min(w, (tx + 1) * T - off), min(h, (ty + 1) * T - off)
                crop = level[y0:y1, x0:x1]
                if not crop.any():
                    continue
                tile = np.zeros((T, T, 3), np.uint8)  # outside the picture: black, like no ground
                dx, dy = x0 + off - tx * T, y0 + off - ty * T
                tile[dy : dy + crop.shape[0], dx : dx + crop.shape[1]] = crop
                ok, buf = cv2.imencode(".jpg", tile, [cv2.IMWRITE_JPEG_QUALITY, WEBMAP_JPEG_QUALITY])
                if not ok:
                    raise OSError(f"terrain tile {z}/{tx}/{ty} could not be encoded")
                f = out / str(z) / str(tx) / f"{ty}.jpg"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(buf.tobytes())  # cv2.imwrite fails on non-ASCII paths (Windows)
                n += 1
        if progress:
            progress(f"web map: terrain tiles, level {z}")
        if z:
            level = cv2.resize(level, (max(1, (w + 1) // 2), max(1, (h + 1) // 2)), interpolation=cv2.INTER_AREA)
    return n


def _clip_segment(p, q, lo: float, hi: float):
    """Clip a segment to the square [lo, hi] x [lo, hi] (Liang-Barsky).

    Args:
        p: (x, y) start.
        q: (x, y) end.
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        ((x, y), (x, y)) of the part inside, or None when it misses the square.
    """
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - lo), (dx, hi - x0), (-dy, y0 - lo), (dy, hi - y0)):
        if pk == 0:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def _clip_line(pts: list[tuple[float, float]], lo: float, hi: float) -> list[list[tuple[int, int]]]:
    """Clip a polyline to a square, as integer tile coordinates.

    Args:
        pts: Polyline vertices (tile-local floats).
        lo: Square's low edge.
        hi: Square's high edge.

    Returns:
        The pieces inside (each 2+ distinct integer vertices).
    """
    pieces, cur = [], []
    for p, q in zip(pts, pts[1:], strict=False):
        c = _clip_segment(p, q, lo, hi)
        if c is None:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = []
            continue
        a = (round(c[0][0]), round(c[0][1]))
        b = (round(c[1][0]), round(c[1][1]))
        if not cur or cur[-1] != a:
            if len(cur) >= 2:
                pieces.append(cur)
            cur = [a]
        if b != cur[-1]:
            cur.append(b)
    if len(cur) >= 2:
        pieces.append(cur)
    return pieces


def write_vector_tiles(
    layers: dict[str, list[dict]], grid: Grid, out: Path, progress: Callable[[str], None] | None = None
) -> int:
    """Write vector tiles out/{z}/{x}/{y}.pbf for every level 0..zmax.

    Args:
        layers: Layer name -> features: {"kind": "point" | "line", "pts": [(wx, wy), ...] in world px at zmax,
            "props": {...}, "id": int or None}.
        grid: The grid (gives zmax).
        out: Folder for the tiles.
        progress: Called with a short status line now and then.

    Returns:
        The number of tiles written.
    """
    E, B = WEBMAP_MVT_EXTENT, WEBMAP_MVT_BUFFER
    n = 0
    for z in range(grid.zmax + 1):
        f = 2.0 ** (z - grid.zmax)  # world px at zmax -> world px at z
        k = E / WEBMAP_TILE  # world px at z -> extent units
        pad = B / k  # the buffer in world px at z
        tiles: dict[tuple[int, int], dict[str, Layer]] = {}

        def layer(t, name, _tiles=tiles):
            """Return the named layer of a tile, created on first use.

            Args:
                t: (tx, ty) tile.
                name: Layer name.
                _tiles: The tiles of this level.

            Returns:
                The Layer.
            """
            return _tiles.setdefault(t, {}).setdefault(name, Layer(name, E))

        for name, feats in layers.items():
            for ft in feats:
                pts = [(x * f, y * f) for x, y in ft["pts"]]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                tx0 = max(0, int((min(xs) - pad) // WEBMAP_TILE))
                tx1 = int((max(xs) + pad) // WEBMAP_TILE)
                ty0 = max(0, int((min(ys) - pad) // WEBMAP_TILE))
                ty1 = int((max(ys) + pad) // WEBMAP_TILE)
                for tx in range(tx0, tx1 + 1):
                    for ty in range(ty0, ty1 + 1):
                        local = [((x - tx * WEBMAP_TILE) * k, (y - ty * WEBMAP_TILE) * k) for x, y in pts]
                        if ft["kind"] == "point":
                            x, y = local[0]
                            if -B <= x <= E + B and -B <= y <= E + B:
                                layer((tx, ty), name).add("point", [(round(x), round(y))], ft["props"], ft.get("id"))
                        else:
                            for piece in _clip_line(local, -B, E + B):
                                layer((tx, ty), name).add("line", piece, ft["props"], ft.get("id"))
        for (tx, ty), tile_layers in tiles.items():
            data = encode_tile(list(tile_layers.values()))
            if not data:
                continue
            p = out / str(z) / str(tx) / f"{ty}.pbf"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            n += 1
        if progress:
            progress(f"web map: vector tiles, level {z}")
    return n
