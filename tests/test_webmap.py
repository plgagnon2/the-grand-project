"""Offline checks for the web map export (no screenshots needed).   python -m tests.test_webmap

A small atlas is made by hand (map nodes, paths, a landmark, a bookmark, a removed map node) with a cached map image,
exported, and the files are read back: the terrain tiles put together again must give the map image, every map node
must sit in the vector tiles where its atlas position says, and the local server must hand out the files.
"""

import json
import math
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from grand_project import core
from grand_project.webmap import export_webmap, is_current, make_server, url_of
from grand_project.webmap.mvt import Layer, encode_tile
from grand_project.webmap.tiles import Grid, _clip_line

IMG_W, IMG_H = 1500, 900  # the test map image (atlas units = px: origin (0, 0), scale 1)


# ------------------------------------------------------------------ a minimal MVT reader (from the spec)
def _varint(b: bytes, i: int):
    n = shift = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return n, i


def _fields(b: bytes):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = _varint(b, i)
        elif wire == 1:
            v, i = b[i : i + 8], i + 8
        elif wire == 2:
            n, i = _varint(b, i)
            v, i = b[i : i + n], i + n
        elif wire == 5:
            v, i = b[i : i + 4], i + 4
        else:
            raise AssertionError(f"wire type {wire}")
        yield field, v


def _packed(b: bytes):
    out, i = [], 0
    while i < len(b):
        v, i = _varint(b, i)
        out.append(v)
    return out


def read_tile(data: bytes) -> dict:
    """Decode a vector tile: {layer name: [(type, [(cmd, x, y)], props, id)]}."""
    import struct

    zz = lambda n: (n >> 1) ^ -(n & 1)  # noqa: E731
    out = {}
    for f, layer in _fields(data):
        assert f == 3
        name, feats, keys, values, version, extent = None, [], [], [], None, None
        for lf, v in _fields(layer):
            if lf == 1:
                name = v.decode()
            elif lf == 2:
                feats.append(v)
            elif lf == 3:
                keys.append(v.decode())
            elif lf == 4:
                (vf, vv), *_ = list(_fields(v))
                values.append(
                    {1: lambda x: x.decode(), 3: lambda x: struct.unpack("<d", x)[0], 5: int, 6: zz, 7: bool}[vf](vv)
                )
            elif lf == 5:
                extent = v
            elif lf == 15:
                version = v
        assert version == 2 and extent == 4096
        rows = []
        for ft in feats:
            fid, tags, gtype, geom = None, [], None, []
            for ff, v in _fields(ft):
                if ff == 1:
                    fid = v
                elif ff == 2:
                    tags = _packed(v)
                elif ff == 3:
                    gtype = v
                elif ff == 4:
                    geom = _packed(v)
            pts, i, x, y = [], 0, 0, 0
            while i < len(geom):
                cmd, cnt = geom[i] & 7, geom[i] >> 3
                i += 1
                for _ in range(cnt):
                    x, y = x + zz(geom[i]), y + zz(geom[i + 1])
                    i += 2
                    pts.append((cmd, x, y))
            props = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags), 2)}
            rows.append((gtype, pts, props, fid))
        out[name] = rows
    return out


