"""Tests for U35 simulator discovery/identity: probing, labeling, registration.

The labeler is exercised against the *real* ``--version`` banners of the four
backends installed on the dev machine (GHDL mcode / llvm / llvm-jit + NVC),
quoted verbatim below — the mcode banner deliberately keeps its "mcode JIT"
wording so the mcode-before-LLVM-JIT ordering trap stays covered.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

import pytest

import fpga_sim.__main__ as main_mod
import fpga_sim.sim_bridge as sim_bridge
from fpga_sim.sim_bridge import SimulatorInfo, _fallback_ghdl, resolve_simulator_arg

# ── Real --version banners (see docs/u35_simulator_picker_plan.md §2) ─────────

MCODE = (
    "GHDL 7.0.0-dev (6.0.0.r205.ge8653994f) [Dunoon edition]\n"
    " Compiled with GNAT Version: 15.2.1 20260123 (Red Hat 15.2.1-\n"
    " static elaboration, mcode JIT code generator\n"
    "Written by Tristan Gingold.\n"
)
LLVM = (
    "GHDL 7.0.0-dev (6.0.0.r205.ge8653994f) [Dunoon edition]\n"
    " Compiled with GNAT Version: 15.2.1 20260123 (Red Hat 15.2.1-\n"
    " llvm 21.1.8 code generator\n"
    "Written by Tristan Gingold.\n"
)
LLVM_JIT = (
    "GHDL 7.0.0-dev (6.0.0.r205.ge8653994f) [Dunoon edition]\n"
    " Compiled with GNAT Version: 15.2.1 20260123 (Red Hat 15.2.1-\n"
    " static elaboration, LLVM JIT code generator\n"
    "Written by Tristan Gingold.\n"
)
NVC = (
    "nvc 1.22-devel (1.21.0.r96.gd83462263) (Using LLVM 21.1.8)\n"
    "Copyright (C) 2011-2026  Nick Gasson\n"
)


def _fake_run(outputs: dict[str, object]) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Build a fake ``subprocess.run`` dispatching on argv[0].

    A ``str`` value is returned as stdout; an ``Exception`` value is raised (to
    model a timeout); an unknown path raises ``FileNotFoundError`` (a missing
    binary).
    """

    def run(cmd: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        payload = outputs.get(cmd[0])
        if payload is None:
            raise FileNotFoundError(cmd[0])
        if isinstance(payload, BaseException):
            raise payload
        assert isinstance(payload, str)
        return subprocess.CompletedProcess(cmd, 0, stdout=payload, stderr="")

    return run


# ── _probe_simulator: version-line labeling ───────────────────────────────────


@pytest.mark.parametrize(
    ("banner", "engine", "backend", "label"),
    [
        (MCODE, "ghdl", "mcode", "GHDL"),
        (LLVM, "ghdl", "llvm", "GHDL-LLVM"),
        (LLVM_JIT, "ghdl", "llvm-jit", "GHDL-JIT"),
        (NVC, "nvc", "nvc", "NVC"),
    ],
)
def test_probe_labels_each_backend(monkeypatch, banner, engine, backend, label):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/x/sim": banner}))
    info = sim_bridge._probe_simulator("/x/sim")
    assert info is not None
    assert (info.engine, info.backend, info.label) == (engine, backend, label)


def test_probe_mcode_not_mislabeled_as_jit(monkeypatch):
    """mcode's banner contains 'JIT' ('mcode JIT ...'); it must still label mcode."""
    assert "JIT" in MCODE  # guard: the fixture really carries the trap
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/x/ghdl": MCODE}))
    info = sim_bridge._probe_simulator("/x/ghdl")
    assert info is not None
    assert info.backend == "mcode"


def test_probe_version_is_first_banner_line(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/x/nvc": NVC}))
    info = sim_bridge._probe_simulator("/x/nvc")
    assert info is not None
    assert info.version == "nvc 1.22-devel (1.21.0.r96.gd83462263) (Using LLVM 21.1.8)"


def test_probe_resolves_relative_path(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"ghdl": MCODE}))
    info = sim_bridge._probe_simulator("ghdl")
    assert info is not None
    assert os.path.isabs(info.path)


