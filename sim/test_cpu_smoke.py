"""Stage-1 smoke test for the embedded-core CPU system (cpu_walking_counter_7seg).

The static bring-up firmware lights LED0 and writes glyph '0' (0x3F) to every
digit, then spins.  Running headlessly confirms the system elaborates and runs:
reset-vector fetch, power-on reset, the combinational read path, IO writes, and
config-register reads all work end to end.
"""

import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def cpu_static_outputs(dut):
    """Check the static firmware lit LED0 and wrote glyph '0' to every digit."""
    # ~20 us is hundreds of clocks at the wrapper's default period - far more
    # than the ~50 clocks the static program needs to reach its spin loop.
    await Timer(20_000, "ns")

    led = int(dut.led.value)
    seg = int(dut.seg.value)
    num_segs = len(dut.seg.value) // 8

    dut._log.info(f"led=0x{led:X} seg=0x{seg:X} num_segs={num_segs}")

    assert led & 0x1, f"LED0 not lit (led=0x{led:X}) - IO-write or fetch path broken"
    for i in range(num_segs):
        glyph = (seg >> (8 * i)) & 0xFF
        assert glyph == 0x3F, (
            f"digit {i} = 0x{glyph:02X}, expected 0x3F ('0') - "
            "config-read, indexed write, or read path broken"
        )