# ------------------------------------------------------------------ a hand-made atlas
def make_atlas(folder: Path) -> tuple[Path, list[tuple[float, float]], np.ndarray]:
    rng = np.random.default_rng(3)
    pts = [(120 + 250 * (i % 5) + rng.uniform(-40, 40), 120 + 220 * (i // 5) + rng.uniform(-40, 40)) for i in range(15)]
    icons = [[] for _ in pts]
    for i, names in {0: ["Breach"], 2: ["Ritual"], 4: ["MapBoss"], 6: ["Breach", "Delirium"], 10: ["Abyss"]}.items():
        icons[i] = names
    nodes = [
        {"id": i, "x": x, "y": y, "status": "confirmed", "seen": 2, "could": 2, "frames": [0], "tower": i == 7,
         "origin": "detected", "icons": icons[i], "abyss": "", "why": ""}
        for i, (x, y) in enumerate(pts)
    ]  # fmt: skip
    nodes.append({**nodes[0], "id": 15, "x": 30.0, "y": 30.0, "status": "removed", "icons": [], "why": "ghost"})
    paths = [
        {"a": i, "b": i + 1, "kind": "trace", "frames": 2, "seen_in": 2, "both_ends": True, "abyss": False}
        for i in range(15)
        if i % 5 < 4
    ]
    a, b = pts[2], pts[7]
    paths.append({"a": 2, "b": 7, "kind": "trace", "frames": 1, "seen_in": 1, "abyss": True,
                  "line": [list(a), [a[0] + 90, (a[1] + b[1]) / 2], list(b)]})  # fmt: skip
    paths.append({"a": 0, "b": 15, "kind": "trace", "frames": 1, "seen_in": 1, "abyss": False})  # to the removed one
    at = core.Atlas()
    at.frames = [{"name": "a", "path": str(folder / "a.png"), "w": 1920, "h": 1080, "M": [[1, 0, 0], [0, 1, 0]],
                  "stats": {}}]  # fmt: skip
    at.final = {
        "nodes": nodes,
        "paths": paths,
        "landmarks": [{"kind": "Vaal city", "x": pts[4][0], "y": pts[4][1] - 50, "status": "kept"}],
        "icons": [],
        "stats": {},
    }
    at.bookmarks = [{"name": "farm <here>", "group": "g", "note": "", "x": pts[6][0], "y": pts[6][1]}]
    path = folder / "atlas.json"
    at.save(path)
    img = cv2.GaussianBlur(rng.integers(0, 255, (IMG_H, IMG_W, 3)).astype(np.uint8), (0, 0), 4)
    img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
    img[:, 1030:] = 0  # unexplored: no tiles there (the image ends at 1500)
    png, npz = core.map_image_files(path)
    core.write_png(png, img, "map image")
    np.savez_compressed(npz, key=at.terrain_key(), origin=np.array([0.0, 0.0, 1.0]), weight=np.ones((1, 1)))
    return path, pts, img


def _web_px(lng: float, lat: float, world: int) -> tuple[float, float]:
    """Longitude / latitude -> world px (the inverse of Grid.lnglat)."""
    wx = (lng + 180.0) / 360.0 * world
    wy = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * world
    return wx, wy


# ------------------------------------------------------------------ tests
def test_mvt_roundtrip():
    lay = Layer("things", 4096)
    lay.add("point", [(10, 4000)], {"s": "a|b", "n": 3, "neg": -2, "f": 1.5, "ok": True}, fid=7)
    lay.add("line", [(0, 0), (100, -50), (4196, 300)], {"s": "a|b"})
    t = read_tile(encode_tile([lay, Layer("empty", 4096)]))
    assert set(t) == {"things"}  # empty layers are left out
    (g1, p1, props1, id1), (g2, p2, props2, _id2) = t["things"]
    assert g1 == 1 and p1 == [(1, 10, 4000)] and id1 == 7
    assert props1 == {"s": "a|b", "n": 3, "neg": -2, "f": 1.5, "ok": True}
    assert g2 == 2 and [(x, y) for _c, x, y in p2] == [(0, 0), (100, -50), (4196, 300)]
    assert [c for c, *_ in p2] == [1, 2, 2] and props2 == {"s": "a|b"}


def test_clip_line_keeps_the_part_inside():
    pieces = _clip_line([(-1000, 100), (1000, 100), (1000, 5000)], -10, 4106)
    assert pieces == [[(-10, 100), (1000, 100), (1000, 4106)]]
    assert _clip_line([(-500, -500), (-400, -300)], 0, 4096) == []


def test_grid_keeps_points_inside_the_world():
    g = Grid((0, 0, 1), 5000, 3000)
    assert g.world >= 2 * 5000  # the picture fills at most the middle half
    (w, s), (e, n) = g.bounds()
    assert -180 < w < e < 180 and -80 < s < n < 80
    wx, wy = _web_px(*g.lnglat(1234.5, 678.9), g.world)
    assert abs(wx - (1234.5 + g.offset)) < 1e-3 and abs(wy - (678.9 + g.offset)) < 1e-3


def test_export_tiles_match_the_atlas():
    with tempfile.TemporaryDirectory() as tmp:
        path, pts, img = make_atlas(Path(tmp))
        web = export_webmap(path)
        info = json.loads((web / "atlas.json").read_text(encoding="utf-8"))
        zmax, T = info["zmax"], 256
        grid = Grid((0, 0, 1), IMG_W, IMG_H)
        assert zmax == grid.zmax
        for f in ("index.html", "app.js", "style.css", "meta.json"):
            assert (web / f).is_file(), f

        # the most detailed terrain tiles put together give the map image back (JPEG: close, not exact)
        canvas = np.zeros((grid.world // 2, grid.world // 2, 3), np.uint8)
        for f in (web / "terrain" / str(zmax)).glob("*/*.jpg"):
            tx, ty = int(f.parent.name), int(f.stem)
            tile = cv2.imdecode(np.fromfile(str(f), np.uint8), cv2.IMREAD_COLOR)
            x, y = tx * T - grid.offset, ty * T - grid.offset
            canvas[y : y + T, x : x + T] = tile
        diff = np.abs(canvas[:IMG_H, :IMG_W].astype(int) - img.astype(int))
        assert diff.mean() < 4, diff.mean()
        # one tile for every 256 px square holding some ground; none over unexplored (black) ground
        want = 0
        for ty in range(grid.offset // T, (grid.offset + IMG_H - 1) // T + 1):
            for tx in range(grid.offset // T, (grid.offset + IMG_W - 1) // T + 1):
                x0, y0 = max(0, tx * T - grid.offset), max(0, ty * T - grid.offset)
                want += bool(img[y0 : ty * T - grid.offset + T, x0 : tx * T - grid.offset + T].any())
        assert len(list((web / "terrain" / str(zmax)).glob("*/*.jpg"))) == want

        # every kept map node is in the most detailed vector tiles, where its atlas position says
        found = {}
        for f in (web / "vector" / str(zmax)).glob("*/*.pbf"):
            tx, ty = int(f.parent.name), int(f.stem)
            for _g, ((_c, x, y),), props, fid in read_tile(f.read_bytes()).get("maps", []):
                if 0 <= x < 4096 and 0 <= y < 4096:  # (copies in the buffer of a neighbour tile are skipped)
                    found[fid] = (tx * T + x / 16, ty * T + y / 16, props)
        assert sorted(found) == list(range(15))  # the removed map node is left out
        for i, (x, y) in enumerate(pts):
            wx, wy, props = found[i]
            assert abs(wx - (x + grid.offset)) <= 0.05 and abs(wy - (y + grid.offset)) <= 0.05, (i, wx, x)
            assert props["id"] == i and props["status"] == "confirmed"
        assert found[6][2]["icons"] == "|Breach|Delirium|"

        # the page data: positions, paths (not the one to the removed map node), icon names, landmark, bookmark
        assert len(info["nodes"]) == 15 and len(info["edges"]) == 13
        for nd, (x, y) in zip(info["nodes"], pts, strict=True):
            wx, wy = _web_px(*nd["c"], grid.world)
            assert abs(wx - (x + grid.offset)) < 0.01 and abs(wy - (y + grid.offset)) < 0.01
        curved = [e for e in info["edges"] if "l" in e]
        assert len(curved) == 1 and (curved[0]["a"], curved[0]["b"]) == (2, 7) and len(curved[0]["l"]) == 3
        assert info["icons"]["Breach"]["label"] == "Breach" and info["icons"]["Breach"]["colour"].startswith("#")
        assert info["landmarks"][0]["kind"] == "Vaal city"
        assert info["bookmarks"][0]["name"] == "farm <here>"
        assert info["maxzoom"] > zmax - 1

        # an unchanged atlas is not exported again; a changed one is
        assert is_current(path)
        stamp = (web / "meta.json").stat().st_mtime_ns
        export_webmap(path)
        assert (web / "meta.json").stat().st_mtime_ns == stamp
        at = core.Atlas.load(path)
        at.bookmarks.append({"name": "new", "group": "", "note": "", "x": 1.0, "y": 1.0})
        at.save(path)
        assert not is_current(path)
        export_webmap(path)
        assert is_current(path)
        assert not web.with_name("web.new").exists() and not web.with_name("web.old").exists()


def test_server_serves_the_folder():
    with tempfile.TemporaryDirectory() as tmp:
        path, _pts, _img = make_atlas(Path(tmp))
        web = export_webmap(path)
        server = make_server(web, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = url_of(server)
            assert url.startswith("http://127.0.0.1:")
            with urllib.request.urlopen(url) as r:
                assert r.status == 200 and b"maplibre-gl" in r.read()
            tile = next((web / "vector").glob("*/*/*.pbf")).relative_to(web).as_posix()
            with urllib.request.urlopen(url + tile) as r:
                assert r.headers["Content-Type"] == "application/x-protobuf"
                assert read_tile(r.read())
            with urllib.request.urlopen(url + "terrain/0/9/9.jpg") as r:  # no ground there: a black tile, not 404
                assert r.headers["Content-Type"] == "image/jpeg" and r.read()[:2] == b"\xff\xd8"
            with urllib.request.urlopen(url + "vector/9/0/0.pbf") as r:  # nothing there: an empty vector tile
                assert r.read() == b""
            try:
                urllib.request.urlopen(url + "nothing.txt")
                raise AssertionError("a missing file was served")
            except urllib.error.HTTPError as e:
                assert e.code == 404
            with urllib.request.urlopen(url + "atlas.json") as r:
                assert json.loads(r.read())["title"] == "atlas"
        finally:
            server.shutdown()
            server.server_close()


def test_viewer_model_loads_without_a_window():
    # the export runs as its own process and uses the viewer's model; that must not need Tk or a display
    code = "import sys, grand_project.webmap.export; sys.exit('tkinter' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    print("PASS: web map")
