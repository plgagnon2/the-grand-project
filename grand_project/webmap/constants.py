"""webmap.constants: the numbers of the web map (MapLibre) export and its local server."""

from __future__ import annotations

# Bumped when the files written change shape, so an older export is rebuilt instead of reused.
WEBMAP_FORMAT = 1

# Raster tiles (the stitched map image): 256 px squares in the usual z/x/y layout, as JPEG. The map image is the
# most detailed level, so 1 tile px = 1 map image px there.
WEBMAP_TILE = 256
WEBMAP_JPEG_QUALITY = 85  # a 256 px terrain tile is ~25 KB at 85; PNG would be ~5x bigger for the same picture
WEBMAP_TERRAIN_PIXELS = 40_000_000  # map image size limit when there is no cached one; the viewer's TERRAIN_PIXELS

# Vector tiles (Mapbox Vector Tile 2.1: map nodes, paths, landmarks, bookmarks).
WEBMAP_MVT_EXTENT = 4096  # tile coordinate range (the MVT default)
WEBMAP_MVT_BUFFER = 128  # extent units kept around each tile, so lines and dots crossing a tile edge draw whole

# How far past the most detailed tiles the page lets the user zoom in (MapLibre stretches the last level).
WEBMAP_OVERZOOM = 2.5

# Local server: 127.0.0.1 only (the map is the player's own data), on a free port chosen by the system.
WEBMAP_HOST = "127.0.0.1"
WEBMAP_PORT = 0

# Colours (CSS) of the map node states, as the viewer draws them.
WEBMAP_STATUS_COLOUR = {
    "confirmed": "#28dcff",  # 2+ screenshots agree
    "icon": "#28dcff",  # placed from its icon
    "single": "#ffa000",  # one screenshot
    "disputed": "#ffa000",
    "doubtful": "#969696",
}
WEBMAP_NO_ICON_FILL = "#1b1e24"  # map node without an icon
