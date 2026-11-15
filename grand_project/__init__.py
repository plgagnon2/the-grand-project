"""The Grand Project: builds one big map of your Path of Exile 2 atlas from your screenshots.

    python -m grand_project                 the viewer (reopens the last atlas)
    python -m grand_project my_atlas.json   the viewer on that atlas
    python -m grand_project.builder ...     build an atlas without the window
    python -m grand_project.detect score    score the detector (needs the test data)
    python -m grand_project.webmap ATLAS    the atlas as a web map in the browser (MapLibre)

Package layout: paths (every folder location), core (screenshots, geometry, placement, the atlas file),
detect (the screenshot detector), finalize (the atlas-wide clean-up), builder (adding screenshots),
cities, towers, viewer (the window), webmap (the atlas in a browser). Each larger part keeps its tunable numbers
in its constants.py.
"""

__version__ = "1.13"  # +1 per round of changes; the window title, README and pyproject.toml show the same
