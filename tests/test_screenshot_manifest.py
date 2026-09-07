"""The screenshot manifest: a still is an interval, and the manifest says which (#388).

``--screenshots`` names each PNG by simulated time, which makes it a waveform
marker -- but the brightness in it is a duty *averaged over a window*, then eased
over ~100 ms of wall time for the eye.  Measured on the issue's own sample, pixel
brightness correlates **r = +0.02** with the instantaneous bit at the named time
and **r = +0.70** with the duty over the preceding window, so a reader comparing a
still against a trace has no way to know which of the two they are looking at.

The manifest closes that by writing down, per shot, the window and both numbers.
These tests cover the three pieces that make it true rather than decorative:

1. the **window** travels with the duties it describes (``DutyTracker.window``),
   including the case that makes it subtle -- a sample that reports nothing
   leaves the previous window standing, because the previous duties are still
   what is on screen;
2. the **timescale** is read from the dump rather than assumed, in both formats
   and through the gzip wrapper both backends actually write;
3. the **manifest** says what was measured and what was displayed, and degrades
   to something honest when there is no dump to reference.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from fpga_sim.sim_duty import DutyTracker, duty_window
from fpga_sim.ui.screenshots import MANIFEST_NAME, ScreenshotRecorder, ShotMetrics
from fpga_sim.waveform import _FST_TIMESCALE_OFFSET, dump_timescale_fs

# ── 1. The window travels with the duties ─────────────────────────────────────


def test_the_window_is_the_interval_the_duties_average_over() -> None:
    """A duty is an average, and this is what it averaged over."""
    tracker = DutyTracker(1)
    # Channel 0 low throughout: acc stays 0, so the duty is 0 over (0, 1000].
    assert tracker.update(0, 0, 0b0, 1000) == [0.0]
    assert tracker.window == (0, 1000)
    assert tracker.update(0, 0, 0b0, 2500) == [0.0]
    assert tracker.window == (1000, 2500)


def test_a_sample_that_reports_nothing_leaves_the_previous_window_standing() -> None:
    """The subtle one: no new duties means the *old* duties are still displayed.

    ``update`` returns ``None`` when no simulated time has passed, and the child
    then keeps sending the values it last measured.  If the window advanced
    anyway, the manifest would attribute those duties to an interval they were
    never measured over -- which is precisely the confusion this feature exists
    to remove.
    """
    tracker = DutyTracker(1)
    tracker.update(0, 0, 0b0, 1000)
    assert tracker.window == (0, 1000)
    assert tracker.update(0, 0, 0b0, 1000) is None  # no time passed
    assert tracker.window == (0, 1000), "the window followed a sample that measured nothing"


def test_a_fresh_tracker_reports_an_empty_window_rather_than_a_wrong_one() -> None:
    tracker = DutyTracker(4)
    assert tracker.window == (0, 0)


def test_the_child_sends_the_window_of_whichever_tracker_it_has() -> None:
    """``duty_window`` takes the first tracker present; both share a sim time."""
    led, seg = DutyTracker(2), DutyTracker(8)
    led.update(0, 0, 0, 500)
    seg.update(0, 0, 0, 500)
    assert duty_window(led, seg) == [0, 500]
    assert duty_window(None, seg) == [0, 500], "a seg-only run still reports its window"
    assert duty_window(None, None) is None, "an unmeasured run must not invent a window"


# ── 2. The timescale is read, not assumed ─────────────────────────────────────


def _fst_header(exponent: int, *, wrapped: bool) -> bytes:
    """An FST file whose header block declares ``10**exponent`` seconds per tick.

    The writer-version string is placed where a real dump puts it -- immediately
    after the timescale byte -- because that adjacency is what pins the offset,
    and a fixture that ignored it could not catch the offset drifting.
    """
    block = bytearray(b"\x00" * _FST_TIMESCALE_OFFSET)  # type 0 + nine uint64s
    block += exponent.to_bytes(1, "big", signed=True)
    block += b"GHDL FST v0".ljust(128, b"\x00")
    if not wrapped:
        return bytes(block)
    body = gzip.compress(bytes(block))
    # FST_BL_ZWRAPPER: type byte, section length, uncompressed length, gzip.
    return b"\xfe" + len(body).to_bytes(8, "big") + len(block).to_bytes(8, "big") + body


@pytest.mark.parametrize("wrapped", [False, True], ids=["plain", "zwrapper"])
@pytest.mark.parametrize(("exponent", "fs"), [(-15, 1), (-12, 1_000), (-9, 1_000_000)])
def test_fst_timescale_is_read_through_the_wrapper(
    tmp_path: Path, wrapped: bool, exponent: int, fs: int
) -> None:
    """Both backends gzip-wrap their FSTs, so the header is not at offset 0.

    Verified against real dumps on 2026-09-08: GHDL and NVC each write
    ``FST_BL_ZWRAPPER`` (type 254) with the header block inside the deflated
    stream, both declaring ``-15`` (1 fs).  A reader that trusted the documented
    layout against the raw bytes read compressed noise and got -70.
    """
    dump = tmp_path / "d.fst"
    dump.write_bytes(_fst_header(exponent, wrapped=wrapped))
    assert dump_timescale_fs(dump) == fs


@pytest.mark.parametrize(
    ("directive", "fs"),
    [
        ("$timescale 1 fs $end", 1),
        ("$timescale\n  1 ps\n$end", 1_000),
        ("$timescale 10ns $end", 10_000_000),
    ],
)
def test_vcd_timescale_is_read_from_the_header(tmp_path: Path, directive: str, fs: int) -> None:
    dump = tmp_path / "d.vcd"
    dump.write_text(f"$date today $end\n{directive}\n$scope module top $end\n", encoding="utf-8")
    assert dump_timescale_fs(dump) == fs


@pytest.mark.parametrize(
    "content",
    [b"", b"\xfe not gzip at all", b"\x00 truncated", b"$timescale banana $end"],
    ids=["empty", "bad-gzip", "truncated", "unparseable"],
)
def test_an_unreadable_dump_yields_no_scale_rather_than_a_wrong_one(
    tmp_path: Path, content: bytes
) -> None:
    """A wrong tick count is worse than none: the manifest omits the dialect."""
    for suffix in (".fst", ".vcd"):
        dump = tmp_path / f"d{suffix}"
        dump.write_bytes(content)
        assert dump_timescale_fs(dump) is None


def test_a_missing_dump_is_not_an_error(tmp_path: Path) -> None:
    assert dump_timescale_fs(tmp_path / "gone.fst") is None


# ── 3. The manifest ───────────────────────────────────────────────────────────


def _recorder_with_two_shots(tmp_path: Path) -> ScreenshotRecorder:
    """A recorder holding two shots, without needing pygame to write a PNG."""
    rec = ScreenshotRecorder(tmp_path)
    from fpga_sim.ui.screenshots import _Shot

    rec.saved = [tmp_path / "shot_0001_sim1000ns.png", tmp_path / "shot_0002_sim2000ns.png"]
    rec._shots = [
        _Shot(
            rec.saved[0],
            1000,
            ShotMetrics(window_ns=(0, 1000), led_duty=(1.0, 0.0), led_level=(0.5, 0.25)),
        ),
        _Shot(
            rec.saved[1],
            2000,
            ShotMetrics(
                window_ns=(1000, 2000),
                led_duty=(0.5,),
                led_level=(0.4,),
                seg_duty=(0.25,),
                seg_level=(0.2,),
            ),
        ),
    ]
    return rec


def test_a_run_that_captured_nothing_writes_no_manifest(tmp_path: Path) -> None:
    assert ScreenshotRecorder(tmp_path).write_manifest() is None
    assert not (tmp_path / MANIFEST_NAME).exists()


def test_the_manifest_records_the_window_and_both_numbers(tmp_path: Path) -> None:
    """Read back what was written, not what was passed in."""
    rec = _recorder_with_two_shots(tmp_path)
    path = rec.write_manifest(board="DE10-Lite", design="blinky.vhd")
    assert path is not None
    doc = json.loads(path.read_text(encoding="utf-8"))

    assert doc["board"] == "DE10-Lite"
    assert doc["design"] == "blinky.vhd"
    assert len(doc["shots"]) == 2
    first = doc["shots"][0]
    assert first["file"] == "shot_0001_sim1000ns.png", "the row must name the PNG, not its path"
    assert first["sim_ns"] == 1000
    assert first["window_ns"] == [0, 1000]
    assert first["led"] == {"duty": [1.0, 0.0], "level": [0.5, 0.25]}
    assert "seg" not in first, "a board with no display must not gain an empty seg block"
    assert doc["shots"][1]["seg"] == {"duty": [0.25], "level": [0.2]}


def test_duty_and_level_describe_the_same_channels(tmp_path: Path) -> None:
    """The pair is the whole point; mismatched lengths would make it unreadable."""
    doc = json.loads(
        _recorder_with_two_shots(tmp_path).write_manifest().read_text(encoding="utf-8")  # type: ignore[union-attr]
    )
    for shot in doc["shots"]:
        for block in ("led", "seg"):
            if block in shot:
                assert len(shot[block]["duty"]) == len(shot[block]["level"])


def test_the_manifest_explains_itself_without_the_source(tmp_path: Path) -> None:
    """#388's acceptance: a reader reconciles a PNG without reading the code."""
    doc = json.loads(
        _recorder_with_two_shots(tmp_path).write_manifest().read_text(encoding="utf-8")  # type: ignore[union-attr]
    )
    prose = doc["how_to_read"]
    assert "window_ns" in prose and "duty" in prose
    assert "persistence-of-vision" in prose, "the easing is the reason the two differ"


