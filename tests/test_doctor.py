"""Tests for ``fpga-sim --doctor`` (U50): the checks, the fix-its, and the report.

Three things are worth guarding here, and they are not the obvious one.

1. **The fix-it commands are real.**  A health check that confidently prints a
   command nobody has run is worse than one that stays quiet, so every install
   command the doctor offers is asserted to appear verbatim in
   ``docs/install.md`` -- the file the install-docs CI workflow (D-19) executes
   on all three operating systems.

2. **The report is ASCII.**  It is printed to a Windows console, where a legacy
   code page turns a stray dash into a ``UnicodeEncodeError`` and the diagnostic
   dies in place of the thing it was diagnosing.

3. **The rendering is asserted on, not recomputed.**  Every row assertion reads
   :func:`~fpga_sim.doctor.render`'s output rather than the ``Check`` objects,
   so a check that decides correctly and prints nothing still fails.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

import pytest

import fpga_sim.__main__ as main_mod
import fpga_sim.doctor as doctor
from fpga_sim.doctor import Check, exit_code, render
from fpga_sim.sim_discovery import SimulatorInfo

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

PROJECT = Path(__file__).resolve().parent.parent

GHDL = SimulatorInfo("ghdl", "/usr/bin/ghdl", "mcode", "GHDL", "GHDL 7.0.0-dev")
NVC = SimulatorInfo("nvc", "/usr/bin/nvc", "nvc", "NVC", "nvc 1.23-devel")


def _pyproject() -> dict[str, Any]:
    with (PROJECT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


# ── The declared Python range, and the fix-its, agree with the repo ───────────


def test_requires_python_matches_pyproject():
    """The doctor's copy of ``requires-python`` cannot drift from the real one."""
    assert doctor.REQUIRES_PYTHON == _pyproject()["project"]["requires-python"]


def test_python_bounds_match_the_declared_string():
    """The tuples compared against are the ones the reported string promises."""
    lo, hi = doctor._PYTHON_MIN, doctor._PYTHON_MAX_EXCLUSIVE
    assert doctor.REQUIRES_PYTHON == f">={lo[0]}.{lo[1]},<{hi[0]}.{hi[1]}"


@pytest.mark.parametrize("tag", ["windows", "macos", "debian", "fedora", "arch", "linux"])
def test_every_platform_tag_has_a_simulator_fix(tag):
    """A tag with no fix-it would raise KeyError in front of the user."""
    assert tag in doctor._SIM_FIX


def test_platform_tag_is_always_one_with_a_fix(monkeypatch):
    """Whatever this machine is, ``_sim_fix`` can be built for it."""
    assert doctor.platform_tag() in doctor._SIM_FIX
    monkeypatch.setattr(doctor, "_os_release_ids", set)
    monkeypatch.setattr(sys, "platform", "linux")
    assert doctor.platform_tag() == "linux"


@pytest.mark.parametrize(
    ("tag", "command"),
    [
        ("windows", "winget install ghdl.ghdl.ucrt64.mcode"),
        ("windows", "pacman -S mingw-w64-ucrt-x86_64-ghdl"),
        ("macos", "brew install nvc"),
        ("debian", "sudo apt install ghdl"),
        ("fedora", "sudo dnf install ghdl"),
        ("arch", "yay -S nvc"),
    ],
)
def test_install_commands_are_documented_in_install_md(tag, command):
    """The doctor never invents an install command docs/install.md has not proven."""
    documented = (PROJECT / "docs" / "install.md").read_text(encoding="utf-8")
    assert command in doctor._SIM_FIX[tag]
    assert command in documented, f"{command!r} is offered by --doctor but not documented"


