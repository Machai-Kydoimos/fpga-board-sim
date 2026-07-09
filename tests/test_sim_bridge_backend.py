"""Unit tests for _SimBackend ABC conformance and backend dispatch."""

import inspect
from datetime import datetime
from pathlib import Path
from typing import cast, get_args

import pytest

from fpga_sim.sim_bridge import (
    _NVC_HEAP,
    Simulator,
    WaveConfig,
    _backend,
    _GHDLBackend,
    _normalize_wave,
    _NVCBackend,
    _SimBackend,
    _waveform_path,
)

# ── ABC conformance ───────────────────────────────────────────────────────────

# D2 hoisted the four discovery helpers onto the _SimBackend ABC as classmethods;
# each backend overrides only NAME plus the per-simulator command builders, which
# stay staticmethods.  Together these are the 8 members every backend exposes.
_SHARED_METHODS = ("find", "available", "lib_dir", "sim_bin_lib")
_OVERRIDE_METHODS = ("plugin_lib_name", "analyze_cmd", "elaborate_cmd", "run_cmd")
_PROTOCOL_METHODS = _SHARED_METHODS + _OVERRIDE_METHODS


@pytest.mark.parametrize("backend", [_GHDLBackend, _NVCBackend])
def test_backend_has_all_protocol_methods(backend: type) -> None:
    """Every backend exposes all 8 members, each callable without an instance."""
    for method in _PROTOCOL_METHODS:
        assert hasattr(backend, method), f"{backend.__name__} missing '{method}'"
        descriptor = inspect.getattr_static(backend, method)
        assert isinstance(descriptor, (staticmethod, classmethod)), (
            f"{backend.__name__}.{method} must be a static- or classmethod"
        )


@pytest.mark.parametrize("backend", [_GHDLBackend, _NVCBackend])
def test_shared_methods_inherited_from_abc(backend: type) -> None:
    """The four shared helpers live on the ABC as classmethods, not copy-pasted.

    Their absence from each subclass __dict__ is exactly what proves D2 removed
    the duplication; redefining one in a backend would reintroduce it.
    """
    for method in _SHARED_METHODS:
        assert method not in vars(backend), (
            f"{backend.__name__}.{method} should be inherited from _SimBackend, not redefined"
        )
        assert isinstance(inspect.getattr_static(_SimBackend, method), classmethod), (
            f"_SimBackend.{method} must be a @classmethod"
        )


@pytest.mark.parametrize("backend", [_GHDLBackend, _NVCBackend])
def test_per_simulator_methods_overridden(backend: type) -> None:
    """Each backend must override the per-simulator command builders."""
    for method in _OVERRIDE_METHODS:
        assert method in vars(backend), f"{backend.__name__} must override '{method}'"


# ── run_cmd signature parity ──────────────────────────────────────────────────


def test_run_cmd_signatures_match() -> None:
    ghdl_sig = inspect.signature(_GHDLBackend.run_cmd)
    nvc_sig = inspect.signature(_NVCBackend.run_cmd)
    assert list(ghdl_sig.parameters) == list(nvc_sig.parameters), (
        "run_cmd parameter lists diverged — update the _SimBackend ABC"
    )


def test_elaborate_cmd_signatures_match() -> None:
    ghdl_sig = inspect.signature(_GHDLBackend.elaborate_cmd)
    nvc_sig = inspect.signature(_NVCBackend.elaborate_cmd)
    assert list(ghdl_sig.parameters) == list(nvc_sig.parameters), (
        "elaborate_cmd parameter lists diverged — update the _SimBackend ABC"
    )


# ── run_cmd behavior ─────────────────────────────────────────────────────────


def test_nvc_run_cmd_ignores_generics() -> None:
    """NVC must not inject generics flags — they were baked in at elaboration."""
    cmd = _NVCBackend.run_cmd("top", {"FOO": "1"}, "/lib/vhpi.so", "/work")
    cmd_str = " ".join(cmd)
    assert "FOO" not in cmd_str
    assert "-g" not in cmd_str


