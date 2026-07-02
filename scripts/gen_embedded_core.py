"""Generate a single-file embedded-core VHDL design from a system spec + ROM image.

Usage:
    uv run python scripts/gen_embedded_core.py --cpu mx65 \
        --system systems/mx65_walking_counter_7seg.toml \
        --rom firmware/mx65_walking_counter_7seg.bin \
        --out hdl/mx65_walking_counter_7seg.vhd

The vendored CPU core is emitted verbatim and board sizes stay generic (resolved
at elaboration).  The output is validated against the simulator's VHDL contract
(check_vhdl_encoding + check_vhdl_contract) before it is written.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from embedded_core import system_spec
from embedded_core.cpu_plugin import get_plugin
from embedded_core.emitter import emit

from fpga_sim.sim_bridge import check_vhdl_contract, check_vhdl_encoding


def main() -> None:
    """Parse arguments, emit the design, validate it, and write the output file."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cpu", required=True, help="CPU plugin name (e.g. mx65)")
    parser.add_argument("--system", required=True, type=Path, help="system spec TOML")
    parser.add_argument("--rom", required=True, type=Path, help="firmware ROM image (.bin)")
    parser.add_argument("--out", required=True, type=Path, help="output .vhd path")
    args = parser.parse_args()

    spec = system_spec.load(args.system)
    if spec.cpu != args.cpu:
        raise SystemExit(f"--cpu {args.cpu!r} does not match spec cpu {spec.cpu!r}")
    plugin = get_plugin(args.cpu)
    vhdl = emit(spec, plugin, args.rom.read_bytes())

    # Validate before writing: encoding + the simulator's top-level contract.
    # The temp file is named <spec.name>.vhd so the entity==filename check passes.
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / f"{spec.name}.vhd"
        probe.write_text(vhdl)
        for label, (ok, msg) in (
            ("encoding", check_vhdl_encoding(probe)),
            ("contract", check_vhdl_contract(probe)),
        ):
            if not ok:
                raise SystemExit(f"generated VHDL failed {label} check: {msg}")

    args.out.write_text(vhdl)
    print(f"wrote {args.out} ({len(vhdl.splitlines())} lines)")


if __name__ == "__main__":
    main()