def test_fix_text_is_ascii():
    """Every canned line survives a legacy Windows console code page."""
    blocks = [*doctor._SIM_FIX.values(), doctor._SIM_FIX_TAIL, doctor._PYGAME_FIX]
    blocks += [doctor._COCOTB_FIX, doctor._PYTHON_FIX, doctor._BOARDS_FIX]
    blocks += [doctor._PROFILE_FIX_POSIX, doctor._PROFILE_FIX_WINDOWS]
    blocks += [doctor._ANALYZE_FIX, doctor._ANALYZE_FIX_WINDOWS]
    for block in blocks:
        assert block.isascii(), f"non-ASCII in a fix-it block: {block!r}"


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("win32", "windows"), ("darwin", "macos"), ("cygwin", "linux")],
)
def test_platform_tag_by_sys_platform(monkeypatch, platform, expected):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(doctor, "_os_release_ids", set)
    assert doctor.platform_tag() == expected


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        ({"fedora"}, "fedora"),
        ({"ubuntu", "debian"}, "debian"),
        ({"ubuntu"}, "debian"),  # ID_LIKE=debian is usual but not guaranteed
        ({"arch", "archlinux"}, "arch"),
        ({"nixos"}, "linux"),
    ],
)
def test_platform_tag_by_os_release(monkeypatch, ids, expected):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(doctor, "_os_release_ids", lambda: ids)
    assert doctor.platform_tag() == expected


def test_os_release_ids_reads_id_and_id_like(tmp_path, monkeypatch):
    """``ID`` and every word of ``ID_LIKE`` count, quotes stripped."""
    release = tmp_path / "os-release"
    release.write_text(
        'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n', encoding="utf-8"
    )
    monkeypatch.setattr(doctor, "_OS_RELEASE", release)
    assert doctor._os_release_ids() == {"linuxmint", "ubuntu", "debian"}


def test_os_release_of_a_missing_file_is_empty(tmp_path, monkeypatch):
    """A distro without the file (or a non-Linux host) must not raise."""
    monkeypatch.setattr(doctor, "_OS_RELEASE", tmp_path / "absent")
    assert doctor._os_release() == {}
    assert doctor._os_release_ids() == set()


def test_describe_platform_uses_pretty_name(tmp_path, monkeypatch):
    release = tmp_path / "os-release"
    release.write_text('PRETTY_NAME="Ubuntu 24.04.1 LTS"\nID=ubuntu\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "_OS_RELEASE", release)
    monkeypatch.setattr(sys, "platform", "linux")
    assert doctor._describe_platform().startswith("Ubuntu 24.04.1 LTS - ")


# ── Individual checks ────────────────────────────────────────────────────────


def test_python_check_passes_on_the_running_interpreter():
    check = doctor.check_python()
    assert check.status == "ok"
    assert doctor.REQUIRES_PYTHON in check.detail


def test_python_check_fails_below_the_floor(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 9, 7, "final", 0))
    check = doctor.check_python()
    assert check.status == "fail"
    assert doctor.REQUIRES_PYTHON in check.detail
    assert check.fix


def test_python_check_fails_above_the_ceiling(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 14, 0, "final", 0))
    assert doctor.check_python().status == "fail"


def test_uv_missing_is_a_warning_not_a_failure(monkeypatch):
    """Nothing at run time needs uv, so its absence must not fail the doctor."""
    monkeypatch.setattr("fpga_sim.doctor.shutil.which", lambda name: None)
    check = doctor.check_uv()
    assert check.status == "warn"
    assert check.fix
    assert exit_code([check]) == 0


def test_uv_present_reports_its_version(monkeypatch):
    monkeypatch.setattr("fpga_sim.doctor.shutil.which", lambda name: "/opt/uv")
    monkeypatch.setattr(doctor, "_first_line", lambda cmd: "uv 0.12.10")
    check = doctor.check_uv()
    assert check.status == "ok"
    assert check.detail == "uv 0.12.10"


def test_first_line_of_a_missing_command_is_empty():
    assert doctor._first_line(["definitely-not-a-real-binary-xyz", "--version"]) == ""


def test_pygame_check_passes_in_this_environment():
    """The suite's own environment is the documented one, so this must pass."""
    check = doctor.check_pygame()
    assert check.status == "ok", check.detail
    assert "SDL" in check.detail