def test_ghdl_run_cmd_includes_generics() -> None:
    """GHDL must inject -gKEY=VALUE flags at run time."""
    cmd = _GHDLBackend.run_cmd("top", {"NUM_LEDS": "4"}, "/lib/vpi.so", "/work")
    assert "-gNUM_LEDS=4" in cmd


def test_ghdl_run_cmd_empty_generics() -> None:
    """GHDL run_cmd with an empty generics dict must not add any -g flags."""
    cmd = _GHDLBackend.run_cmd("top", {}, "/lib/vpi.so", "/work")
    assert not any(a.startswith("-g") for a in cmd)


# ── NVC elaboration/run heap cap (-H) ─────────────────────────────────────────


def test_nvc_elaborate_cmd_raises_heap() -> None:
    """NVC elaboration lifts the 16M default global-heap cap via -H."""
    cmd = _NVCBackend.elaborate_cmd("top", {}, "/work")
    assert cmd[cmd.index("-H") + 1] == _NVC_HEAP
    # -H is a global option: it must precede the -e subcommand.
    assert cmd.index("-H") < cmd.index("-e")


def test_nvc_run_cmd_raises_heap() -> None:
    """NVC run carries the same -H cap (large designs need it at run time too)."""
    cmd = _NVCBackend.run_cmd("top", {}, "/lib/vhpi.so", "/work")
    assert cmd[cmd.index("-H") + 1] == _NVC_HEAP
    assert cmd.index("-H") < cmd.index("-r")


def test_nvc_analyze_cmd_has_no_heap_flag() -> None:
    """Analysis does not build the hierarchy, so it needs no -H bump."""
    assert "-H" not in _NVCBackend.analyze_cmd(Path("x.vhd"), "/work")


def test_ghdl_commands_have_no_heap_flag() -> None:
    """-H is NVC-specific; GHDL has no equivalent limit and must not carry it."""
    assert "-H" not in _GHDLBackend.elaborate_cmd("top", {}, "/work")
    assert "-H" not in _GHDLBackend.run_cmd("top", {}, "/lib/vpi.so", "/work")


# ── _backend() dispatch ───────────────────────────────────────────────────────


def test_backend_dispatch_ghdl() -> None:
    assert _backend("ghdl") is _GHDLBackend


def test_backend_dispatch_nvc() -> None:
    assert _backend("nvc") is _NVCBackend


def test_backend_dispatch_default_is_ghdl() -> None:
    # An out-of-domain value can still reach _backend at runtime (e.g. a corrupt
    # session.json or FPGA_SIM_SIMULATOR env var); it must fall back to GHDL.  The
    # cast simulates that boundary, since the Simulator Literal forbids it statically.
    assert _backend(cast(Simulator, "anything_else")) is _GHDLBackend


# ── Simulator Literal contract ────────────────────────────────────────────────


def test_simulator_literal_members() -> None:
    """Simulator enumerates exactly the supported backends (extend for U20 iverilog)."""
    assert set(get_args(Simulator)) == {"ghdl", "nvc"}


def test_detect_simulators_within_literal() -> None:
    """detect_simulators() only ever returns valid Simulator members."""
    from fpga_sim.sim_bridge import detect_simulators

    assert set(detect_simulators()) <= set(get_args(Simulator))


# ── NAME attribute ────────────────────────────────────────────────────────────


def test_ghdl_name() -> None:
    assert _GHDLBackend.NAME == "ghdl"


def test_nvc_name() -> None:
    assert _NVCBackend.NAME == "nvc"


# ── _SimBackend ABC ───────────────────────────────────────────────────────────


def test_sim_backend_is_abc() -> None:
    """_SimBackend is an ABC whose abstract members are exactly the overrides."""
    assert issubclass(_GHDLBackend, _SimBackend)
    assert issubclass(_NVCBackend, _SimBackend)
    assert _SimBackend.__abstractmethods__ == frozenset(_OVERRIDE_METHODS)


