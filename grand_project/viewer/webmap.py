"""viewer.webmap: part of the Viewer window (a mixin; see viewer/app.py): File > Open web map."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from grand_project.webmap import is_current

from .helpers import LOG


class WebMapMixin:
    """Viewer mixin for the web map: the atlas in the browser (MapLibre), exported and served by its own process.

    `python -m grand_project.webmap` writes the tiles (only when the atlas changed) and serves them on 127.0.0.1;
    a process, not a thread, so the export does not starve the window. It runs until the viewer closes.
    """

    def open_web_map(self):
        """Opens the atlas in the browser (File > Open web map).

        The atlas is saved first, so the web map shows what the window shows. A server still running for an
        unchanged atlas just gets its page opened again; otherwise it is stopped and a new one started, which
        exports what changed.
        """
        if not self.atlas or not self.path or not self.atlas.frames:
            self.log("web map: open an atlas with screenshots first")
            return
        self.save()
        proc = getattr(self, "_web_proc", None)
        url = getattr(self, "_web_url", None)
        if proc is not None and proc.poll() is None and url and self._web_for == self.path and is_current(self.path):
            webbrowser.open(url)  # same atlas, nothing changed since the export: the running server is fine
            return
        self.stop_web_map()
        root = Path(__file__).resolve().parents[2]  # the folder holding the grand_project package
        proc = subprocess.Popen(
            [sys.executable, "-m", "grand_project.webmap", str(self.path)],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        self._web_proc, self._web_url, self._web_for = proc, None, self.path
        self._set_progress("web map: starting…")
        self.log("web map: exporting the atlas for the browser")

        def watch():
            """Background thread: passes the process's status lines on and notes the page address."""
            tail = []
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                tail = (tail + [line])[-20:]
                if line.startswith("serving "):
                    self._web_url = line.split(" ", 1)[1]
                    self._q.put(("progress", None))
                    self._q.put(("log", f"web map: open at {self._web_url} (stops when the viewer closes)"))
                elif line.startswith("web map:"):
                    self._q.put(("progress", line))
            proc.wait()
            self._q.put(("progress", None))
            if proc.returncode not in (0, None) and not getattr(self, "_web_stopping", False):
                LOG.error("web map failed: %s", " | ".join(tail))
                self._q.put(("log", f"web map failed: {tail[-1] if tail else proc.returncode}"))

        threading.Thread(target=watch, daemon=True).start()

    def stop_web_map(self):
        """Stops the web map server, if one is running (the browser page then stops loading new tiles)."""
        proc = getattr(self, "_web_proc", None)
        if proc is not None and proc.poll() is None:
            self._web_stopping = True
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=3)
            self._web_stopping = False
        self._web_proc, self._web_url = None, None
