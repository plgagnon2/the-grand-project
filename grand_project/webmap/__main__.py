"""python -m grand_project.webmap ATLAS.json [--force] [--no-serve] [--no-browser] [--port N]

Exports the atlas as a web map (when it changed) and serves it on 127.0.0.1 until stopped. Prints one status line
per step; "serving <url>" once the page can be opened (the viewer watches for it).
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .constants import WEBMAP_PORT
from .export import export_webmap
from .server import make_server, url_of


def main(argv: list[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments (default sys.argv[1:]).

    Returns:
        The exit code.
    """
    ap = argparse.ArgumentParser(prog="python -m grand_project.webmap", description=__doc__.splitlines()[2])
    ap.add_argument("atlas", type=Path, help="the atlas .json file")
    ap.add_argument("--force", action="store_true", help="rebuild the web map even when it is up to date")
    ap.add_argument("--no-serve", action="store_true", help="only export, do not start the local server")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--port", type=int, default=WEBMAP_PORT, help="port (default: a free one)")
    args = ap.parse_args(argv)
    if not args.atlas.is_file():
        print(f"no atlas at {args.atlas}", file=sys.stderr)
        return 2

    def say(line: str) -> None:
        """Print a status line at once (the viewer reads them as they come).

        Args:
            line: The status line.
        """
        print(line, flush=True)

    folder = export_webmap(args.atlas, force=args.force, progress=say)
    if args.no_serve:
        say(f"web map in {folder}")
        return 0
    server = make_server(folder, args.port)
    url = url_of(server)
    say(f"serving {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
