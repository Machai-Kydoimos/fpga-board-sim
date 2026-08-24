"""The environment holds exactly one pygame distribution, and it is pygame-ce.

``pygame`` and ``pygame-ce`` are two different distributions that install into
the *same* ``pygame/`` import directory, and pip does not treat that as a
conflict.  Installing pygame-ce into an environment that already has upstream
pygame appears to succeed: both are listed by ``pip list``, ``pip check``
reports nothing wrong, and pygame-ce's files simply overwrite pygame's.  The
damage lands later -- the natural cleanup, ``pip uninstall pygame``, deletes
files that now belong to pygame-ce, and the next ``import pygame`` raises
``AttributeError: module 'pygame' has no attribute 'init'`` with nothing to
suggest a packaging cause.

``uv sync`` -- the documented install path -- swaps the two atomically and can
never produce this state, so this guard is aimed squarely at a pip-managed
environment.  It is nearly free and converts a baffling runtime failure into a
message that says what to do.

The second test pins the *declaration* rather than the environment.  The choice
of fork is a decision with reasons (upstream's last release predates Python
3.13's wheels; pygame-ce carries ~2.5 years of newer bundled SDL), and a
one-word edit to ``pyproject.toml`` would silently undo it -- with every test
still passing, because the code is written against the API both share.
"""

from __future__ import annotations

import sys
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

PROJECT = Path(__file__).parent.parent
PYGAME_DISTRIBUTIONS = {"pygame", "pygame-ce"}


def _installed_pygame_distributions() -> list[str]:
    """Return the pygame-family distribution names visible to this interpreter."""
    found = set()
    for dist in distributions():
        name = dist.metadata["Name"]
        if name and name.lower() in PYGAME_DISTRIBUTIONS:
            found.add(name.lower())
    return sorted(found)


def _declared_dependencies() -> list[str]:
    with (PROJECT / "pyproject.toml").open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    deps: list[str] = data["project"]["dependencies"]
    return deps


def test_exactly_one_pygame_distribution_is_installed():
    installed = _installed_pygame_distributions()
    assert len(installed) == 1, (
        f"found {len(installed)} pygame distributions installed: {installed}. "
        "pygame and pygame-ce share the same 'pygame/' import directory, so "
        "having both is a corrupted environment even though pip reports it as "
        "healthy -- and uninstalling either one will delete files the other "
        "needs. Fix: uninstall both, then reinstall (uv sync, or "
        "'pip install pygame-ce'). See docs/install.md."
    )


def test_the_installed_distribution_is_pygame_ce():
    assert _installed_pygame_distributions() == ["pygame-ce"], (
        "expected pygame-ce; upstream pygame is a different distribution whose "
        "last release (2.6.1, 2024-09-29) ships no wheels past cp313 and bundles "
        "SDL 2.28.4. Run 'uv sync' to install what pyproject.toml declares."
    )


def test_pyproject_declares_pygame_ce():
    deps = _declared_dependencies()
    pygame_deps = [
        d for d in deps if d.split(">=")[0].split("[")[0].strip().lower() in PYGAME_DISTRIBUTIONS
    ]
    assert pygame_deps == ["pygame-ce>=2.5.8"], (
        f"pyproject.toml declares {pygame_deps!r}. Depending on upstream 'pygame' "
        "again would install a different distribution over the same import name; "
        "and note the two version lines are not comparable -- pygame-ce's latest "
        "(2.5.8) is numerically lower than upstream's (2.6.1), so a 'pygame-ce>=2.6' "
        "pin is unsatisfiable."
    )
