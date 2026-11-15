"""PoE2 Atlas viewer: browse, search and bookmark a merged atlas, and add screenshots to it.

    python -m grand_project.viewer                      (reopens the last atlas)
    python -m grand_project.viewer my_atlas.json

Mouse:  wheel = zoom at cursor, drag = pan, click = select, double-click = zoom in,
        right-click = bookmark here / show source screenshots.
Keys:   + / - zoom, 0 fit, arrows pan, Ctrl+F search, Ctrl+B bookmark selection,
        Ctrl+O open, Ctrl+S save (Cmd instead of Ctrl on macOS), Delete remove selected bookmark.

Shows the atlas-wide result (atlas["final"]): nodes and paths checked against every screenshot.
The atlas file is the same JSON the command-line builder writes; bookmarks are stored in it.
"""

from .constants import VERSION  # noqa: F401


def __getattr__(name):
    """Loads the window (and Tk) only when Viewer or main is asked for, so the viewer's data model and constants can
    be used without a display (the web map export runs as its own process).
    """
    if name in ("Viewer", "main"):
        from . import app

        return getattr(app, name)
    raise AttributeError(name)
