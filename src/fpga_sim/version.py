"""The one place that answers "which build of the simulator is this?".

Nothing else in the project stamps a version into its output -- not the session
logs, not ``manifest.json``, not ``session.json`` -- so this module exists for
the inspect overlay (U55), whose whole job is to let somebody quote what they
were looking at.  A report that names a region but not a build is only half an
address: the region may have moved, been renamed, or not existed yet.

Two facts, in order of reliability:

*The distribution version* comes from installed metadata rather than from
``pyproject.toml``.  Reading the TOML works from a checkout and fails from a
wheel, which is exactly backwards -- the installed case is the one where the
source tree may not be there to read.

*The commit* is a courtesy for checkouts, and only that.  ``git describe``
is shelled out to once, lazily, behind a cache, because the overlay redraws at
frame rate and a subprocess per frame would be absurd.  Every failure mode --
no git, no repository, a git that hangs -- degrades to the bare version rather
than raising, because a version stamp must never be the reason a UI frame does
not paint.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from fpga_sim.paths import REPO_ROOT

#: The installed distribution name (``pyproject.toml`` ``[project] name``).
_DIST = "fpga-simulator"

#: Shown when the package is not installed and its metadata cannot be read.
_UNKNOWN = "0.0.0+unknown"

#: Seconds to wait for ``git describe`` before giving up on the commit suffix.
_GIT_TIMEOUT_S = 2.0


def _package_version() -> str:
    """Return the installed distribution version, or a marker when absent."""
    try:
        return _dist_version(_DIST)
    except PackageNotFoundError:
        return _UNKNOWN


def _git_short_hash() -> str | None:
    """Return the repository's short commit hash, or None when unavailable.

    Never raises.  A missing ``git``, a source tree that is not a checkout, and
    a hung invocation all read the same way here: there is no commit to add.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            # Third-party output: a stray byte in a hash should never be the
            # reason a version string cannot be built.
            errors="replace",
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


@lru_cache(maxsize=1)
def app_version() -> str:
    """Return the build identifier, e.g. ``0.22.0+g9c6590e`` or ``0.22.0``.

    Cached: the overlay asks for this every frame it paints, and the answer
    cannot change inside one process.
    """
    base = _package_version()
    commit = _git_short_hash()
    return f"{base}+g{commit}" if commit else base