def test_a_dump_supplies_the_tick_dialect_surfer_needs(tmp_path: Path) -> None:
    """Both dialects, because the two viewers disagree about units."""
    dump = tmp_path / "run.fst"
    dump.write_bytes(_fst_header(-15, wrapped=True))  # 1 fs per tick
    doc = json.loads(
        _recorder_with_two_shots(tmp_path)  # type: ignore[union-attr]
        .write_manifest(dump=dump)
        .read_text(encoding="utf-8")
    )
    assert doc["waveform"]["timescale_fs"] == 1
    assert doc["waveform"]["dump"] == str(dump)
    assert doc["waveform"]["gtkw"].endswith("run.gtkw")
    marker = doc["shots"][0]["marker"]
    assert marker["gtkwave"] == "1000 ns"
    assert marker["surfer_ticks"] == 1000 * 1_000_000, "1 ns is 1e6 ticks at a 1 fs scale"


def test_without_a_dump_no_tick_count_is_invented(tmp_path: Path) -> None:
    """A tick count is meaningless without a scale, so it is omitted."""
    doc = json.loads(
        _recorder_with_two_shots(tmp_path).write_manifest().read_text(encoding="utf-8")  # type: ignore[union-attr]
    )
    assert "waveform" not in doc
    assert doc["shots"][0]["marker"] == {"gtkwave": "1000 ns"}