@pytest.mark.parametrize(
    ("installed", "expected_in_detail"),
    [
        ([], "not installed"),
        (["pygame"], "upstream pygame"),
        (["pygame", "pygame-ce"], "both installed"),
    ],
)
def test_pygame_check_reports_each_broken_state(monkeypatch, installed, expected_in_detail):
    monkeypatch.setattr(doctor, "_pygame_distributions", lambda: installed)
    check = doctor.check_pygame()
    assert check.status == "fail"
    assert expected_in_detail in check.detail
    assert "pip uninstall -y pygame pygame-ce" in "\n".join(check.fix)


def test_cocotb_check_passes_in_this_environment():
    assert doctor.check_cocotb().status == "ok"


def test_cocotb_check_fails_when_not_installed(monkeypatch):
    def missing(_name: str) -> str:
        raise PackageNotFoundError("cocotb")

    monkeypatch.setattr(doctor, "_dist_version", missing)
    check = doctor.check_cocotb()
    assert check.status == "fail"
    assert "uv sync" in "\n".join(check.fix)


def test_boards_check_counts_the_repo_definitions():
    check = doctor.check_boards()
    assert check.status == "ok"
    assert "definitions" in check.detail


def test_boards_check_fails_and_names_the_sync_scripts(monkeypatch):
    monkeypatch.setattr(doctor, "discover_boards", lambda path: [])
    check = doctor.check_boards()
    assert check.status == "fail"
    assert "sync_amaranth_boards.py" in "\n".join(check.fix)


def test_profile_check_uses_the_session_file_location(tmp_path, monkeypatch):
    """The doctor reports the directory the product will actually use."""
    target = tmp_path / "profile" / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)
    check = doctor.check_profile_dir()
    assert check.status == "ok"
    assert str(tmp_path / "profile") in check.detail
    assert not list((tmp_path / "profile").iterdir()), "the write probe was left behind"


def test_profile_check_fails_when_the_directory_cannot_be_made(tmp_path, monkeypatch):
    """A *file* where the profile directory belongs fails on every platform."""
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", blocker / "sub" / "session.json")
    check = doctor.check_profile_dir()
    assert check.status == "fail"
    assert check.fix


def test_simulators_check_lists_each_install():
    check = doctor.check_simulators([GHDL, NVC])
    assert check.status == "ok"
    body = "\n".join(check.extra)
    assert "/usr/bin/ghdl" in body and "/usr/bin/nvc" in body
    assert "mcode" in body
    assert "default when --sim is not given: GHDL" in body


def test_simulators_check_fails_with_a_platform_fix(monkeypatch):
    monkeypatch.setattr(doctor, "platform_tag", lambda: "fedora")
    check = doctor.check_simulators([])
    assert check.status == "fail"
    fix = "\n".join(check.fix)
    assert "sudo dnf install ghdl" in fix
    assert "--add-sim" in fix  # the "it is installed, just not on PATH" case


def test_dependent_checks_skip_rather_than_fail_without_a_simulator():
    """A second failure for the same missing thing is noise, not information."""
    checks = [doctor.check_cocotb_plugin([]), doctor.check_analyze([])]
    assert [c.status for c in checks] == ["skip", "skip"]
    assert exit_code(checks) == 0


def test_cocotb_plugin_check_fails_when_the_plugin_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "VENV_DIR", tmp_path)
    monkeypatch.setattr(
        "fpga_sim.sim_runner._build_sim_env",
        lambda engine, sim_path=None: ({"PYGPI_PYTHON_LIB": ""}, str(tmp_path / "nope.so")),
    )
    check = doctor.check_cocotb_plugin([GHDL])
    assert check.status == "fail"
    assert "plugin missing" in check.detail
    assert "libpython not found" in check.detail
    assert "uv sync" in "\n".join(check.fix)


def test_cocotb_plugin_check_passes_and_asks_once_per_engine(monkeypatch, tmp_path):
    """Four GHDL installs share one plugin; the environment is built once each."""
    plugin = tmp_path / "libcocotbvpi_ghdl.so"
    plugin.write_text("", encoding="utf-8")
    libpython = tmp_path / "libpython3.10.so"
    libpython.write_text("", encoding="utf-8")
    calls: list[str] = []

    def fake_env(engine: str, sim_path: str | None = None) -> tuple[dict[str, str], str]:
        calls.append(engine)
        return {"PYGPI_PYTHON_LIB": str(libpython)}, str(plugin)

    monkeypatch.setattr(doctor, "VENV_DIR", tmp_path)
    monkeypatch.setattr("fpga_sim.sim_runner._build_sim_env", fake_env)
    jit = SimulatorInfo("ghdl", "/opt/ghdl-jit/bin/ghdl", "llvm-jit", "GHDL-JIT", "GHDL 7.0")
    check = doctor.check_cocotb_plugin([GHDL, jit, NVC])
    assert check.status == "ok"
    assert calls == ["ghdl", "nvc"]
    assert "libcocotbvpi_ghdl.so" in check.detail


