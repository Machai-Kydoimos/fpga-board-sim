# U39–U41 — Simulated board peripherals: arc plan (framework + character LCD + SPI OLED)

**Status:** DRAFT — **in review** (drafted 2026-07-27, committed 2026-07-28). Not started; no
milestone or issues opened, and no roadmap card filed yet. The phase ledger in §13 is the status
source of truth once execution begins.

**Card IDs:** U39/U40/U41 and P25–P30 are the next free numbers — **verified against
[`improvement_roadmap.md`](improvement_roadmap.md) 2026-07-28** (highest allocated: U38, D16, P24).
Re-verify before opening issues if this sits unstarted through another arc.

**Decided 2026-07-27 (Rick):** in-repo package with a maintained extraction strategy · integrated
display section now, maximize-overlay later · open-drain supports both electrical styles with
`tristate_split` as the module default · first slice is **two** device families (HD44780 character
LCD + SSD1306 SPI OLED) · HPS answered by four committed options, two of them in this arc.

**Roadmap:** consumes a subset of **P5** (peripheral extraction / `BoardDef.peripherals`), retires the
untriggered "LCD / OLED display support" parked item (`improvement_roadmap.md:553`), and creates the
follow-on cards in §13. Strategy stays in the roadmap; this is the execution plan.

**Audience contract:** written to be executed phase-by-phase by a capable model without additional
context. Every phase has **Do**, **Verify**, **Quality gates**. Do not start a phase until the
previous phase's Verify passes. One PR per phase; branch each phase off post-merge `main`; never
commit to `main`.

---

## 1. Context — why this work exists

The simulator runs a user's real VHDL against a faithful model of a real board, but the board model
stops at LEDs, switches, buttons and 7-segment displays. Every board in the fleet also carries
peripherals — displays, sensors, codecs, memories — and on real hardware a student's next lesson after
"blink an LED" is "drive the LCD".

Today that lesson is unreachable, and quietly so: a design that declares LCD ports **analyzes,
elaborates and runs**, and the ports are silently discarded. `sim_bridge.py:953-956` rejects only
default-less `in`/`inout` ports; `out` always passes:

```python
if name in _CONTRACT_PORTS or decl.mode not in ("in", "inout") or decl.has_default:
    continue
```

So nothing rejects the design and nothing models the device. The user sees a dark board.

**Goal:** a user writes VHDL exactly as they would for the real board, and the simulator models the
peripheral, the bus traffic, and — where there is a display — the pixels. The framework must be as
good for the developer adding peripheral #7 as for the user driving peripheral #1.

**Outcome of this arc:** two device families working end-to-end on any board in the fleet, a
documented "how to add a peripheral" contract, and a maintained plan for extracting the subsystem into
a sister repo once its interfaces stop moving.

---

## 2. Peripheral catalog

Compiled 2026-07-27 from the Terasic SystemCD/ResourcePackage archives in `/tmp/terasic` (DE0-CV,
DE0-Nano, DE10-Lite, DE10-Standard, DE1-SoC, DE2-115, DE23-Lite, DE25-Standard, VEEK-MT2) — the
`golden_top.v` reference designs give the authoritative port names — cross-checked against the
`peripherals` blocks already hand-authored in `boards/custom/*.json`.

### 2.1 Devices, buses and port names

| Peripheral | Representative device | Bus / method | Representative port names | Capture class (§5.2) | Tier |
|---|---|---|---|---|---|
| Character LCD | CFAH1602B (HD44780) | 8/4-bit parallel, latched on E | `LCD_DATA[7:0] LCD_RS LCD_RW LCD_EN LCD_ON LCD_BLON` | `transaction_fifo` | **1** |
| Graphic OLED / LCD | SSD1306, SSD1331, ST7565/ST7567 | SPI 4-wire (+ D/C) | `oled_*`, `HPS_LCM_SPIM_*` | `state_mirror` | **1** |
| ADC | LTC2308, TLA2518/TLA2528 | SPI or I²C | `ADC_SCLK ADC_DIN ADC_DOUT ADC_CONVST` | `transaction_fifo` + injection | 2 |
| Accelerometer / IMU | ADXL345, MPU-9250 | I²C or SPI | `G_SENSOR_*`, `I2C_SCLK/SDAT` | `transaction_fifo` + injection | 2 |
| Light sensor | APDS-9300 | I²C | `I2C_SCLK/SDAT` | `transaction_fifo` + injection | 2 |
| EEPROM | 24LC32 | I²C | `EEP_I2C_SCLK EEP_I2C_SDAT` | `transaction_fifo` | 2 |
| PS/2 | keyboard / mouse | PS/2 (open-drain clk+data) | `PS2_CLK PS2_DAT PS2_CLK2 PS2_DAT2` | `transaction_fifo` + injection | 2 |
| UART / RS-232 | FT232R, ZT3232 | async serial | `UART_RXD UART_TXD UART_CTS UART_RTS` | `transaction_fifo` | 2 |
| IR receiver / emitter | IRM-V538 | NEC pulse-distance | `IRDA_RXD` | `transaction_fifo` + injection | 2 |
| VGA DAC | ADV7123 | parallel RGB + HS/VS + pixel clk | `VGA_R/G/B[7:0] VGA_HS VGA_VS VGA_CLK VGA_BLANK_N VGA_SYNC_N` | `state_mirror` | 3 |
| HDMI TX | ADV7513 | parallel RGB24 + DE, I²C config | `HDMI_TX_D[23:0] HDMI_TX_CLK/HS/VS/DE` | `state_mirror` | 3 |
| TFT panel | 800×480 (VEEK) | parallel RGB + I²C touch | panel RGB + touch I²C | `state_mirror` | 3 |
| Audio codec | WM8731, SSM2603 | I²S data + I²C control | `AUD_BCLK AUD_XCK AUD_DACDAT AUD_DACLRCK AUD_ADCDAT AUD_ADCLRCK` | `transaction_fifo` (waveform/VU view) | 3 |
| Video-in decoder | ADV7180 | ITU-R BT.656 8-bit + I²C | `TD_DATA[7:0] TD_HS TD_VS TD_CLK27 TD_RESET_N` | `state_mirror` | 4 |
| SDRAM | IS42S16320D | SDRAM command bus | `DRAM_ADDR/BA/DQ/CAS_N/RAS_N/WE_N/CKE/CLK/DQM` | `state_mirror` (memory) | 4 |
| SRAM / Flash | 61WV102416, S29GL064N | async parallel | `SRAM_*`, `FL_*` | `state_mirror` | 4 |
| SD card | — | SPI or SD 4-bit | `SD_CLK SD_CMD SD_DAT` | `transaction_fifo` | 4 |
| Ethernet PHY | 88E1111, KSZ9031 | (R)GMII/MII + MDIO | `ENET0_*` | — | out of scope |
| USB | ISP1362, USB3300 | ULPI / parallel | `OTG_*`, `HPS_USB_*` | — | out of scope |
| DDR3 / DDR4 | ISSI | hard memory controller | `DDR4_*` | — | out of scope (hard IP) |
| GPIO / HSMC header | — | raw pins | `GPIO[35:0]`, `HSMC_*` | attach point, not a device | — |

