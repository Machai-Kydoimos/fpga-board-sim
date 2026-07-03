"""Generate a single-file embedded-core VHDL design from a system spec + ROM image.

Usage (short form -- --cpu/--rom/--out are inferred from the spec):
    uv run python scripts/gen_embedded_core.py --system systems/mx65_walking_counter_7seg.toml

Usage (long form -- explicit flags override the inferred values):
    uv run python scripts/gen_embedded_core.py --cpu mx65 \
        --system systems/mx65_walking_counter_7seg.toml \
        --rom firmware/mx65_walking_counter_7seg.bin \
        --out hdl/mx65_walking_counter_7seg.vhd

The vendored CPU core is emitted verbatim and board sizes stay generic (resolved
at elaboration).  The output is validated against the simulator's VHDL contract
(check_vhdl_encoding + check_vhdl_contract) before it is written.

``--prescaler-bits`` is a generation-time-only knob: it overrides the
PRESCALER_BITS generic's *default* in the emitted VHDL (the wrapper never
passes it, so whatever default is baked in at generation time is what runs).
Used e.g. to produce a temporary variant build with a faster visible step
rate for headless GIF capture, without touching the committed design.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from embedded_core.cpu_plugin import CpuPlugin, get_plugin
from embedded_core.emitter import emit
from embedded_core.system_spec import SystemSpec, load

from fpga_sim.sim_bridge import check_vhdl_contract, check_vhdl_encoding

REPO = Path(__file__).resolve().parents[1]


def generate_vhdl(spec: SystemSpec, plugin: CpuPlugin, rom_bytes: bytes) -> str:
    """Emit the design and validate it against the simulator's VHDL contract.

    Raises ``SystemExit`` with a clear message if validation fails, or if the
    firmware source (embedded verbatim as a ROM-block comment, see guide §8)
    is missing or not pure ASCII. Shared by this module's CLI and
    ``scripts/regen_embedded_cores.py`` so there is exactly one
    validate-then-write code path.
    """
    firmware_path = REPO / "firmware" / f"{spec.firmware}{plugin.asm_ext}"
    if not firmware_path.is_file():
        raise SystemExit(f"firmware source not found: {firmware_path}")
    try:
        firmware_source = firmware_path.read_bytes().decode("ascii")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"firmware source {firmware_path} is not pure ASCII: {exc}") from exc

    vhdl = emit(spec, plugin, rom_bytes, firmware_source)
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
    return vhdl


def main() -> None:
    """Parse arguments, emit the design, validate it, and write the output file."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--cpu", help="CPU plugin name (default: the spec's cpu field)")
    parser.add_argument("--system", required=True, type=Path, help="system spec TOML")
    parser.add_argument(
        "--rom", type=Path, help="firmware ROM image (default: firmware/<spec.firmware>.bin)"
    )
    parser.add_argument("--out", type=Path, help="output .vhd path (default: hdl/<spec.name>.vhd)")
    parser.add_argument(
        "--prescaler-bits",
        type=int,
        help=(
            "override the PRESCALER_BITS generic default at generation time "
            "(generation-time only -- see the module docstring)"
        ),
    )
    args = parser.parse_args()

    spec = load(args.system)
    if args.cpu is not None and args.cpu != spec.cpu:
        raise SystemExit(f"--cpu {args.cpu!r} does not match spec cpu {spec.cpu!r}")
    if args.prescaler_bits is not None:
        spec.generics["prescaler_bits"] = args.prescaler_bits
    rom_path = args.rom if args.rom is not None else REPO / "firmware" / f"{spec.firmware}.bin"
    out_path = args.out if args.out is not None else REPO / "hdl" / f"{spec.name}.vhd"

    plugin = get_plugin(spec.cpu)
    vhdl = generate_vhdl(spec, plugin, rom_path.read_bytes())
    out_path.write_text(vhdl)
    print(f"wrote {out_path} ({len(vhdl.splitlines())} lines)")


if __name__ == "__main__":
    main()