def test_cocotb_plugin_check_fails_without_the_project_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(doctor, "VENV_DIR", tmp_path / "absent")
    check = doctor.check_cocotb_plugin([GHDL])
    assert check.status == "fail"
    assert "does not exist" in check.detail


def test_analyze_check_reports_a_failing_simulator(monkeypatch):
    """The compiler's own words survive into the report; the fix-it is added."""
    monkeypatch.setattr(doctor, "platform_tag", lambda: "fedora")
    monkeypatch.setattr(
        "fpga_sim.wrapper.analyze_vhdl", lambda *a, **k: (False, "ghdl: cannot find libghdl")
    )
    check = doctor.check_analyze([GHDL])
    assert check.status == "fail"
    assert "GHDL" in check.detail
    assert "cannot find libghdl" in "\n".join(check.extra)
    assert "--list-sims" in "\n".join(check.fix)


def test_analyze_check_survives_a_simulator_that_crashes(monkeypatch):
    def boom(*_a: object, **_k: object) -> tuple[bool, str]:
        raise OSError("Exec format error")

    monkeypatch.setattr("fpga_sim.wrapper.analyze_vhdl", boom)
    check = doctor.check_analyze([GHDL])
    assert check.status == "fail"
    assert "Exec format error" in "\n".join(check.extra)


def test_analyze_check_adds_the_windows_path_advice(monkeypatch):
    monkeypatch.setattr(doctor, "platform_tag", lambda: "windows")
    monkeypatch.setattr("fpga_sim.wrapper.analyze_vhdl", lambda *a, **k: (False, "boom"))
    fix = "\n".join(doctor.check_analyze([GHDL]).fix)
    assert "new PowerShell window" in fix


def test_analyze_check_skips_without_a_board(monkeypatch):
    monkeypatch.setattr(doctor, "discover_boards", lambda path: [])
    assert doctor.check_analyze([GHDL]).status == "skip"


# ── The rendered report ──────────────────────────────────────────────────────


def _sample_checks() -> list[Check]:
    return [
        Check("Python", "ok", "3.12.1 (CPython)", ("/usr/bin/python3",)),
        Check("uv", "warn", "not on PATH", fix=("Install uv.",)),
        Check("Simulators", "fail", "none found on PATH", fix=("sudo dnf install ghdl",)),
        Check("Analyze", "skip", "no simulator to analyze with"),
    ]


def test_render_shows_every_row_with_its_status():
    out = render(_sample_checks())
    assert "[ ok ] Python" in out
    assert "[warn] uv" in out
    assert "[FAIL] Simulators" in out
    assert "[skip] Analyze" in out
    assert "/usr/bin/python3" in out  # the extra line under its row


def test_render_status_marks_are_all_the_same_width():
    """Ragged marks would break the column the report is read down."""
    assert len({len(m) for m in doctor._STATUS_MARK.values()}) == 1


def test_render_summarizes_the_failures():
    assert "1 of 4 checks failed." in render(_sample_checks())


def test_render_summarizes_a_clean_run():
    out = render([Check("Python", "ok", "fine"), Check("cocotb", "ok", "2.0.1")])
    assert "All 2 checks passed." in out
    assert "How to fix" not in out


def test_render_counts_warnings_in_an_otherwise_clean_run():
    out = render([Check("Python", "ok", "fine"), Check("uv", "warn", "absent", fix=("x",))])
    assert "All 2 checks passed (1 with a warning)." in out