def test_probe_garbage_returns_none(monkeypatch):
    monkeypatch.setattr(
        "fpga_sim.sim_bridge.subprocess.run", _fake_run({"/x/foo": "randomtool 1.0\n"})
    )
    assert sim_bridge._probe_simulator("/x/foo") is None


def test_probe_empty_output_returns_none(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/x/foo": "\n  \n"}))
    assert sim_bridge._probe_simulator("/x/foo") is None


def test_probe_timeout_returns_none(monkeypatch):
    monkeypatch.setattr(
        "fpga_sim.sim_bridge.subprocess.run",
        _fake_run({"/x/ghdl": subprocess.TimeoutExpired(["/x/ghdl"], 5)}),
    )
    assert sim_bridge._probe_simulator("/x/ghdl") is None


def test_probe_missing_binary_returns_none(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({}))
    assert sim_bridge._probe_simulator("/nope/ghdl") is None


# ── discover_simulators: discovery set, order, de-dup, extras ─────────────────


def test_discover_order_and_labels(monkeypatch):
    """PATH ghdl, PATH nvc, then variants — each truthfully labeled."""
    which_map = {"ghdl": "/usr/bin/ghdl", "nvc": "/usr/bin/nvc"}
    monkeypatch.setattr("fpga_sim.sim_bridge.shutil.which", lambda name: which_map.get(name))
    monkeypatch.setattr(sim_bridge, "_GHDL_VARIANT_GLOBS", ("/opt/ghdl-*/bin/ghdl",))
    monkeypatch.setattr("fpga_sim.sim_bridge.glob.glob", lambda pat: ["/opt/ghdl-llvm/bin/ghdl"])
    monkeypatch.setattr(
        "fpga_sim.sim_bridge.subprocess.run",
        _fake_run({"/usr/bin/ghdl": MCODE, "/usr/bin/nvc": NVC, "/opt/ghdl-llvm/bin/ghdl": LLVM}),
    )
    monkeypatch.delenv("FPGA_SIM_EXTRA_SIMS", raising=False)
    infos = sim_bridge.discover_simulators()
    assert [i.label for i in infos] == ["GHDL", "NVC", "GHDL-LLVM"]
    assert [i.engine for i in infos] == ["ghdl", "nvc", "ghdl"]
    assert [i.backend for i in infos] == ["mcode", "nvc", "llvm"]


def test_discover_dedups_by_realpath(tmp_path, monkeypatch):
    """A binary reached by two paths (symlink) appears once."""
    real = tmp_path / "ghdl_real"
    real.write_text("#!/bin/sh\ntrue\n")
    link = tmp_path / "ghdl_link"
    link.symlink_to(real)
    real_rp = os.path.realpath(str(real))

    def fake_probe(path: str) -> SimulatorInfo | None:
        if os.path.realpath(path) == real_rp:
            return SimulatorInfo("ghdl", real_rp, "mcode", "GHDL", "GHDL x")
        return None

    monkeypatch.setattr(sim_bridge, "_probe_simulator", fake_probe)
    monkeypatch.setattr("fpga_sim.sim_bridge.shutil.which", lambda name: None)
    monkeypatch.setattr(sim_bridge, "_GHDL_VARIANT_GLOBS", ())
    monkeypatch.delenv("FPGA_SIM_EXTRA_SIMS", raising=False)

    infos = sim_bridge.discover_simulators([str(real), str(link)])
    assert len(infos) == 1
    assert infos[0].path == real_rp


def test_discover_merges_env_and_file_extras(monkeypatch):
    """Extras come from both the session list and FPGA_SIM_EXTRA_SIMS (file first)."""
    probed: list[str] = []

    def fake_probe(path: str) -> SimulatorInfo | None:
        probed.append(path)
        return SimulatorInfo("ghdl", os.path.realpath(path), "mcode", "GHDL", "v")

    monkeypatch.setattr(sim_bridge, "_probe_simulator", fake_probe)
    monkeypatch.setattr("fpga_sim.sim_bridge.shutil.which", lambda name: None)
    monkeypatch.setattr(sim_bridge, "_GHDL_VARIANT_GLOBS", ())
    monkeypatch.setenv("FPGA_SIM_EXTRA_SIMS", os.pathsep.join(["/env/a", "/env/b"]))

    infos = sim_bridge.discover_simulators(["/file/x"])
    paths = {i.path for i in infos}
    assert os.path.realpath("/file/x") in paths
    assert os.path.realpath("/env/a") in paths
    assert os.path.realpath("/env/b") in paths
    assert probed.index("/file/x") < probed.index("/env/a")  # file extras precede env extras


def test_discover_disambiguates_duplicate_labels(monkeypatch):
    """Two installs of the same backend at different paths get numeric suffixes."""
    monkeypatch.setattr("fpga_sim.sim_bridge.shutil.which", lambda name: None)
    monkeypatch.setattr(sim_bridge, "_GHDL_VARIANT_GLOBS", ())
    monkeypatch.delenv("FPGA_SIM_EXTRA_SIMS", raising=False)
    monkeypatch.setattr(
        "fpga_sim.sim_bridge.subprocess.run", _fake_run({"/a/ghdl": LLVM, "/b/ghdl": LLVM})
    )
    infos = sim_bridge.discover_simulators(["/a/ghdl", "/b/ghdl"])
    assert [i.label for i in infos] == ["GHDL-LLVM-1", "GHDL-LLVM-2"]


def test_discover_skips_broken_candidates(monkeypatch):
    """An unprobeable candidate is dropped, not surfaced."""
    monkeypatch.setattr("fpga_sim.sim_bridge.shutil.which", lambda name: None)
    monkeypatch.setattr(sim_bridge, "_GHDL_VARIANT_GLOBS", ())
    monkeypatch.delenv("FPGA_SIM_EXTRA_SIMS", raising=False)
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/good/ghdl": MCODE}))
    infos = sim_bridge.discover_simulators(["/good/ghdl", "/broken/thing"])
    assert [i.path for i in infos] == [os.path.realpath("/good/ghdl")]


# ── --list-sims / --add-sim CLI (SESSION_FILE redirected) ─────────────────────


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    """Redirect SESSION_FILE to a temp location for every CLI test."""
    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)
    return target


