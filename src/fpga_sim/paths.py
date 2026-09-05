"""Where the project's own files live, resolved once (roadmap D17).

Every module that needs the repository root used to spell it out itself, as
``Path(__file__).parent.parent.parent`` — eight times across five modules, one
of them with a ``.resolve()`` and the rest without.  The chain counts
directories between *that* file and the root, so it is silently wrong the
moment the file moves: a module pushed one package deeper keeps type-checking,
keeps importing, and starts pointing at ``src/`` instead.  Two of the eight sat
on the path a user's VHDL travels (the wrapper template and the duty fragments,
reached through ``analyze_vhdl`` → ``_generate_wrapper``), where the failure
would have surfaced as a missing template rather than as a moved file.

So the count lives here, once.  Import the constant; never re-derive the root.
``.resolve()`` is applied deliberately — it makes a symlinked checkout agree
with itself, and one of the original eight already depended on that.

These name *trees*, not individual files: a module that owns one file under a
tree (the wrapper template, say) still builds its own constant from
:data:`SIM_DIR`, because that path belongs to the module that reads it.
"""

from __future__ import annotations

from pathlib import Path

#: The repository root: the directory holding ``src/``, ``hdl/``, ``boards/``…
#: (``src/fpga_sim/paths.py`` → up three).
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

#: Bundled example designs, and the file picker's starting directory.
HDL_DIR: Path = REPO_ROOT / "hdl"

#: JSON board definitions, one subdirectory per source.
BOARDS_DIR: Path = REPO_ROOT / "boards"

#: The cocotb testbench, the wrapper template and the duty fragments — the half
#: of the project that runs *inside* the simulator rather than beside it.
SIM_DIR: Path = REPO_ROOT / "sim"

#: The project's own virtual environment, when the run uses it (the simulator
#: child needs its cocotb libraries).
VENV_DIR: Path = REPO_ROOT / ".venv"
