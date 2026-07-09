"""Tests for platform_open.open_with_default_app (extracted from error_dialog, U29)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpga_sim.platform_open import open_with_default_app

EXAMPLE = Path("/tmp/example.vhd")


def test_linux_uses_xdg_open(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("fpga_sim.platform_open.sys.platform", "linux")
    monkeypatch.setattr(
        "fpga_sim.platform_open.subprocess.Popen",
        lambda argv, **kw: calls.append(argv),
    )
    open_with_default_app(EXAMPLE)
    assert calls == [["xdg-open", str(EXAMPLE)]]


def test_darwin_uses_open(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr("fpga_sim.platform_open.sys.platform", "darwin")
    monkeypatch.setattr(
        "fpga_sim.platform_open.subprocess.Popen",
        lambda argv, **kw: calls.append(argv),
    )
    open_with_default_app(EXAMPLE)
    assert calls == [["open", str(EXAMPLE)]]


def test_win32_uses_startfile(monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr("fpga_sim.platform_open.sys.platform", "win32")
    # os.startfile exists only on Windows, so add it for the test (raising=False).
    monkeypatch.setattr("fpga_sim.platform_open.os.startfile", calls.append, raising=False)
    open_with_default_app(EXAMPLE)
    assert calls == [EXAMPLE]


def test_failure_is_swallowed(monkeypatch, capsys):
    def _boom(*a: Any, **kw: Any) -> None:
        raise OSError("no opener")

    monkeypatch.setattr("fpga_sim.platform_open.sys.platform", "linux")
    monkeypatch.setattr("fpga_sim.platform_open.subprocess.Popen", _boom)
    open_with_default_app(EXAMPLE)  # must not raise
    assert "could not open" in capsys.readouterr().err