### 2.2 The bus taxonomy — the extensibility spine

Twenty-odd device types collapse to **six** interface mechanisms. This is the reason the framework can
be small: a new device usually needs no new bus code, only a descriptor, a model and a view.

| # | Mechanism | Electrical style | Devices |
|---|---|---|---|
| 1 | Parallel, strobe-latched | push-pull | HD44780, SRAM, Flash |
| 2 | Synchronous serial, push-pull (SPI) | push-pull | OLED/LCD controllers, ADC, IMU, SD-SPI |
| 3 | Synchronous serial, open-drain (I²C, PS/2, 1-Wire) | **open-drain** | sensors, EEPROM, codec control, touch, keyboard |
| 4 | Asynchronous serial (UART, IR) | push-pull | RS-232, IrDA |
| 5 | Synchronous streaming (I²S, BT.656, parallel RGB) | push-pull | audio, video-in, VGA/HDMI/TFT |
| 6 | Command/burst memory (SDRAM, SD 4-bit) | mixed | SDRAM, SD card |

Mechanisms 1 and 2 are electrically free (§7) and cover both first-slice devices. Mechanism 3 needs the
open-drain decision in §7 and is deliberately deferred.

### 2.3 What the board data knows today

- The schema already defines `peripherals` (`boards/schema/board.schema.json:75-80`, `:235-249`), open
  by design (`additionalProperties: true`).
- **6 boards populate it**, all hand-authored: `de10_standard`, `de23_lite`, `de25_standard`,
  `de2_115`, `veek_mt2`, `veek_mt_sockit`.
- **`BoardDef` has no `peripherals` field** (`board_loader.py:116-133`), so those blocks are silently
  dropped at load and never reach the child. This is roadmap **P5**.
- **No board JSON carries peripheral *port names*.** Those exist only in the golden tops.
- **Only 2 boards have a character LCD** (`de2_115`, `veek_mt2`); 2 have the 800×480 TFT. Census
  2026-07-27 across all 283 files.
- **Connector/header data effectively does not exist**: exactly 1 board carries any `connector`
  metadata (6 components on `mister.json`), and the schema has no `connectors` definition. So "which
  Pmod slot" cannot be validated yet — attachment must be by port name.
- ULX3S-class dedicated-connector displays **are** recoverable from data we already download: litex and
  amaranth platform files declare `oled*` resources, and our parsers deliberately drop them
  (`scripts/litex_parser.py:220-221`, `scripts/amaranth_parser.py:415-418` — tightened in #235, the
  "ULX3S 10-vs-8 LEDs" fix). That is P28 (§13), not this arc.

---

## 3. Prior art — what is adoptable and what is not

Investigated 2026-07-27 in response to "has something like this been implemented before?"