def test_an_unreadable_dump_still_names_the_dump(tmp_path: Path) -> None:
    """The path is useful even when the scale is not: only the ticks drop out."""
    dump = tmp_path / "run.fst"
    dump.write_bytes(b"\xfe not gzip")
    doc = json.loads(
        _recorder_with_two_shots(tmp_path)  # type: ignore[union-attr]
        .write_manifest(dump=dump)
        .read_text(encoding="utf-8")
    )
    assert doc["waveform"]["dump"] == str(dump)
    assert doc["waveform"]["timescale_fs"] is None
    assert "surfer_ticks" not in doc["shots"][0]["marker"]


# ── 4. End to end, against a dump this machine's simulator actually wrote ─────


@pytest.mark.slow
def test_a_real_ghdl_fst_declares_one_femtosecond(tmp_path: Path, ghdl: str) -> None:
    """The claim the reader rests on, checked against a real writer.

    The constant offset and the gzip wrapper are both facts about GHDL's and
    NVC's *current* FST writers.  A synthetic fixture cannot notice either of
    them changing; this can.
    """
    import subprocess

    from fpga_sim.paths import HDL_DIR

    src = HDL_DIR / "blinky.vhd"
    dump = tmp_path / "blinky.fst"
    for argv in (
        [ghdl, "-a", "--std=08", "--workdir=" + str(tmp_path), str(src)],
        [ghdl, "-e", "--std=08", "--workdir=" + str(tmp_path), "blinky"],
        [
            ghdl,
            "-r",
            "--std=08",
            "--workdir=" + str(tmp_path),
            "blinky",
            f"--fst={dump}",
            "--stop-time=1us",
        ],
    ):
        subprocess.run(argv, cwd=tmp_path, check=True, capture_output=True, timeout=120)

    assert dump.exists() and dump.stat().st_size > 0
    assert dump_timescale_fs(dump) == 1, "GHDL's FST writer changed its timescale or its layout"
