"""Tests for the implicit-encoding checker.

Two jobs here. The unit tests pin the detection rules -- particularly the
exclusions, where a false positive would tell someone to add an ``encoding``
kwarg to a call that raises ``TypeError`` on one. The repo-wide test is what
actually enforces the rule in CI: the pre-commit hook only covers people who
have hooks installed and did not pass ``--no-verify``, and CI runs the lint
tools directly rather than through pre-commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_encoding import check_paths, check_source  # noqa: E402

PROJECT = Path(__file__).parent.parent
SCRIPT = PROJECT / "scripts" / "check_encoding.py"


def _findings(src):
    return check_source(src, "probe.py")


# --- the sites ruff PLW1514 cannot see -------------------------------------


def test_flags_read_text_on_an_uninferable_receiver():
    """The SESSION_FILE shape: ruff reports nothing here."""
    assert _findings("SESSION_FILE.read_text()")


def test_flags_a_derived_path():
    """The tmp_path shape that makes most of this suite invisible to ruff."""
    assert _findings('(tmp_path / "b.vhdl").write_text("-- b")')


def test_flags_subprocess_text_mode():
    """PLW1514 does not inspect subprocess at all."""
    assert _findings("subprocess.run(cmd, capture_output=True, text=True)")


def test_flags_universal_newlines_as_text_mode():
    """The older spelling of text=True decodes just the same."""
    assert _findings("subprocess.run(cmd, universal_newlines=True)")


def test_flags_bare_builtin_open_and_path_open():
    assert _findings("open(p)")
    assert _findings("p.open()")


# --- exclusions: a false positive here would be actively harmful -----------


def test_accepts_an_explicit_encoding():
    assert not _findings('p.read_text(encoding="utf-8")')
    assert not _findings('subprocess.run(cmd, text=True, encoding="utf-8")')


def test_ignores_binary_modes():
    assert not _findings('open(p, "rb")')
    assert not _findings('p.open("wb")')
    assert not _findings('open(p, mode="rb")')


def test_ignores_openers_that_take_no_encoding():
    """tarfile/gzip/PIL raise TypeError if handed an encoding kwarg."""
    assert not _findings('tarfile.open(fileobj=b, mode="r:gz")')
    assert not _findings("Image.open(p)")
    assert not _findings("gzip.open(p)")


def test_binary_check_reads_the_mode_position_not_the_payload():
    """Regression: write_text takes its payload positionally.

    Scanning every positional string for a ``b`` classifies
    ``'{"type": "object"}'`` as binary mode -- because *object* contains a b --
    and silently skips a real site. This shape was missed on the first sweep.
    """
    assert _findings('p.write_text(\'{"type": "object"}\')')
    assert _findings('p.write_text("-- b\\n")')
    assert _findings('p.write_text("#!/bin/sh\\ntrue\\n")')


def test_subprocess_without_text_mode_is_binary_and_fine():
    """No text=True means bytes come back undecoded; encoding would be meaningless."""
    assert not _findings("subprocess.run(cmd, capture_output=True)")


def test_a_lookalike_keyword_is_not_text_mode():
    """`with_text=True` is a different parameter; the repo has one."""
    assert not _findings("draw_bar(surface, track, with_text=True)")


# --- enforcement -----------------------------------------------------------


def test_repo_is_clean():
    """No implicit-encoding site anywhere in the tree.

    This is the check that runs in CI. The pre-commit hook is only a faster
    local path to the same answer.
    """
    files = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.split()
    findings = check_paths([PROJECT / f for f in files])
    assert not findings, "implicit text encoding:\n" + "\n".join(findings)


def test_cli_reports_and_exits_nonzero(tmp_path):
    """Exit status drives the pre-commit hook, so it has to be right."""
    bad = tmp_path / "bad.py"
    bad.write_text("p.read_text()\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bad)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 1
    assert "without encoding=" in result.stdout


def test_cli_exits_zero_on_a_clean_file(tmp_path):
    good = tmp_path / "good.py"
    good.write_text('p.read_text(encoding="utf-8")\n', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(good)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0


def test_cli_without_arguments_is_a_usage_error():
    """pre-commit passes filenames; a no-arg call must not silently pass."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 2
