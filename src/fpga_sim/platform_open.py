"""Open a file with the host platform's default application.

A tiny, UI-free helper shared by the error dialog's [View Example] button (U4)
and the waveform auto-open fallback (U29), so neither imports the other and
``sim_bridge`` stays free of UI imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_with_default_app(path: Path) -> None:
    """Open *path* with the platform's default application (best-effort).

    Detached so it never blocks the caller, and swallows failures (a missing
    handler must not crash the launcher) — the caller has already printed a
    usable path.
    """
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], start_new_session=True)
        else:
            subprocess.Popen(["xdg-open", str(path)], start_new_session=True)
    except OSError as e:
        print(f"[platform_open] could not open {path}: {e}", file=sys.stderr, flush=True)
