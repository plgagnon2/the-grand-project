"""webmap.export: writes an atlas as a web map folder that MapLibre shows in a browser.

    <atlas>_files/web/
        index.html, app.js, style.css   the page (copied from webmap/static)
        terrain/{z}/{x}/{y}.jpg         the stitched map image as raster tiles
        vector/{z}/{x}/{y}.pbf          map nodes, paths, landmarks, bookmarks as vector tiles (MVT)
        atlas.json                      what the page needs besides tiles: zoom range, bounds, and the map nodes /
                                        paths / landmarks / bookmarks again for search and directions
        meta.json                       what the export was made from, so an unchanged atlas is not exported again

The map image is the viewer's cached one when it matches the atlas (the clean map, after Fix seams), else it is
stitched from the screenshots here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from grand_project import __version__, core
from grand_project import fileio as atlas_io
from grand_project.viewer.constants import ICON_INFO
from grand_project.viewer.model import view_model

from .constants import WEBMAP_FORMAT, WEBMAP_NO_ICON_FILL, WEBMAP_OVERZOOM, WEBMAP_STATUS_COLOUR, WEBMAP_TERRAIN_PIXELS
from .tiles import Grid, write_raster_tiles, write_vector_tiles

STATIC = Path(__file__).resolve().parent / "static"


def web_folder(atlas_path) -> Path:
    """Return the web map folder of an atlas.

    Args:
        atlas_path: Path of the atlas .json file.

    Returns:
        <atlas>_files/web (not created).
    """
    return core.atlas_files(atlas_path) / "web"


def _hex(bgr) -> str:
    """Convert a BGR colour tuple to CSS hex.

    Args:
        bgr: (b, g, r) 0..255.

    Returns:
        "#rrggbb".
    """
    b, g, r = (int(v) for v in bgr)
    return f"#{r:02x}{g:02x}{b:02x}"


def map_image(atlas: core.Atlas, atlas_path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Return the stitched map image: the viewer's cache when its key matches the atlas, else built now.

    Args:
        atlas: The atlas.
        atlas_path: Its .json path (finds the cache).

    Returns:
        (BGR image, (x0, y0, scale) origin).
    """
    png, npz = core.map_image_files(atlas_path)
    try:
        with np.load(npz) as meta:
            if str(meta["key"]) == atlas.terrain_key():
                img = cv2.imdecode(np.fromfile(str(png), np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img, tuple(float(v) for v in meta["origin"])
    except (OSError, KeyError, ValueError):
        pass  # no cache, or an older / other atlas's: build it
    img, origin = atlas.composite(max_pixels=WEBMAP_TERRAIN_PIXELS)
    return img, tuple(float(v) for v in origin)


def source_key(atlas_path: Path) -> str:
    """Return the key of what an export is made from: the atlas file, its cached map image, the program version.

    Args:
        atlas_path: Path of the atlas .json file.

    Returns:
        The hex digest; an export whose meta.json holds the same key is up to date.
    """
    h = hashlib.sha1(f"{WEBMAP_FORMAT}|{__version__}".encode())
    h.update(Path(atlas_path).read_bytes())
    png, _npz = core.map_image_files(atlas_path)
    if png.exists():
        st = png.stat()
        h.update(f"{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()


def is_current(atlas_path) -> bool:
    """Tell whether the atlas's web map folder is up to date.

    Args:
        atlas_path: Path of the atlas .json file.

    Returns:
        True when it exists and was made from the same atlas, map image and program version.
    """
    meta = web_folder(atlas_path) / "meta.json"
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("key") == source_key(Path(atlas_path))
    except (OSError, ValueError):
        return False


def _features(V: dict, grid: Grid) -> tuple[dict[str, list[dict]], dict]:
    """Build the vector tile features and the page's search / directions data from the viewer's model.

    Removed map nodes (and paths touching them) are left out, as are removed landmarks.

    Args:
        V: The viewer model (viewer.model.view_model).
        grid: The grid of the map image.

    Returns:
        (layers for write_vector_tiles, the "nodes" / "edges" / "landmarks" / "bookmarks" parts of atlas.json).
    """
    nodes = V["nodes"]
    keep = [i for i, nd in enumerate(nodes) if nd["status"] != "removed"]
    index = {i: k for k, i in enumerate(keep)}  # model index -> web id (0.. in order)
    maps, page_nodes = [], []
    for i in keep:
        nd = nodes[i]
        icons = sorted(set(nd.get("icons") or []))
        fill = _hex(ICON_INFO[icons[0]][1]) if icons and icons[0] in ICON_INFO else WEBMAP_NO_ICON_FILL
        maps.append(
            {
                "kind": "point",
                "pts": [grid.world_px(nd["x"], nd["y"])],
                "id": index[i],
                "props": {
                    "id": index[i],
                    "status": nd["status"],
                    "ring": WEBMAP_STATUS_COLOUR.get(nd["status"], "#ffffff"),
                    "fill": fill,
                    # "|A|B|": the page highlights an icon type with a substring test ("in" on strings)
                    "icons": "|" + "|".join(icons) + "|" if icons else "",
                    "tower": bool(nd.get("tower")),
                },
            }
        )
        page_nodes.append(
            {
                "id": index[i],
                "c": grid.lnglat(nd["x"], nd["y"]),
                "status": nd["status"],
                "icons": icons,
                "seen": nd.get("seen", 0),
                "tower": bool(nd.get("tower")),
            }
        )
    paths, edges = [], []
    for p in V["paths"]:
        if p["a"] not in index or p["b"] not in index:
            continue
        a, b = nodes[p["a"]], nodes[p["b"]]
        line = p.get("line") or [[a["x"], a["y"]], [b["x"], b["y"]]]
        strong = p.get("seen_in", p.get("frames", 0)) >= 2 or bool(p.get("both_ends"))
        paths.append(
            {
                "kind": "line",
                "pts": [grid.world_px(x, y) for x, y in line],
                "props": {"abyss": bool(p.get("abyss")), "strong": bool(strong)},
            }
        )
        edge = {"a": index[p["a"]], "b": index[p["b"]]}
        if len(line) > 2:  # a curved path: the page draws routes along it
            edge["l"] = [grid.lnglat(x, y) for x, y in line]
        edges.append(edge)
    landmarks, page_landmarks = [], []
    for lm in V["landmarks"]:
        if str(lm.get("status", "")).startswith("removed"):
            continue
        landmarks.append({"kind": "point", "pts": [grid.world_px(lm["x"], lm["y"])], "props": {"kind": lm["kind"]}})
        page_landmarks.append({"kind": lm["kind"], "c": grid.lnglat(lm["x"], lm["y"])})
    bookmarks, page_bookmarks = [], []
    for bm in V.get("bookmarks", []):
        bookmarks.append({"kind": "point", "pts": [grid.world_px(bm["x"], bm["y"])], "props": {"name": bm["name"]}})
        page_bookmarks.append(
            {
                "name": bm["name"],
                "group": bm.get("group", ""),
                "note": bm.get("note", ""),
                "c": grid.lnglat(bm["x"], bm["y"]),
            }
        )
    layers = {"paths": paths, "landmarks": landmarks, "maps": maps, "bookmarks": bookmarks}
    page = {"nodes": page_nodes, "edges": edges, "landmarks": page_landmarks, "bookmarks": page_bookmarks}
    return layers, page


def export_webmap(atlas_path, force: bool = False, progress: Callable[[str], None] | None = None) -> Path:
    """Write (or refresh) the atlas's web map folder.

    Args:
        atlas_path: Path of the atlas .json file.
        force: Rebuild even when the folder is up to date.
        progress: Called with short status lines.

    Returns:
        The web map folder.
    """
    atlas_path = Path(atlas_path)
    out = web_folder(atlas_path)
    say = progress or (lambda _s: None)
    if not force and is_current(atlas_path):
        say("web map: up to date")
        return out
    key = source_key(atlas_path)
    atlas = core.Atlas.load(atlas_path)
    say("web map: reading the map image")
    image, origin = map_image(atlas, atlas_path)
    grid = Grid(origin, image.shape[1], image.shape[0])
    V = view_model(atlas)
    V["bookmarks"] = list(atlas.bookmarks)
    layers, page = _features(V, grid)

    tmp = out.with_name("web.new")  # built aside, then swapped in: a half-written map is never served
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    n_raster = write_raster_tiles(image, grid, tmp / "terrain", say)
    n_vector = write_vector_tiles(layers, grid, tmp / "vector", say)
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copyfile(f, tmp / f.name)
    icon_names = sorted({ic for nd in page["nodes"] for ic in nd["icons"]})
    info = {
        "title": atlas_path.stem,
        "version": __version__,
        "zmax": grid.zmax,
        # MapLibre shows 256 px raster tiles of level z at map zoom z - 1: full detail at zmax - 1, then stretched
        "maxzoom": grid.zmax - 1 + WEBMAP_OVERZOOM,
        "bounds": grid.bounds(),
        "icons": {
            n: {"label": ICON_INFO[n][0] if n in ICON_INFO else n, "colour": _icon_colour(n)} for n in icon_names
        },
        "status_colour": WEBMAP_STATUS_COLOUR,
        **page,
    }
    atlas_io.write_text_atomic(tmp / "atlas.json", json.dumps(info, separators=(",", ":")))
    atlas_io.write_text_atomic(
        tmp / "meta.json", json.dumps({"key": key, "terrain_tiles": n_raster, "vector_tiles": n_vector}, indent=1)
    )
    old = out.with_name("web.old")
    shutil.rmtree(old, ignore_errors=True)
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    shutil.rmtree(old, ignore_errors=True)
    say(f"web map: {n_raster} terrain tiles, {n_vector} vector tiles")
    return out


def _icon_colour(name: str) -> str:
    """Return an icon type's colour as CSS hex (white for an unknown type).

    Args:
        name: Icon type name.

    Returns:
        "#rrggbb".
    """
    return _hex(ICON_INFO[name][1]) if name in ICON_INFO else "#ffffff"
