"""webmap.server: serves a web map folder on 127.0.0.1 so the browser can load its tiles.

Browsers do not load tiles from file:// pages, so the folder is served over local HTTP. Only this computer can
reach it (127.0.0.1); the server runs until its process is stopped.
"""

from __future__ import annotations

import functools
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from .constants import WEBMAP_HOST, WEBMAP_PORT, WEBMAP_TILE

_TILE = re.compile(r"^/(terrain|vector)/\d+/\d+/\d+\.(jpg|pbf)$")


@functools.cache
def _black_tile() -> bytes:
    """Return a black JPEG tile (the page's background colour), sent for terrain tiles with no ground.

    Returns:
        The JPEG bytes.
    """
    return cv2.imencode(".jpg", np.zeros((WEBMAP_TILE, WEBMAP_TILE, 3), np.uint8))[1].tobytes()


class _Handler(SimpleHTTPRequestHandler):
    """Static files with the vector tile type, no caching of the atlas data, and no request log.

    Tiles that were not written (no ground, nothing on the map there) are answered with an empty tile instead of
    "not found": MapLibre reports every missing tile as an error in the browser console.
    """

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".pbf": "application/x-protobuf",
        ".js": "text/javascript",
        ".json": "application/json",
    }

    def send_head(self):
        """Serves a file, or an empty tile for a tile that was not written.

        Returns:
            The open file (or a bytes buffer) for do_GET to copy out, or None after an error response.
        """
        path = self.path.split("?", 1)[0]
        if _TILE.match(path) and not Path(self.translate_path(path)).is_file():
            import io

            body = _black_tile() if path.endswith(".jpg") else b""  # an empty vector tile is a valid one
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg" if path.endswith(".jpg") else "application/x-protobuf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return io.BytesIO(body)
        return super().send_head()

    def end_headers(self):
        """Adds no-cache headers, so a re-exported map shows at the next page load."""
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):  # noqa: A002 (the base class's name)
        """Drops the per-request log line (hundreds of tile requests)."""


def make_server(folder: Path, port: int = WEBMAP_PORT) -> ThreadingHTTPServer:
    """Create (not start) the server for a web map folder.

    Args:
        folder: The web map folder.
        port: Port to listen on; 0 lets the system pick a free one.

    Returns:
        The server; its URL is url_of(server).
    """
    handler = functools.partial(_Handler, directory=str(folder))
    return ThreadingHTTPServer((WEBMAP_HOST, port), handler)


def url_of(server: ThreadingHTTPServer) -> str:
    """Return the page address of a server.

    Args:
        server: A server from make_server.

    Returns:
        "http://127.0.0.1:<port>/".
    """
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"