def test_list_sims_prints_table_and_returns_zero(session_file, monkeypatch, capsys):
    infos = [
        SimulatorInfo("ghdl", "/usr/local/bin/ghdl", "mcode", "GHDL", "GHDL 7.0.0-dev [x]"),
        SimulatorInfo("nvc", "/usr/local/bin/nvc", "nvc", "NVC", "nvc 1.22-devel"),
    ]
    monkeypatch.setattr(main_mod, "discover_simulators", lambda extra: infos)
    rc = main_mod._list_sims()
    out = capsys.readouterr().out
    assert rc == 0
    assert "GHDL" in out and "mcode" in out and "/usr/local/bin/ghdl" in out
    assert "NVC" in out and "/usr/local/bin/nvc" in out


def test_list_sims_empty(session_file, monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "discover_simulators", lambda extra: [])
    rc = main_mod._list_sims()
    assert rc == 0
    assert "No simulators found" in capsys.readouterr().out


def test_add_sim_registers_and_persists(session_file, monkeypatch, capsys):
    info = SimulatorInfo("ghdl", "/opt/ghdl-llvm/bin/ghdl", "llvm", "GHDL-LLVM", "GHDL 7.0.0")
    monkeypatch.setattr(main_mod, "_probe_simulator", lambda path: info)
    monkeypatch.setattr(main_mod, "discover_simulators", lambda extra: [info])
    rc = main_mod._add_sim("/opt/ghdl-llvm/bin/ghdl")
    assert rc == 0
    from fpga_sim.session_config import load_session

    assert load_session()["extra_simulators"] == ["/opt/ghdl-llvm/bin/ghdl"]
    assert "GHDL-LLVM" in capsys.readouterr().out


