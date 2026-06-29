"""Convert a flat ROM image (.bin) into a VHDL ROM-constant aggregate body.

The single-file rule means firmware bytes must be *inlined* into the generated
VHDL as a constant (the design can't read an external file at analysis time).
This helper turns an assembled ``.bin`` (ca65/ld65 output) into the aggregate
body that goes inside ``constant ROM : rom_t := ( ... );``.

Sparse named association -- only non-zero bytes, plus ``others => x"00"`` --
reproduces the image exactly while staying compact (a 2 KB ROM holding a tiny
program is almost all zeros).  This is the seed of the Stage-3 generator's
RomImage loader.

Usage:
    uv run python -m embedded_core.rom_to_vhdl firmware/cpu_walking_counter_7seg.bin
"""

from __future__ import annotations

import argparse
from pathlib import Path


def rom_aggregate(data: bytes, *, indent: str = "    ", per_line: int = 4) -> str:
    """Return the VHDL aggregate body for *data*.

    Emits one ``16#OFF# => x"BB"`` association per non-zero byte (``OFF`` is the
    byte offset, three hex digits) followed by ``others => x"00"``, wrapped at
    *per_line* associations and prefixed with *indent*.
    """
    entries = [f'16#{offset:03X}# => x"{byte:02X}"' for offset, byte in enumerate(data) if byte]
    lines = [
        indent + ", ".join(entries[n : n + per_line]) + ","
        for n in range(0, len(entries), per_line)
    ]
    lines.append(indent + 'others => x"00"')
    return "\n".join(lines)


def main() -> None:
    """Print the aggregate body for a .bin given on the command line."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("bin", type=Path, help="flat ROM image (ca65/ld65 output)")
    parser.add_argument("--per-line", type=int, default=4, help="associations per line")
    parser.add_argument("--indent", default="    ", help="leading indent for each line")
    args = parser.parse_args()
    print(rom_aggregate(args.bin.read_bytes(), indent=args.indent, per_line=args.per_line))


if __name__ == "__main__":
    main()
