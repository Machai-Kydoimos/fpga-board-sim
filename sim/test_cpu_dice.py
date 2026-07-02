"""Behavioral test for the embedded-core LFSR/dice-roller demo.

The firmware (firmware/mx65_dice_7seg.s) blanks every digit but 0 and shows
"0" at cold start; each btn(0) rising edge reads the free-running LFSR
peripheral, reduces it to 1-6, and shows that value on digit 0 (as a glyph)
and on the LEDs (as the raw binary value). This system also carries an
intentionally unequal ROM/RAM map (see systems/mx65_dice_7seg.toml) -- the
runtime proof that Phase 2's per-region address slices are independent.
"""

import cocotb
from cocotb.triggers import Timer

_SETTLE_NS = 50_000  # generous margin over the cold-start blank-and-init sequence
_STEP_NS = 41_000  # one prescaler tick (PRESCALER_BITS=10 @ the wrapper's 40 ns clock)

# Decimal-to-7-seg glyphs for digits 1-6 (must match the firmware's DECLUT).
_GLYPH_TO_VALUE = {0x06: 1, 0x5B: 2, 0x4F: 3, 0x66: 4, 0x6D: 5, 0x7D: 6}

# (hold ticks, release ticks) per press -- varied and each >=2 so every rising
# edge is unambiguous (buttons are sampled once per tick, ticks ~41 us apart).
_PRESSES = [(2, 2), (3, 2), (2, 3), (4, 2), (2, 4), (3, 3)]


def _leds(dut):
    return int(dut.led.value)


def _segs(dut):
    """Return the per-digit segment bytes, digit 0 (units) first."""
    raw = int(dut.seg.value)
    return [(raw >> (8 * i)) & 0xFF for i in range(len(dut.seg.value) // 8)]


@cocotb.test()
async def dice_boots_blank_then_rolls_varied_1_to_6_on_button_press(dut):
    """Boots blank with '0' on digit 0, then each btn(0) press rolls a varied 1-6."""
    dut.btn.value = 0
    await Timer(_SETTLE_NS, "ns")
    segs = _segs(dut)
    assert segs[0] == 0x3F, f"digit 0 = 0x{segs[0]:02X}, expected 0x3F (glyph '0')"
    assert all(b == 0x00 for b in segs[1:]), f"other digits not blank: {segs}"
    assert _leds(dut) == 0, f"led = 0x{_leds(dut):X}, expected 0 (no roll yet)"

    rolls = []
    for hold_ticks, release_ticks in _PRESSES:
        dut.btn.value = 1
        await Timer(hold_ticks * _STEP_NS, "ns")
        dut.btn.value = 0
        await Timer(release_ticks * _STEP_NS, "ns")

        glyph = _segs(dut)[0]
        value = _GLYPH_TO_VALUE.get(glyph)
        assert value is not None, f"digit 0 = 0x{glyph:02X} is not a 1-6 glyph"
        assert _leds(dut) == value, f"led = 0x{_leds(dut):X}, expected the rolled value {value}"
        rolls.append(value)

    assert len(set(rolls)) >= 2, f"rolls never varied across 6 presses: {rolls}"