def test_render_prints_fix_its_only_for_what_is_wrong():
    out = render([*_sample_checks(), Check("cocotb", "ok", "2.0.1", fix=("never shown",))])
    assert "How to fix" in out
    assert "sudo dnf install ghdl" in out
    assert "Install uv." in out
    assert "never shown" not in out


def test_render_leaves_no_trailing_whitespace():
    """The report gets pasted; a blank separator must not carry an indent."""
    out = render([*_sample_checks(), Check("x", "fail", "y", fix=("a", "", "b"))])
    assert not [line for line in out.split("\n") if line != line.rstrip()]


def test_render_is_ascii():
    """Printed to a Windows console; a stray dash would raise UnicodeEncodeError."""
    assert render(_sample_checks()).isascii()


def test_render_of_a_real_run_is_ascii_apart_from_the_machine_s_own_strings():
    """Our own text is ASCII even when a board or banner is not."""
    checks = [doctor.check_python(), doctor.check_uv(), doctor.check_cocotb()]
    assert render(checks).isascii()


def test_exit_code_is_zero_without_failures():
    assert exit_code([Check("a", "ok", ""), Check("b", "warn", ""), Check("c", "skip", "")]) == 0


def test_exit_code_is_one_with_any_failure():
    assert exit_code([Check("a", "ok", ""), Check("b", "fail", "")]) == 1


def test_run_checks_covers_every_check_function(monkeypatch):
    """A check added to the module but never called would be invisible."""
    monkeypatch.setattr(doctor, "discover_simulators", lambda extra: [])
    names = [c.name for c in doctor.run_checks()]
    assert names == [
        "Python",
        "uv",
        "pygame-ce",
        "cocotb",
        "Boards",
        "Profile",
        "Simulators",
        "cocotb plugin",
        "Analyze",
    ]


def test_run_doctor_prints_the_report_and_returns_the_code(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run_checks", lambda: [Check("Simulators", "fail", "none")])
    rc = doctor.run_doctor()
    out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL] Simulators" in out
    assert out.endswith("\n")


def test_session_extras_survive_an_unreadable_session(monkeypatch):
    """A corrupt session file must not stop the diagnostic that would explain it."""
    monkeypatch.setattr(
        "fpga_sim.session_config.load_session", lambda: (_ for _ in ()).throw(ValueError("bad"))
    )
    assert doctor._session_extra_sims() == []


# ── CLI wiring ───────────────────────────────────────────────────────────────


def test_doctor_flag_parses(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fpga-sim", "--doctor"])
    assert main_mod._parse_args().doctor is True


def test_main_runs_the_doctor_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fpga-sim", "--doctor"])
    monkeypatch.setattr(doctor, "run_doctor", lambda: 3)
    with pytest.raises(SystemExit) as exit_info:
        main_mod.main()
    assert exit_info.value.code == 3


# ── End to end, against the real machine ─────────────────────────────────────


@pytest.mark.slow
def test_the_doctor_agrees_with_a_machine_that_can_simulate(ghdl):
    """With GHDL installed and the repo synced, every check must pass.

    This is the one test that runs the real thing: real discovery, a real
    ``analyze`` + ``elaborate`` of ``hdl/blinky.vhd``, real board loading.  If
    it fails, the report itself is the failure message.
    """
    checks = doctor.run_checks()
    report = render(checks)
    assert exit_code(checks) == 0, f"\n{report}"
    statuses = {c.name: c.status for c in checks}
    assert statuses["Simulators"] == "ok"
    assert statuses["Analyze"] == "ok"
    assert "compiled and elaborated" in report


@pytest.mark.slow
def test_the_doctor_runs_without_pygame_on_the_import_path(ghdl):
    """``python -m fpga_sim.doctor`` is the entry point for a broken pygame.

    ``fpga-sim --doctor`` imports pygame before argparse sees the flag, so the
    pygame/pygame-ce collision the doctor reports would stop it running at all.
    The module entry point must therefore start the report itself, with no
    pygame banner ahead of it.
    """
    done = subprocess.run(
        [sys.executable, "-m", "fpga_sim.doctor"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=PROJECT,
        encoding="utf-8",
        errors="replace",
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("fpga-sim doctor"), done.stdout[:200]
