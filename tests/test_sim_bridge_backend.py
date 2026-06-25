"""Unit tests for _SimBackend ABC conformance and backend dispatch."""

import inspect
from typing import cast, get_args

import pytest

from fpga_sim.sim_bridge import Simulator, _backend, _GHDLBackend, _NVCBackend, _SimBackend

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
