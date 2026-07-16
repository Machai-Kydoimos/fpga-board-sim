"""Tests for the U34 single-window process handle (start_simulation + SimChild).

``start_simulation`` is exercised with the sim-environment builder and the
``subprocess.Popen`` call replaced by fakes, so the env-var construction and the
``SimChild.stop()`` escalation ladder run for real without launching GHDL/NVC.
A real ``SimLinkHost`` is used (it only binds a loopback port), and every test
releases it via ``stop()`` or ``link.close()``.
"""

from __future__ import annotations

import io
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

import fpga_sim.sim_bridge as sim_bridge

if TYPE_CHECKING:
    from collections.abc import Callable

    from fpga_sim.sim_bridge import SimChild


class _FakeProc:
    """A scripted stand-in for ``subprocess.Popen`` for the stop() tests.

    ``poll_seq`` tokens: ``"run"`` -> ``None`` (alive), ``"dead"`` -> ``rc``.
    The final token repeats, so ``("run",)`` stays alive forever while
    ``("run", "run", "dead")`` reports alive twice then exits.
    """

    def __init__(
        self, *, poll_seq: tuple[str, ...] = ("dead",), rc: int = 0, wait_timeouts: int = 0
    ) -> None:
        self._seq = list(poll_seq)
        self.rc = rc
        self.wait_timeouts = wait_timeouts
        self.terminated = False
        self.killed = False
        self.stderr = io.BytesIO(b"")  # the reader thread hits EOF immediately

    def poll(self) -> int | None:
        tok = self._seq[0] if len(self._seq) == 1 else self._seq.pop(0)
        return None if tok == "run" else self.rc

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_timeouts > 0:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("sim", timeout or 0.0)
        return self.rc

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


_Started = tuple["SimChild", dict[str, Any], _FakeProc]


@pytest.fixture
def start(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Callable[..., _Started]:
    """Return a ``start(**kwargs)`` that runs start_simulation against fakes."""
    vhdl = tmp_path / "blinky.vhd"
    vhdl.write_text("entity blinky is end;")
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    monkeypatch.setattr(sim_bridge, "_build_sim_env", lambda **kw: ({}, "plugin.so"))
    monkeypatch.setattr(sim_bridge, "WAVEFORM_DIR", tmp_path / "waveforms")
    captured: dict[str, Any] = {}

    def _start(*, proc: _FakeProc | None = None, **kwargs: Any) -> _Started:
        fake = proc if proc is not None else _FakeProc(poll_seq=("run", "run", "dead"))

        def fake_popen(cmd: Any, env: Any = None, cwd: Any = None, **kw: Any) -> _FakeProc:
            captured["cmd"] = cmd
            captured["env"] = env
            captured["cwd"] = cwd
            return fake

        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        kwargs.setdefault("work_dir", str(work_dir))
        kwargs.setdefault("simulator", "ghdl")
        child = sim_bridge.start_simulation("", vhdl, "blinky", {}, **kwargs)
        return child, captured, fake

    return _start


# ── Env construction ──────────────────────────────────────────────────────────


def test_env_has_link_vars_and_bridge_module(start: Callable[..., _Started]) -> None:
    child, captured, _ = start()
    env = captured["env"]
    assert env["FPGA_SIM_LINK_PORT"].isdigit()
    assert len(bytes.fromhex(env["FPGA_SIM_LINK_KEY"])) == 16
    assert env["COCOTB_TEST_MODULES"] == "sim_testbench_bridge"
    assert env["TOPLEVEL"] == "sim_wrapper"
    child.link.close()


def test_env_drops_windowed_vars(start: Callable[..., _Started]) -> None:
    child, captured, _ = start()
    env = captured["env"]
    for key in (
        "FPGA_SIM_WIDTH",
        "FPGA_SIM_HEIGHT",
        "FPGA_SIM_THEME",
        "FPGA_SIM_EXIT_INTENT_FILE",
        "FPGA_SIM_NATIVE_CONVENTION",
    ):
        assert key not in env
    child.link.close()


def test_env_carries_metrics_metadata(start: Callable[..., _Started]) -> None:
    child, captured, _ = start()
    env = captured["env"]
    assert env["FPGA_SIM_SIMULATOR"] == "ghdl"
    assert env["FPGA_SIM_TOPLEVEL"] == "blinky"
    assert "FPGA_SIM_VHDL_PATH" in env
    assert env["FPGA_SIM_GENERICS"] == "{}"
    assert env["FPGA_SIM_BOARD_JSON"] == ""
    child.link.close()


def test_speed_and_benchmark_are_plumbed(start: Callable[..., _Started]) -> None:
    child, captured, _ = start(speed_factor=0.25, benchmark_secs=3.0)
    env = captured["env"]
    assert env["FPGA_SIM_SPEED"] == "0.25"
    assert float(env["FPGA_SIM_BENCHMARK"]) == 3.0
    child.link.close()


def test_no_benchmark_or_speed_by_default(start: Callable[..., _Started]) -> None:
    child, captured, _ = start()
    assert "FPGA_SIM_BENCHMARK" not in captured["env"]
    assert "FPGA_SIM_SPEED" not in captured["env"]
    child.link.close()


def test_run_command_targets_sim_wrapper(start: Callable[..., _Started]) -> None:
    child, captured, _ = start()
    assert "sim_wrapper" in captured["cmd"]
    assert any("plugin.so" in str(arg) for arg in captured["cmd"])
    child.link.close()


def test_child_exposes_wave_and_stderr_tail_fields(start: Callable[..., _Started]) -> None:
    child, _captured, _ = start()
    assert child.wave_cfg is None  # capture off by default
    assert child.match is None
    assert child.stderr_tail.maxlen == sim_bridge._STDERR_TAIL_LINES
    child.link.close()


# ── SimChild.stop() escalation ladder ─────────────────────────────────────────


def test_stop_returns_immediately_when_already_exited(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("dead",), rc=0)
    child, _cap, _f = start(proc=fake)
    assert child.stop() == 0
    assert fake.terminated is False


def test_stop_waits_out_a_graceful_exit(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("run", "run", "dead"), rc=0)
    child, _cap, _f = start(proc=fake)
    assert child.stop(timeout=1.0) == 0
    assert fake.terminated is False


def test_stop_escalates_to_terminate(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("run",), rc=7)
    child, _cap, _f = start(proc=fake)
    assert child.stop(timeout=0.05) == 7
    assert fake.terminated is True
    assert fake.killed is False


def test_stop_escalates_to_kill_when_terminate_hangs(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("run",), rc=9, wait_timeouts=1)
    child, _cap, _f = start(proc=fake)
    assert child.stop(timeout=0.05) == 9
    assert fake.terminated is True
    assert fake.killed is True


def test_stop_is_idempotent(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("dead",), rc=0)
    child, _cap, _f = start(proc=fake)
    assert child.stop() == 0
    assert child.stop() == 0  # second call is safe (link already closed)


def test_poll_delegates_to_the_process(start: Callable[..., _Started]) -> None:
    fake = _FakeProc(poll_seq=("dead",), rc=3)
    child, _cap, _f = start(proc=fake)
    assert child.poll() == 3
    child.link.close()
