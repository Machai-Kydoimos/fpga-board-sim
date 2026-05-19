# 7-Segment Display Support — Implementation Plan v2

*Status: ready for implementation, 2026-04-18. Updated 2026-04-18: added NVC tests (§5.7), generate\_board\_images SVG (§6.4), ruff/mypy compliance note (§2.5), and 11 precision corrections (COUNTER\_BITS=32, regex tightening, `_prev_seg_bits` instance variable, NVC headless note, closure type annotations, `from_dict` dict type, cocotb bit-width, SVG polygon helper spec, bad-contract fixture content, CHANGELOG, `_layout()` guidance).*
*Supersedes: `7seg_display_plan_draft.md` (draft research document, retained for reference).*

---

## Contents

1. [Research Summary](#1-research-summary)
2. [Design Decisions (settled)](#2-design-decisions-settled)
   - [2.5 Cross-cutting: ruff & mypy compliance](#25-cross-cutting-ruff--mypy-compliance)
3. [Phase 0 — Prerequisites](#3-phase-0--prerequisites)
4. [Phase 1 — Data Model & Board Loader](#4-phase-1--data-model--board-loader)
5. [Phase 2 — VHDL Wrapper & sim_bridge](#5-phase-2--vhdl-wrapper--sim_bridge)
6. [Phase 3 — UI Widget & Layout](#6-phase-3--ui-widget--layout)
7. [Phase 4 — Polish & Integration](#7-phase-4--polish--integration)
8. [Open Risks & Mitigations](#8-open-risks--mitigations)

---

## 1. Research Summary

Nine boards in the `amaranth-boards` submodule define `Display7SegResource` entries.
All nine are currently silently dropped by the `_stub_single` handler in `board_loader.py:228`.

### Independent boards (N separate digit resources per board)

| Board | Digits | Has DP | Inverted |
|-------|--------|--------|----------|
| DE0 | 4 | Yes | Yes |
| Nandland-Go | 2 | No | Yes |
| DE0-CV | 6 | No | Yes |
| DE1-SoC | 6 | No | Yes |
| DE10-Lite | 6 | Yes | Yes |

### Multiplexed boards (shared segment bus + companion select resource)

| Board | Digits | Has DP | Companion resource | Select polarity |
|-------|--------|--------|--------------------|-----------------|
| Nexys4-DDR | 8 | Yes | `display_7seg_an` (8-pin `PinsN`) | Active-low |
| Mercury | 4 | Yes | `display_7seg_ctrl` (4-pin `Pins`) | Active-high |
| RZ-EasyFPGA-A2/2 | 4 | Yes | `display_7seg_ctrl` (4-pin `Pins(invert=True)`) | Active-low |
| StepMXO2 | 2† | Yes | `display_7seg_ctrl` (2-pin `Pins(invert=True)`) | Active-low |

†StepMXO2 has two `Display7SegResource` entries with a 2-pin companion — treated as
2 independent digits in v1.

### ULX3S exclusion

The ULX3S display is driven through an I2C GPIO expander (not direct FPGA pins) so
`Display7SegResource` was correctly omitted by the amaranth-boards authors. Add a comment
in `_make_namespace()` to document this design boundary.

---

## 2. Design Decisions (settled)

### VHDL interface — logical vector (Option A, unanimous)

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;   -- 7-seg boards only
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
    -- digit i occupies bits [8i+7 : 8i] = {dp, g, f, e, d, c, b, a}, active-high
  );
end entity;
```

- `seg` is present only on 7-seg boards; absent on all others.
- Polarity normalised to active-high in VHDL regardless of board hardware.
- `NUM_SEGS` is `positive` (≥ 1) — no null-range issues.
- Two wrapper templates (existing unchanged; new `sim_wrapper_7seg_template.vhd`).
- `check_vhdl_contract()` enforces the presence/absence of `seg` based on the board.

Multiplexed physical mode (where the user writes a scan state machine) is reserved for v2.

### 2.5 Cross-cutting: ruff & mypy compliance

Every file under `src/` is checked by `ruff check`, `ruff format --check`, and `mypy`
in the `lint` CI job (`.github/workflows/ci.yml`) on every push. Configuration is in
`pyproject.toml`:

- **mypy** — `disallow_untyped_defs = true`; all functions in `src/` need full type
  annotations on parameters and return values.
- **ruff `ANN`** — annotations required on all public functions and methods.
- **ruff `D`** — one-line docstrings required on all public classes and methods.
- `tests/*` and `sim/test_*.py` are exempt from `ANN`/`D`.

**Implication for every phase:** all new code in `src/` (`board_loader.py`,
`sim_bridge.py`, `ui/components.py`, `generate_board_images.py`) must include full
type annotations and docstrings from the start. Budget ~20 min per phase to run
`uv run ruff check . && uv run mypy .` and fix any violations before opening a PR.

### Display layout — horizontal split (Option B)

```
┌─────────────────┬────────────────────┐
│                 │   [0] [1] [2]      │
│   FPGA Chip     │   [3] [4] [5]      │  top section split 55/45
│                 │                    │
├─────────────────┴────────────────────┤
│        ● ● ● ● ● ● ● ●              │
├──────────────────────────────────────┤
│     [BTN0] [BTN1] [BTN2]            │
├──────────────────────────────────────┤
│     SW0  SW1  SW2  SW3               │
└──────────────────────────────────────┘
```

Option A (vertical section below chip) is the explicit fallback if Option B proves
unexpectedly difficult during implementation; document the choice when made.

---

## 3. Phase 0 — Prerequisites

Add VHDL test fixtures before writing any implementation code. These gate the contract
checker tests in Phase 2 and must exist before implementation begins.

### Files to create

| File | Purpose |
|------|---------|
| `hdl/counter_7seg.vhd` | Working 7-seg example; also the target for GHDL/NVC CI tests |
| `hdl/bad_contract_7seg_missing_seg.vhdl` | Valid syntax, has `clk/sw/btn/led` but no `seg` — used to test contract rejection |
| `hdl/bad_contract_7seg_extra_seg.vhdl` | Has `clk/sw/btn/led/seg` — used to test rejection on non-7-seg boards |

### `hdl/bad_contract_7seg_missing_seg.vhdl`

Valid VHDL that compiles cleanly with `ghdl -a`, but intentionally **omits `seg`**.
Use this as the target for `test_7seg_board_rejects_standard_design` in §5.5.
Entity name must be `bad_contract_7seg_missing_seg` (matches filename stem).

```vhdl
library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_7seg_missing_seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
    -- seg intentionally absent
  );
end entity;

architecture rtl of bad_contract_7seg_missing_seg is
begin
  led <= (others => '0');
end architecture;
```

### `hdl/bad_contract_7seg_extra_seg.vhdl`

Valid VHDL with a `seg` port, used to verify that a **non-7-seg board** rejects it.
Entity name must be `bad_contract_7seg_extra_seg` (matches filename stem).

```vhdl
library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_7seg_extra_seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity;

architecture rtl of bad_contract_7seg_extra_seg is
begin
  led <= (others => '0');
  seg <= (others => '0');
end architecture;
```

### `hdl/counter_7seg.vhd`

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
    COUNTER_BITS : positive := 32   -- 32 so bits 4*i+3..4*i are valid for all 9 boards (max 8 digits × 4 bits = 32)
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

  -- {dp=0, g, f, e, d, c, b, a}, active-high
  type seg_lut_t is array(0 to 15) of std_logic_vector(7 downto 0);
  constant SEG_LUT : seg_lut_t := (
    x"3F",  -- 0
    x"06",  -- 1
    x"5B",  -- 2
    x"4F",  -- 3
    x"66",  -- 4
    x"6D",  -- 5
    x"7D",  -- 6
    x"07",  -- 7
    x"7F",  -- 8
    x"6F",  -- 9
    x"77",  -- A
    x"7C",  -- b
    x"39",  -- C
    x"5E",  -- d
    x"79",  -- E
    x"71"   -- F
  );
begin
  process(clk) is
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  -- Safe only when NUM_LEDS <= COUNTER_BITS (always true for real boards)
  led <= std_logic_vector(counter(COUNTER_BITS - 1 downto COUNTER_BITS - NUM_LEDS));

  gen_segs : for i in 0 to NUM_SEGS - 1 generate
    seg(8*i + 7 downto 8*i) <= SEG_LUT(to_integer(counter(4*i + 3 downto 4*i)));
  end generate;

end architecture;
```

---

## 4. Phase 1 — Data Model & Board Loader

**Files touched**: `src/fpga_sim/board_loader.py`,
`tests/test_board_loader_sevenseg.py`, `tests/test_sevenseg_json.py`

**Completion gate**: all inline tests pass without submodule; parametric real-board tests
pass with submodule; existing tests unchanged.

### 4.1 `SevenSegDef` dataclass

Add to `board_loader.py` alongside `BoardDef`:

```python
@dataclass
class SevenSegDef:
    """7-segment display capability extracted from a board definition."""
    num_digits: int
    has_dp: bool
    is_multiplexed: bool
    inverted: bool         # board hardware active-low (metadata; VHDL is active-high)
    select_inverted: bool  # mux select lines active-low (v2 use)

    def to_dict(self) -> dict[str, object]:
        return {
            "num_digits": self.num_digits,
            "has_dp": self.has_dp,
            "is_multiplexed": self.is_multiplexed,
            "inverted": self.inverted,
            "select_inverted": self.select_inverted,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "SevenSegDef":
        return cls(
            num_digits=d["num_digits"],           # strict: required field
            has_dp=d["has_dp"],                   # strict: required field
            is_multiplexed=d["is_multiplexed"],   # strict: required field
            inverted=d.get("inverted", False),    # .get(): forward-compat default
            select_inverted=d.get("select_inverted", False),
        )
```

`num_digits`, `has_dp`, `is_multiplexed` use strict `d[key]` access (not `.get()`)
because their absence indicates a serialisation bug, not a version difference.

### 4.2 `BoardDef` extension

```python
@dataclass
class BoardDef:
    ...
    seven_seg: SevenSegDef | None = None

    @property
    def summary(self) -> str:
        parts = [f"{len(self.leds)} LEDs",
                 f"{len(self.buttons)} buttons",
                 f"{len(self.switches)} switches"]
        if self.seven_seg:
            parts.append(f"{self.seven_seg.num_digits}-digit 7-seg")
        return ", ".join(parts)
```

`to_json()` addition:
```python
"seven_seg": self.seven_seg.to_dict() if self.seven_seg else None,
```

`from_json()` addition:
```python
seven_seg=(SevenSegDef.from_dict(data["seven_seg"])
           if data.get("seven_seg") else None),
```

### 4.3 `Display7SegResource` mock

Replace the `_stub_single` entry in `_make_namespace()`:

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
    # Mirrors real amaranth API: (number,) or (name, number)
    if len(args) >= 2 and isinstance(args[0], str):
        number = int(args[1])
    elif args:
        number = int(args[0])
    else:
        number = 0
    ios: list = subsigs + ([attrs] if attrs else [])
    r = _Resource("display_7seg", number, *ios)
    r._seg_invert = invert
    r._seg_has_dp = dp is not None
    return r

# In _make_namespace():
"Display7SegResource": _display7seg_resource,
```

### 4.4 `_classify()` guard

Add an explicit early return so future readers understand the intent:

```python
def _classify(resource: _Resource) -> str | None:
    n = resource.name.lower()
    if n == "_stub" or n.startswith("display_7seg"):
        return None
    ...
```

### 4.5 Extraction helpers (fully specified)

```python
def _count_ctrl_pins(ctrl: _Resource) -> int:
    """Count pins in a mux-select companion resource."""
    pins, _, _, _ = _extract_pins(ctrl)   # reuse existing helper
    return max(1, len(pins))

def _ctrl_is_inverted(ctrl: _Resource) -> bool:
    """True when the companion resource uses PinsN or invert=True."""
    _, _, inverted, _ = _extract_pins(ctrl)
    return inverted

def _extract_sevenseg(resources: list[_Resource]) -> "SevenSegDef | None":
    seg_resources = [r for r in resources
                     if isinstance(r, _Resource) and r.name == "display_7seg"]
    if not seg_resources:
        return None

    ctrl_resource = next(
        (r for r in resources
         if isinstance(r, _Resource)
         and r.name.startswith("display_7seg_")
         and r.name != "display_7seg"),
        None,
    )
    # Prefix-based: catches any future companion name (e.g. "display_7seg_sel"),
    # not just the two currently known ("display_7seg_an", "display_7seg_ctrl").

    # Collect invert: check both resource-level flag AND pin-level PinsN.
    # _extract_pins() normalises PinsN → inverted=True, so checking it
    # catches boards that set polarity at the pin rather than resource level.
    res_level_inv = any(getattr(r, "_seg_invert", False) for r in seg_resources)
    _, _, pin_level_inv, _ = _extract_pins(seg_resources[0])
    inverted = res_level_inv or pin_level_inv

    has_dp = any(getattr(r, "_seg_has_dp", False) for r in seg_resources)

    if ctrl_resource is not None:
        return SevenSegDef(
            num_digits=_count_ctrl_pins(ctrl_resource),
            has_dp=has_dp,
            is_multiplexed=True,
            inverted=inverted,
            select_inverted=_ctrl_is_inverted(ctrl_resource),
        )
    else:
        return SevenSegDef(
            num_digits=len(seg_resources),
            has_dp=has_dp,
            is_multiplexed=False,
            inverted=inverted,
            select_inverted=False,
        )
```

### 4.6 `load_board_from_source()` — two-pass extraction

After the existing LED/button/switch loop, add:

```python
seven_seg = _extract_sevenseg(resources)
```

Pass `seven_seg=seven_seg` to the `BoardDef(...)` constructor.

### 4.7 Tests — `tests/test_board_loader_sevenseg.py`

#### Hermetic inline-source tests (no submodule, always run)

```python
_INLINE_4SEG_INDEPENDENT = """
from amaranth.build import *
from amaranth.vendor import IntelPlatform
class FakeDe0Platform(IntelPlatform):
    resources = [
        *LEDResources(pins="A B C D"),
        Display7SegResource(0, a="P1",b="P2",c="P3",d="P4",e="P5",f="P6",g="P7",dp="P8",invert=True),
        Display7SegResource(1, a="Q1",b="Q2",c="Q3",d="Q4",e="Q5",f="Q6",g="Q7",dp="Q8",invert=True),
        Display7SegResource(2, a="R1",b="R2",c="R3",d="R4",e="R5",f="R6",g="R7",dp="R8",invert=True),
        Display7SegResource(3, a="S1",b="S2",c="S3",d="S4",e="S5",f="S6",g="S7",dp="S8",invert=True),
    ]
"""

def test_inline_4seg_independent():
    boards = load_board_from_source(_INLINE_4SEG_INDEPENDENT)
    ssd = boards[0].seven_seg
    assert ssd.num_digits == 4
    assert ssd.is_multiplexed is False
    assert ssd.has_dp is True
    assert ssd.inverted is True

_INLINE_8SEG_MULTIPLEXED = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class FakeNexys4Platform(XilinxPlatform):
    resources = [
        *LEDResources(pins="A B C D E F G H"),
        Display7SegResource(0, a="SA",b="SB",c="SC",d="SD",e="SE",f="SF",g="SG",dp="SP"),
        Resource("display_7seg_an", 0, PinsN("AN0 AN1 AN2 AN3 AN4 AN5 AN6 AN7", dir="o")),
    ]
"""

def test_inline_8seg_multiplexed():
    boards = load_board_from_source(_INLINE_8SEG_MULTIPLEXED)
    ssd = boards[0].seven_seg
    assert ssd.num_digits == 8
    assert ssd.is_multiplexed is True
    assert ssd.select_inverted is True   # PinsN companion → active-low

_INLINE_6SEG_NO_DP = """
from amaranth.build import *
from amaranth.vendor import IntelPlatform
class FakeDeCvPlatform(IntelPlatform):
    resources = [
        *LEDResources(pins="A B"),
        Display7SegResource(0, a="P1",b="P2",c="P3",d="P4",e="P5",f="P6",g="P7",invert=True),
        Display7SegResource(1, a="Q1",b="Q2",c="Q3",d="Q4",e="Q5",f="Q6",g="Q7",invert=True),
        Display7SegResource(2, a="R1",b="R2",c="R3",d="R4",e="R5",f="R6",g="R7",invert=True),
        Display7SegResource(3, a="S1",b="S2",c="S3",d="S4",e="S5",f="S6",g="S7",invert=True),
        Display7SegResource(4, a="T1",b="T2",c="T3",d="T4",e="T5",f="T6",g="T7",invert=True),
        Display7SegResource(5, a="U1",b="U2",c="U3",d="U4",e="U5",f="U6",g="U7",invert=True),
    ]
"""

def test_inline_no_dp_flag():
    boards = load_board_from_source(_INLINE_6SEG_NO_DP)
    assert boards[0].seven_seg.has_dp is False

_INLINE_NO_SEG = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class FakeArtyPlatform(XilinxPlatform):
    resources = [*LEDResources(pins="A B C D")]
"""

def test_inline_no_sevenseg():
    boards = load_board_from_source(_INLINE_NO_SEG)
    assert boards[0].seven_seg is None
```

#### Real-submodule parametric test (integration, requires submodule)

```python
_EXPECTED_7SEG = {
    # name_fragment: (num_digits, has_dp, is_multiplexed)
    "DE0":         (4, True,  False),
    "Nandland Go": (2, False, False),
    "DE0-CV":      (6, False, False),
    "DE1-SoC":     (6, False, False),
    "DE10-Lite":   (6, True,  False),
    "Nexys4-DDR":  (8, True,  True),
    "Mercury":     (4, True,  True),
}

@pytest.mark.parametrize("name_frag,expected", _EXPECTED_7SEG.items())
def test_real_board_sevenseg(all_boards, name_frag, expected):
    matches = [b for b in all_boards if name_frag.lower() in b.name.lower()]
    if not matches:
        pytest.skip(f"{name_frag} not in submodule")
    ssd = matches[0].seven_seg
    assert ssd is not None, f"{name_frag}: expected SevenSegDef, got None"
    num_digits, has_dp, is_mux = expected
    assert ssd.num_digits == num_digits
    assert ssd.has_dp == has_dp
    assert ssd.is_multiplexed == is_mux

def test_arty_has_no_sevenseg(all_boards):
    arty = next((b for b in all_boards if "Arty A7-35" in b.name), None)
    if arty is None:
        pytest.skip("Arty not in submodule")
    assert arty.seven_seg is None
```

### 4.8 Tests — `tests/test_sevenseg_json.py`

```python
from fpga_sim.board_loader import BoardDef, SevenSegDef
import pytest

def test_roundtrip_with_sevenseg():
    ssd = SevenSegDef(6, False, False, True, False)
    bd = BoardDef(name="Test", class_name="TestPlatform", seven_seg=ssd)
    assert BoardDef.from_json(bd.to_json()).seven_seg == ssd

def test_roundtrip_without_sevenseg():
    bd = BoardDef(name="Test", class_name="TestPlatform")
    assert BoardDef.from_json(bd.to_json()).seven_seg is None

@pytest.mark.parametrize("num_digits,has_dp,is_mux,inv,sel_inv", [
    (4, True,  False, True,  False),
    (8, True,  True,  False, True),
    (2, False, False, False, False),
    (6, False, False, True,  False),
])
def test_sevensegdef_dict_roundtrip(num_digits, has_dp, is_mux, inv, sel_inv):
    ssd = SevenSegDef(num_digits, has_dp, is_mux, inv, sel_inv)
    assert SevenSegDef.from_dict(ssd.to_dict()) == ssd
```

---

## 5. Phase 2 — VHDL Wrapper & sim_bridge

**Files touched**: `sim/sim_wrapper_7seg_template.vhd` (new),
`src/fpga_sim/sim_bridge.py`, `sim/sim_testbench.py`,
`sim/test_7seg.py` (new), `tests/test_vhdl_validation.py`,
`tests/test_nvc.py`, `src/fpga_sim/__main__.py`, `CLAUDE.md`

**Completion gate**: `counter_7seg.vhd` analyzes, elaborates, and runs headlessly
under both GHDL and NVC; cocotb reads a valid hex glyph from `dut.seg.value`;
`check_vhdl_contract()` correctly gates 7-seg vs non-7-seg designs; all new and
existing tests pass.

### 5.1 `sim/sim_wrapper_7seg_template.vhd`

Identical to the existing `sim_wrapper_template.vhd` with `NUM_SEGS` added.
The generic default is `4` — safe for GHDL early elaboration with any design.
The runtime value is passed via `-gNUM_SEGS=N`, same as all other generics.
The only substitution token is `{toplevel}` (unchanged from the existing template).

```vhdl
entity sim_wrapper is
  generic (
    NUM_SWITCHES     : positive := 4;
    NUM_BUTTONS      : positive := 4;
    NUM_LEDS         : positive := 4;
    NUM_SEGS         : positive := 4;       -- new
    COUNTER_BITS     : positive := 24;
    CLK_HALF_NS_INIT : positive := 20
  );
  port (
    sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led         : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);  -- new
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
      NUM_SEGS     => NUM_SEGS,             -- new
      COUNTER_BITS => COUNTER_BITS
    )
    port map (
      clk => clk,
      sw  => sw,
      btn => btn,
      led => led,
      seg => seg                            -- new
    );
end architecture;
```

The existing `sim_wrapper_template.vhd` is **not modified**.

### 5.2 `sim_bridge.py` — full API chain

This is the most critical change. `board_def` must flow from callers through the bridge.
All new parameters are optional with `None` defaults to preserve backward compatibility.

#### New constants and helpers

```python
_WRAPPER_7SEG_TEMPLATE: Path = (
    Path(__file__).parent.parent.parent / "sim" / "sim_wrapper_7seg_template.vhd"
)

def _choose_wrapper_template(board_def: "BoardDef | None") -> Path:
    if board_def is not None and board_def.seven_seg is not None:
        return _WRAPPER_7SEG_TEMPLATE
    return _WRAPPER_TEMPLATE
```

#### Updated `_generate_wrapper()`

```python
def _generate_wrapper(
    toplevel: str,
    work_dir: str,
    board_def: "BoardDef | None" = None,   # new optional param
) -> Path:
    template = _choose_wrapper_template(board_def)
    content = template.read_text().replace("{toplevel}", toplevel)
    out = Path(work_dir) / "sim_wrapper.vhd"
    out.write_text(content)
    return out
```

#### Updated `check_vhdl_contract()`

```python
def check_vhdl_contract(
    path: str | Path,
    board_def: "BoardDef | None" = None,   # new optional param
) -> tuple[bool, str]:
    ...
    # Existing checks (entity name, required ports) unchanged.

    # 7-seg contract gating (only when board_def is provided)
    has_seg_port = bool(re.search(r"\bseg\s*:\s*out\b", text, re.IGNORECASE))
    # r"\bseg\b" is too broad — matches "seg_count", comments, etc.
    board_needs_seg = board_def is not None and board_def.seven_seg is not None

    if board_needs_seg and not has_seg_port:
        nd = board_def.seven_seg.num_digits
        return False, (
            f"Board has a {nd}-digit 7-segment display but '{path.name}' "
            "has no 'seg' port.\n"
            "Add: seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)"
        )
    if not board_needs_seg and has_seg_port:
        return False, (
            f"'{path.name}' declares a 'seg' port but the selected board "
            "has no 7-segment display.\n"
            "Remove the 'seg' port, or select a 7-seg board (DE0, Nexys4-DDR, etc.)."
        )
    ...
```

#### Updated `analyze_vhdl()`

```python
def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: str = "ghdl",
    board_def: "BoardDef | None" = None,   # new optional param
) -> tuple[bool, str]:
    ...
    wrapper_path = _generate_wrapper(toplevel, work_dir, board_def=board_def)
    ...
```

#### Updated `launch_simulation()`

```python
def launch_simulation(
    board_json: str,
    vhdl_path: str | Path,
    toplevel: str = "blinky",
    generics: dict[str, str] | None = None,
    sim_width: int = 1024,
    sim_height: int = 700,
    work_dir: str | None = None,
    simulator: str = "ghdl",
    board_def: "BoardDef | None" = None,   # new optional param
) -> bool:
    ...
    # Resolve board_def from JSON if not passed directly
    if board_def is None and board_json:
        from fpga_sim.board_loader import BoardDef as _BD
        try:
            board_def = _BD.from_json(board_json)
        except Exception:
            pass

    # Add NUM_SEGS to generics when applicable
    generics = dict(generics or {})
    if board_def and board_def.seven_seg:
        generics["NUM_SEGS"] = str(board_def.seven_seg.num_digits)

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")
        ...
        wrapper_path = _generate_wrapper(toplevel, work_dir, board_def=board_def)
        ...
```

#### `__main__.py` call sites

Two one-line changes:
1. `check_vhdl_contract(vhdl_path)` → `check_vhdl_contract(vhdl_path, board_def=selected_board)`
2. `analyze_vhdl(vhdl_path, ...)` → `analyze_vhdl(vhdl_path, ..., board_def=selected_board)`

(`selected_board` is already in scope at both call sites in the existing main flow.)

### 5.3 `sim/sim_testbench.py` changes

#### 7-seg reading in the main loop

After the existing LED-reading block:

```python
# 7-segment display output
_seven_seg_def = board_def.seven_seg if board_def else None
if _seven_seg_def is not None:
    try:
        seg_raw = int(dut.seg.value)
        for i in range(_seven_seg_def.num_digits):
            board.set_seg(i, (seg_raw >> (8 * i)) & 0xFF)
    except Exception:
        pass  # X/Z at simulation start; safely ignored
```

#### Updated banner

```python
print(f"  {num_led} LEDs, {num_btn} buttons, {num_sw} switches"
      + (f", {_seven_seg_def.num_digits}-digit 7-seg" if _seven_seg_def else ""))
```

#### Updated `_write_meta_sidecar()`

Add `num_segs` field to the meta dict.

### 5.4 CLAUDE.md — dual VHDL contract

Add a second contract block for 7-seg boards (see design decision section for the
exact VHDL block).

### 5.5 Tests — additions to `tests/test_vhdl_validation.py`

#### Contract checker with `board_def`

```python
def test_7seg_board_rejects_standard_design():
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    ok, msg = check_vhdl_contract(HDL / "blinky.vhd", board_def=bd)
    assert not ok
    assert "seg" in msg.lower()

def test_non7seg_board_rejects_7seg_design():
    from fpga_sim.board_loader import BoardDef
    bd = BoardDef("Arty", "ArtyPlatform")   # no seven_seg
    ok, msg = check_vhdl_contract(HDL / "counter_7seg.vhd", board_def=bd)
    assert not ok
    assert "seg" in msg.lower()

def test_7seg_board_accepts_7seg_design():
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    ok, _ = check_vhdl_contract(HDL / "counter_7seg.vhd", board_def=bd)
    assert ok

def test_non7seg_board_accepts_standard_design():
    ok, _ = check_vhdl_contract(HDL / "blinky.vhd", board_def=None)
    assert ok
```

#### Template selection (no GHDL required)

```python
def test_choose_wrapper_template_non_7seg():
    from fpga_sim.sim_bridge import _WRAPPER_TEMPLATE, _choose_wrapper_template
    assert _choose_wrapper_template(None) == _WRAPPER_TEMPLATE

def test_choose_wrapper_template_7seg():
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    from fpga_sim.sim_bridge import _WRAPPER_7SEG_TEMPLATE, _choose_wrapper_template
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    assert _choose_wrapper_template(bd) == _WRAPPER_7SEG_TEMPLATE

def test_generate_wrapper_7seg_has_seg_port(tmp_path):
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    from fpga_sim.sim_bridge import _generate_wrapper
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    out = _generate_wrapper("counter_7seg", str(tmp_path), board_def=bd)
    text = out.read_text()
    assert "seg" in text.lower()
    assert "NUM_SEGS" in text
    assert "counter_7seg" in text   # {toplevel} substituted

def test_generate_wrapper_non7seg_no_seg_port(tmp_path):
    from fpga_sim.sim_bridge import _generate_wrapper
    out = _generate_wrapper("blinky", str(tmp_path), board_def=None)
    assert "NUM_SEGS" not in out.read_text()
```

#### GHDL/NVC tests — add `counter_7seg` to the existing parametric list

```python
# In the GOOD_BLINKYS / GOOD_7SEG section:
GOOD_7SEG = ["counter_7seg.vhd"]

@pytest.mark.slow
@pytest.mark.parametrize("filename", GOOD_7SEG)
def test_good_7seg_ghdl_pass(filename, ghdl):
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    f = HDL / filename
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=bd)
    assert ok, f"GHDL failed on {filename}: {detail}"
```

### 5.6 `sim/test_7seg.py` — cocotb tests

```python
import cocotb
from cocotb.triggers import Timer

_VALID_HEX_GLYPHS = {
    0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
    0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71,
}

@cocotb.test()
async def test_seg_digit_0_is_valid_glyph(dut):
    """Digit 0 must show a recognisable hex glyph after the counter advances."""
    await Timer(200_000, "ns")
    seg_raw = int(dut.seg.value)
    digit0 = seg_raw & 0xFF
    assert digit0 in _VALID_HEX_GLYPHS, f"digit 0 = 0x{digit0:02X} is not a hex glyph"

@cocotb.test()
async def test_seg_advances_over_time(dut):
    """The segment vector must change (counter is running)."""
    readings = []
    for _ in range(3):
        await Timer(200_000, "ns")
        readings.append(int(dut.seg.value))
    assert len(set(readings)) >= 2, f"seg stuck: {readings}"

@cocotb.test()
async def test_seg_width_matches_num_segs(dut):
    """All 8*NUM_SEGS bits must be addressable; check no truncation for 4 digits."""
    await Timer(50_000, "ns")
    seg_raw = int(dut.seg.value)
    expected_bits = len(dut.seg.value)   # cocotb BinaryValue length = actual port width
    assert 0 <= seg_raw < (1 << expected_bits), (
        f"seg value {seg_raw} is out of {expected_bits}-bit range"
    )
```

### 5.7 Tests — NVC additions to `tests/test_nvc.py`

`tests/test_nvc.py` already contains a full NVC+cocotb integration test for blinky
(`test_nvc_cocotb_simulation_passes`). Add two analogous functions for 7-seg:

```python
@pytest.mark.slow
def test_7seg_analyzes_with_nvc(nvc, nvc_work_dir):
    """counter_7seg.vhd must analyse cleanly under NVC using the 7-seg wrapper."""
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    ok, detail = analyze_vhdl(
        HDL / "counter_7seg.vhd",
        work_dir=nvc_work_dir,
        toplevel="counter_7seg",
        simulator="nvc",
        board_def=bd,
    )
    assert ok, f"NVC analysis failed: {detail}"


@pytest.mark.slow
def test_7seg_nvc_simulation_passes(nvc, nvc_sim_env):
    """counter_7seg.vhd must run headlessly under NVC and produce non-zero seg output."""
    from fpga_sim.board_loader import BoardDef, SevenSegDef
    bd = BoardDef("DE0", "DE0Platform",
                  seven_seg=SevenSegDef(4, True, False, False, False))
    result = launch_simulation(
        board_json=bd.to_json(),
        vhdl_path=HDL / "counter_7seg.vhd",
        toplevel="counter_7seg",
        simulator="nvc",
        board_def=bd,
    )
    assert result, "NVC simulation of counter_7seg exited with non-zero status"
```

**Headless note for `test_7seg_nvc_simulation_passes`:** The existing
`test_nvc_cocotb_simulation_passes` uses a `nvc_sim_env` fixture that sets
`SDL_VIDEODRIVER=offscreen` and `DISPLAY=:99` (or equivalent) so that the pygame
window in `sim_testbench.py` does not require a display server. Reuse that fixture
unchanged — do not invent a separate env-patching approach.

**NVC generics note:** NVC requires generics at `elaborate_cmd` time (not `run_cmd`
time). This is already handled by `_NVCBackend.elaborate_cmd()` — the `NUM_SEGS`
generic added in §5.2 flows through `launch_simulation()` → `generics` dict →
`elaborate_cmd`. No additional changes to `sim_bridge.py` are needed.

---

## 6. Phase 3 — UI Widget & Layout

**Files touched**: `src/fpga_sim/ui/components.py`,
`src/fpga_sim/ui/board_display.py`,
`src/fpga_sim/generate_board_images.py`,
`tests/test_sevenseg_component.py` (new)

**Completion gate**: all 9 boards show correct digit counts and amber segments; digits
scale correctly on window resize; no crash at minimum 24 px digit width; SVG board
previews include 7-seg digit outlines; non-7-seg boards unchanged.

### 6.1 `SevenSeg` widget (in `ui/components.py`)

`draw()` takes no `font` parameter — it calls `get_font()` from `ui/constants.py`
internally, consistent with all other components.

```python
from fpga_sim.ui.constants import get_font as _get_font

class SevenSeg:
    """Draws one digit of a 7-segment display."""

    SEG_ON  = (255, 140,  0)   # amber
    SEG_OFF = ( 45,  25,  5)   # dark amber (ghost segments)
    BG      = ( 15,  15, 15)

    # Bit positions: {dp, g, f, e, d, c, b, a}
    _BIT = {"a": 0, "b": 1, "c": 2, "d": 3,
            "e": 4, "f": 5, "g": 6, "dp": 7}

    def __init__(self, index: int, has_dp: bool = False) -> None:
        self.index = index
        self.has_dp = has_dp
        self.bits: int = 0
        self.rect = pygame.Rect(0, 0, 48, 76)  # overwritten by _layout()

    def set_bits(self, value8: int) -> None:
        """Set from 8-bit value {dp,g,f,e,d,c,b,a}, active-high."""
        self.bits = value8 & 0xFF

    def _seg(self, name: str) -> bool:
        return bool(self.bits & (1 << self._BIT[name]))

    def draw(self, surface: pygame.Surface) -> None:
        W, H = self.rect.width, self.rect.height
        thick = max(3, int(W * 0.12))
        gap   = max(2, int(W * 0.06))
        inner = max(1, W - 2 * gap - 2 * thick)
        half  = H // 2
        x0, y0 = self.rect.topleft

        pygame.draw.rect(surface, self.BG, self.rect, border_radius=3)
        pygame.draw.rect(surface, (5, 5, 5), self.rect, width=1, border_radius=3)

        def colour(n: str) -> tuple[int, int, int]:
            return self.SEG_ON if self._seg(n) else self.SEG_OFF

        def hrect(x: int, y: int, w: int, h: int, n: str) -> None:
            c = colour(n)
            pts = [(x+h//2,y),(x+w-h//2,y),(x+w,y+h//2),
                   (x+w-h//2,y+h),(x+h//2,y+h),(x,y+h//2)]
            pygame.draw.polygon(surface, c, pts)

        def vrect(x: int, y: int, w: int, h: int, n: str) -> None:
            c = colour(n)
            pts = [(x+w//2,y),(x+w,y+w//2),(x+w,y+h-w//2),
                   (x+w//2,y+h),(x,y+h-w//2),(x,y+w//2)]
            pygame.draw.polygon(surface, c, pts)

        ax, ay = x0+gap+thick, y0+gap
        hrect(ax, ay,                           inner, thick, "a")
        vrect(x0+W-gap-thick, y0+gap+thick,     thick, half-2*gap,        "b")
        vrect(x0+W-gap-thick, y0+half+gap,      thick, half-2*gap-thick,  "c")
        hrect(ax, y0+H-gap-thick,               inner, thick, "d")
        vrect(x0+gap, y0+half+gap,              thick, half-2*gap-thick,  "e")
        vrect(x0+gap, y0+gap+thick,             thick, half-2*gap,        "f")
        hrect(ax, y0+half-thick//2,             inner, thick, "g")

        if self.has_dp:
            r = max(2, thick // 2)
            pygame.draw.circle(surface, colour("dp"), (x0+W+r+2, y0+H-r-2), r)

        lbl_sz = max(8, int(H * 0.18))
        lbl = _get_font(lbl_sz).render(str(self.index), True, (90, 90, 90))
        surface.blit(lbl, (x0+W//2 - lbl.get_width()//2, y0+H+2))
```

### 6.2 `FPGABoard` changes (`ui/board_display.py`)

#### New member and method

```python
# In __init__, after building self.leds / self.buttons / self.switches:
if board_def and board_def.seven_seg:
    ssd = board_def.seven_seg
    self._seven_segs: list[SevenSeg] = [
        SevenSeg(i, has_dp=ssd.has_dp)
        for i in range(ssd.num_digits)
    ]
else:
    self._seven_segs = []

def set_seg(self, index: int, bits8: int) -> None:
    if 0 <= index < len(self._seven_segs):
        self._seven_segs[index].set_bits(bits8)
```

#### Dirty-flag extension

`_prev_seg_bits` is an **instance variable** initialised in `__init__`
(not a local in `_draw()`), so it persists across calls:

```python
# In __init__, immediately after building self._seven_segs:
self._prev_seg_bits: list[int] = [0] * len(self._seven_segs)

# In update() / redraw guard (uses self._prev_seg_bits, not a local):
seg_changed = any(
    s.bits != prev for s, prev in zip(self._seven_segs, self._prev_seg_bits)
)
if not (led_changed or seg_changed):
    return  # skip _draw()
self._prev_seg_bits = [s.bits for s in self._seven_segs]
```

#### Layout — Option B horizontal split

> **Implementor note:** `_layout()` uses a section-weighting system (each section
> is assigned a `weight` that determines its share of the window height). Read the
> existing `_layout()` code in `ui/board_display.py` end-to-end before editing —
> the `top_rect` is the sub-rect already allocated to the "fpga" section. Confine
> changes to the inner split of that rect and the new `"seven_segs"` section.

```python
if self._seven_segs:
    top_rect = ...  # existing full-width top rect already computed by _layout()
    chip_w = int(top_rect.width * 0.55)
    seg_w  = top_rect.width - chip_w - section_pad
    chip_rect = pygame.Rect(top_rect.x, top_rect.y, chip_w, top_rect.height)
    seg_rect  = pygame.Rect(top_rect.x + chip_w + section_pad,
                            top_rect.y, seg_w, top_rect.height)
    self._place_items([self.fpga_chip], chip_rect, "fpga")
    self._place_items(self._seven_segs, seg_rect, "seven_segs")
else:
    self._place_items([self.fpga_chip], ..., "fpga")   # unchanged
```

#### Dynamic row count (in `_place_items` `"seven_segs"` branch)

```python
MIN_DW = 24
cols = len(items)
while cols > 1 and (avail_w / cols) * 0.85 < MIN_DW:
    cols = math.ceil(cols / 2)
rows = math.ceil(len(items) / cols)
```

#### Drawing

```python
# In _draw(), after leds:
for seg_widget in self._seven_segs:
    seg_widget.draw(surface)
# Section title "7-SEG" drawn at top of seg_rect (consistent with "LEDs" etc.)
```

### 6.3 Tests — `tests/test_sevenseg_component.py`

```python
import pytest
import pygame
from fpga_sim.ui.components import SevenSeg


@pytest.fixture(scope="module")
def surface():
    pygame.init()
    yield pygame.Surface((400, 300))
    pygame.quit()


def test_zero_glyph_middle_bar_off():
    seg = SevenSeg(0)
    seg.set_bits(0x3F)   # "0": a,b,c,d,e,f on; g off
    assert seg._seg("a") and seg._seg("f")
    assert not seg._seg("g")
    assert not seg._seg("dp")

def test_one_glyph_only_bc():
    seg = SevenSeg(0)
    seg.set_bits(0x06)   # "1": b,c on
    assert seg._seg("b") and seg._seg("c")
    assert not seg._seg("a") and not seg._seg("g")

def test_all_on_includes_dp():
    seg = SevenSeg(0, has_dp=True)
    seg.set_bits(0xFF)
    for name in ("a","b","c","d","e","f","g","dp"):
        assert seg._seg(name), f"segment '{name}' should be on"

def test_blank_all_off():
    seg = SevenSeg(0)
    seg.set_bits(0x00)
    for name in ("a","b","c","d","e","f","g"):
        assert not seg._seg(name)

@pytest.mark.parametrize("size", [(24,38),(48,76),(96,152),(200,320)])
def test_draw_various_sizes_no_crash(surface, size):
    seg = SevenSeg(0, has_dp=True)
    seg.rect = pygame.Rect(10, 10, *size)
    seg.set_bits(0x6D)   # "5"
    seg.draw(surface)

def test_draw_no_dp_with_dp_bit_set_no_crash(surface):
    seg = SevenSeg(0, has_dp=False)
    seg.rect = pygame.Rect(10, 10, 48, 76)
    seg.set_bits(0xFF)   # dp bit set but has_dp=False → no circle drawn
    seg.draw(surface)

def test_set_bits_masks_to_8_bits():
    seg = SevenSeg(0)
    seg.set_bits(0x1FF)   # 9-bit value
    assert seg.bits == 0xFF

def test_index_label_is_digit_index():
    seg = SevenSeg(3)
    assert seg.index == 3
```

### 6.4 `generate_board_images.py` — SVG support

`generate_board_images.py` has two independent render paths:

- **PNG / JPEG** — calls `FPGABoard._draw()` internally. Once `FPGABoard.__init__`
  constructs `_seven_segs` from `board_def.seven_seg` (§6.2) and `_draw()` renders
  them, raster board images automatically include 7-seg digits. **No extra work.**

- **SVG** — has a hand-written per-component renderer (`_svg_draw_led()`,
  `_svg_draw_button()`, `_svg_draw_switch()`). A new `_svg_draw_7seg()` function
  is required, integrated into `build_svg()`.

#### `_svg_draw_7seg()` sketch

Draw each digit as a compact 7-segment outline with all segments in the OFF (ghost)
colour, plus a digit-index label below — matching the amber-dark aesthetic of the
interactive display. The SVG is a static preview, so showing segments in the OFF
state is correct (no live signal data).

```python
def _svg_draw_7seg(
    parent: ET.Element,
    seg_rect: pygame.Rect,
    digit_index: int,
    has_dp: bool,
    scale: float,
) -> None:
    """Draw a single 7-segment digit outline (all segments OFF) into the SVG."""
    W, H = seg_rect.width, seg_rect.height
    thick = max(3, int(W * 0.12))
    gap   = max(2, int(W * 0.06))
    x0, y0 = seg_rect.topleft

    # Housing background
    ET.SubElement(parent, "rect", {
        "x": str(x0), "y": str(y0),
        "width": str(W), "height": str(H),
        "rx": "3", "fill": "#0F0F0F", "stroke": "#050505", "stroke-width": "1",
    })

    # Draw each segment as a filled polygon in SEG_OFF colour (#2D1905).
    # _svg_draw_seg_polygon() is a NEW private helper defined in this same file —
    # it is NOT imported from elsewhere. It computes the 6-point SVG polygon
    # coordinates using the same hrect/vrect geometry as SevenSeg.draw() in
    # components.py, and emits an ET.SubElement "polygon" node with
    # fill="#2D1905". One function handles both horizontal (a, d, g) and
    # vertical (b, c, e, f) orientations via a `horizontal: bool` parameter.
    for seg_name in ("a", "b", "c", "d", "e", "f", "g"):
        _svg_draw_seg_polygon(parent, x0, y0, W, H, thick, gap, seg=seg_name)

    # Decimal point circle (if present)
    if has_dp:
        r = max(2, thick // 2)
        ET.SubElement(parent, "circle", {
            "cx": str(x0 + W + r + 2), "cy": str(y0 + H - r - 2),
            "r": str(r), "fill": "#2D1905",
        })

    # Digit index label
    ET.SubElement(parent, "text", {
        "x": str(x0 + W // 2), "y": str(y0 + H + 12),
        "text-anchor": "middle", "fill": "#5A5A5A",
        "font-size": str(max(8, int(H * 0.18))),
    }).text = str(digit_index)
```

Integrate into `build_svg()` alongside `_svg_draw_led()` etc., using the same
`_place_items()` rect positions already computed for the interactive display.

---

## 7. Phase 4 — Polish & Integration

- Update `_write_meta_sidecar()` in `sim_testbench.py` to include `num_segs`
- Update the simulation banner print to include 7-seg digit count when present
- Add `counter_7seg.vhd` to the GHDL and NVC VHDL test matrices in CI
- Add `sim/test_7seg.py` to the CI cocotb job list (runs under both simulators)
- Update `CHANGELOG.md`: add a `## [Unreleased]` entry or bump to the next version,
  listing "7-segment display support (8 boards; Mercury excluded — see §8)" under *Added*
- Update README with a screenshot showing a 7-seg board (DE0 or Nexys4-DDR)
- Update CONTRIBUTING.md: mention 7-seg as a supported component type
- Add comment in `_make_namespace()` above the `Display7SegResource` entry explaining
  ULX3S exclusion (I2C-indirect, not representable with direct pin resources)
- Capture v2 mux mode in `project_enhancements.md` memory once v1 ships

---

## 8. Open Risks & Mitigations

| Risk | Status | Mitigation |
|------|--------|------------|
| GHDL null-range ports if single template used | Not applicable — two-template approach avoids this | Two templates; `positive` generic |
| `check_vhdl_contract` API change breaks callers | Fully specified | Optional `board_def=None` param; backward compat |
| `launch_simulation` wrapper selection | Fully specified | Deserialise `board_json` if `board_def` not passed directly |
| `_count_ctrl_pins` / `_ctrl_is_inverted` implementation | Fully specified | Reuse existing `_extract_pins()` helper |
| `inverted` detection at pin vs resource level | Fixed | Check both `r._seg_invert` and `_extract_pins()` result |
| Hermetic test coverage | Addressed | Inline-source tests for all loader cases |
| CI integration for new VHDL / cocotb | Addressed | GHDL + NVC matrices; `test_7seg.py` in phase 4 |
| NVC test coverage for 7-seg | Addressed | §5.7 adds analysis + simulation tests to `test_nvc.py` |
| `generate_board_images.py` SVG path | Addressed | §6.4 specifies `_svg_draw_7seg()`; PNG/JPEG automatic |
| ruff/mypy compliance | Addressed | §2.5: full annotations + docstrings required in all `src/` code |
| Font sourcing in `SevenSeg.draw()` | Fixed | Internal `get_font()` call; no font param |
| StepMXO2 partial-mux treatment | Deferred intentionally | v1 treats as 2 independent digits; correct digit count |
| Option B layout complexity | Mitigated | Option A documented as explicit fallback |
| v2 mux mode scope creep | Deferred | `SevenSegDef.is_multiplexed` / `select_inverted` populated correctly in v1; v2 uses a separate wrapper template |
| New board uses unknown companion resource name | Mitigated | Companion detection uses `r.name.startswith("display_7seg_") and r.name != "display_7seg"` — any future suffix is picked up without plan changes |
| Mercury (and potentially future boards) store 7-seg in extension resource lists, not in `resources` | Known limitation — v1 ships without Mercury 7-seg | See §8.1 below |

### 8.1 Mercury and extension resource lists

**Root cause.** `MercuryPlatform` in `amaranth-boards/amaranth_boards/mercury.py` stores
its 7-seg pins in a class attribute `_sevenseg = [Display7SegResource(...), Resource("display_7seg_ctrl", ...)]`,
which is combined with other optional peripherals into `baseboard_no_sram`. This list is
**not** assigned to `resources` — it is intended to be mixed in at toolchain time via
`platform.add_resources(platform.baseboard_no_sram)`. The board loader only reads
`getattr(obj, "resources", None)`, so it never sees `_sevenseg`.

**Boards affected (confirmed as of submodule snapshot, 2026-04-18).** Only Mercury.
ULX3S is separately excluded because its display is I2C-indirect (no direct FPGA pins at all).
All other 7-seg boards (DE0, DE0-CV, DE1-SoC, DE10-Lite, Nandland-Go, Nexys4-DDR,
RZ-EasyFPGA-A2/2, StepMXO2) have their `Display7SegResource` entries directly in
`resources` and are fully detected.

**Future boards.** Any new amaranth-boards board that follows the Mercury pattern
(extension resource list named `baseboard_*` or similar) would have the same gap.
The two approaches below apply to all such boards.

**Approach A — Scan all list-typed class attributes (~1 h, medium risk).**
After reading `resources`, also inspect every class attribute whose value is a `list`
of `_Resource` objects. Merge all found `display_7seg` and `display_7seg_*` entries,
deduplicate by `(name, number)`. Risk: could accidentally absorb unrelated resource lists
that happen to contain `_Resource` objects on future boards or connectors lists.

**Approach B — Scan `baseboard_*` attributes specifically (~30 min, low risk).**
After reading `resources`, also check any class attribute whose name starts with
`"baseboard_"`. For each such list, extract `display_7seg` and `display_7seg_*`
resources and merge them with those from `resources`. Risk: naming is Mercury-specific;
a future board using a different prefix would still be missed.

**Recommendation.** Approach B for a targeted Mercury fix now; revisit with Approach A
only if a third board pattern emerges. Either fix belongs in a follow-up PR against
`board_loader.py:_extract_sevenseg()` and `load_board_from_source()`, after the main
7-seg feature ships.
