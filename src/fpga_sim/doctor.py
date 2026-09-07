"""``fpga-sim --doctor``: does this machine have what it needs, and if not, what to type.

The install check used to be "run the test suite" -- 2,800 tests, most of them
about board JSON, none of them phrased for someone who just wants to know why
the window will not open.  This module answers that question instead: one row
per thing the simulator needs, each either fine or accompanied by **the command
to fix it on this operating system**.

Two design rules follow from who runs it.

*It runs the real code paths, not a description of them.*  Simulators come from
:func:`~fpga_sim.sim_discovery.discover_simulators`, the cocotb plugin path from
:func:`~fpga_sim.sim_runner._build_sim_env`, and the end-to-end check is a true
``analyze`` + ``elaborate`` of a bundled design against a bundled board.  A
health check that re-derives what the product does can agree with itself while
the product fails.

*It must survive the environment it diagnoses.*  Nothing here imports pygame at
module scope, and ``python -m fpga_sim.doctor`` is a supported entry point --
because the pygame/pygame-ce collision this module reports breaks ``import
pygame`` itself, and ``fpga-sim --doctor`` imports pygame before argparse ever
sees the flag.  Same reason cocotb is inspected through its distribution
metadata rather than imported.

Exit code: 0 when every check passes or only warns, 1 when any check fails.
A warning is for something absent that the simulator does not actually need
(``uv`` itself, say) -- it is reported, it is not a failure.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distributions
from importlib.metadata import version as _dist_version
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

from fpga_sim import session_config
from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
from fpga_sim.paths import HDL_DIR, VENV_DIR
from fpga_sim.sim_discovery import discover_simulators

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fpga_sim.board_loader import BoardDef
    from fpga_sim.sim_discovery import SimulatorInfo

#: The interpreter range ``pyproject.toml`` declares, kept here as text plus the
#: bounds to compare against.  Duplicating it is deliberate: the doctor must run
#: on an interpreter too old to have ``tomllib``, and reading the project's own
#: metadata says nothing when the project was never installed.
#: ``tests/test_doctor.py`` fails if this drifts from ``requires-python``.
REQUIRES_PYTHON = ">=3.10,<3.14"
_PYTHON_MIN = (3, 10)
_PYTHON_MAX_EXCLUSIVE = (3, 14)

#: The design and board the end-to-end check uses.  Both are bundled, so the
#: check measures the toolchain rather than anything the user wrote; the board
#: is the course's, and falls back to whichever board loads first.
_PROBE_DESIGN = "blinky.vhd"
_PROBE_BOARD = "DE10-Standard"

_STATUS_MARK = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]", "skip": "[skip]"}

#: The file that names a Linux distribution.  A module attribute so the platform
#: tests can point it at a fixture rather than at whatever ran them (mirroring
#: :data:`~fpga_sim.sim_discovery._GHDL_VARIANT_GLOBS`).
_OS_RELEASE = Path("/etc/os-release")


@dataclass(frozen=True)
class Check:
    """One row of the report.

    *detail* is the finding in the user's terms; *extra* holds continuation
    lines (paths, per-simulator results) shown under the row; *fix* is printed
    only when the check did not pass, in the "How to fix" block at the end.
    """

    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    detail: str
    extra: tuple[str, ...] = ()
    fix: tuple[str, ...] = ()


# ── Platform identification and the per-OS fix-it text ────────────────────────


def platform_tag() -> str:
    """Name the install recipe this machine follows.

    Returns ``"windows"``, ``"macos"``, or -- because a Linux fix-it is only
    useful if it names the right package manager -- the distro family
    ``"debian"`` / ``"fedora"`` / ``"arch"``, falling back to ``"linux"`` when
    ``/etc/os-release`` says nothing recognizable.
    """
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    ids = _os_release_ids()
    for family in ("debian", "fedora", "arch"):
        if family in ids:
            return family
    if "ubuntu" in ids:  # ID_LIKE=debian is usual, but not guaranteed
        return "debian"
    return "linux"


def _os_release() -> dict[str, str]:
    """Parse ``/etc/os-release`` into its key/value pairs, quotes stripped."""
    try:
        text = _OS_RELEASE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip('"')
    return fields


def _os_release_ids() -> set[str]:
    """Return ``ID`` plus every word of ``ID_LIKE`` from ``/etc/os-release``."""
    fields = _os_release()
    return set((f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}").lower().split())


def _describe_platform() -> str:
    """Name this machine in one line, for the report header."""
    machine = platform.machine() or "unknown"
    if sys.platform == "darwin":
        release = platform.mac_ver()[0] or platform.release()
        return f"macOS {release} - {machine}"
    if sys.platform.startswith("win"):
        return f"Windows {platform.release()} - {machine}"
    pretty = _os_release().get("PRETTY_NAME", "")
    return f"{pretty or platform.system()} - {machine}"


def _lines(text: str) -> tuple[str, ...]:
    """Split a dedented fix-it block into lines, dropping the trailing blank."""
    return tuple(dedent(text).strip("\n").split("\n"))


#: Per-platform "install a simulator" fix-it.  Every command here is one
#: ``docs/install.md`` documents and the install-docs CI workflow (D-19) runs
#: verbatim -- the doctor must never invent a command nobody has proven.
_SIM_FIX: dict[str, str] = {
    "windows": """
        Install GHDL (the tested choice on Windows), in PowerShell:
            winget install ghdl.ghdl.ucrt64.mcode
        Then open a NEW PowerShell window. winget updates PATH, but terminals
        that were already open do not see the change.
        If winget does not offer that package, install MSYS2 and run this in a
        UCRT64 shell:
            pacman -S mingw-w64-ucrt-x86_64-ghdl
    """,
    "macos": """
        Install NVC (the shortest path on macOS):
            brew install nvc
        GHDL needs its release tarball instead: 'brew install ghdl' was a cask,
        and it was disabled on 2026-09-01 for failing the Gatekeeper check. The
        tarball recipe is in docs/install.md, section "GHDL".
    """,
    "debian": """
        Install GHDL from the distribution's repository:
            sudo apt install ghdl
        NVC, and GHDL's faster LLVM backends, are in docs/install.md.
    """,
    "fedora": """
        Install GHDL from the distribution's repository:
            sudo dnf install ghdl
        NVC, and GHDL's faster LLVM backends, are in docs/install.md.
    """,
    "arch": """
        Install NVC from the AUR:
            yay -S nvc
        GHDL, and the from-source builds, are in docs/install.md.
    """,
    "linux": """
        Install GHDL or NVC. docs/install.md has the per-distribution matrix,
        the from-source builds, and the Gentoo / FreeBSD packages.
    """,
}

_SIM_FIX_TAIL = """
    Already installed? Then it is not on PATH. Check with 'ghdl --version' or
    'nvc --version'. A simulator kept somewhere unusual can be registered once:
        uv run fpga-sim --add-sim /path/to/ghdl
