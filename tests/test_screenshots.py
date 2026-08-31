"""Tests for --screenshots on the benchmark path (issue #129).

Three layers: the ``ScreenshotRecorder`` gate in isolation (pure decisions, no
display), the ``SimulationScreen`` wiring that feeds it, and the ``__main__``
flag validation that rejects the unusable combinations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fpga_sim.ui.screenshots import COARSE_LEVELS, ScreenshotRecorder


@pytest.fixture(autouse=True)
def _isolate_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect session writes away from ~/.fpga_simulator for every test."""
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr("fpga_sim.sim_session_log._SESSION_DIR", tmp_path / "sessions")


@pytest.fixture
def surface(headless_pygame: Any) -> Any:
    """A small off-screen surface — ``capture`` only needs something PNG-saveable."""
    return headless_pygame.Surface((32, 24))


# ── The gate, in isolation ────────────────────────────────────────────────────

_SIG_A: tuple[object, ...] = (1, 2, 3)
_SIG_B: tuple[object, ...] = (1, 2, 4)


def _rec(tmp_path: Path, **kw: Any) -> ScreenshotRecorder:
    return ScreenshotRecorder(tmp_path / "shots", **kw)


def test_creates_the_output_directory(tmp_path: Path) -> None:
    rec = _rec(tmp_path)
    assert rec.out_dir.is_dir()


def test_existing_directory_and_its_files_survive(tmp_path: Path) -> None:
    out = tmp_path / "shots"
    out.mkdir()
    (out / "keepme.txt").write_text("previous run", encoding="utf-8")
    ScreenshotRecorder(out)
    assert (out / "keepme.txt").read_text(encoding="utf-8") == "previous run"


def test_first_frame_is_always_due(tmp_path: Path) -> None:
    assert _rec(tmp_path).due(_SIG_A, 0.0)


def test_due_is_pure(tmp_path: Path) -> None:
    """Asking twice must answer the same — it runs on every frame."""
    rec = _rec(tmp_path)
    assert rec.due(_SIG_A, 0.0) and rec.due(_SIG_A, 0.0)


def test_change_is_rate_limited(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path, min_gap_s=0.25, interval_s=1.0)
    rec.capture(surface, _SIG_A, 0.0)
    assert not rec.due(_SIG_B, 0.10)  # changed, but too soon after the last shot
    assert rec.due(_SIG_B, 0.25)  # changed, and the gap has elapsed


def test_unchanged_waits_for_the_liveness_interval(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path, min_gap_s=0.25, interval_s=1.0)
    rec.capture(surface, _SIG_A, 0.0)
    assert not rec.due(_SIG_A, 0.5)  # unchanged: the min gap is not enough
    assert rec.due(_SIG_A, 1.0)  # unchanged: but the trail shot is owed


def test_capture_writes_a_png_and_names_it_by_index_and_time(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path)
    first = rec.capture(surface, _SIG_A, 10.0)  # t0 is the first capture, not zero
    second = rec.capture(surface, _SIG_B, 11.5)
    assert first is not None and second is not None
    assert first.name == "shot_0001_t000.00s.png"
    assert second.name == "shot_0002_t001.50s.png"
    assert first.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert rec.saved == [first, second]


def test_limit_caps_files_and_counts_the_drops(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path, limit=2)
    for i in range(5):
        rec.capture(surface, (i,), float(i))
    assert len(rec.saved) == 2
    assert rec.dropped == 3
    assert len(list(rec.out_dir.glob("*.png"))) == 2


def test_summary_reports_count_and_directory(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path)
    assert "no frames captured" in rec.summary()
    rec.capture(surface, _SIG_A, 0.0)
    assert "1 PNGs" in rec.summary() and str(rec.out_dir) in rec.summary()


def test_summary_mentions_the_limit_only_when_it_bit(tmp_path: Path, surface: Any) -> None:
    rec = _rec(tmp_path, limit=1)
    rec.capture(surface, _SIG_A, 0.0)
    assert "dropped" not in rec.summary()
    rec.capture(surface, _SIG_B, 1.0)
    assert "1 dropped past the 1-frame limit" in rec.summary()


# ── The coarse signature the gate is fed ──────────────────────────────────────


def test_default_quantization_is_unchanged(headless_pygame: Any, fake_child: Any) -> None:
    """The U23 redraw gate must keep its 1000 levels: this is its regression guard."""
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    board = _make_screen(headless_pygame, child).board
    board.set_led_level(0, 0.5)
    assert board.visual_signature() == board.visual_signature(quantize=1000)