| Project | What it is | Verdict |
|---|---|---|
| [RoaLogic virtualdevboard](https://github.com/RoaLogic/virtualdevboard) | "A development board entirely emulated on a PC… peripherals emulated using graphical components (LEDs, 7-segment Display, VGA)". Verilator + wxWidgets + C++20, BSD-3. | **Closest concept match, not adoptable** — Verilog-only via Verilator, no VHDL path, ~3 stars. Cite as validation of the concept. |
| [damdoy/lcd_simulator](https://github.com/damdoy/lcd_simulator) | Verilator + Qt; maps Verilog outputs to an LCD shown in a GUI | Same shape as our renderer; Verilog/Qt. Reference only. |
| [apparentlymart/verilog-vga-simulator](https://github.com/apparentlymart/verilog-vga-simulator) | Verilog **VPI** + SDL VGA window | Useful precedent that VPI-side display capture works; still Verilog. |
| Virtual FPGA Lab (GSoC'21, Makerchip) | Browser visualization of LEDs, 7-seg, LCD 16×2, VGA | Confirms the device shortlist; no reusable code path for us. |
| [cocotbext-i2c](https://github.com/alexforencich/cocotbext-i2c), [cocotbext-spi](https://github.com/schang412/cocotbext-spi), [cocotbext-uart](https://github.com/alexforencich/cocotbext-uart) | MIT cocotb bus models incl. slave devices | **Informative, not drop-in.** Under the capture design (§5.1) the decode input is a transaction list, not live signal handles. Crib their device semantics, not their driver layer. |
| [UVVM](https://github.com/UVVM/UVVM), [OSVVM](https://github.com/OSVVM/OsvvmLibraries) | Mature open-source **VHDL** verification IP (SPI, I²C, UART, GPIO, AXI, …), both officially supporting **GHDL and NVC** | **Best source for bit-level protocol behavior.** Their transaction layers assume a testbench-shaped design rather than a generated wrapper, so adopt the behavior, not the framework. Revisit as a real dependency if the VHDL side grows. |
| [Renode](https://renode.io) + Verilator co-simulation | Emulated SoC (Zynq-7000) co-simulated with Verilated HDL over sockets | Relevant only to full HPS emulation (§8). Its HDL path is Verilog/Verilator and it ships no Cyclone V SoC platform. |

**Conclusion:** no existing project can be adopted wholesale — every close match is Verilator/Verilog
and this project is VHDL/GHDL/NVC. The reusable assets are *behavioral knowledge* (UVVM/OSVVM for bit
timing, cocotbext-* for device semantics) rather than code.

---

## 4. Verified current state (evidence map)

| Claim | Evidence |
|---|---|
| Python-side edge callbacks are an **explicitly rejected** mechanism in this project | `docs/architecture.md:206-210` — "any Python-side sampling or edge callback either aliases or reintroduces the per-event GPI round-trips the VHDL-side clock exists to avoid"; `sim/sim_wrapper_template.vhd:5-6` (VHDL clock cut step time ~10×) |
| GPI cost per wake is negligible; **wake count** is what matters | `docs/u25_ghdl_perf_profile.md:69-78` ("~99% of the loop inside the simulator"); `improvement_roadmap.md:311` (U24 batching = +3%, won't-do) |
| Sim rate is 0.0013×–0.019× of real time | `docs/u25_ghdl_perf_profile.md:24-27`, `:153-157` |
| Extra `out` ports on a user design **already pass** the contract | `sim_bridge.py:953-956` |
| The wrapper is a `str.format` template with mandatory tokens, plus a **second** independent native path | `sim_bridge.py:2139-2149`; `_render_native_wrapper` `:1823-2083` |
| One splice dict already feeds both wrapper paths | `_duty_splice` `sim_bridge.py:1783-1807`, consumed at `:2139` and `:2053,2061,2073` |
| Fragment-file splice mechanism exists | `sim/duty/<algo>.<part>.vhd.frag` + `_duty_fragment` `sim_bridge.py:1772-1781` |
| Wide packed out-ports are already read every send | `led_acc`/`led_tch` are `48 * N` bits; read at `sim_testbench.py:116` |
| Feature discovery is by probing the wrapper, not by plumbing arguments | `_duty_ports` `sim_testbench.py:104-113` — "the running wrapper is the authority" |
| `int(handle.value)` raises on `U`/`X`/`Z`; every existing read is guarded | `sim_testbench.py:284-295` |
| Adding an IPC kind is trivial; unknown kinds are silently ignored | `sim_link.py:103-124`; `sim_testbench.py:298-337`; `simulation_screen.py:318-330` |
| The host keeps only the **latest** `state` payload — a separate kind would silently drop entries | `simulation_screen.py:318-320` |
| Single-window invariant | `controller.py:19-21`; U34, shipped v0.15.0 |
| U23 dirty-flag skip freezes anything not in `visual_signature()` | `simulation_screen.py:502-524`; `board_display.py:762-784` |
| `_layout()` is a weighted proportional section engine | `board_display.py:408-471`, placers `:484`, `:550` |
| Schema defines `peripherals`; `BoardDef` drops it | `boards/schema/board.schema.json:75-80`, `:235-249`; `board_loader.py:116-133`, `:258-337`; roadmap **P5** `:532` |
| HPS peripherals are unreachable from fabric | `DE10_Standard_golden_top.v` — `HPS_LCM_SPIM_CLK/MOSI/MISO/SS`, `HPS_I2C*`, `HPS_UART_*` on HPS-dedicated pins |
| `sim/capture_frames.py` is a **second** boundary consumer of `dut.led`/`dut.seg` | `sim/capture_frames.py:413-422` |
| No `entry_points`; both existing plugin systems are in-repo registries | `pyproject.toml:29-31`, `:139-140`; `scripts/embedded_core/cpu_plugin.py:101-109`; `_SimBackend` `sim_bridge.py:136-202` |

---

## 5. Architecture

### 5.1 The shape: capture in VHDL, decode in Python, render in the host

```text
   sim_wrapper (VHDL)                 sim child (Python)              host (pygame)
 ┌────────────────────────┐        ┌──────────────────────┐      ┌──────────────────┐
 │ uut : user design      │        │ probe getattr(dut,   │      │ view.draw(surf,  │
 │   lcd_e ──┐            │        │   "lcd_cap")         │      │   rect)          │
 │   lcd_rs ─┤ internal   │        │                      │      │                  │
 │   lcd_data┤ nets       │        │ 2 handle reads per   │      │ signature() ──▶  │
 │           ▼            │        │ send (4–50 ms)       │      │ visual_signature │
 │  capture frag          │──ports─▶ unpack + pure model  │──IPC─▶ state["periph"]   │
 │   ring FIFO / mirror   │        │ (no cocotb import)   │      │                  │
 │   + change counter     │        │                      │      │                  │
 └────────────────────────┘        └──────────────────────┘      └──────────────────┘
```

This is the U9 duty engine's shape, deliberately: integrate/capture in VHDL, do the math in a pure
Python module, stream the result, render it. It adds **zero** new Python wakes, so
`docs/architecture.md:206-210` stays true. The design's peripheral signals stay **internal nets** — only
the capture ports reach the boundary — with the internal names added to the GTKW save file
(`_write_gtkw` already emits hierarchical `sim_wrapper.uut.*` strings).

### 5.2 Two capture classes, chosen by bandwidth arithmetic

The send cadence is 4–50 ms wall (`sim_testbench.py:78-80`). At the sim rates in §4 that is
**65 µs–950 µs of simulated time per window**. Therefore:

| Class | Wrapper exports | Python owns | Choose when | First device |
|---|---|---|---|---|
| `transaction_fifo` | ring of N payloads + 16-bit write counter | full device semantics (decode, RAM, cursor) | peak ≤ ~20 transactions per 50 ms sim window | **HD44780** — min write cycle 37 µs → ≤25/window; realistic designs send ~32 chars once at startup |
| `state_mirror` | the device's user-visible memory as a packed vector + change counter | presentation only (bit unpacking, flags) | high rate, or losing data would corrupt the image | **SSD1306** — a 1024-byte frame at 10 MHz SPI is 820 µs, so a whole frame lands inside one window |

`state_mirror` also removes overflow as a failure mode: the host always reads current truth, never a
backlog. This is the same argument U9 made for measuring duty rather than sampling it, and it is the
class the later pixel tier (VGA/HDMI/TFT) will use.

**Document this rule with its arithmetic in the developer guide.** It is the single most important
decision a peripheral author makes.

### 5.3 Binding: auto-attach by convention match

A binding is a named role → design-port map, matched by the machinery that already recognizes
board-native designs. **No attach UI in this arc:** if the design declares ports matching a known
device's convention, the device attaches automatically and the launcher shows an info message, exactly
as `_native_convention_message` (`sim_bridge.py:1543`) does for board-native designs. Multiple devices
attach simultaneously by construction (the splice takes a list).

Two provenances for the port names, one matcher, precedence board-canonical > module (mirroring
`_convention_precedence`, `sim_bridge.py:1450-1462`):

| Provenance | Where names live | Example | In this arc |
|---|---|---|---|
| **Module** (Pmod / GPIO header / dedicated connector) | the device pack's `device.toml` | `lcd_e lcd_rs lcd_rw lcd_data` | yes — works on all 283 boards |
| **Board-intrinsic** | new `peripheral_conventions` block on the board JSON | DE2-115 `LCD_EN LCD_RS LCD_RW LCD_DATA` | yes — DE2-115 hand-authored, ~6 lines |

`boards/custom/*.json` can declare peripherals with port names from day one; that is the cheapest
authoring path and needs no sync machinery (`sync_common.py:127-196` already folds `peripherals`
forward on re-sync).

### 5.4 A device is one directory (extraction-ready)

```text
src/fpga_sim/peripherals/hd44780/
  device.toml     descriptor: class, bus, capture params, geometry, module convention roles
  model.py        pure: stdlib + fpga_sim.board_loader only. No cocotb, pygame, ui or sim_bridge
  view.py         pygame renderer: draw(surface, rect) + signature()
  sources.toml    datasheet citation (verify-or-omit, mirroring docs/led_color_sources/)
sim/periph/
  transaction_fifo.capture.vhd.frag   shared by bus = "parallel_latched"
  spi_mirror.capture.vhd.frag         shared by bus = "spi_byte" + class = state_mirror
```

The registry is a **directory scan** (`peripherals/__init__.py`), mirroring `_discover_boards_json`
(`board_loader.py:345-365`) — which is also what makes an out-of-tree `FPGA_SIM_PERIPHERALS_PATH`
possible later (same shape as icebox P6). Extraction is `git mv` of a device directory.

### 5.5 Why not the alternatives (do not relitigate)

- **Python/cocotb edge-triggered device models** (`start_soon` + `RisingEdge`): rejected by
  `docs/architecture.md:206-210` on this project's own measured grounds. Secondary problems: an
  unhandled exception in a forked task fails the test and surfaces to the user as "the simulation
  stopped unexpectedly" (`simulation_screen.py:324-330`); `int(LogicArray)` raises on the `U` bits
  present before the design's first assignment; correct sampling needs `ReadOnly` delta reasoning.
  Reusing cocotbext-* was the main draw, and under the capture design their input is a transaction list
  rather than live handles, so they are not drop-in anyway.
- **A separate OS process per peripheral**: does not solve open-drain (§7) — process topology is
  irrelevant to VHDL net resolution — and costs an IPC hop per transaction. It *is* the right tier for a
  genuinely heavyweight model later (an MCU-on-a-Pmod), so keep the view protocol data-in/pixels-out,
  but do not build it now.
- **A sister repo now**: peripheral models couple to three interfaces that are still moving (splice
  contract, IPC payload, view protocol). The repo has no `entry_points`, and both existing plugin
  systems are deliberate in-repo registries. In-repo plus §9's maintained extraction strategy gets the
  extensibility without a version matrix across two repos.
- **Extra analyze passes for peripheral VHDL**: unnecessary — append device VHDL to `sim_wrapper.vhd`
  *after* `str.format` (embedded-core precedent, `scripts/embedded_core/emitter.py`; `analyze_cmd` is
  scalar with no multi-file support). Guard the latent brace trap with a test.
- **A second OS window**: reverses U34, splits the U23 dirty-flag domain, and needs a second-window
  story in four headless capture paths (`capture_frames.py`, `generate_board_images.py`, `--benchmark`,
  `capture_selector.py`). Its only real advantages — independent sizing, second monitor — apply solely
  to the large-framebuffer case, which is not in this arc. Icebox P27.
- **Full ARM/HPS emulation**: §8.

---

## 6. Locked decisions

1. Capture in VHDL, decode in pure Python, render in the host. No Python edge callbacks, no `start_soon`.
2. Two capture classes (`transaction_fifo`, `state_mirror`), chosen by the §5.2 arithmetic.
3. Bindings auto-attach by port-name convention match; info message, no attach dialog this arc.
4. One splice dict feeds both wrapper paths, mirroring `_duty_splice`. No second mechanism.
5. Peripheral state rides **inside** the existing `state` payload as `state["periph"]` — latest-wins,
   inheriting the throttle, the pause snapshot and the `input_seq` echo. No new IPC kind this arc.
6. Displays render as a new weighted `_layout()` section and **must** extend `visual_signature()` with a
   **quantized** animation phase (unquantized would dirty every frame and defeat U23).
7. A device is one directory; `model.py` is pure; the registry is a directory scan.
8. Both first-slice devices are `push_pull`. No injection, no `Z`/`H`, no open-drain this arc.
9. HPS: ship options 1 and 2 in this arc (§8); options 3 and 4 are committed follow-on cards.
10. `docs/peripheral_extraction_strategy.md` is created in Phase 1 and updated by every later phase.

---

## 7. Electrical styles — and the open-drain finding

| Style | Design declares | Sound? | Used for |
|---|---|---|---|
| `push_pull` | plain `out` / `in` | always | HD44780 parallel, SPI (SCK/MOSI/CS out, MISO in) — **all of this arc** |
| `tristate_split` | `x_o` / `x_oe` / `x_i` | always — the wrapper owns the buffer | module default for open-drain buses (follow-on) |
| `opendrain_h` | the real `inout` names | with a documented read rule + lint | board-native fidelity (follow-on) |

**The finding.** A shared `std_logic` net cannot be made to idle at literal `'1'`:

| design drives | wrapper drives | resolves to | consequence |
|---|---|---|---|
| `Z` (released) | `H` (weak 1) | `H` | **`if sda = '1'` is FALSE** — `'H'` and `'1'` are distinct enumeration literals |
| `Z` | `1` (strong) | `1` | fine |
| `0` (pull low) | `H` | `0` | fine |
| `0` | `1` (strong) | **`X`** | driver contention |

There is no pull-up strength that both idles at `'1'` and lets the design pull low, and it cannot be
fixed from the wrapper because **the design reads the same net it drives** — there is no rebuffer point,
and `'DRIVING_VALUE'` is legal only inside the driving unit.

**A separate process does not help.** The problem is at the VHDL boundary, not in the model's location:
any driver — a VHDL process, cocotb over VPI, or a socket-fed model in another OS process — still
contributes one `std_logic` value to the same resolved net.

**What does work** is splitting the net in VHDL: `tristate_split` (always sound; costs a 3-line
top-level tri-state buffer on real hardware, which many textbooks teach anyway) or `opendrain_h`
(faithful port names; bus idles at `'H'`; needs a documented read rule and a source lint warning on
`= '1'` comparisons against a bound net). `opendrain_h` is more usable than the table suggests — an I²C
master's ACK test is `if sda = '0'`, which works fine with `'H'`; the break is only when a captured
`'H'` flows into a vector comparison.

Both first-slice devices are `push_pull`, so **no injection path and no `Z`/`H` handling is needed at
all** in this arc — a large de-risking. Open-drain device families are P26 (§13), to be designed against
a concrete I²C device rather than in the abstract.

---

## 8. HPS — the committed program

HPS peripherals sit on HPS-dedicated pins (`HPS_LCM_SPIM_*`, `HPS_I2C*`, `HPS_UART_*`), so no VHDL a
user writes can reach them. All four accepted options work around that rather than pretending otherwise.

| # | Option | Cost | Where |
|---|---|---|---|
| 1 | HPS-side devices as attachable modules, honestly labeled | free | **Phase 8** |
| 2 | Soft-core (mx65/T80) firmware drives an attached peripheral | S–M | **Phase 7** |
| 3 | Fabric-visible lwHPS2FPGA bridge as a peripheral; registers poked host-side, as Linux `/dev/mem` would | M | follow-on **U42** |
| 4 | Soft 32-bit core + real GCC/C (NEORV32 / VexRiscv) driving the same peripheral models on every board | L | follow-on **U43**, gated on P8's multi-file/multi-library analyze relief valve |

Option 4 is the strategic answer to "the user will need more than pure VHDL": real C, real toolchain,
every board, no emulator — and roadmap P8 already names its blocker (`library neorv32` needs the
relief valve).

**Rejected:** full ARM co-simulation (Renode/QEMU). Renode's HDL path is Verilog/Verilator while this
project is VHDL/GHDL/NVC with U20 (Verilog) still open, and Renode ships Zynq-7000, not Cyclone V SoC.
Icebox, trigger = U20 lands.

---

## 9. Extraction strategy (maintained from day one)

`docs/peripheral_extraction_strategy.md`, created in Phase 1, updated by every later phase:

1. **Enforced dependency direction** — `peripherals/*/model.py`: stdlib + `fpga_sim.board_loader` only.
   `view.py` may import pygame but nothing from `sim_bridge`/`controller`. Enforced by
   `tests/test_periph_purity.py` (modeled on `tests/test_sim_testbench_lint.py`).
2. **A device is one movable directory.** Extraction = `git mv` + a registry entry.
3. **Directory-scan registry**, so an out-of-tree `FPGA_SIM_PERIPHERALS_PATH` needs no redesign.
4. **Three version-stamped contracts**: the splice contract (frag tokens, port naming, byte-identity
   rule), the `state["periph"]` payload schema, the view protocol (`draw(surface, rect)`,
   `signature()`). Any change bumps its version in the doc.
5. **A standing checklist** every phase PR ticks: *did this add a coupling not in the contract list?*

---

## 10. Phases

### Phase 0 — de-risking spike (S, throwaway branch)

**Do:** hand-write spiked wrappers; touch no product code.

1. `transaction_fifo`: parallel latch on the `lcd_e` falling edge, `{rs, rw, data}` into a ring, wide
   packed out-port + 16-bit counter. Analyze/elaborate/run under GHDL **mcode and llvm** and NVC; read
   from cocotb and assert FIFO contents, ordering and exact counter value.
2. `state_mirror`: SPI byte assembly (CPOL/CPHA generic) + a page-addressed RAM; assert mirror contents
   after a known command/data stream.
3. Perf: `FPGA_SIM_BENCHMARK` with and without each frag. Expect ≤ run noise (pure VHDL, no new Python
   wakes). **Record the numbers — this is the claim the whole design rests on.**
4. `analyze_vhdl` step-3 default-generic elaboration of each spiked wrapper (`NUM_LEDS=4` defaults).
5. Confirm the §4 claim that a user design's extra `out` ports pass `check_vhdl_contract` **today**.
   This decides whether Phase 3 needs contract work at all.
6. Read cost of the widest planned port (SSD1306 mirror ≈ 8192 bits) via `int(handle.value)` at the 4 ms
   cadence, on both backends.

**Verify:** all six produce recorded numbers; every assertion passes on GHDL-mcode, GHDL-llvm and NVC.
**Quality gates:** results written to `docs/u39_peripheral_spike.md` (model: `docs/u25_ghdl_perf_profile.md`).
This is the only phase whose outcome can change the architecture, so it goes first and its results are
written down.

### Phase 1 — pure models + registry (M; no VHDL, no cocotb)

**Do:**

- `src/fpga_sim/peripherals/__init__.py` — `DeviceSpec` frozen dataclass, `load_devices()` directory
  scan, `get_device(name)` raising with a "known: …" list (`cpu_plugin.py:101-109` precedent).
- `src/fpga_sim/peripherals/capture.py` — `unpack_ring(vector, depth, payload_bits)` and
  `TransactionTracker` (two-snapshot differencing, `lost` count, 16-bit counter wraparound). Model on
  `sim_duty.unpack` (`sim_duty.py:44`) and `DutyTracker.update` (`:54`), including its "return `None`
  when nothing new, caller holds last value" convention.
- `peripherals/hd44780/{model.py,device.toml,sources.toml}` and
  `peripherals/ssd1306/{model.py,device.toml,sources.toml}`.
- `tests/test_periph_capture.py`, `tests/test_hd44780.py`, `tests/test_ssd1306.py`,
  `tests/test_periph_registry.py`, `tests/test_periph_purity.py`.
- `docs/peripheral_extraction_strategy.md` v1 (§9).

**Verify:** those tests pass with **no simulator installed**; the purity lint proves `model.py` imports
neither pygame nor cocotb.
**Quality gates:** the HD44780 tests must cover the traps in §11.

### Phase 2 — board data (S)

**Do:** add `peripherals: list[PeripheralInfo]` to `BoardDef` (`board_loader.py:116-133`), emit in
`to_json` (`:258`), parse in `from_json` (`:297`); add a `peripheral_conventions` block to
`boards/schema/board.schema.json`; hand-author DE2-115's LCD block from the golden top. Extend
`tests/test_board_loader.py` (note `:322-333` currently asserts peripherals are *ignored* — update it),
`tests/test_board_schema.py`, `tests/test_serialization.py`.

**Verify:** all 283 boards still load; the DE2-115 block round-trips through `FPGA_SIM_BOARD_JSON`;
`uv run python scripts/check_board_drift.py` clean.
**Quality gates:** no sync-tooling changes; schema stays backward compatible.

### Phase 3 — binding matcher + wrapper splice (L) — the riskiest phase

**Do:**

- `src/fpga_sim/peripherals/binding.py` — `PeripheralBinding` frozen dataclass; matcher reusing
  `_parse_toplevel_interface` (`sim_bridge.py:815`) and the `_match_native_port` shape (`:1150`).
  **Do not write a second entity parser.**
- `sim_bridge.py`: `_periph_splice(bindings) -> dict[str, str]` beside `_duty_splice` (`:1783`),
  returning all-empty strings for no bindings so a peripheral-free wrapper stays **byte-identical**.
  Thread `periph=` with a default through `check_vhdl_contract` → `ContractResult` (`:1122`) →
  `analyze_vhdl` (`:2213`) → `_generate_wrapper` (`:2086`) → `_render_native_wrapper` (`:1823`) →
  `SimChild`.
- `sim/sim_wrapper_template.vhd`: four new tokens, inserted **before** `clk_half_ns` in the entity and
  **before** `led => {led_sig}` in the port map, each carrying its own trailing separator (the closing
  entries have no trailing comma — `{seg_port}`/`{seg_port_map}` already follow this convention). Every
  new `in` port gets a VHDL default (`:= '0'`), per the template's own comment at `:32-35`.
- `sim/periph/transaction_fifo.capture.vhd.frag`, `sim/periph/spi_mirror.capture.vhd.frag`.
- `sim/lcd_probe.vhd`, `sim/oled_probe.vhd` (§11).
- Tests: `tests/test_periph_binding.py` (hermetic generated-text assertions; model
  `tests/test_native_convention.py`); a byte-identity test for the no-peripheral wrapper on **both**
  wrapper paths; a brace-set guard test asserting the template's `{...}` set equals the known token set.

**Verify:** the wrapper analyzes and elaborates on GHDL and NVC with and without bindings; the
no-binding wrapper is byte-identical to Phase 2's; both probes elaborate under default generics.
**Quality gates:** keep this phase **decode-free** — no device semantics here.

### Phase 4 — child sampling + IPC (M)

**Do:** `_periph_ports(dut, prefix)` in `sim/sim_testbench.py` mirroring `_duty_ports` (`:104`);
coherent snapshot reads with no `await` between related handles and X/Z guards (`_sample_duty` `:116`
precedent — **never bare `int()`**); `state["periph"]` sub-dict; extend the `changed` term (`:342`);
pause-instant final sample (`:316-335` precedent); flush before `bye`. Update the `sim_link.py`
docstring (`:11-28`) — that docstring **is** the message contract. Give `sim/capture_frames.py` the same
probe. Cocotb suites `sim/test_lcd.py`, `sim/test_oled.py`; pytest runners `tests/test_lcd_design.py`,
`tests/test_oled_design.py` copied from `tests/test_native_scan_design.py`.

**Verify:** both runners green under GHDL and NVC with exact `PASS=n`/`FAIL=0`; `--benchmark` sim rate
within run noise of Phase 3's.
**Quality gates:** add the new `sim/*.py` to `[tool.ruff.lint.per-file-ignores]` and
`[[tool.mypy.overrides]]` in `pyproject.toml` (bare module names for `sim/`, `tests.*` for tests).

### Phase 5 — renderer (M)

**Do:** `hd44780/view.py` (5×8 glyph grid, block cursor, blink) and `ssd1306/view.py`
(`pygame.image.frombuffer` + scale); a `("peripherals", …, 2)` weighted section in
`board_display.py:_layout()` reusing `_place_items` (`:484`); extend `visual_signature()` (`:764`) with
device state and a **quantized** blink phase; new `Theme` roles with overrides in all three themes
(`theme.py` — high-contrast overrides nearly every role explicitly); wire `_apply_state`
(`simulation_screen.py:368`). Tests: widget tests plus a U23 regression test asserting the signature
changes across a cursor blink and does **not** change on an idle frame.

**Verify:** headless screenshots per the `reference_headless_sim_testing` recipe; frame-skip ratio from
`RunStats.frames_drawn` still high on a static design.
**Quality gates:** **Rick's visual review of PNGs before merge** (UI/render carve-out from merge-on-green).

### Phase 6 — auto-attach UX, demos, docs (M)

**Do:** auto-attach info message mirroring `_native_convention_message` (`sim_bridge.py:1543`);
`--peripheral` CLI for headless/tests; session-log fields (`sim_session_log.py`). Demos
`hdl/periph/lcd_hello.vhd`, `hdl/periph/oled_bounce.vhd`, and one board-native
`hdl/native/de2_115_lcd.vhd` (not surfaced in the picker, like the other `hdl/native/` examples).
`docs/peripheral_developer_guide.md` — the "how to add a peripheral" contract, structured on
`docs/embedded_core_system_guide.md`: admission checklist, the §5.2 bandwidth rule **with its
arithmetic**, a worked end-to-end example, a "deepest pothole" section, and the §7 electrical-style
table. Update `docs/writing_designs.md`, `docs/user_guide.md`, `docs/architecture.md` (**amend the
invariant at `:206-210` to say "plus one poll per send for peripheral capture ports"**), `CLAUDE.md`,
`README.md`, `CHANGELOG.md`.

**Verify:** a fresh reader can add a third device by following the guide alone.

### Phase 7 — soft-core firmware drives the LCD (M) — HPS option 2

**Do:** extend the existing `PERIPHERALS` axis in `scripts/embedded_core/system_spec.py:66` from
`("lfsr",)` to include `"lcd"`; add the `cpu_io.vhd.tmpl` fragment triple (the guide's 4-piece recipe);
`systems/mx65_lcd_hello.toml`, `firmware/mx65_lcd_hello.s` (ca65 — never hand-assemble), generated
`hdl/mx65_lcd_hello.vhd`; golden + reassembly + GHDL/NVC tests in `tests/test_embedded_core.py`;
`sim/test_cpu_lcd.py`.

**Verify:** `uv run python scripts/regen_embedded_cores.py` clean; empty-`peripherals` systems stay
byte-identical (the generator's existing invariant).
**Quality gates:** respect the terminology firewall — this `peripherals` axis is CPU-side IO, not board
peripherals (`docs/embedded_core_system_guide.md:735-737`).

### Phase 8 — HPS-side device as an attachable module (XS–S) — HPS option 1

**Do:** an `st7565/` device pack (the DE10-Standard / DE1-SoC 128×64 HPS LCD) reusing the `spi_mirror`
capture frag unchanged, shipped with an honest label: *on hardware this hangs off the HPS SPI master;
here you drive it from fabric.*

**Verify:** **no changes to `sim/periph/*.frag` or `sim_bridge.py`** — a new device must be data plus two
Python modules. If that is not true, the framework is wrong and Phase 3 needs revisiting. This phase is
deliberately the framework's own acceptance test.

---

## 11. Test strategy

**Pure Python (no simulator).** HD44780: 4-bit nibble pairing including a lone trailing nibble;
`Function Set` / `Entry Mode` / `Display On-Off` / `Clear` / `Set DDRAM Address` decode; the **row-1
base address `0x40`, not `0x10`** (the classic wrong-line bug); writing past column 15 landing in
off-screen `0x10..0x27` rather than bleeding onto row 1; increment vs. decrement; display shift;
cursor/blink flags; prefix-replay idempotence. SSD1306: page-major → row-major unpacking, addressing
modes, invert/contrast flags. `capture.py`: ring ordering, a counter delta of exactly `DEPTH`, a delta
> `DEPTH` reporting the right `lost`, and 16-bit wraparound (`& _ACC_MASK`, `sim_duty.py:96`).

**Cocotb suites (GHDL + NVC, against the generated `sim_wrapper`).** These prove the **VHDL binding**, so
they assert what the pure tests cannot: the frag latches on the correct edge, in the correct bit order,
exactly once per strobe; the counter equals the probe's own transaction count (no double- or missed
latch); `RS=0` and `RS=1` with identical data decode differently; SPI CPOL/CPHA variants assemble
identically; a deliberate overflow burst reports the exact `lost` count.

**Pytest runners.** Copy `tests/test_native_scan_design.py`: real `check_vhdl_contract` → real
`analyze_vhdl` (exercising steps 1/2/3/3b) → `_backend(sim).elaborate_cmd`/`run_cmd` → `_build_sim_env`
→ `--stop-time` → assert exact `PASS=n`/`FAIL=0`, parameterized over `ghdl`/`nvc`, marked
`@pytest.mark.slow`.

**`sim/lcd_probe.vhd` / `sim/oled_probe.vhd`** — the `sim/duty_probe.vhd` analogue: satisfies the generic
contract, lives under `sim/` so the file picker never lists it, `generate`-guarded so it elaborates under
the wrapper's **default** generics, ground truth documented in the header. Selectors: `sw(0)` 8-bit vs
4-bit · `sw(1)` row-2 via `Set DDRAM 0x40` · `sw(2)` 20-char off-screen wrap · `sw(3)` minimum-period
overflow burst · `led(0)` mirrors "sequence complete" so tests wait on a signal rather than a magic
`Timer`. Include a guarded one-strobe-per-clock mode as the pathological-rate reproducer for the perf
guardrail.

---

## 12. Risk register

| Risk | Mitigation |
|---|---|
| Capture frag latches on the wrong edge / bit order — silently wrong output | Phase 0 proves it on 3 backends before any product code; cocotb suites assert exact counts |
| `transaction_fifo` overflow on a fast design | §5.2 arithmetic sizes `DEPTH=64` at ~2.5× the worst realistic rate; `lost` is reported to the user, never silent; `state_mirror` is the escape hatch |
| `str.format` brace trap becomes live via a comment in a frag | brace-set guard test in Phase 3; append device VHDL after `.format()` |
| Native wrapper path forgotten (it is a second, independent code path) | one `_periph_splice` dict feeds both, exactly as `_duty_splice` does; byte-identity test for the no-peripheral case on **both** paths |
| U23 dirty-flag freezes the cursor blink | quantized phase in `visual_signature()` + an explicit regression test both ways |
| `int(handle.value)` raises on `U` before first assignment | guarded reads only, `_sample_duty` (`:116`) precedent; never bare `int()` |
| Peripheral section squeezes LEDs/switches on small windows | weight 2 plus a minimum-height floor; the maximize overlay is the documented answer for the pixel tier |
| `sim/capture_frames.py` renders an empty peripheral section into docs assets | Phase 4 gives it the same probe |
| ULX3S OLED controller part is unconfirmed | Phase 2 confirms it from the litex/amaranth `oled*` resource data **before** `oled_bounce.vhd` claims that board |
| Scope creep into I²C / VGA mid-arc | §7 and §13 fence them explicitly; both are follow-on cards |

---

## 13. Sizing, ledger, and follow-on cards

| Phase | Scope | Size | PR | Status |
|---|---|---|---|---|
| 0 | Spike + plan commit | S | — | not started |
| 1 | Pure models + registry + extraction strategy | M | — | not started |
| 2 | `BoardDef.peripherals` + `peripheral_conventions` + DE2-115 | S | — | not started |
| 3 | Binding matcher + wrapper splice + probes | **L** | — | not started |
| 4 | Child sampling + IPC + cocotb suites | M | — | not started |
| 5 | Renderer + theme + U23 integration | M | — | not started |
| 6 | Auto-attach UX + demos + docs | M | — | not started |
| 7 | Soft-core firmware drives the LCD | M | — | not started |
| 8 | HPS-side device as attachable module | XS–S | — | not started |

Comparable to the U21 arc (9 phases) and the LED-complete arc. Target release **v0.21.0**; ship the
already-merged U23 / #256 / macOS-CI work as v0.20.0 first.

| ID | Scope | Trigger |
|---|---|---|
| U42 | lwHPS2FPGA bridge peripheral, registers poked host-side | after this arc |
| U43 | Soft 32-bit core + real C toolchain (NEORV32 / VexRiscv) | **P8** multi-file/multi-library analyze relief valve lands |
| P25 | Pixel-rate tier: VGA / HDMI / parallel-RGB TFT via `state_mirror` + maximize overlay | a user wants a video design, or the 800×480 VEEK TFT is scheduled |
| P26 | Open-drain device families (I²C sensors, PS/2) — `tristate_split` default + `opendrain_h` + the `= '1'` lint | a concrete I²C device is scheduled, so the convention is designed against a real device |
| P27 | Separate OS window for a display | a full VGA/HDMI view people want on a second monitor |
| P28 | Peripheral extraction in the sync parsers (ULX3S-class `oled*`, Digilent `## Pmod Header JA` slots) — the rest of **P5** | ≥3 board-intrinsic devices are modeled |
| P29 | Out-of-tree `FPGA_SIM_PERIPHERALS_PATH` / sister-repo extraction | the three §9 contracts stop changing |
| P30 | Peripheral bus-transaction inspector panel (protocol decode view) | a user asks, or debugging a device model needs it |

**P30 note:** the Python model already decodes the traffic, so rendering "I²C write 0x3C reg 0x00 =
0xAE" is nearly free and is arguably worth more pedagogically than the pixels. Deferred only because it
needs a non-dropping transport (`simulation_screen.py:318-320` keeps latest-wins).

---

## 14. Cross-cutting quality gates (every phase PR)

`uv run ruff check` + `uv run ruff format --check` + `uv run mypy .` + `uv run pytest` locally before
every commit (use `set -o pipefail` when piping to `tail`). CHANGELOG entry per PR. Never predict PR
numbers in docs. Before each PR explicitly consider doc updates and test additions. US spelling
everywhere. VHDL plain ASCII or UTF-8 without BOM. Feature branch per phase; never commit to `main`.
UI/render PRs: PNGs for Rick's visual review before merge.

---

## 15. Closeout checklist

- [ ] Condense U39/U40/U41 to ✅ one-line stubs in `improvement_roadmap.md`; full detail to `roadmap_delivered.md`
- [ ] Retire the untriggered "LCD / OLED display support" parked item (`improvement_roadmap.md:553`)
- [ ] Update **P5** to reflect the subset consumed (`BoardDef.peripherals` round-trip) and what remains (P28)
- [ ] File U42, U43 and P25–P30 with their triggers
- [ ] `CLAUDE.md`: peripheral entries in the file table + a "Peripherals" contract section beside the existing VHDL-contract sections
- [ ] `docs/architecture.md:206-210` invariant amended; `writing_designs.md`, `user_guide.md`, `README.md` updated
- [ ] `docs/peripheral_extraction_strategy.md` final pass — all couplings listed and versioned
- [ ] Project memory updated (`project_peripherals_arc.md` + MEMORY.md pointer)
- [ ] CHANGELOG entries per phase reconciled for the release

---

## 16. Verification (end-to-end, after Phase 6)

```bash
uv sync --group dev
uv run ruff check && uv run ruff format --check && uv run mypy .
uv run pytest                                  # pure model + binding tests; no simulator needed
uv run pytest -m slow                          # GHDL + NVC cocotb suites for both devices
uv run python scripts/check_board_drift.py     # board data unchanged

# real app, real design, real simulator
uv run fpga-sim --board DE2_115                # load hdl/periph/lcd_hello.vhd; expect the auto-attach
                                               # info message, then "Hello, world!" on the LCD section
uv run fpga-sim --board Basys3                 # same design, attached module on a board with no LCD
uv run fpga-sim --board RadionaULX3S           # hdl/periph/oled_bounce.vhd

# headless proof + screenshots (see the reference_headless_sim_testing recipe)
uv run fpga-sim --board DE2_115 --benchmark    # sim rate within noise of a peripheral-free run
```

**Done when:** a user writes a design against a module's port names, the device auto-attaches with an
info message, its output renders live in the one window on any board in the fleet, both devices pass
their cocotb suites under GHDL and NVC, the peripheral-free wrapper is byte-identical to before,
`--benchmark` shows no regression, and a reader can add device #3 from
`docs/peripheral_developer_guide.md` alone.
