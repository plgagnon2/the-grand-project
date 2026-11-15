"""webmap: the atlas as a web map (MapLibre): raster tiles of the map image, vector tiles of map nodes and paths,
search and directions in the browser.

    python -m grand_project.webmap my_atlas.json            export (when changed), serve and open the browser
    python -m grand_project.webmap my_atlas.json --no-serve  only export, into <atlas>_files/web/
"""

from .export import export_webmap, is_current, web_folder  # noqa: F401
from .server import make_server, url_of  # noqa: F401
