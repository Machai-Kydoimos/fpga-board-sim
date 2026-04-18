# 7-Segment Display Support — Design Plan

*Status: draft for review, 2026-04-18. No implementation has started.*

---

## Contents

1. [Research Findings](#1-research-findings)
2. [Missing Boards — ULX3S and Others](#2-missing-boards--ulx3s-and-others)
3. [Design Decision 1: VHDL Interface](#3-design-decision-1-vhdl-interface)
4. [Design Decision 2: Display Layout](#4-design-decision-2-display-layout)
5. [Design Decision 3: Multiplexed Hardware Mode (v2)](#5-design-decision-3-multiplexed-hardware-mode-v2)
6. [Data Model — `SevenSegDef`](#6-data-model--sevensegdef)
7. [Board Loader Changes](#7-board-loader-changes)
8. [VHDL Wrapper & sim_bridge Changes](#8-vhdl-wrapper--sim_bridge-changes)
9. [SevenSeg Widget — Rendering & Scaling](#9-sevenseg-widget--rendering--scaling)
10. [FPGABoard Layout Changes](#10-fpgaboard-layout-changes)
11. [sim_testbench Changes](#11-sim_testbench-changes)
12. [Example VHDL — `counter_7seg.vhd`](#12-example-vhdl--counter_7segvhd)
13. [Test Strategy](#13-test-strategy)
14. [Phased Delivery](#14-phased-delivery)

---

## 1. Research Findings

### Boards with 7-segment resources in amaranth-boards

Nine boards define `Display7SegResource` entries. `Display7SegResource` is currently **stubbed
to `_stub_single`** in `board_loader.py:228` — all nine boards silently drop their 7-seg
resources today.

All boards also have LEDs/buttons/switches, so none would be filtered by the existing
"must have at least one component" gate in `load_board_from_source()`.

#### Independent boards (N separate digit resources, no shared segment pins)

| Board | Digits | Has DP | Inverted | Device family |
|-------|--------|--------|----------|---------------|
| DE0 | 4 | Yes | Yes | Cyclone III (Intel) |
| Nandland-Go | 2 | No | Yes | iCE40HX1K (Lattice) |
| DE0-CV | 6 | **No** | Yes | Cyclone V (Intel) |
| DE1-SoC | 6 | **No** | Yes | Cyclone V (Intel) |
| DE10-Lite | 6 | Yes | Yes | MAX 10 (Intel) |

#### Multiplexed boards (1 shared segment resource + companion select/enable resource)

| Board | Digits | Has DP | Companion resource | Select polarity | Device family |
|-------|--------|--------|--------------------|-----------------|---------------|
| Nexys4-DDR | 8 | Yes | `display_7seg_an` (8-pin `PinsN`) | Active-low | Artix-7 (Xilinx) |
| Mercury | 4 | Yes | `display_7seg_ctrl` (4-pin `Pins`) | Active-high | Spartan-3 (Xilinx) |
| RZ-EasyFPGA-A2/2 | 4 | Yes | `display_7seg_ctrl` (4-pin `Pins(invert=True)`) | Active-low | Cyclone IV (Intel) |
| StepMXO2 | 2† | Yes | `display_7seg_ctrl` (2-pin `Pins(invert=True)`) | Active-low | MachXO2 (Lattice) |

†StepMXO2 has two `Display7SegResource` entries plus a companion with 2 enable pins. This is
a non-standard partial-mux scheme (each enable independently gates one digit-resource, rather
than scanning 4 digits in time-division). **Treat as 2 independent digits for v1.**

#### Sub-signal structure (uniform across all boards)

All boards use the `Display7SegResource()` helper which creates:

```
Subsignal("a", Pins(...))   # top horizontal
Subsignal("b", Pins(...))   # top-right vertical
Subsignal("c", Pins(...))   # bottom-right vertical
Subsignal("d", Pins(...))   # bottom horizontal
Subsignal("e", Pins(...))   # bottom-left vertical
Subsignal("f", Pins(...))   # top-left vertical
Subsignal("g", Pins(...))   # middle horizontal
Subsignal("dp", Pins(...))  # decimal point (optional)
```

All subsignals are `dir="o"` (output). The `invert=True` parameter on the resource
indicates active-low hardware; our simulator normalises to active-high at the VHDL level.

---

## 2. Missing Boards — ULX3S and Others

### ULX3S

The ULX3S physical board **does** have a 6-digit 7-segment display. However, it is driven
through an **I2C GPIO expander** (HT16K33 or similar), not directly wired to FPGA GPIO pins.
Because `Display7SegResource` requires direct pin-to-FPGA connections, the amaranth-boards
authors correctly omitted it from the definition.

Supporting the ULX3S 7-seg display would require a fundamentally different model (I2C
transaction simulation), which is out of scope for this feature.

### Completeness of the search

The grep for `Display7SegResource`, `display_7seg`, `seven_seg`, and `7seg` across all
`.py` files in `amaranth_boards/` is exhaustive — there are no other naming conventions in
use. **The 9-board list above is the complete set** of boards representable with the
current submodule.

Other boards may exist in the real world with direct 7-seg connections that are not yet in
the amaranth-boards submodule at all (e.g. Basys3). Those would be automatically picked up
if their definitions were added.

### Implication for board_loader

Add a comment in `_make_namespace()` explaining why the ULX3S and similar boards are
excluded, so future developers understand the design boundary.

---

## 3. Design Decision 1: VHDL Interface

### Option A — Logical segment vector, 8 bits per digit *(Recommended for v1)*

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;   -- only in the 7-seg VHDL contract
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
    --   per digit i: bits [8i+7 : 8i] = {dp, g, f, e, d, c, b, a}
    --   active-high (1 = segment on) regardless of board hardware polarity
  );
end entity;
```

**Key properties:**
- Uniform across all 9 boards regardless of mux vs independent architecture.
- User drives 8 bits per digit; no multiplexing state-machine required.
- Polarity is normalised to active-high in VHDL; board `inverted` flag is metadata only.
- `NUM_SEGS` is `positive` (≥ 1) in the 7-seg template — no null-range VHDL issues.
- A 7-seg VHDL file is **not portable to non-7-seg boards** (because the non-7-seg
  wrapper has no `seg` port). This is correct behaviour — a 7-seg design doesn't
  belong on a board without a display.

**Wrapper strategy:** Two templates. The existing `sim_wrapper_template.vhd` is unchanged.
A new `sim_wrapper_7seg_template.vhd` adds `NUM_SEGS`, `seg`, and the corresponding
generic/port-map lines. `sim_bridge.py` selects the template based on
`board_def.seven_seg is not None`.

**Contract check:** For 7-seg boards, `check_vhdl_contract()` requires `seg` present. For
non-7-seg boards, `seg` must be absent (its presence would cause a port-map mismatch in
the non-7-seg wrapper and is detected early).

**Pros:** Simple to teach, uniform interface, no mux complexity, clean two-template split.

**Con:** 7-seg VHDL only works on 7-seg boards (but this is semantically correct).

---

### Option B — Separate 7-bit segment bus + 1-bit DP per digit

```vhdl
seg    : out std_logic_vector(7 * NUM_SEGS - 1 downto 0);  -- {g,f,e,d,c,b,a}
seg_dp : out std_logic_vector(NUM_SEGS     - 1 downto 0);  -- decimal points
```

Cleanly separates the decimal point into its own vector. Adds a second port to every design
with no meaningful advantage over Option A. Not recommended — the extra port complicates
both the VHDL contract and the wrapper without providing benefit to the user.

---

### Option C — Physical multiplexed interface *(Reserved for v2)*

```vhdl
-- For mux boards (Nexys4-DDR, Mercury, RZ-EasyFPGA):
seg    : out std_logic_vector(6 downto 0);            -- shared segments a–g
seg_dp : out std_logic;                               -- shared decimal point
seg_an : out std_logic_vector(NUM_SEGS - 1 downto 0);-- digit-select / anode
```

Authentic to real multiplexed hardware; the user must implement a digit-scanning state
machine in VHDL (as they would on real hardware). The testbench would need to:
1. Each sim tick: detect which `seg_an` bit is asserted.
2. Latch the segment values for the active digit.
3. Time-average across scan cycles to produce a stable display (persistence-of-vision).

This is educationally valuable — especially for the Nexys4-DDR, the most common Xilinx
education board. However it cannot be a universal interface (non-mux boards like DE0 have
no select lines). It would need to be an opt-in "physical mode" selectable per-board.

**Decision:** Reserve for v2. Implement once v1 (Option A) is stable. Add a note in the
future enhancement list.

---

## 4. Design Decision 2: Display Layout

### Current layout (vertical sections)

```
┌──────────────────────────────┐
│          FPGA Chip           │  weight 3
├──────────────────────────────┤
│     ● ● ● ● ● ● ● ●         │  weight 4   LEDs
├──────────────────────────────┤
│    [BTN0] [BTN1] [BTN2]      │  weight 1
├──────────────────────────────┤
│    SW0  SW1  SW2  SW3        │  weight 1
└──────────────────────────────┘
```

---

### Option A — New vertical section between FPGA chip and LEDs *(Easiest)*

```
┌──────────────────────────────┐
│          FPGA Chip           │  weight 3
├──────────────────────────────┤
│  [0] [1] [2] [3] [4] [5]    │  weight 2   ← new 7-SEG section
├──────────────────────────────┤
│     ● ● ● ● ● ● ● ●         │  weight 3   LEDs (weight reduced)
├──────────────────────────────┤
│    [BTN0] [BTN1] [BTN2]      │  weight 1
├──────────────────────────────┤
│    SW0  SW1  SW2  SW3        │  weight 1
└──────────────────────────────┘
```

The section-weighting system in `_layout()` already handles arbitrary sections — adding one
is a small change (insert into the `sections` list, add a `_place_items` branch). For 6
digits in a row at ~50 px each: 300 px wide, easily fits in a 1024 px window.

**Pros:** Minimal code change; proven layout system handles scaling automatically.
**Con:** Feels slightly arbitrary — the display logically belongs next to the chip, not
floating between the chip and LEDs. For boards with many LEDs (Nexys4-DDR has 16) the
board becomes very tall.

---

### Option B — Horizontal split at top: FPGA chip left, 7-seg panel right *(Recommended)*

```
┌─────────────────┬────────────────────┐
│                 │   [0] [1] [2]      │
│   FPGA Chip     │   [3] [4] [5]      │  split top section
│                 │                    │
├─────────────────┴────────────────────┤
│        ● ● ● ● ● ● ● ●              │  LEDs (weight unchanged)
├──────────────────────────────────────┤
│     [BTN0] [BTN1] [BTN2]            │
├──────────────────────────────────────┤
│     SW0  SW1  SW2  SW3               │
└──────────────────────────────────────┘
```

The FPGA chip graphic is currently centred within a full-width rect. Splitting that rect
55% / 45% still leaves the chip plenty of room (the chip image is already capped at
`min(avail_w * 0.70, 420 * s, ...)` so it never fills its allocated space anyway).

**Implementation scope:** Confined to `_layout()` (compute `chip_rect` and `seven_seg_rect`
from the top section) and `_draw()` (draw chip in `chip_rect`, 7-seg panel in
`seven_seg_rect`). The below-the-split sections are unchanged. A section title "7-SEG"
appears at the top of the right-column panel, consistent with "FPGA", "LEDs" etc.

**Digit grid within the 7-seg panel:**
- ≤ 4 digits: single horizontal row.
- > 4 digits (DE0-CV, DE1-SoC, DE10-Lite at 6; Nexys4-DDR at 8): 2 rows,
  `ceil(N/2)` columns.
- At very small window sizes, the column count adapts dynamically (see scaling notes below).

**Pros:** Most natural layout — matches the physical feel of a real PCB; 7-seg is visually
adjacent to the chip. Uses otherwise-wasted space beside the chip. No change to LED/button
sections.

**Con:** More layout code than Option A; needs careful handling of small windows.

---

### Option C — Overlay toggle panel

A SimPanel-style strip that can be toggled on/off with a key. Overkill for v1 — when a
board has a 7-seg display it is always relevant during simulation. Could be revisited if we
add waveform output or other overlays that compete for screen space. Not recommended for v1.

---

## 5. Design Decision 3: Multiplexed Hardware Mode (v2)

Documented here for completeness so the v2 design has a clear starting point.

### What "physical mux mode" means

For boards with `is_multiplexed=True`, offer an opt-in contract variant using the
Option C interface (`seg`, `seg_dp`, `seg_an`). The testbench simulation loop reads
`dut.seg_an.value` every tick, identifies the active digit, records `dut.seg.value` for
that digit, and updates the display. A persistence-of-vision model can time-average
across multiple scan cycles before committing a display update (preventing flicker if the
user's scan rate is low).

### Board-specific contracts

This requires the contract checker to know which interface the board expects. One approach:
`FPGA_SIM_SEG_MODE` env var (`"logical"` or `"mux"`). The board selector or VHDL file
picker could let the user choose on mux-capable boards.

### Implication for v1

v1 must not hard-code anything that blocks v2. Specifically:
- `SevenSegDef.is_multiplexed` is populated correctly in v1 (even though v1 ignores it
  for VHDL generation).
- `SevenSegDef.select_inverted` is populated correctly in v1.
- The `sim_wrapper_7seg_template.vhd` need not be changed for v2 — a separate
  `sim_wrapper_7seg_mux_template.vhd` can be added.

---

## 6. Data Model — `SevenSegDef`

### New dataclass

```python
@dataclass
class SevenSegDef:
    """7-segment display capability extracted from a board definition."""
    num_digits: int         # total logical digits to simulate
    has_dp: bool            # decimal point pin present in board definition
    is_multiplexed: bool    # True: boards with shared segment bus + select lines
    inverted: bool          # board hardware is active-low (metadata; VHDL is active-high)
    select_inverted: bool   # mux select lines are active-low (v2 use)

    def to_dict(self) -> dict[str, object]:
        return {
            "num_digits": self.num_digits,
            "has_dp": self.has_dp,
            "is_multiplexed": self.is_multiplexed,
            "inverted": self.inverted,
            "select_inverted": self.select_inverted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SevenSegDef":
        return cls(
            num_digits=d["num_digits"],
            has_dp=d["has_dp"],
            is_multiplexed=d["is_multiplexed"],
            inverted=d.get("inverted", False),
            select_inverted=d.get("select_inverted", False),
        )
```

### `BoardDef` extension

```python
@dataclass
class BoardDef:
    ...
    seven_seg: SevenSegDef | None = None  # None for boards without 7-seg
```

`summary` property updated:
```python
@property
def summary(self) -> str:
    parts = [f"{len(self.leds)} LEDs",
             f"{len(self.buttons)} buttons",
             f"{len(self.switches)} switches"]
    if self.seven_seg:
        parts.append(f"{self.seven_seg.num_digits}-digit 7-seg")
    return ", ".join(parts)
```

### JSON serialisation

`to_json()` gains:
```python
"seven_seg": self.seven_seg.to_dict() if self.seven_seg else None,
```

`from_json()` gains:
```python
seven_seg=(SevenSegDef.from_dict(data["seven_seg"])
           if data.get("seven_seg") else None),
```

---

## 7. Board Loader Changes

### Replace `Display7SegResource` stub

In `_make_namespace()` at line 228, replace:
```python
"Display7SegResource": _stub_single,
```
with a real implementation:

```python
def _display7seg_resource(
    *args: object,
    a: str, b: str, c: str, d: str, e: str, f: str, g: str,
    dp: str | None = None,
    invert: bool = False,
    conn: str | None = None,
    attrs: "_Attrs | None" = None,
) -> "_Resource":
    subsigs = [
        _Subsignal("a", _Pins(a, dir="o")),
        _Subsignal("b", _Pins(b, dir="o")),
        _Subsignal("c", _Pins(c, dir="o")),
        _Subsignal("d", _Pins(d, dir="o")),
        _Subsignal("e", _Pins(e, dir="o")),
        _Subsignal("f", _Pins(f, dir="o")),
        _Subsignal("g", _Pins(g, dir="o")),
    ]
    if dp is not None:
        subsigs.append(_Subsignal("dp", _Pins(dp, dir="o")))
    number = args[1] if (len(args) >= 2 and isinstance(args[0], str)) else (
              args[0] if args else 0)
    ios: list = subsigs + ([attrs] if attrs else [])
    r = _Resource("display_7seg", int(number), *ios)
    r._seg_invert = invert          # stored for extraction
    r._seg_has_dp = dp is not None  # stored for extraction
    return r

# In _make_namespace():
"Display7SegResource": _display7seg_resource,
```

### Update `_classify()`

Ensure `display_7seg`, `display_7seg_an`, and `display_7seg_ctrl` return `None`
(not classified as led/button/switch). They are handled in the separate second pass.

Currently these already return `None` because they don't match `"led"`, `"button"`, etc.
This is correct — but make it explicit with an early guard:

```python
def _classify(resource: _Resource) -> str | None:
    n = resource.name.lower()
    if n == "_stub" or n.startswith("display_7seg"):
        return None
    ...
```

### Two-pass extraction in `load_board_from_source()`

After the existing first pass (leds, buttons, switches), add:

```python
seven_seg = _extract_sevenseg(resources)
```

New helper `_extract_sevenseg(resources)`:

```python
def _extract_sevenseg(resources: list[_Resource]) -> SevenSegDef | None:
    seg_resources = [r for r in resources
                     if isinstance(r, _Resource) and r.name == "display_7seg"]
    if not seg_resources:
        return None

    # Companion resource (mux select/enable lines)
    ctrl_resource = next(
        (r for r in resources if isinstance(r, _Resource)
         and r.name in ("display_7seg_an", "display_7seg_ctrl")),
        None,
    )

    inverted = any(getattr(r, "_seg_invert", False) for r in seg_resources)
    has_dp   = any(getattr(r, "_seg_has_dp",  False) for r in seg_resources)

    if ctrl_resource is not None:
        # Multiplexed: number of select pins = number of digits
        ctrl_pins = _count_ctrl_pins(ctrl_resource)
        select_inverted = _ctrl_is_inverted(ctrl_resource)
        return SevenSegDef(
            num_digits=ctrl_pins,
            has_dp=has_dp,
            is_multiplexed=True,
            inverted=inverted,
            select_inverted=select_inverted,
        )
    else:
        # Independent: one resource per digit
        return SevenSegDef(
            num_digits=len(seg_resources),
            has_dp=has_dp,
            is_multiplexed=False,
            inverted=inverted,
            select_inverted=False,
        )
```

`_count_ctrl_pins()` counts pins in the companion resource (handles both flat `_Pins` and
`_Subsignal("en", _Pins(...))` nesting). `_ctrl_is_inverted()` checks `_PinsN` usage or
`invert=True` on the companion pins.

### Updated `BoardDef` construction

Pass `seven_seg=seven_seg` to the `BoardDef(...)` constructor call.

---

## 8. VHDL Wrapper & sim_bridge Changes

### New template: `sim/sim_wrapper_7seg_template.vhd`

Identical to `sim_wrapper_template.vhd` with these additions:

```vhdl
entity sim_wrapper is
  generic (
    NUM_SWITCHES     : positive := 4;
    NUM_BUTTONS      : positive := 4;
    NUM_LEDS         : positive := 4;
    NUM_SEGS         : positive := 4;   -- ← new; always ≥1 in this template
    COUNTER_BITS     : positive := 24;
    CLK_HALF_NS_INIT : positive := 20
  );
  port (
    sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led         : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);  -- ← new
    clk_half_ns : in  natural := CLK_HALF_NS_INIT
  );
end entity;

architecture rtl of sim_wrapper is
  signal clk : std_logic := '0';
begin
  clk_proc : process
  begin
    clk <= '0'; wait for clk_half_ns * 1 ns;
    clk <= '1'; wait for clk_half_ns * 1 ns;
  end process;

  uut : entity work.{toplevel}
    generic map (
      NUM_SWITCHES => NUM_SWITCHES,
      NUM_BUTTONS  => NUM_BUTTONS,
      NUM_LEDS     => NUM_LEDS,
      NUM_SEGS     => NUM_SEGS,         -- ← new
      COUNTER_BITS => COUNTER_BITS
    )
    port map (
      clk => clk,
      sw  => sw,
      btn => btn,
      led => led,
      seg => seg                        -- ← new
    );
end architecture;
```

The existing `sim_wrapper_template.vhd` is **not modified**.

### sim_bridge.py changes

| Function / location | Change |
|---------------------|--------|
| New `_choose_wrapper_template(board_def)` | Returns 7-seg template path if `board_def.seven_seg` else current template |
| `_generate_wrapper()` (or equivalent) | Call `_choose_wrapper_template()` |
| `check_vhdl_contract(vhdl_path, board_def)` | If board has 7-seg: require `seg` port. If not: error if user declares `seg` (port-map mismatch in non-7-seg wrapper). |
| `launch_simulation(..., generics, ...)` | Add `"NUM_SEGS": board_def.seven_seg.num_digits` to generics dict when applicable |
| CLAUDE.md | Add second VHDL contract block for 7-seg boards |

### VHDL contract documentation

The CLAUDE.md VHDL Design Contract section gets a second block:

```vhdl
-- For boards with seven_seg resources (NUM_SEGS ≥ 1):
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;   -- provided by simulator; matches board digit count
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
    -- per digit i: bits [8i+7 : 8i] = {dp, g, f, e, d, c, b, a}, active-high
  );
end entity;
```

---

## 9. SevenSeg Widget — Rendering & Scaling

### Scaling architecture

The existing scaling system uses `_ui_scale(w, h) = min(w/1024, h/700)` → scale `s`. On
every `WINDOWRESIZED` event, `_layout()` recomputes all component `rect` fields using `s`.
Because component `draw()` methods derive all geometry proportionally from `self.rect`, they
automatically scale correctly.

**Rule for `SevenSeg.draw()`:** All pixel values must be derived from `self.rect.width`
(`W`) and `self.rect.height` (`H`). No scale factor `s` is accepted or needed in `draw()`.
The `rect` dimensions already encode scale because `_place_items()` set them using
`round(base_px * s)` caps.

### Segment geometry

```
  ─── a ───
 |         |
 f         b
 |         |
  ─── g ───
 |         |
 e         c
 |         |
  ─── d ───   · dp
```

For a digit rect of width `W`, height `H`:

```
thick = max(3, int(W * 0.12))   # segment thickness
gap   = max(2, int(W * 0.06))   # gap between segment and edge
inner = W - 2*gap - 2*thick     # inner span for horizontal segments
half  = H // 2                  # midpoint for g and vertical split
```

Each segment is drawn as a filled hexagon (chamfered rectangle) for authentic 7-seg
aesthetics — a plain rect has blunt ends; a hexagon with 45° corners looks like real
moulded plastic segments.

Segment bounding rectangles (top-left x, top-left y, width, height):

| Seg | x | y | w | h |
|-----|---|---|---|---|
| a | gap+thick | gap | inner | thick |
| b | W-gap-thick | gap+thick | thick | half-2*gap |
| c | W-gap-thick | half+gap | thick | half-2*gap-thick |
| d | gap+thick | H-gap-thick | inner | thick |
| e | gap | half+gap | thick | half-2*gap-thick |
| f | gap | gap+thick | thick | half-2*gap |
| g | gap+thick | half-thick//2 | inner | thick |
| dp | W+3 (right of digit rect) | H-thick-2 | thick | thick (circle) |

### Colours

```python
SEG_ON   = (255, 140,   0)   # amber — classic 7-seg colour
SEG_OFF  = ( 45,  25,   5)   # very dark amber (ghost segments, always visible)
BG       = ( 15,  15,  15)   # near-black housing background
BORDER   = (  5,   5,   5)   # housing border
```

Ghost segments (always drawn faintly even when off) match real 7-seg hardware aesthetics
and help the user understand the geometry of an unfamiliar pattern.

### Class definition

```python
class SevenSeg:
    """Draws one digit of a 7-segment display."""

    SEG_ON  = (255, 140,  0)
    SEG_OFF = ( 45,  25,  5)
    BG      = ( 15,  15, 15)

    # Bit positions in the 8-bit value: {dp, g, f, e, d, c, b, a}
    _BIT = {"a": 0, "b": 1, "c": 2, "d": 3,
            "e": 4, "f": 5, "g": 6, "dp": 7}

    def __init__(self, index: int, has_dp: bool = False) -> None:
        self.index = index
        self.has_dp = has_dp
        self.bits: int = 0
        self.rect = pygame.Rect(0, 0, 48, 76)  # default; overwritten by layout

    def set_bits(self, value8: int) -> None:
        """Set from 8-bit value {dp,g,f,e,d,c,b,a}, active-high."""
        self.bits = value8 & 0xFF

    def _seg(self, name: str) -> bool:
        return bool(self.bits & (1 << self._BIT[name]))

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        W, H = self.rect.width, self.rect.height
        thick = max(3, int(W * 0.12))
        gap   = max(2, int(W * 0.06))
        inner = max(1, W - 2 * gap - 2 * thick)
        half  = H // 2
        x0, y0 = self.rect.topleft

        # Housing
        pygame.draw.rect(surface, self.BG, self.rect, border_radius=3)
        pygame.draw.rect(surface, (5, 5, 5), self.rect, width=1, border_radius=3)

        def colour(seg_name: str) -> tuple:
            return self.SEG_ON if self._seg(seg_name) else self.SEG_OFF

        def hrect(x, y, w, h, seg_name: str) -> None:
            """Draw a horizontal segment as a hexagon."""
            c = colour(seg_name)
            pts = [
                (x + h//2, y),
                (x + w - h//2, y),
                (x + w, y + h//2),
                (x + w - h//2, y + h),
                (x + h//2, y + h),
                (x, y + h//2),
            ]
            pygame.draw.polygon(surface, c, pts)

        def vrect(x, y, w, h, seg_name: str) -> None:
            """Draw a vertical segment as a hexagon."""
            c = colour(seg_name)
            pts = [
                (x + w//2, y),
                (x + w, y + w//2),
                (x + w, y + h - w//2),
                (x + w//2, y + h),
                (x, y + h - w//2),
                (x, y + w//2),
            ]
            pygame.draw.polygon(surface, c, pts)

        ax, ay = x0 + gap + thick, y0 + gap
        hrect(ax, ay, inner, thick, "a")                              # a top
        vrect(x0 + W - gap - thick, y0 + gap + thick,
              thick, half - 2*gap, "b")                               # b TR
        vrect(x0 + W - gap - thick, y0 + half + gap,
              thick, half - 2*gap - thick, "c")                       # c BR
        hrect(ax, y0 + H - gap - thick, inner, thick, "d")           # d bottom
        vrect(x0 + gap, y0 + half + gap,
              thick, half - 2*gap - thick, "e")                       # e BL
        vrect(x0 + gap, y0 + gap + thick,
              thick, half - 2*gap, "f")                               # f TL
        hrect(ax, y0 + half - thick//2, inner, thick, "g")           # g middle

        if self.has_dp:
            r = max(2, thick // 2)
            dp_c = colour("dp")
            pygame.draw.circle(surface, dp_c,
                               (x0 + W + r + 2, y0 + H - r - 2), r)

        # Digit index label
        label_sz = max(9, int(H * 0.18))
        lbl = font.render(str(self.index), True, (100, 100, 100))
        surface.blit(lbl, (x0 + W // 2 - lbl.get_width() // 2,
                           y0 + H + 2))
```

---

## 10. FPGABoard Layout Changes

### Scaling requirements for 7-seg in `_place_items()`

Add a `"seven_segs"` branch. Digit aspect ratio must be enforced (~0.62 wide × 1.0 tall)
and capped against scale-derived maxima to prevent oversized digits at large windows:

```python
elif kind == "seven_segs":
    # Control height first (scale-capped), derive width from aspect ratio
    dh = min(avail_h * 0.85, round(76 * scale))    # 76 px at reference size
    dw = min(dh * 0.62, avail_w_per_col * 0.85, round(48 * scale))
    label_h = max(10, int(dh * 0.22))  # space below digit for index label
    dh_net = dh  # the SevenSeg rect height (label drawn outside the rect)
```

The `dp` circle extends ~`thick + 4` px to the right of the digit rect. Account for this
in column spacing by adding a small gap per digit.

### Dynamic row count for small windows (Option B)

When the available width in the 7-seg panel is narrow, recompute rows to keep digits legible:

```python
# Minimum readable digit width
MIN_DW = 24
cols = num_digits
while cols > 1 and (avail_w / cols) * 0.85 < MIN_DW:
    cols = math.ceil(cols / 2)
rows = math.ceil(num_digits / cols)
```

This handles the Nexys4-DDR (8 digits) at small window sizes gracefully: at 640 px wide,
45% right column = 288 px; 8 digits at 36 px each = fine; at 320 px, drops to 4×2.

### Option B layout changes in `_layout()`

```python
if self.board_def.seven_seg and self._seven_segs:
    top_rect = pygame.Rect(margin, margin, w - 2*margin, top_sec_h)
    chip_w = int(top_rect.width * 0.55)
    seg_w  = top_rect.width - chip_w - section_pad
    chip_rect = pygame.Rect(top_rect.x, top_rect.y, chip_w, top_rect.height)
    seg_rect  = pygame.Rect(top_rect.x + chip_w + section_pad,
                            top_rect.y, seg_w, top_rect.height)
    self._place_items([self.fpga_chip], ..., "fpga")   # within chip_rect
    self._place_items(self._seven_segs, ..., "seven_segs")  # within seg_rect
else:
    # unchanged: full-width chip section
    self._place_items([self.fpga_chip], ..., "fpga")
```

### New `FPGABoard` members

```python
self._seven_segs: list[SevenSeg] = []   # populated in __init__ from board_def.seven_seg

def set_seg(self, index: int, bits8: int) -> None:
    if 0 <= index < len(self._seven_segs):
        self._seven_segs[index].set_bits(bits8)
```

### Dirty-flag integration

The existing LED-state dirty flag (from the performance work) should extend to 7-seg: if no
LED or segment state changed since the last frame, skip `_draw()`. This is a small addition
to the comparison check already in place.

---

## 11. sim_testbench Changes

### Initialization

At startup, after `_load_board_from_env()`:

```python
_seven_seg_def: SevenSegDef | None = board_def.seven_seg
```

Pass to `FPGABoard` constructor (which already takes `board_def`, so no new param needed —
`FPGABoard.__init__` constructs `_seven_segs` from `board_def.seven_seg`).

### Main simulation loop

After the existing LED-reading block:

```python
# 7-segment display output
if _seven_seg_def is not None:
    try:
        seg_raw = int(dut.seg.value)   # BinaryValue → int
        for i in range(_seven_seg_def.num_digits):
            board.set_seg(i, (seg_raw >> (8 * i)) & 0xFF)
    except Exception:
        pass  # signal may be undefined (X/Z) at sim start
```

`cocotb.BinaryValue.integer` with `big_endian=False` may be used for clarity; the plain
`int()` also works and treats undefined bits as 0.

### Drawing

`FPGABoard._draw()` already iterates and calls `.draw()` on all component lists. Extend:

```python
for seg in self._seven_segs:
    seg.draw(surface, font)
```

Draw a "7-SEG" section title above the panel (in `_draw()`, not `_place_items()`).

---

## 12. Example VHDL — `counter_7seg.vhd`

A hex counter that shows its count across all available digits. Uses a lookup table for
segment encoding. Works on all 9 boards (DE0 at 4 digits, DE10-Lite at 6, Nexys4-DDR at 8,
etc.) because NUM_SEGS is set by the simulator.

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity;

architecture rtl of counter_7seg is
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');

  -- 7-segment encoding: {dp=0, g, f, e, d, c, b, a}, active-high
  type seg_lut_t is array(0 to 15) of std_logic_vector(7 downto 0);
  constant SEG_LUT : seg_lut_t := (
    x"3F",  -- 0: a,b,c,d,e,f
    x"06",  -- 1: b,c
    x"5B",  -- 2: a,b,d,e,g
    x"4F",  -- 3: a,b,c,d,g
    x"66",  -- 4: b,c,f,g
    x"6D",  -- 5: a,c,d,f,g
    x"7D",  -- 6: a,c,d,e,f,g
    x"07",  -- 7: a,b,c
    x"7F",  -- 8: all segments
    x"6F",  -- 9: a,b,c,d,f,g
    x"77",  -- A: a,b,c,e,f,g
    x"7C",  -- b: c,d,e,f,g
    x"39",  -- C: a,d,e,f
    x"5E",  -- d: b,c,d,e,g
    x"79",  -- E: a,d,e,f,g
    x"71"   -- F: a,e,f,g
  );
begin
  process(clk) is
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  -- Mirror upper LED bits to the LED outputs
  led <= std_logic_vector(
    counter(COUNTER_BITS - 1 downto COUNTER_BITS - NUM_LEDS));

  -- Show counter nibbles across the 7-seg digits
  gen_segs : for i in 0 to NUM_SEGS - 1 generate
    seg(8*i + 7 downto 8*i) <= SEG_LUT(
      to_integer(counter(4*i + 3 downto 4*i)));
  end generate;

end architecture;
```

This design immediately demonstrates:
- The `{dp,g,f,e,d,c,b,a}` bit ordering.
- How `NUM_SEGS` drives the generate loop.
- Coexistence of LED and 7-seg outputs in the same entity.

---

## 13. Test Strategy

### `tests/test_board_loader_sevenseg.py`

```python
# Load real board files from the submodule
def test_de0_sevenseg():           # 4 independent, has_dp, inverted
def test_de0_cv_no_dp():           # 6 independent, no dp
def test_de10_lite_sevenseg():     # 6 independent, has_dp
def test_nandland_go_sevenseg():   # 2 independent, no dp
def test_nexys4ddr_multiplexed():  # 8 mux, is_multiplexed=True, select_inverted=True
def test_rz_easyfpga_multiplexed():# 4 mux
def test_arty_no_sevenseg():       # no 7-seg → seven_seg is None
def test_ulx3s_no_sevenseg():      # ULX3S → seven_seg is None (I2C indirect)
```

### `tests/test_sevenseg_json.py`

Round-trip serialisation:
- `BoardDef.from_json(bd.to_json()).seven_seg` equals original `bd.seven_seg`.
- Board without 7-seg round-trips `seven_seg=None`.
- `SevenSegDef.from_dict(ssd.to_dict())` is identity for all field combinations.

### `tests/test_sevenseg_component.py`

Headless pygame (using `pygame.display.set_mode((1,1))` fixture):

- `SevenSeg.set_bits(0x3F)` → segments a–f on, g off ("0").
- `SevenSeg.set_bits(0x06)` → b, c on ("1").
- `SevenSeg.set_bits(0x00)` → all off (blank digit).
- `SevenSeg.set_bits(0xFF)` → all on including dp.
- `SevenSeg.draw()` does not raise for rect sizes from 20×32 to 200×320.
- `SevenSeg.draw()` with `has_dp=False` does not draw a dp circle.

### `sim/test_7seg.py`

Headless cocotb test analogous to `sim/test_blinky.py`:

```python
@cocotb.test()
async def test_counter_counts(dut):
    await Timer(50_000, "ns")   # let counter advance
    seg_val = int(dut.seg.value)
    assert seg_val != 0         # at least one digit is non-zero

@cocotb.test()
async def test_seg_changes_over_time(dut):
    await Timer(1_000, "ns")
    v1 = int(dut.seg.value)
    await Timer(100_000, "ns")
    v2 = int(dut.seg.value)
    assert v1 != v2             # counter progresses
```

---

## 14. Phased Delivery

| Phase | Scope | Key files touched | Completion criterion |
|-------|-------|-------------------|---------------------|
| **1 — Data model & loader** | `SevenSegDef`, real `Display7SegResource` mock, two-pass extraction, JSON round-trip | `board_loader.py`, `tests/test_board_loader_sevenseg.py`, `tests/test_sevenseg_json.py` | 9 boards report correct `SevenSegDef`; all existing tests pass |
| **2 — VHDL & bridge** | New wrapper template, `check_vhdl_contract`, generics, `counter_7seg.vhd`, testbench seg-reading | `sim/sim_wrapper_7seg_template.vhd`, `sim_bridge.py`, `sim/sim_testbench.py`, `hdl/counter_7seg.vhd`, `sim/test_7seg.py`, `CLAUDE.md` | `counter_7seg.vhd` compiles and runs headlessly; segment signal readable in cocotb |
| **3 — UI** | `SevenSeg` widget, layout horizontal split (Option B), `FPGABoard.set_seg()`, section title | `ui/components.py`, `ui/board_display.py`, `tests/test_sevenseg_component.py` | Digits visible and scale correctly on window resize; amber segments render on all 9 boards |
| **4 — Polish** | CLAUDE.md full update, CONTRIBUTING.md, README screenshot/section, verify all 9 boards | docs, `CLAUDE.md`, `README.md` | Feature complete; documentation accurate |

Phase 1 and Phase 2 are largely independent of each other after `SevenSegDef` exists —
the VHDL bridge work can be prototyped against a hardcoded `SevenSegDef` while the
loader extraction is being refined.

---

## Open Questions / Risks

| Item | Note |
|------|------|
| GHDL null-range ports | If two-template approach is abandoned and a single template with `NUM_SEGS : natural := 0` is preferred, GHDL's handling of `std_logic_vector(-1 downto 0)` ports must be verified experimentally. |
| StepMXO2 control lines | Treated as 2 independent digits in v1. If that turns out to produce wrong VHDL behaviour, revisit as part of v2 mux mode. |
| Minimum legible digit size | 24 px wide assumed. Verify during UI implementation — may need adjustment. |
| Option B fallback | If horizontal split proves unexpectedly complex, Option A (vertical section) is a complete fallback with nearly identical user experience. Document the decision when chosen. |
| v2 mux mode | Capture in the enhancement list (`project_enhancements.md` memory) once v1 ships. |