"""

_PYGAME_FIX = """
    Reinstall the GUI dependency:
        uv sync
    With pip instead, uninstall BOTH first. The two distributions own the same
    'pygame/' directory, so removing one deletes files the other needs:
        pip uninstall -y pygame pygame-ce
        pip install pygame-ce
    Background: docs/install.md, section "pygame-ce".
"""

_COCOTB_FIX = """
    Reinstall the Python dependencies into the project's own environment:
        uv sync
    Then run through that environment, so the simulator child finds them:
        uv run fpga-sim --doctor
"""

_PYTHON_FIX = f"""
    This project needs Python {REQUIRES_PYTHON} (the upper bound is cocotb's).
    uv reads that from pyproject.toml and fetches a suitable interpreter itself,
    even when the only Python on the machine is newer:
        uv sync
        uv run fpga-sim
"""

_BOARDS_FIX = """
    Board definitions are generated.  Regenerate them from the repository root:
        uv run python scripts/sync_amaranth_boards.py
        uv run python scripts/sync_litex_boards.py
        uv run python scripts/sync_digilent_xdc.py
"""

_PROFILE_FIX_POSIX = """
    The simulator keeps its settings, recent files and session logs there.
    Make it writable, or remove it and let the simulator recreate it:
        chmod u+rwx ~/.fpga_simulator
"""

_PROFILE_FIX_WINDOWS = """
    The simulator keeps its settings, recent files and session logs there.
    Check that %USERPROFILE%\\.fpga_simulator exists as a folder, is not
    read-only, and is not being blocked by a sync client or antivirus.
"""

_ANALYZE_FIX = """
    A simulator that reports a version but cannot compile a bundled design is
    an incomplete install, not a problem with your VHDL. Reinstall it (see
    docs/install.md), or use a different one:
        uv run fpga-sim --list-sims
        uv run fpga-sim --sim nvc
"""

_ANALYZE_FIX_WINDOWS = """
    On Windows this is usually a PATH or DLL problem rather than a broken GHDL:
    open a new PowerShell window (winget's PATH change is not visible to
    terminals that were already open), then read docs/install.md, sections
    "Windows: GHDL not on PATH after winget install" and "Windows: Python DLL
    not found".
"""


def _sim_fix() -> tuple[str, ...]:
    """Build the "no simulator" fix-it for this platform, plus the shared tail.

    The blank line is deliberate: "install one" and "you have one, it is not on
    PATH" are two different answers, and the reader needs only one of them.
    """
    return _lines(_SIM_FIX[platform_tag()]) + ("",) + _lines(_SIM_FIX_TAIL)


# ── Individual checks ─────────────────────────────────────────────────────────


def _first_line(cmd: list[str]) -> str:
    """Return the first line a command prints, or ``""`` if it will not run.

    Best-effort by design: the doctor reporting "not found" is better than the
    doctor crashing, whatever a candidate binary does.
    """
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
    except Exception:  # noqa: BLE001 - any failure means "cannot ask it"
        return ""
    for line in (f"{done.stdout or ''}\n{done.stderr or ''}").splitlines():
        if line.strip():
            return line.strip()
    return ""


def check_python() -> Check:
    """Check the running interpreter against ``requires-python``."""
    detail = f"{platform.python_version()} ({platform.python_implementation()})"
    extra = (sys.executable,)
    current = sys.version_info[:2]
    if current < _PYTHON_MIN or current >= _PYTHON_MAX_EXCLUSIVE:
        return Check(
            "Python",
            "fail",
            f"{detail} - outside the supported range {REQUIRES_PYTHON}",
            extra,
            _lines(_PYTHON_FIX),
        )
    return Check("Python", "ok", f"{detail}, within {REQUIRES_PYTHON}", extra)


def check_uv() -> Check:
    """Report whether ``uv`` is available: how the docs install, not a requirement.

    Everything works in an environment assembled another way, so a missing
    ``uv`` warns rather than fails.  It only means the fix-it lines printed
    below cannot be pasted as written.
    """
    exe = shutil.which("uv")
    if exe is None:
        return Check(
            "uv",
            "warn",
            "not on PATH - the documented commands all start with 'uv run'",
            fix=_lines("""
                Install uv (https://docs.astral.sh/uv/), or keep using the
                environment you have. Nothing here needs uv at run time.
            """),
        )
    return Check("uv", "ok", _first_line([exe, "--version"]) or "installed", (exe,))


def _pygame_distributions() -> list[str]:
    """Return the pygame-family distribution names visible to this interpreter.

    Read from metadata rather than by importing, because the state worth
    reporting (both distributions installed at once) is exactly the state in
    which the import fails.
    """
    family = {"pygame", "pygame-ce"}
    found = {
        name.lower()
        for dist in distributions()
        if (name := dist.metadata["Name"]) and name.lower() in family
    }
    return sorted(found)


def check_pygame() -> Check:
    """Check that pygame-ce is installed, is installed alone, and imports."""
    installed = _pygame_distributions()
    if not installed:
        return Check("pygame-ce", "fail", "not installed", fix=_lines(_PYGAME_FIX))
    if len(installed) > 1:
        return Check(
            "pygame-ce",
            "fail",
            f"{' and '.join(installed)} are both installed, in one shared "
            "'pygame/' directory: this environment is broken",
            fix=_lines(_PYGAME_FIX),
        )
    if installed == ["pygame"]:
        return Check(
            "pygame-ce",
            "fail",
            "upstream pygame is installed instead of pygame-ce",
            fix=_lines(_PYGAME_FIX),
        )
    # Only now is importing safe enough to be worth the version and SDL build.
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame

        sdl = ".".join(str(n) for n in pygame.get_sdl_version())
        return Check("pygame-ce", "ok", f"{pygame.version.ver} (SDL {sdl})")
    except Exception as exc:  # noqa: BLE001 - report it, do not abort the report
        return Check(
            "pygame-ce",
            "fail",
            f"installed but will not import: {type(exc).__name__}: {exc}",
            fix=_lines(_PYGAME_FIX),
        )


def check_cocotb() -> Check:
    """Check for cocotb, which supplies the VPI/VHPI plugin the child loads."""
    try:
        return Check("cocotb", "ok", _dist_version("cocotb"))
    except PackageNotFoundError:
        return Check("cocotb", "fail", "not installed", fix=_lines(_COCOTB_FIX))


def check_boards() -> Check:
    """Check that board definitions load; without them the launcher has nothing."""
    where = str(get_default_boards_path())
    boards = discover_boards(get_default_boards_path())
    if not boards:
        return Check(
            "Boards", "fail", f"no definitions found under {where}", fix=_lines(_BOARDS_FIX)
        )
    sources = sorted({b.source for b in boards if b.source})
    detail = f"{len(boards)} definitions in {len(sources)} sources" if sources else "loaded"
    return Check("Boards", "ok", detail, (where, ", ".join(sources)))


def check_profile_dir() -> Check:
    """Check that ``~/.fpga_simulator/`` exists and this user can write to it.

    Read through :mod:`fpga_sim.session_config` rather than rebuilt from
    ``Path.home()``, so the doctor reports the directory the product will
    actually use.
    """
    target = session_config.SESSION_FILE.parent
    probe = target / ".doctor-write-probe"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
    except OSError as exc:
        fix = _PROFILE_FIX_WINDOWS if platform_tag() == "windows" else _PROFILE_FIX_POSIX
        # ``strerror``, not ``str(exc)``: the latter repeats the errno and the
        # probe file's name, and the row already says which directory failed.
        return Check(
            "Profile",
            "fail",
            f"cannot write to {target}: {exc.strerror or exc}",
            fix=_lines(fix),
        )
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return Check("Profile", "ok", f"writable: {target}")


def check_simulators(infos: Sequence[SimulatorInfo]) -> Check:
    """Check that at least one VHDL simulator is installed, and report which."""
    if not infos:
        return Check("Simulators", "fail", "none found on PATH", fix=_sim_fix())
    width = max(len(i.label) for i in infos)
    extra: list[str] = []
    for info in infos:
        extra.append(f"{info.label:<{width}}  {info.backend:<8}  {info.version}")
        extra.append(f"{'':<{width}}  {'':<8}  {info.path}")
    # Discovery lists the PATH engine first, and that is the one a run with no
    # --sim and no saved choice uses.  Worth saying: the table above otherwise
    # reads as several equal options.
    extra.append(f"default when --sim is not given: {infos[0].label}")
    return Check("Simulators", "ok", f"{len(infos)} found", tuple(extra))


def check_cocotb_plugin(infos: Sequence[SimulatorInfo]) -> Check:
    """Check that the plugin and libpython handed to the simulator child exist.

    This is the half of the pipeline an ``analyze`` never touches and a student
    only meets as a simulation that dies on launch, so it is asked through the
    same :func:`~fpga_sim.sim_runner._build_sim_env` the run path calls, one
    engine at a time: the plugin is per engine, not per install.
    """
    from fpga_sim.sim_runner import _build_sim_env

    if not infos:
        return Check("cocotb plugin", "skip", "no simulator to check it for")
    if not VENV_DIR.is_dir():
        return Check(
            "cocotb plugin",
            "fail",
            f"the project environment {VENV_DIR} does not exist; the simulator "
            "child loads cocotb from it",
            fix=_lines(_COCOTB_FIX),
        )
    seen: list[str] = []
    found: list[str] = []
    missing: list[str] = []
    where: list[str] = []

    def note(line: str) -> None:
        """Record a location once -- both engines normally share both of them."""
        if line not in where:
            where.append(line)

    for info in infos:
        if info.engine in seen:
            continue  # the plugin is per engine; four GHDL installs share one
        seen.append(info.engine)
        try:
            env, plugin = _build_sim_env(info.engine, sim_path=info.path)
        except OSError as exc:
            missing.append(f"{info.engine}: {exc}")
            continue
        if Path(plugin).exists():
            found.append(f"{info.engine} -> {Path(plugin).name}")
            note(f"plugins    {Path(plugin).parent}")
        else:
            missing.append(f"{info.engine} plugin missing: {plugin}")
        libpython = env.get("PYGPI_PYTHON_LIB", "")
        if libpython and Path(libpython).exists():
            note(f"libpython  {libpython}")
        else:
            missing.append(f"{info.engine} libpython not found: {libpython or 'unresolved'}")

    if missing:
        return Check("cocotb plugin", "fail", "; ".join(missing), tuple(where), _lines(_COCOTB_FIX))
    return Check("cocotb plugin", "ok", ", ".join(found), tuple(where))


def _probe_board() -> BoardDef | None:
    """Pick the board the end-to-end check runs against: the course's, else the first."""
    boards = discover_boards(get_default_boards_path())
    if not boards:
        return None
    return find_board(boards, _PROBE_BOARD) or boards[0]


def check_analyze(infos: Sequence[SimulatorInfo]) -> Check:
    """Compile and elaborate a bundled design on every simulator found.

    The one check that exercises the whole validation path a user's file takes:
    contract check, wrapper generation, ``-a`` of both files, and elaboration.
    Every discovered install is tried rather than only the default, because
    "GHDL answers --version" and "GHDL can compile" are different facts, and the
    second is the one that decides whether the simulator runs.
    """
    from fpga_sim.vhdl_contract import check_vhdl_contract
    from fpga_sim.wrapper import analyze_vhdl

    if not infos:
        return Check("Analyze", "skip", "no simulator to analyze with")
    design = HDL_DIR / _PROBE_DESIGN
    if not design.is_file():
        return Check("Analyze", "fail", f"bundled design missing: {design}")
    board = _probe_board()
    if board is None:
        return Check("Analyze", "skip", "no board definition to analyze against")

    res = check_vhdl_contract(design, board_def=board)
    if not res.ok:
        return Check(
            "Analyze",
            "fail",
            f"{design.name} does not satisfy the contract for {board.name}",
            tuple(res.message.splitlines()[:4]),
        )

    failures: list[str] = []
    extra: list[str] = []
    width = max(len(i.label) for i in infos)
    for info in infos:
        work_dir = tempfile.mkdtemp(prefix="fpga_sim_doctor_")
        started = time.perf_counter()
        try:
            ok, detail = analyze_vhdl(
                design,
                work_dir=work_dir,
                toplevel=design.stem,
                simulator=info.engine,
                sim_path=info.path,
                board_def=board,
                match=res.match,
            )
        except Exception as exc:  # noqa: BLE001 - a crashing simulator is a finding
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        elapsed = time.perf_counter() - started
        if ok:
            extra.append(f"{info.label:<{width}}  ok    {elapsed:5.2f}s")
        else:
            failures.append(info.label)
            extra.append(f"{info.label:<{width}}  FAIL  {elapsed:5.2f}s")
            extra.extend(f"{'':<{width}}    {ln}" for ln in detail.strip().splitlines()[:4])

    subject = f"{design.name} on {board.name}"
    if failures:
        fix = _lines(_ANALYZE_FIX)
        if platform_tag() == "windows":
            fix += _lines(_ANALYZE_FIX_WINDOWS)
        return Check(
            "Analyze",
            "fail",
            f"{subject}: {', '.join(failures)} could not compile it",
            tuple(extra),
            fix,
        )
    return Check("Analyze", "ok", f"{subject}: compiled and elaborated", tuple(extra))


# ── Running and rendering the whole report ────────────────────────────────────


def run_checks(infos: Sequence[SimulatorInfo] | None = None) -> list[Check]:
    """Run every check in order and return the rows.

    *infos* is injectable so a test can describe a machine it does not have;
    left unset, the simulators are discovered exactly as the launcher does.
    """
    if infos is None:
        infos = discover_simulators(_session_extra_sims())
    return [
        check_python(),
        check_uv(),
        check_pygame(),
        check_cocotb(),
        check_boards(),
        check_profile_dir(),
        check_simulators(infos),
        check_cocotb_plugin(infos),
        check_analyze(infos),
    ]


def _session_extra_sims() -> list[str]:
    """Return the simulator paths registered with ``--add-sim`` (best-effort)."""
    try:
        raw = session_config.load_session().get("extra_simulators", [])
    except Exception:  # noqa: BLE001 - an unreadable session must not stop the doctor
        return []
    return [str(p) for p in raw] if isinstance(raw, list) else []


def render(checks: Sequence[Check]) -> str:
    """Format the rows as the report the user reads (and pastes into an issue)."""
    width = max((len(c.name) for c in checks), default=0)
    pad = " " * (len(_STATUS_MARK["ok"]) + 3 + width + 2)
    out = [f"fpga-sim doctor - {_describe_platform()}", ""]
    for check in checks:
        mark = _STATUS_MARK.get(check.status, "[ ?? ]")
        out.append(f"  {mark} {check.name:<{width}}  {check.detail}")
        out.extend(f"{pad}{line}" for line in check.extra)

    failed = [c for c in checks if c.status == "fail"]
    warned = [c for c in checks if c.status == "warn"]
    out.append("")
    if failed:
        out.append(f"{len(failed)} of {len(checks)} checks failed.")
    elif warned:
        out.append(f"All {len(checks)} checks passed ({len(warned)} with a warning).")
    else:
        out.append(f"All {len(checks)} checks passed.")

    problems = [c for c in checks if c.status in ("fail", "warn") and c.fix]
    if problems:
        out.extend(["", "How to fix", ""])
        for check in problems:
            out.append(f"  {check.name}: {check.detail}")
            out.extend(f"    {line}" for line in check.fix)
            out.append("")
    # Right-trimmed line by line: the indent a blank separator inherits would
    # otherwise show up as trailing whitespace in whatever the reader pastes it
    # into.
    return "\n".join(line.rstrip() for line in out).rstrip() + "\n"


def exit_code(checks: Sequence[Check]) -> int:
    """0 unless something is actually broken; a warning is not a failure."""
    return 1 if any(c.status == "fail" for c in checks) else 0


def run_doctor() -> int:
    """``--doctor``: run every check, print the report, return the exit code."""
    checks = run_checks()
    print(render(checks), end="")
    return exit_code(checks)


if __name__ == "__main__":  # pragma: no cover - the pygame-free entry point
    sys.exit(run_doctor())
