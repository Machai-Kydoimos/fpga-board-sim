"""Tests for SimMetrics: background thread lifecycle, CSV headers, and row writing."""

import csv
import time

import pytest

from fpga_sim.sim_metrics import _FIELDS, SimMetrics

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make(tmp_path, flush_interval=1):
    return SimMetrics(tmp_path / "metrics.csv", flush_interval=flush_interval)


def _sample_record(m):
    m.record(
        timer_us=100.0,
        draw_us=50.0,
        tick_us=25.0,
        sim_step_ns=1000,
        clk_period_ns=10.0,
        speed_factor=0.1,
    )


# ── Thread lifecycle ──────────────────────────────────────────────────────────


def test_start_launches_background_thread(tmp_path):
    m = _make(tmp_path)
    m.start()
    assert m._thread.is_alive()
    m.stop()


def test_stop_terminates_thread(tmp_path):
    m = _make(tmp_path)
    m.start()
    m.stop()
    assert not m._thread.is_alive()


def test_csv_file_created_on_start(tmp_path):
    m = _make(tmp_path)
    m.start()
    m.stop()
    assert (tmp_path / "metrics.csv").exists()


# ── Header correctness ────────────────────────────────────────────────────────


def test_csv_has_all_required_headers(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    m.stop()
    with path.open() as f:
        header = next(csv.reader(f))
    assert header == _FIELDS


def test_csv_header_includes_wall_and_timer(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    m.stop()
    with path.open() as f:
        header = next(csv.reader(f))
    assert "wall_us" in header
    assert "timer_us" in header
    assert "sim_step_ns" in header


# ── Row writing ───────────────────────────────────────────────────────────────


def test_record_writes_one_row(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    _sample_record(m)
    m.stop()
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 1


def test_record_values_are_written_correctly(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    m.record(
        timer_us=123.4,
        draw_us=56.7,
        tick_us=8.9,
        sim_step_ns=2000,
        clk_period_ns=5.0,
        speed_factor=0.5,
    )
    m.stop()
    rows = list(csv.DictReader(path.open()))
    assert float(rows[0]["timer_us"]) == pytest.approx(123.4, abs=0.1)
    assert float(rows[0]["draw_us"]) == pytest.approx(56.7, abs=0.1)
    assert int(rows[0]["sim_step_ns"]) == 2000
    assert float(rows[0]["speed_factor"]) == pytest.approx(0.5, rel=1e-4)


def test_multiple_records_produce_multiple_rows(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    for i in range(5):
        m.record(
            timer_us=float(i * 10),
            draw_us=5.0,
            tick_us=2.0,
            sim_step_ns=100 * i,
            clk_period_ns=10.0,
            speed_factor=0.1,
        )
    m.stop()
    rows = list(csv.DictReader(path.open()))
    assert len(rows) == 5


def test_no_records_produces_header_only_file(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    m.stop()
    rows = list(csv.DictReader(path.open()))
    assert rows == []


# ── wall_us ───────────────────────────────────────────────────────────────────


def test_wall_us_is_nonnegative(tmp_path):
    path = tmp_path / "metrics.csv"
    m = SimMetrics(path, flush_interval=1)
    m.start()
    time.sleep(0.001)  # ensure a measurable elapsed wall time
    _sample_record(m)
    m.stop()
    rows = list(csv.DictReader(path.open()))
    assert float(rows[0]["wall_us"]) >= 0.0


# ── Post-stop safety ──────────────────────────────────────────────────────────


def test_record_after_stop_does_not_raise(tmp_path):
    """record() after stop() posts to the queue; should not raise."""
    m = _make(tmp_path)
    m.start()
    m.stop()
    # Thread is gone; put_nowait still works on SimpleQueue
    _sample_record(m)  # must not raise