def test_add_sim_is_idempotent(session_file, monkeypatch):
    info = SimulatorInfo("ghdl", "/opt/ghdl-llvm/bin/ghdl", "llvm", "GHDL-LLVM", "v")
    monkeypatch.setattr(main_mod, "_probe_simulator", lambda path: info)
    monkeypatch.setattr(main_mod, "discover_simulators", lambda extra: [info])
    main_mod._add_sim("/opt/ghdl-llvm/bin/ghdl")
    main_mod._add_sim("/opt/ghdl-llvm/bin/ghdl")
    from fpga_sim.session_config import load_session

    assert load_session()["extra_simulators"] == ["/opt/ghdl-llvm/bin/ghdl"]


def test_add_sim_rejects_unrecognized(session_file, monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_probe_simulator", lambda path: None)
    monkeypatch.setattr(main_mod, "_probe_diagnostic", lambda path: "not a sim v1")
    rc = main_mod._add_sim("/bin/ls")
    assert rc == 1
    from fpga_sim.session_config import load_session

    assert "extra_simulators" not in load_session()
    err = capsys.readouterr().err
    assert "not a recognized" in err.lower()
    assert "not a sim v1" in err


# ── resolve_simulator_arg: the shared --sim / UI resolver (U35b) ──────────────

_DISCOVERED = [
    SimulatorInfo("ghdl", "/usr/local/bin/ghdl", "mcode", "GHDL", "g"),
    SimulatorInfo("nvc", "/usr/local/bin/nvc", "nvc", "NVC", "n"),
    SimulatorInfo("ghdl", "/opt/ghdl-llvm/bin/ghdl", "llvm", "GHDL-LLVM", "g"),
    SimulatorInfo("ghdl", "/opt/ghdl-jit/bin/ghdl", "llvm-jit", "GHDL-JIT", "g"),
]


def test_resolve_arg_none_is_default():
    assert resolve_simulator_arg(None, _DISCOVERED) is _DISCOVERED[0]


def test_resolve_arg_engine_slug_ghdl_is_path_default():
    """A bare 'ghdl' selects the first (PATH) GHDL install, not a variant."""
    assert resolve_simulator_arg("ghdl", _DISCOVERED) is _DISCOVERED[0]


def test_resolve_arg_engine_slug_nvc():
    assert resolve_simulator_arg("nvc", _DISCOVERED) is _DISCOVERED[1]


@pytest.mark.parametrize(
    ("slug", "backend"),
    [
        ("ghdl-mcode", "mcode"),
        ("ghdl-llvm", "llvm"),
        ("ghdl-jit", "llvm-jit"),
        ("ghdl-llvm-jit", "llvm-jit"),  # accepted alias
    ],
)
def test_resolve_arg_variant_slug(slug, backend):
    got = resolve_simulator_arg(slug, _DISCOVERED)
    assert got is not None and got.backend == backend


def test_resolve_arg_variant_absent_returns_none():
    assert resolve_simulator_arg("ghdl-llvm", [_DISCOVERED[0]]) is None


def test_resolve_arg_unknown_bare_token_returns_none():
    assert resolve_simulator_arg("iverilog", _DISCOVERED) is None


def test_resolve_arg_empty_discovered_returns_none():
    assert resolve_simulator_arg(None, []) is None


def test_resolve_arg_path_probes(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({"/opt/x/ghdl": LLVM}))
    got = resolve_simulator_arg("/opt/x/ghdl", _DISCOVERED)
    assert got is not None
    assert (got.engine, got.backend) == ("ghdl", "llvm")


def test_resolve_arg_bad_path_returns_none(monkeypatch):
    monkeypatch.setattr("fpga_sim.sim_bridge.subprocess.run", _fake_run({}))
    assert resolve_simulator_arg("/no/such/ghdl", _DISCOVERED) is None


def test_fallback_ghdl_is_usable_placeholder():
    fb = _fallback_ghdl()
    assert (fb.engine, fb.path) == ("ghdl", "ghdl")  # argv[0]='ghdl' → PATH / install hint
