"""Tests for the U7 exit-intent channel (SimExit + the sidecar file protocol).

The parse side (``_read_exit_intent``) is covered directly; the launch side is
covered by calling the real ``launch_simulation()`` with the simulator
subprocess and environment builder replaced by fakes, so the env-var handoff,
the stale-file cleanup, and the read-back all run for real.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import fpga_sim.sim_bridge as sim_bridge
from fpga_sim.sim_bridge import SimExit, _read_exit_intent, launch_simulation

# ── _read_exit_intent ─────────────────────────────────────────────────────────


def test_missing_file_means_stopped(tmp_path):
    assert _read_exit_intent(tmp_path / "nope.txt", 0) is SimExit.STOPPED


@pytest.mark.parametrize("intent", list(SimExit))
def test_every_value_round_trips(tmp_path, intent):
    f = tmp_path / "exit_intent.txt"
    f.write_text(intent.value)
    assert _read_exit_intent(f, 0) is intent


def test_junk_value_means_stopped(tmp_path):
    f = tmp_path / "exit_intent.txt"
    f.write_text("reboot_universe")
    assert _read_exit_intent(f, 0) is SimExit.STOPPED


def test_surrounding_whitespace_is_tolerated(tmp_path):
    f = tmp_path / "exit_intent.txt"
    f.write_text("  reload_vhdl\n")
    assert _read_exit_intent(f, 0) is SimExit.RELOAD_VHDL


def test_nonzero_returncode_ignores_the_file(tmp_path):
    """A crash must never be treated as navigation."""
    f = tmp_path / "exit_intent.txt"
    f.write_text(SimExit.BACK_TO_BOARDS.value)
    assert _read_exit_intent(f, 1) is SimExit.STOPPED


# ── launch_simulation round-trip (fake simulator subprocess) ──────────────────


@pytest.fixture()
def launch_env(tmp_path, monkeypatch):
    """Wire launch_simulation() to a fake simulator process.

    Returns ``(run, captured)``: call ``run(write=..., returncode=...)`` to
    launch; the fake subprocess records the env it got in *captured* and
    optionally writes *write* to the advertised intent file.
    """
    vhdl = tmp_path / "blinky.vhd"
    vhdl.write_text("entity blinky is end;")
    work_dir = tmp_path / "wd"
    work_dir.mkdir()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(sim_bridge, "_build_sim_env", lambda **kw: ({}, "plugin.so"))
    # Redirect waveform output away from the real ~/.fpga_simulator (U10).
    monkeypatch.setattr(sim_bridge, "WAVEFORM_DIR", tmp_path / "waveforms")

    def run(
        *, write: str | None = None, returncode: int = 0, waveform: str | None = None
    ) -> SimExit:
        def fake_run(cmd: Any, env: Any = None, cwd: Any = None, **kw: Any) -> Any:
            captured["cmd"] = cmd
            captured["env"] = env
            captured["cwd"] = cwd
            if write is not None:
                Path(env["FPGA_SIM_EXIT_INTENT_FILE"]).write_text(write)
            return subprocess.CompletedProcess(cmd, returncode)

        # sim_bridge does a plain ``import subprocess``, so patching the global
        # module's ``run`` is exactly what launch_simulation() will call.
        monkeypatch.setattr(subprocess, "run", fake_run)
        return launch_simulation(
            "",  # no board JSON
            vhdl,
            "blinky",
            {},
            work_dir=str(work_dir),
            simulator="ghdl",  # ghdl path: no elaborate subprocess before the run
            waveform=waveform,
        )

    return run, captured, work_dir


def test_launch_advertises_intent_file_in_workdir(launch_env):
    run, captured, work_dir = launch_env
    assert run() is SimExit.STOPPED  # nothing written → plain stop
    assert captured["env"]["FPGA_SIM_EXIT_INTENT_FILE"] == str(work_dir / "exit_intent.txt")


def test_launch_returns_the_intent_the_sim_wrote(launch_env):
    run, _captured, _work_dir = launch_env
    assert run(write="change_vhdl") is SimExit.CHANGE_VHDL


def test_launch_clears_a_stale_intent_from_a_reused_workdir(launch_env):
    run, _captured, work_dir = launch_env
    (work_dir / "exit_intent.txt").write_text("reload_vhdl")  # from a previous run
    assert run() is SimExit.STOPPED


def test_launch_ignores_intent_when_subprocess_failed(launch_env):
    run, _captured, _work_dir = launch_env
    assert run(write="back_to_boards", returncode=2) is SimExit.STOPPED


# ── waveform capture plumbing (U10) ───────────────────────────────────────────


def test_launch_without_waveform_adds_no_dump_flag(launch_env):
    run, captured, _work_dir = launch_env
    run()  # default: capture off
    assert not any(a.startswith(("--vcd", "--fst")) for a in captured["cmd"])


def test_launch_waveform_off_adds_no_dump_flag(launch_env):
    run, captured, _work_dir = launch_env
    run(waveform="off")
    assert not any(a.startswith(("--vcd", "--fst")) for a in captured["cmd"])


def test_launch_with_vcd_adds_flag_and_creates_dir(launch_env, tmp_path):
    run, captured, _work_dir = launch_env
    run(waveform="vcd")
    vcd_flags = [a for a in captured["cmd"] if a.startswith("--vcd=")]
    assert len(vcd_flags) == 1
    # Named "<toplevel>_<timestamp>.vcd" under the redirected WAVEFORM_DIR.
    assert "blinky_" in vcd_flags[0] and vcd_flags[0].endswith(".vcd")
    assert str(tmp_path / "waveforms") in vcd_flags[0]
    assert (tmp_path / "waveforms").is_dir()  # created before the run
