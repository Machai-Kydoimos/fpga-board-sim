"""The two halves of the implicit-encoding guard stay wired up.

Text I/O without an explicit ``encoding=`` uses the locale default, which is
cp1252 on Windows and UTF-8 elsewhere, so the same bytes decode to different
text per platform -- and because cp1252 maps almost every byte, the usual
result is silent mojibake rather than an exception.

Two checks cover that, and neither is sufficient alone:

* ruff ``PLW1514`` -- static, but only where ruff can prove the receiver is a
  ``Path``.  It cannot see an unannotated ``tmp_path`` fixture, so most of this
  suite is invisible to it.
* ``EncodingWarning`` promoted to an error -- runtime, needs no inference, but
  only covers code a test actually runs.

Both are plain configuration, so either could be dropped in an unrelated edit
and nothing would fail; the guard would just quietly stop guarding.  These
tests are the tripwire for that.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

PROJECT = Path(__file__).parent.parent
CI_WORKFLOW = PROJECT / ".github" / "workflows" / "ci.yml"


def _pyproject() -> dict[str, Any]:
    with (PROJECT / "pyproject.toml").open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    return data


def test_ruff_selects_the_unspecified_encoding_rule():
    """The static half: PLW1514 is selected."""
    assert "PLW1514" in _pyproject()["tool"]["ruff"]["lint"]["select"]


def test_ruff_preview_is_on_but_scoped_to_named_rules():
    """PLW1514 is preview-only, so preview must be on -- and fenced in.

    Without ``explicit-preview-rules`` this enrols the repo in every other
    preview rule too (six unrelated ones fire today).
    """
    lint = _pyproject()["tool"]["ruff"]["lint"]
    assert lint.get("preview") is True
    assert lint.get("explicit-preview-rules") is True


def test_preview_is_not_enabled_for_the_formatter():
    """Preview belongs under [lint]; at [tool.ruff] it also changes format style."""
    assert "preview" not in _pyproject()["tool"]["ruff"]


def test_pytest_promotes_encoding_warnings_to_errors():
    """The runtime half: an EncodingWarning fails the suite rather than scrolling past."""
    filters = _pyproject()["tool"]["pytest"]["ini_options"]["filterwarnings"]
    assert "error::EncodingWarning" in filters


def test_ci_actually_emits_encoding_warnings():
    """The filter above is inert unless CPython is told to emit the warnings.

    Without ``PYTHONWARNDEFAULTENCODING=1`` no EncodingWarning is ever raised,
    so the filter would pass vacuously and the runtime half would be dead.
    """
    assert "PYTHONWARNDEFAULTENCODING" in CI_WORKFLOW.read_text(encoding="utf-8")
