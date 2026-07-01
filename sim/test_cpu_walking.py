"""Stage-2 behavioral tests for the embedded-core walking counter.

The 6502 firmware (firmware/mx65_walking_counter_7seg.s) replicates
hdl/walking_counter_7seg.vhd in software:

  * a single lit LED bounces back and forth across all LEDs,
  * every LED step advances a decimal odometer on the 7-segment digits,
  * btn(0) (rising edge) reverses the LED walk and the count direction,
  * btn(1) (held) lights every LED and every segment (lamp test),
  * more switches step faster.

A hardware prescaler raises a tick every 2^PRESCALER_BITS (=1024) clocks; at the
wrapper's 40 ns period that is ~41 us, and driving all switches high makes the
firmware step on every tick.  The waits below are sized in those ~41 us steps.
"""

import cocotb
from cocotb.triggers import Timer

# Decimal-to-7-seg glyphs for digits 0-9 (must match the firmware's DECLUT).
_BCD_GLYPHS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
_GLYPH_TO_DIGIT = {glyph: digit for digit, glyph in enumerate(_BCD_GLYPHS)}

_STEP_NS = 41_000  # one prescaler tick == one step at full switch speed


def _leds(dut):
    return int(dut.led.value)


def _segs(dut):
    """Return the per-digit segment bytes, digit 0 (units) first."""
    raw = int(dut.seg.value)
    return [(raw >> (8 * i)) & 0xFF for i in range(len(dut.seg.value) // 8)]


def _number(dut):
    """Decode the displayed digits into a decimal value, or None if not all glyphs."""
    value = 0
    for i, glyph in enumerate(_segs(dut)):
        digit = _GLYPH_TO_DIGIT.get(glyph)
        if digit is None:
            return None
        value += digit * (10**i)
    return value


@cocotb.test()
async def walking_digits_are_glyphs_and_advance(dut):
    """Drive full speed and confirm every digit is a 0-9 glyph and the odometer ticks."""
    dut.sw.value = (1 << len(dut.sw.value)) - 1  # all switches on -> step every tick
    dut.btn.value = 0

    await Timer(7 * _STEP_NS, "ns")
    first = _segs(dut)
    for i, glyph in enumerate(first):
        assert glyph in _GLYPH_TO_DIGIT, f"digit {i} = 0x{glyph:02X} is not a 0-9 glyph"

    await Timer(7 * _STEP_NS, "ns")
    assert _segs(dut) != first, f"odometer not advancing: {first} -> {_segs(dut)}"


@cocotb.test()
async def led_is_one_hot_and_bounces(dut):
    """Confirm exactly one LED is lit at all times and the lit LED moves both ways."""
    dut.sw.value = (1 << len(dut.sw.value)) - 1
    dut.btn.value = 0

    positions = []
    for _ in range(24):
        await Timer(50_000, "ns")
        led = _leds(dut)
        assert led != 0 and (led & (led - 1)) == 0, f"LED not one-hot: 0x{led:X}"
        positions.append(led.bit_length() - 1)

    assert max(positions) < len(dut.led.value), f"LED out of range: {positions}"
    deltas = [b - a for a, b in zip(positions, positions[1:], strict=False) if b != a]
    assert any(d > 0 for d in deltas), f"LED never walked up: {positions}"
    assert any(d < 0 for d in deltas), f"LED never walked down (no bounce): {positions}"


@cocotb.test()
async def btn0_reverses_count_direction(dut):
    """Confirm a btn(0) rising edge flips the odometer from counting up to down."""
    dut.sw.value = (1 << len(dut.sw.value)) - 1
    dut.btn.value = 0

    # Let the counter climb well clear of zero so the post-reverse window can't wrap.
    await Timer(19 * _STEP_NS, "ns")
    n1 = _number(dut)
    await Timer(6 * _STEP_NS, "ns")
    n2 = _number(dut)
    assert n1 is not None and n2 is not None, "digits unreadable before reverse"
    assert n2 > n1, f"counter not incrementing before btn(0): {n1} -> {n2}"

    # Press btn(0): hold across several ticks (one rising edge), then release.
    dut.btn.value = 1
    await Timer(6 * _STEP_NS, "ns")
    dut.btn.value = 0
    await Timer(2 * _STEP_NS, "ns")

    n3 = _number(dut)
    await Timer(6 * _STEP_NS, "ns")
    n4 = _number(dut)
    assert n3 is not None and n4 is not None, "digits unreadable after reverse"
    assert n4 < n3, f"counter not decrementing after btn(0): {n3} -> {n4}"


@cocotb.test()
async def btn1_lights_every_lamp(dut):
    """Confirm holding btn(1) drives every LED and every segment high (lamp test)."""
    dut.sw.value = 0
    dut.btn.value = 0b10  # btn(1) held

    await Timer(4 * _STEP_NS, "ns")

    n_leds = len(dut.led.value)
    assert _leds(dut) == (1 << n_leds) - 1, (
        f"lamp test: led = 0x{_leds(dut):X}, expected all {n_leds} bits set"
    )
    for i, glyph in enumerate(_segs(dut)):
        assert glyph == 0xFF, f"lamp test: digit {i} = 0x{glyph:02X}, expected 0xFF"

    dut.btn.value = 0