# ── Waveform capture (U10): run_cmd wave flags + helpers ──────────────────────


def test_ghdl_run_cmd_no_wave_by_default():
    """No wave arg → GHDL command carries no --vcd/--fst dump flag."""
    cmd = _GHDLBackend.run_cmd("top", {}, "/lib/vpi.so", "/work")
    assert not any(a.startswith(("--vcd", "--fst")) for a in cmd)


def test_nvc_run_cmd_no_wave_by_default():
    """No wave arg → NVC command carries no --wave/--format dump flag."""
    cmd = _NVCBackend.run_cmd("top", {}, "/lib/vhpi.so", "/work")
    assert not any(a.startswith(("--wave", "--format")) for a in cmd)


@pytest.mark.parametrize("fmt", ["vcd", "fst"])
def test_ghdl_run_cmd_wave_flag_follows_toplevel(fmt):
    """GHDL selects the format by flag name (--vcd=/--fst=), placed after the unit."""
    cmd = _GHDLBackend.run_cmd(
        "top", {}, "/lib/vpi.so", "/work", wave=WaveConfig(f"/w/o.{fmt}", fmt)
    )
    flag = f"--{fmt}=/w/o.{fmt}"
    assert flag in cmd
    assert cmd.index("top") < cmd.index(flag)  # simulation options follow the toplevel


@pytest.mark.parametrize("fmt", ["vcd", "fst"])
def test_nvc_run_cmd_wave_flags_precede_toplevel(fmt):
    """NVC uses --wave=<path> + explicit --format=<fmt>, before the positional top."""
    cmd = _NVCBackend.run_cmd(
        "top", {}, "/lib/vhpi.so", "/work", wave=WaveConfig(f"/w/o.{fmt}", fmt)
    )
    assert f"--wave=/w/o.{fmt}" in cmd
    assert f"--format={fmt}" in cmd
    assert cmd[-1] == "top"  # the toplevel must stay last
    assert cmd.index(f"--wave=/w/o.{fmt}") < cmd.index("top")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("vcd", "vcd"),
        ("fst", "fst"),
        ("off", None),
        ("", None),
        (None, None),
        ("VCD", None),  # case-sensitive: only exact lowercase activates
        ("garbage", None),
    ],
)
def test_normalize_wave(value, expected):
    """Only exact 'vcd'/'fst' activate capture; everything else means off."""
    assert _normalize_wave(value) == expected


def test_waveform_path_is_timestamped_under_waveform_dir(monkeypatch, tmp_path):
    """<entity>_<timestamp>.<ext> under the (redirectable) default dir."""
    monkeypatch.setattr("fpga_sim.sim_bridge.WAVEFORM_DIR", tmp_path)
    monkeypatch.delenv("FPGA_SIM_WAVEFORM_DIR", raising=False)
    when = datetime(2026, 7, 9, 14, 30, 5)
    assert _waveform_path("blinky", "vcd", now=when) == tmp_path / "blinky_2026-07-09_14-30-05.vcd"
    assert (
        _waveform_path("counter_7seg", "fst", now=when)
        == tmp_path / "counter_7seg_2026-07-09_14-30-05.fst"
    )


def test_waveform_dir_env_override(monkeypatch, tmp_path):
    """FPGA_SIM_WAVEFORM_DIR relocates output; a blank value falls back to the default."""
    monkeypatch.setattr("fpga_sim.sim_bridge.WAVEFORM_DIR", tmp_path / "default")
    proj = tmp_path / "proj" / "waves"
    monkeypatch.setenv("FPGA_SIM_WAVEFORM_DIR", str(proj))
    p = _waveform_path("blinky", "vcd")
    assert p.parent == proj
    assert p.name.startswith("blinky_") and p.suffix == ".vcd"
    monkeypatch.setenv("FPGA_SIM_WAVEFORM_DIR", "   ")  # blank → default
    assert _waveform_path("blinky", "vcd").parent == tmp_path / "default"