def test_coarse_quantization_ignores_a_sub_step_fade(headless_pygame: Any, fake_child: Any) -> None:
    """Two levels inside one coarse bucket read as the same frame; a real fade does not."""
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    board = _make_screen(headless_pygame, child).board
    board.set_led_level(0, 0.500)
    settled = board.visual_signature(quantize=COARSE_LEVELS)
    board.set_led_level(0, 0.505)  # a POV-easing step: same bucket
    assert board.visual_signature(quantize=COARSE_LEVELS) == settled
    assert board.visual_signature() != settled  # ...but U23 still sees it
    board.set_led_level(0, 0.80)  # a real change: different bucket
    assert board.visual_signature(quantize=COARSE_LEVELS) != settled


# ── SimulationScreen wiring ───────────────────────────────────────────────────


def test_no_recorder_without_the_flag(headless_pygame: Any, fake_child: Any) -> None:
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    assert _make_screen(headless_pygame, child).shots is None


def test_screen_captures_once_connected(
    headless_pygame: Any, fake_child: Any, tmp_path: Path
) -> None:
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    screen = _make_screen(headless_pygame, child, screenshot_dir=tmp_path / "out")
    assert screen.shots is not None
    screen._connected = True
    screen._render_frame()
    assert len(screen.shots.saved) == 1
    assert screen.shots.saved[0].exists()


def test_screen_skips_the_starting_splash(
    headless_pygame: Any, fake_child: Any, tmp_path: Path
) -> None:
    """Frames drawn before the child connects are the spinner, not the board."""
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    screen = _make_screen(headless_pygame, child, screenshot_dir=tmp_path / "out")
    assert screen.shots is not None
    screen._render_frame()  # not connected yet
    screen._render_frame()
    assert screen.shots.saved == []


def test_a_due_shot_forces_a_frame_u23_would_skip(
    headless_pygame: Any, fake_child: Any, tmp_path: Path
) -> None:
    """A static design still leaves a trail: the liveness shot un-skips its frame."""
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    screen = _make_screen(headless_pygame, child, screenshot_dir=tmp_path / "out")
    assert screen.shots is not None
    screen._connected = True
    screen._render_frame()  # first frame: drawn, captured
    drawn_after_first = screen.run_stats.frames_drawn

    screen._render_frame()  # nothing changed, no shot owed -> skipped
    assert screen.run_stats.frames_drawn == drawn_after_first

    # Jump past the liveness interval; the shot is owed, so the frame must draw.
    screen.shots.interval_s = 0.0
    screen._render_frame()
    assert screen.run_stats.frames_drawn == drawn_after_first + 1
    assert len(screen.shots.saved) == 2


# ── CLI validation ────────────────────────────────────────────────────────────


def _args(**kw: Any) -> Any:
    import argparse

    base = {"benchmark": None, "no_ui": False, "screenshots": None, "board": None, "vhdl": None}
    return argparse.Namespace(**{**base, **kw})


def test_benchmark_only_flags_warn_rather_than_fail() -> None:
    """A flag that is merely inapplicable must not kill a working invocation.

    All four are benchmark-only; ``--board`` / ``--vhdl`` have been ignored
    outside benchmark mode since it existed, so one rule covers them all.
    """
    from fpga_sim.__main__ import _inapplicable_flags, _validate_args

    args = _args(board="X", vhdl="a.vhd", no_ui=True, screenshots="/tmp/x")
    assert _validate_args(args) is None  # not fatal
    assert _inapplicable_flags(args) == ["--board", "--vhdl", "--no-ui", "--screenshots"]


def test_only_the_flags_actually_given_are_named() -> None:
    from fpga_sim.__main__ import _inapplicable_flags

    assert _inapplicable_flags(_args(screenshots="/tmp/x")) == ["--screenshots"]
    assert _inapplicable_flags(_args(no_ui=True)) == ["--no-ui"]
    assert _inapplicable_flags(_args()) == []


def test_nothing_is_inapplicable_in_benchmark_mode() -> None:
    from fpga_sim.__main__ import _inapplicable_flags

    args = _args(benchmark=5, board="X", vhdl="a.vhd", screenshots="/tmp/x")
    assert _inapplicable_flags(args) == []


def test_screenshots_with_no_ui_is_rejected() -> None:
    from fpga_sim.__main__ import _validate_args

    err = _validate_args(_args(benchmark=5, no_ui=True, screenshots="/tmp/x"))
    assert err is not None and "--no-ui does not draw" in err


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"benchmark": 5},
        {"benchmark": 5, "no_ui": True},
        {"benchmark": 5, "screenshots": "/tmp/x"},
        {"no_ui": True},  # inapplicable, but not fatal
        {"screenshots": "/tmp/x"},
    ],
)
def test_usable_combinations_pass(kw: dict[str, Any]) -> None:
    from fpga_sim.__main__ import _validate_args

    assert _validate_args(_args(**kw)) is None
