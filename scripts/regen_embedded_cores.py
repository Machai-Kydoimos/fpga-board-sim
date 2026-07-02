"""Regenerate (or check) every embedded-core system from its systems/*.toml spec.

One-command loop over ``systems/*.toml``: for each spec, load the CPU plugin +
firmware ``.bin``, emit the design, and compare it to the committed
``hdl/<name>.vhd``.

    uv run python scripts/regen_embedded_cores.py             # check only (default)
    uv run python scripts/regen_embedded_cores.py --write      # regenerate differing files
    uv run python scripts/regen_embedded_cores.py --assemble   # also reassemble firmware

``--write`` reuses ``gen_embedded_core.generate_vhdl()`` -- the same
validate-then-write path the CLI uses -- so there is exactly one way a design
gets written; it only touches files that actually differ.

``--assemble`` additionally reassembles each firmware source with its pinned
dev-time toolchain (ca65 + ld65 for mx65, z88dk z80asm for T80) into a scratch
directory and byte-compares the result against the checked-in ``.bin``. It
never writes a ``.bin`` -- updating one stays a deliberate manual act -- and
prints the exact commands it ran so a human can repeat them. Reassembly for a
firmware is skipped (not failed) when its toolchain is not installed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from embedded_core.cpu_plugin import get_plugin
from embedded_core.system_spec import SystemSpec, load
from gen_embedded_core import generate_vhdl

REPO = Path(__file__).resolve().parents[1]
SYSTEMS = REPO / "systems"
FIRMWARE = REPO / "firmware"
HDL = REPO / "hdl"

# Dev-time-only assembler binaries each core's firmware needs, keyed by spec.cpu.
_REQUIRED_TOOLS: dict[str, tuple[str, ...]] = {
    "mx65": ("ca65", "ld65"),
    "t80": ("z80asm",),
}


def _assemble_mx65(stem: str, scratch: Path) -> tuple[Path, list[str]]:
    """Reassemble a 6502 firmware stem with ca65 + ld65. Return (bin path, commands run)."""
    src = FIRMWARE / f"{stem}.s"
    obj = scratch / f"{stem}.o"
    out = scratch / f"{stem}.bin"
    cfg = FIRMWARE / "mx65.cfg"
    commands = [
        ["ca65", "--cpu", "6502", "-o", str(obj), str(src)],
        ["ld65", "-C", str(cfg), "-o", str(out), str(obj)],
    ]
    for command in commands:
        subprocess.run(command, check=True, capture_output=True, text=True)
    return out, [" ".join(command) for command in commands]


def _assemble_t80(stem: str, scratch: Path) -> tuple[Path, list[str]]:
    """Reassemble a Z80 firmware stem with z88dk z80asm. Return (bin path, commands run).

    z88dk z80asm 2.7.1o glues its value to ``-o`` (no space) and drops
    ``.obj``/``.sym`` byproducts next to its input, so the source is copied
    into the scratch dir first and the command runs with that as cwd.
    """
    src = FIRMWARE / f"{stem}.asm"
    local_src = scratch / src.name
    local_src.write_text(src.read_text())
    out = scratch / f"{stem}.bin"
    command = ["z80asm", "-b", f"-o{out.name}", local_src.name]
    subprocess.run(command, check=True, capture_output=True, text=True, cwd=scratch)
    return out, [f"(cd {scratch} && {' '.join(command)})"]


_ASSEMBLERS = {"mx65": _assemble_mx65, "t80": _assemble_t80}


def _check_or_write(spec: SystemSpec, *, write: bool) -> tuple[str, bool]:
    """Emit spec's design and compare/write it against hdl/<name>.vhd.

    Returns (status word, ok) where ``ok`` is True when the committed file is
    now known to match the generator's output (either it already did, or
    ``--write`` just made it so).
    """
    plugin = get_plugin(spec.cpu)
    rom = FIRMWARE / f"{spec.firmware}.bin"
    out_path = HDL / f"{spec.name}.vhd"
    vhdl = generate_vhdl(spec, plugin, rom.read_bytes())
    existing = out_path.read_text() if out_path.is_file() else None
    if existing == vhdl:
        return "OK", True
    if write:
        out_path.write_text(vhdl)
        return "WRITTEN", True
    return ("MISSING" if existing is None else "DIFFERS"), False


def _reassemble_and_report(spec: SystemSpec) -> bool:
    """Reassemble spec's firmware and report drift against the checked-in .bin.

    Returns True when the firmware reassembles clean (or its toolchain is
    absent and the check was skipped); False on drift.
    """
    missing_tools = [t for t in _REQUIRED_TOOLS[spec.cpu] if shutil.which(t) is None]
    if missing_tools:
        print(f"    firmware {spec.firmware}: SKIPPED (missing {', '.join(missing_tools)})")
        return True
    committed = FIRMWARE / f"{spec.firmware}.bin"
    with tempfile.TemporaryDirectory(prefix="regen_asm_") as d:
        out, commands = _ASSEMBLERS[spec.cpu](spec.firmware, Path(d))
        clean = out.read_bytes() == committed.read_bytes()
    print(f"    firmware {spec.firmware}: reassembles {'OK' if clean else 'DRIFT'}")
    for command in commands:
        print(f"      $ {command}")
    return clean


def main() -> int:
    """Check (or write) every system in systems/*.toml; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate differing/missing files in place"
    )
    parser.add_argument(
        "--assemble", action="store_true", help="also reassemble firmware and report drift"
    )
    args = parser.parse_args()

    all_clean = True
    for toml_path in sorted(SYSTEMS.glob("*.toml")):
        spec = load(toml_path)
        status, ok = _check_or_write(spec, write=args.write)
        print(f"{spec.name}: {status}")
        all_clean = all_clean and ok
        if args.assemble:
            all_clean = _reassemble_and_report(spec) and all_clean

    return 0 if all_clean else 1


if __name__ == "__main__":
    sys.exit(main())
