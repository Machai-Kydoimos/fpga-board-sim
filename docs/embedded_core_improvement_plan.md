# Embedded-Core Improvement Plan

> **Origin:** full review of the embedded-core work (generator, docs, firmware, tests, shipped
> designs, and roadmap items P7/P8) performed 2026-07-02, after #135 landed. This plan turns every
> review finding into ordered, executable work.
> **Companions:** [`embedded_core_system_guide.md`](embedded_core_system_guide.md) (user-facing
> guide), [`embedded_core_system_plan.md`](embedded_core_system_plan.md) (original build plan),
> [`embedded_core_build_notes.md`](embedded_core_build_notes.md) (per-stage log),
> [`improvement_roadmap.md`](improvement_roadmap.md) (strategy source of truth; P7 = VSG, P8 =
> RISC-V third core).
> **Executor:** written to be followed by Claude (Sonnet/Opus/Fable) or a human in a later session
> with no other context. Line numbers cited here drift — always re-grep the quoted anchor text.

---

## How to use this document

- Work **one phase per PR**, in order. Phases are sequenced so each lands green, each is
  independently verifiable, and later phases reuse tooling built by earlier ones.
- Per the repo's backlog model, open a **just-in-time GitHub issue per phase when starting it**
  (title referencing this plan + phase number, the way the Sprint 2 issues #123–#125 reference
  their roadmap cards) and close it with the phase's PR. Do **not** pre-create all eight.
- Before starting a phase, read its **Rationale** (why it exists, why now) and **Expected diff
  shape** (what a correct PR looks like). If your diff doesn't match the expected shape, stop and
  find out why before proceeding.
- Update the **Status ledger** below when a phase lands (PR number, date, state). That is how a
  later session knows where to resume.
- User decision already made (2026-07-02): **ROM and RAM sizes must be independent** — real designs
  commonly use different sizes. This is a requirement (Phase 2 + Phase 6), not just a bug fix.

## Status ledger

| Phase | Title | Size | State | PR | Date |
|---|---|---|---|---|---|
| 0 | Errata & repo hygiene | S | done | [#140](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/140) | 2026-07-02 |
| 1 | Reassembly guards + regeneration tooling | M | done | [#142](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/142) | 2026-07-02 |
| 2 | Spec/generator validation; decouple ROM/RAM sizes | M | in review | — | — |
| 3 | Correct shipped provenance & banners (first regen) | S | not started | — | — |
| 4 | Emitter fragment refactor (byte-identical) | M | not started | — | — |
| 5 | Newcomer on-ramp: hello design + front-door docs | M | not started | — | — |
| 6 | Peripheral extension: LFSR + dice design | L | not started | — | — |
| 7 | Stopwatch RTL showcase + parking | M | not started | — | — |

---

## Global invariants and conventions (every phase)

1. **No existing firmware `.bin` is modified anywhere in this plan.** Phases 5–6 add *new* `.bin`s;
   the six existing ones are untouched. If any step appears to require changing an existing `.bin`,
   stop — something is wrong.
2. **Vendored cores are never touched** (`scripts/embedded_core/cores/**`). Integrity tests pin
   them.
3. **Generated designs (`hdl/mx65_*.vhd`, `hdl/t80_*.vhd`) change only via regeneration**, never by
   hand-editing. From Phase 1 on, use `scripts/regen_embedded_cores.py`. After any commit that
   touches generated files, `regen --check` must report zero differences.
4. **The golden tests are the arbiter.** Any phase claiming "byte-identical output" proves it by
   the `test_generator_reproduces_*` tests passing with **zero changes to committed `hdl/` files**
   (`git status --porcelain hdl/` empty).
5. **Pre-commit gate** (repo convention): `uv run ruff check`, `uv run ruff format --check`,
   `uv run mypy .` (CI runs mypy over tests + sim too), `uv run pytest`. Fast inner loop while
   iterating: `uv run pytest tests/test_embedded_core.py -v`.
6. **Repo conventions:** feature branch per phase (never commit to main); conventional-commit
   titles (`fix:`/`feat:`/`docs:`/`test:`/`refactor:`); US spelling everywhere; VHDL is ASCII-only,
   LF endings; every PR explicitly considers doc updates and test additions.
7. **Completion checklist per phase** (repo convention): when a phase adds files, add rows to
   CLAUDE.md's Key Files table and README's Project Structure block as directed in the phase;
   cross-check interconnected doc sections.
8. **Toolchain facts (this machine, 2026-07-02):** `ca65`/`ld65` at `/usr/bin` (cc65); `z80asm` at
   `/usr/bin` is **z88dk's** Z80 Module Assembler 2.7.1o (Fedora package `z88dk-1.10.1`, a 2015 CVS
   snapshot). Two unrelated assemblers are named `z80asm` (z88dk's vs z80pack's) — this project uses
   **z88dk's**. Assemblers are dev-time only; CI never needs them (reassembly tests skip when
   absent).
9. **CI budget:** new integration tests (hello, dice, stopwatch) each add GHDL+NVC runs. Keep
   `--stop-time` minimal (static designs need far less than the walking counter's window).
10. **Write new Python strict-mode-clean.** Roadmap D8's full `strict = true` flip is still
    pending; fully annotate everything this plan adds (regen script, spec/emitter changes, tests)
    so D8's debt doesn't grow and D8 can land before, during, or after this plan indifferently.

---

## Finding index (traceability)

Every finding from the 2026-07-02 review, mapped to where it is addressed. Severity: **H** = will
mislead or break users; **M** = friction/scaling risk; **L** = polish.

| ID | Finding (short) | Sev | Phase |
|---|---|---|---|
| F1 | Plan doc status contradicts build notes ("Stage 5 remains future") | M | 0 |
| F2 | Guide + plan reference `mx65_walking_counter_7seg.asm`; file is `.s` | L | 0 |
| F3 | `sim/test_cpu_walking.py` docstring says "Stage-2 … 6502 firmware" (now shared by 6 designs) | L | 0 |
| F4 | Generated 48–156 KB designs pollute PR diffs (no `linguist-generated`) | L | 0 |
| F5 | Firmware `bounce` underflows when `N_LEDS = 1` (any design can run on any board) | L | 0 (doc) + parked (clamp) |
| F6 | T80 `irq_mode="simple"` (IM 1) declared but never generated/tested | L | 0 (doc) + parked (design) |
| F7 | Roadmap P8 should be framed "normalized bus v2 first", plus library-rewrite scripting + single-file relief-valve decision | M | 0 |
| F8 | No z80asm reassembly guard (4 Z80 `.asm`); `mx65_irq…s` also unguarded (only walking has one) | H | 1 |
| F9 | Regenerating six designs = six hand-typed 4-flag commands; no one-command regen | M | 1 |
| F10 | CLI demands `--cpu`/`--rom`/`--out` though the spec already knows them | L | 1 |
| F11 | ROM and RAM sizes are silently tied (shared `ADDR_HIGH` slice) — **user requires independent sizes** | H | 2 (+6 runtime proof) |
| F12 | Region base alignment unchecked → silent wrong decode | H | 2 |
| F13 | Region overlap unchecked | M | 2 |
| F14 | Oversized firmware vs ROM region → confusing late VHDL error | M | 2 |
| F15 | Unknown TOML keys silently ignored (`irq_moed = "simple"` → silently polled) | H | 2 |
| F16 | Six `CpuPlugin` fields are consumed nowhere (look like config, do nothing) | M | 2 |
| F17 | Guide §6 states no memory-map rules (power-of-two, alignment, overlap, ROM-at-boot) | M | 2 |
| F18 | `cpu_rom.vhd.tmpl` hardcodes "ca65 + ld65 … `.s`" — wrong provenance in all 4 shipped Z80 designs | M | 3 |
| F19 | `mx65_irq` spec/banner says ISR acks "by reading $E010" — actually write-1-to-clear IFR $E012 | M | 3 |
| F20 | Emitter's conditional VHDL lives as Python strings — won't scale to next axis / third core | M | 4 |
| F21 | No minimal on-ramp design (guide §7's "smallest thing" exists only as prose) | H | 5 |
| F22 | README: embedded-core family completely invisible (designs list, contract docs, structure, GIFs) | H | 5 |
| F23 | `firmware/README.md` stale: mx65-walking-only, manual-paste flow, no z80asm docs/version pin | H | 5 |
| F24 | Guide lacks a quickstart ("your first change") and a toolflow diagram | M | 5 |
| F25 | Guide §13's "extend cpu_io" promise has no worked example; extension path untested | M | 6 |
| F26 | No interactive RTL showcase beyond snake (stopwatch/reaction-timer gap) | M | 7 |
| F27 | Traffic-light FSM teaching design (low priority) | L | parked |
| F28 | Hex-counter firmware variant | L | parked (kept as guide exercise) |
| F29 | VSG (roadmap P7) cannot parse `@@TOKEN@@` templates or partial-unit fragments; P7 card's exclusion list misses `scripts/embedded_core/templates/**` and "VSG-clean by construction" phrasing misleads (user-raised 2026-07-02) | M | 0 |
| F30 | Plan↔roadmap sequencing was unrecorded (P7/P8 ordering; U4/U22/D8/P5 watch items) (user-raised 2026-07-02) | M | 0 + next section |

---

## Relationship to the improvement roadmap

Checked 2026-07-02 against `improvement_roadmap.md` (Sprint 2 in flight: D6b ScreenController,
U5 Settings dialog, full D8 `strict = true` flip) and the open-issue tracker (the Sprint 2 cards'
just-in-time issues #123 = D6b, #124 = U5, #125 = D8; plus #129 = `--screenshots` for the
headless benchmark, a Tier-3 candidate). All four are file-disjoint from this plan; none blocks
any phase. Issue #129, once landed, is a handy *manual* visual check for the designs Phases 5–7
add, but the phases' cocotb tests are the actual acceptance gates — no dependency either way.

**Nothing in the roadmap needs to land before this plan starts.** Active roadmap work lives in
`src/fpga_sim/` (UI, controller, session, sim_bridge internals); this plan lives in
`scripts/embedded_core/`, `scripts/gen_embedded_core.py`, `hdl/`, `firmware/`, `systems/`,
`tests/test_embedded_core.py`, `sim/test_cpu_*.py`, and docs. File overlap with Sprint 2 is
**zero** — they can proceed in parallel without rebase pain.

Constraints and watch items in both directions:

| Roadmap item | Constraint | Why |
|---|---|---|
| **P7 (VSG lint/format)** | **Not before Phase 0; ideally after Phase 4** | Phase 0 fixes P7's exclusion list (F29 — templates/fragments are not parseable VHDL); Phase 4 finalizes the template/fragment layout the VSG ruleset should be tuned against. P7's one-time reformat touches only hand-written `hdl/`, which this plan barely touches (one new file in Phase 7), so interleaving is safe but pointless churn. |
| **P8 (NEORV32 third core)** | **After Phases 0–4** (ideally after 7) | Phase 2's spec validation and Phase 4's fragment seam are the foundations the 32-bit arc builds on; Phase 0 records the "bus v2 first" framing on the card. |
| **U4 (contextual error hints)** | None — awareness only | U4 edits `check_vhdl_contract()` in `sim_bridge.py`, which `gen_embedded_core.py` calls for validate-then-write. Keep the `(ok, msg)` return shape or update the generator call site; the embedded-core tests catch a break either way. |
| **U22 (7-seg physical mux)** | None — awareness only | U22 must keep the logical packed-`seg` contract as the design-side default, or every 7-seg example — including the six-plus generated CPU designs — breaks. Phase 0 adds this as a carried-forward note on the U22 card. |
| **D8 (mypy strict flip)** | None — either order works | Global convention 10: all new plan code is written strict-clean, so D8 can land whenever. |
| **P5 (board peripherals extraction)** | Terminology only | Phase 6's system-spec `peripherals` (CPU-side IO subsystems inside a generated design) is unrelated to board-JSON `peripherals` (physical on-board devices, P5's domain). Phase 6's guide text names the distinction so future contributors don't conflate them. |

---

### Phase 0 — Errata & repo hygiene

**Goal:** eliminate every *factual error* in shipped docs and add zero-risk hygiene. No code
behavior changes, no generated-output changes.

**Rationale:** several shipped statements are simply wrong (stale status, wrong file extensions,
wrong ack mechanism claims come in Phase 3 since they need regeneration). Fixing prose first means
every later phase builds on accurate documentation, and this PR can land the same day it is
written. Highest correctness-per-minute in the plan.

**Items:**

1. **(F1)** `docs/embedded_core_system_plan.md` — grep `Stage 5 remains`. Rewrite the status
   callout to: Stages 0–5 fully complete (IRQ variant, T80 second core, both Z80 axes, capstone —
   see build notes); remaining Stage-5 ideas (third core, customasm) parked as roadmap P8 /
   this plan. Also update the `- **Stage 5 (later)**` bullet (grep `Stage 5 (later)`) to
   reflect done vs parked.
2. **(F2)** Fix `.asm` → `.s` for the 6502 firmware reference in two places:
   `docs/embedded_core_system_guide.md` (grep `mx65_walking_counter_7seg.asm`, §7) and
   `docs/embedded_core_system_plan.md` (same grep, the "Firmware:" line). Do **not** change Z80
   `.asm` references — those are correct.
3. **(F3)** `sim/test_cpu_walking.py` module docstring: state it is the **shared behavioral suite
   run by every embedded-core design** (both cores, all six systems — polled, simple-IRQ, IM 2,
   port-IO, capstone), that the firmware for each replicates `hdl/walking_counter_7seg.vhd`, and
   keep the existing tick-timing paragraph unchanged.
4. **(F4)** `.gitattributes` — append (with a one-line comment):

   ```gitattributes
   # Generated single-file embedded-core designs (regenerate; never hand-edit) — collapse in diffs
   hdl/mx65_*.vhd linguist-generated=true
   hdl/t80_*.vhd  linguist-generated=true
   ```

5. **(F5, doc half)** Guide §7 (button/edge-detect bullet area) or §12: add one sentence — the
   walking firmware assumes **`NUM_LEDS ≥ 2`**; on a 1-LED board the bounce logic underflows and
   the LED goes dark (7-seg odometer unaffected). All 7-seg boards satisfy this; the note matters
   because any design can be run on any of the 278 boards. (Firmware clamp itself is **parked** —
   see Parked section — because it would modify existing `.bin`s, violating invariant 1.)
6. **(F6, doc half)** Guide §4.6 (adapter-variants table) or §10: one sentence — T80
   `irq_mode="simple"` (Z80 IM 1) is generator-supported (base adapter + fixed-vector controller,
   same emitter branch the mx65 IRQ design exercises) but has **no committed design or test**;
   treat as declared-but-unexercised. (Committed IM 1 design is parked.)
7. **(F7, F29, F30)** `docs/improvement_roadmap.md` — one consolidated roadmap-editing pass:
   - **P8 card** (grep `**P8**`), append to the Notes cell: (a) build NEORV32 as **"normalized bus
     v2 first"** — define a handshaked, width-parameterized bus (valid/ready + byte enables) and
     re-express the mx65/T80 adapters as its degenerate case (ack always `'1'`, width 8) instead of
     special-casing a second bus beside v1; (b) script the `neorv32.` → `work.` library rewrite as
     a re-runnable patch script (T80-style documented patch, but automated — 20 files is too many
     to hand-edit reproducibly); (c) record an explicit **decision point**: at ~11k inlined lines
     per design, evaluate whether `sim_bridge`'s single-file rule should gain a relief valve
     (analyze a design + companion files) *before* committing to inline-everything for a 32-bit
     core; (d) sequencing: requires this plan's Phases 0–4 (spec validation + fragment seam) —
     link this document.
   - **P7 card** (grep `**P7**`), fix the exclusion list and the misleading phrase (F29): add
     `scripts/embedded_core/templates/**` to the **hard exclusions** — `.vhd.tmpl` files carry
     `@@TOKEN@@` markers and (from Phase 4) `.vhd.frag` fragments are partial design units, so
     **VSG cannot parse either**, exactly like the already-excluded `sim/sim_wrapper_template.vhd`.
     Rephrase "make the generator templates VSG-clean by construction" to "author templates to the
     ruleset's style — VSG never parses them; CI checks hand-written `hdl/` only". Optionally
     record a refinement idea: generated *blocks* **can** be mechanically style-checked by slicing
     a generated file at the `-- System blocks (generated)` ruler — everything after it is
     complete, valid design units (the vendored core above it is what must stay untouched) — a
     temp-file check, not a requirement.
   - **U22 card** (grep `**U22**`), add a carried-forward line: physical-mux mode must keep the
     logical packed-`seg` contract as the design-side **default** — every 7-seg example, including
     the generated embedded-core designs, assumes it.
   - Add a companion pointer so the roadmap references this plan as the active embedded-core arc
     (one line in the Icebox intro near the P7/P8 rows:
     `Active embedded-core follow-up arc: [embedded_core_improvement_plan.md](embedded_core_improvement_plan.md)`).

**Verification:** `uv run pytest` (unchanged, green); grep confirms no `mx65_walking_counter_7seg.asm`
remains; `git check-attr linguist-generated hdl/t80_walking_counter_7seg.vhd` reports `set`.

**Expected diff shape:** 5 docs + 1 test docstring + `.gitattributes`. Zero `.py` logic, zero
`hdl/`, zero `scripts/embedded_core/` changes.

---

### Phase 1 — Reassembly guards + regeneration tooling

**Goal:** make every later phase cheap and safe: prove all checked-in `.bin`s reproduce from their
sources *before* anything else moves, and make "regenerate everything" one command.

**Rationale:** Phases 3–6 regenerate designs and add firmware. Without reassembly guards we cannot
distinguish "my change" from "toolchain drift" the first time we assemble anything; without the
regen script, every template tweak costs six hand-typed commands and invites skew. This phase
changes **no generated output** — it only adds tests, CLI defaults, and a script.

**Items:**

1. **(F8) z80asm + full ca65 reassembly guards** in `tests/test_embedded_core.py`.
   - First, **pin the exact z80asm invocation manually** (scratchpad, not the repo): copy
     `firmware/t80_walking_counter_7seg.asm` to a temp dir, run the build-notes command shape
     (`z80asm -b -o<out.bin> <file.asm>` — note z88dk 2.7.1o glues the value to `-o`), and
     byte-compare against the checked-in `.bin`. **If it does not reproduce, STOP the phase and
     report** — do not touch `.bin`s; toolchain drift is a human decision. Record the working
     command verbatim in the new test and (Phase 5) the firmware README.
   - Add `test_firmware_reassembles_with_z80asm`, `@pytest.mark.slow`, parametrized over the four
     stems (`t80_walking_counter_7seg`, `t80_irq_counter_7seg`, `t80_portio_counter_7seg`,
     `t80_irq_portio_counter_7seg`), skipping when `z80asm` is absent. Run with the `.asm` **copied
     into a temp dir and cwd set there** — z88dk z80asm drops `.obj`/`.sym` byproducts next to its
     inputs (they are gitignored, but keep the tree clean).
   - Parametrize the existing `test_firmware_reassembles_with_ca65` (grep that name) over **both**
     mx65 stems (`mx65_walking_counter_7seg`, `mx65_irq_counter_7seg`) — the IRQ firmware currently
     has no guard.
2. **(F10) CLI inference** in `scripts/gen_embedded_core.py`: make `--cpu`, `--rom`, `--out`
   optional. Defaults derived from the spec, with `REPO = Path(__file__).resolve().parents[1]`:
   `cpu = spec.cpu`; `rom = REPO / "firmware" / f"{spec.firmware}.bin"`;
   `out = REPO / "hdl" / f"{spec.name}.vhd"`. Keep the existing mismatch check when `--cpu` *is*
   given; keep explicit flags as overrides. Update the module docstring usage block and guide §10
   to show the short form (`--system` only) with the long form as the override. Add a CLI test
   that invokes with only `--system` + `--out <tmp>` (always pass `--out` in tests so the tree is
   never written) and byte-compares against the committed design.
3. **Plugin assembly metadata (groundwork for Phase 3 and the script):** add two fields to
   `CpuPlugin` in `scripts/embedded_core/cpu_plugin.py` —
   `asm_toolchain: str` and `asm_ext: str`; mx65 = `("ca65 + ld65", ".s")`,
   T80 = `("z88dk z80asm", ".asm")`. **Not consumed by templates yet** (that is Phase 3, so this
   phase stays output-identical); the regen script uses them to locate sources.
4. **(F9) `scripts/regen_embedded_cores.py`** — the one-command loop:
   - Iterate `sorted((REPO / "systems").glob("*.toml"))`; for each: load spec, resolve plugin,
     read `firmware/<firmware>.bin`, `emit(...)`, compare to `hdl/<name>.vhd`.
   - **Default mode = check**: print one line per system (`OK` / `DIFFERS` / `MISSING`), exit
     nonzero on any difference. `--write` regenerates differing files in place (via the same
     validated path `gen_embedded_core` uses — reuse its validate-then-write, don't duplicate).
   - `--assemble`: additionally reassemble each firmware source (per-plugin command builders live
     in this script: ca65+ld65 with `firmware/mx65.cfg` for mx65; the pinned z80asm command for
     t80) into a scratch dir, byte-compare to the committed `.bin`, and report drift. **Never
     writes `.bin`s** — updating a `.bin` stays a deliberate manual act (invariant 1); the script
     prints the exact commands it ran so a human can repeat them.
   - Skip-and-note per firmware when its toolchain is absent.
   - Add a test running the script in check mode on the clean tree → exit 0, all `OK`.
5. **CLAUDE.md**: add a Key Files row for `scripts/regen_embedded_cores.py`.

**Verification:** `uv run pytest tests/test_embedded_core.py -v` — new reassembly tests pass
locally (both toolchains installed); `uv run python scripts/regen_embedded_cores.py` → all six
`OK`, exit 0; `uv run python scripts/regen_embedded_cores.py --assemble` → all six `.bin`s
reproduce; `git status --porcelain hdl/ firmware/` empty throughout.

**Expected diff shape:** tests + one new script + CLI-arg handling + 2 plugin fields + docs rows.
**Zero changes** under `hdl/`, `firmware/`, `templates/`.

---

### Phase 2 — Spec/generator validation; decouple ROM/RAM sizes

**Goal:** a wrong or ambitious user-authored `systems/*.toml` fails **at the generator with a clear
message** (or simply works), never as a silent mis-decode or a confusing VHDL error. Deliver the
user-required independence of ROM and RAM sizes.

**Rationale:** every committed spec happens to dodge these traps (2 KB ROM = 2 KB RAM, aligned,
non-overlapping), which is exactly why the first newcomer spec won't. The ROM/RAM tie is the worst:
the user has confirmed real designs routinely differ, and today a 4 KB ROM + 2 KB RAM spec emits a
file that fails elaboration with a width-mismatch error nowhere near the cause. All items in this
phase are **byte-identical for the six committed specs** — goldens prove it.

**Items:**

1. **(F11) Decouple ROM/RAM address slices.**
   - `scripts/embedded_core/emitter.py`: replace the single `ADDR_HIGH` token with
     `ROM_ADDR_HIGH = str(spec.rom.addr_bits - 1)` and `RAM_ADDR_HIGH = str(spec.ram.addr_bits - 1)`.
   - `templates/top.vhd.tmpl`: `rom_inst` port map uses `cpu_addr(@@ROM_ADDR_HIGH@@ downto 0)`;
     `ram_inst` uses `cpu_addr(@@RAM_ADDR_HIGH@@ downto 0)`.
   - Delete `SystemSpec.addr_high` (grep `addr_high` across `scripts/` and `tests/` — update
     `test_memory_map_drives_widths_and_decode` and any other assertion that referenced it).
   - Byte-identity argument: all six committed specs have `rom.addr_bits == ram.addr_bits == 11`,
     so both new tokens render `10`, exactly the old `ADDR_HIGH`. Verify with goldens + regen check.
   - **New test proving unequal sizes work:** build a synthetic mx65 spec in-test (ROM 4 KB at
     `0xF000`, RAM 2 KB at `0x0000`, IO at `0xE000`), emit with the committed walking `.bin`
     (2 KB ≤ 4 KB), and **analyze** the result under GHDL (skip-if-absent, mirroring the existing
     `ghdl` fixture pattern). Analysis-only is deliberate: the walking firmware's vectors assume
     ROM at `0xF800`, so don't *run* this image — Phase 6 provides the full runtime proof with a
     committed unequal-size design.
2. **(F12, F13, F15 + eager sizing) Spec validation** in `scripts/embedded_core/system_spec.py`:
   - In `SystemSpec.__post_init__` (or a `_validate_regions` helper it calls), for each region:
     size is a power of two (surface the existing lazy `addr_bits` check **eagerly at load**);
     `base % size == 0` (else e.g. `region 'io' base 0xE080 is not aligned to its size 0x100`);
     `base + size <= 0x10000`.
   - Pairwise **overlap check** over `[base, base + size)`. **Exemption:** when
     `io_transport == "port"`, exclude the `io` region from alignment and overlap checks — it lives
     in the Z80's separate I/O space (the committed port specs legitimately declare io at
     `0x0000/0x100` "under" ROM). ROM/RAM checks always apply.
   - **(F15) Unknown-key rejection** in `load()` (mirrors the board-schema strictness of #131):
     allowed top-level keys `{name, firmware, cpu, description, generics, memory, irq_mode,
     io_transport}`; `memory` subtables exactly `{ram, rom, io}` with keys `{base, size}`;
     `generics` keys exactly `{num_switches, num_buttons, num_leds, num_segs, counter_bits,
     prescaler_bits}`. Error names the unknown key and the allowed set — this turns
     `irq_moed = "simple"` from a silently-polled design into an immediate error.
3. **(F14) ROM-fit check** at the top of `emitter.emit()`:
   `len(rom_bytes) > spec.rom.size` → `ValueError` stating both numbers and the spec's ROM region.
4. **(F16) `CpuPlugin` honesty.**
   - **Consume `boots_at_zero`** as a placement guard (in `emit()`, next to the ROM-fit check):
     `boots_at_zero=True` → require `spec.rom.base == 0`; `False` (vector-fetch cores like the
     6502) → require `spec.rom.base + spec.rom.size == 0x10000` (the reset vectors at
     `$FFFA–$FFFF` must land in ROM). Error text cites guide §6 "put ROM where the core boots".
     Confirm all six committed specs already satisfy this (they do: T80 ROM at `0x0000`; mx65 ROM
     `0xF800 + 0x800 = 0x10000`).
   - Annotate the remaining unconsumed fields (`address_bits`, `data_bits`, `reset_active_high`,
     `irq_active_high`, `endian`) with an explicit comment: *documentation-only — the adapter VHDL
     implements this fact; changing the field has no effect (candidates to become functional with
     the P8 bus-v2 work)*. Add the same one-sentence caveat to guide §4.3.
5. **(F17) Guide §6 "Memory-map rules" paragraph** (now stating what the generator enforces):
   regions are power-of-two sized, size-aligned, non-overlapping, within 64 KB; **ROM and RAM sizes
   are independent** (each region's slice is generated from its own size); ROM must sit where the
   core boots (`$0000` for boots-at-zero cores, top-of-memory for vector-fetch cores — enforced);
   the firmware image must fit the ROM region; with `io_transport = "port"` the io region describes
   the separate I/O space and is exempt from memory-overlap rules. Update the spec-comment in
   `systems/mx65_walking_counter_7seg.toml` if it contradicts anything.
6. **Rejection tests** (clone the style of `test_spec_rejects_unknown_axis_values`): one per rule —
   misaligned base, overlapping regions, out-of-range region, unknown top-level key, unknown
   generic, oversized ROM image, boots-at-zero core with ROM not at 0, vector core with ROM not at
   top. Each asserts the message names the offending region/key.

**Verification:** full suite green with **zero `hdl/` changes**; `regen_embedded_cores.py` → all
`OK`; new unequal-size analysis test passes; every rejection test asserts a clear message.

**Expected diff shape:** `system_spec.py` + `emitter.py` + `cpu_plugin.py` + `top.vhd.tmpl`
(two lines) + tests + guide §6/§4.3. **No committed `hdl/` or `firmware/` changes.**

---

### Phase 3 — Correct shipped provenance & banners (first regeneration)

**Goal:** fix the two factual errors baked into shipped `.vhd` banners, and exercise the Phase-1
regen loop end-to-end for the first time on a deliberately tiny, reviewable diff.

**Rationale:** all four Z80 designs claim their ROM was "assembled by ca65 + ld65 from
`firmware/….s`" (wrong toolchain, wrong extension), and the mx65 IRQ design claims its ISR acks "by
reading $E010" when the design's own headline lesson is *write*-to-clear (the ISR write-1-clears
IFR `$E012`). These are teaching artifacts shipping wrong facts. Doing this *before* the Phase-4
refactor keeps that refactor purely byte-identical.

**Items:**

1. **(F18)** `templates/cpu_rom.vhd.tmpl` — grep `assembled by ca65`. Change the line to:

   ```vhdl
     -- ROM image: assembled by @@ASM_TOOLCHAIN@@ from firmware/@@FIRMWARE@@@@ASM_EXT@@
   ```

   and have `emitter.emit()` supply `ASM_TOOLCHAIN`/`ASM_EXT` from the Phase-1 plugin fields.
   For mx65 the rendered text is character-identical to today (`ca65 + ld65` + `.s`), so the two
   mx65 designs must **not** change; the four T80 designs change exactly this one comment line.
2. **(F19)** `systems/mx65_irq_counter_7seg.toml` — in `description`, replace the clause
   `the ISR runs once per tick -- acknowledging it by reading $E010 -- and does the same work as
   the polled design` with wording equivalent to: *the ISR reads IFR (`$E012`) to see which source
   fired — the timer tick or an input change — acknowledges it with a write-1-to-clear, and does
   the same work as the polled design*. Keep the rest of the description intact.
3. Regenerate: `uv run python scripts/regen_embedded_cores.py --write`.
4. Grep-assert cleanliness: no `ca65` string remains in any `hdl/t80_*.vhd`; no
   `reading $E010` remains anywhere.

**Verification:** goldens green (they regenerate-and-compare, so committed files and generator
agree); `regen --check` clean; full suite green.

**Expected diff shape:** exactly **5 generated files change, comment lines only** (4 × one
provenance line in `t80_*.vhd`; banner block in `mx65_irq_counter_7seg.vhd`), plus the template,
the toml, ~10 emitter lines, and possibly golden-test constants. If `git diff` shows any non-comment
VHDL change, stop.

---

### Phase 4 — Emitter fragment refactor (byte-identical)

**Goal:** move the multi-line conditional VHDL out of Python string literals into template
fragments, so `cpu_io`'s full content is readable as VHDL and the next feature axis (or P8) doesn't
multiply inline strings.

**Rationale (F20):** the entire interrupt controller (~70 lines of VHDL) lives in
`emitter.py`'s `emit()` as Python strings spliced through eight tokens. The guide tells newcomers
to "extend `cpu_io`", but doing so today means editing templates *and* Python literals *and* token
plumbing. Phase 6 (peripheral fragments) and P8 both need this seam clean. Doing it *now*, between
two output-changing phases, gives it the strongest possible acceptance criterion: **zero bytes of
output change**.

**Items:**

1. Create `scripts/embedded_core/templates/fragments/` using the extension **`.vhd.frag`**
   (deliberately not `.vhd`: fragments aren't standalone-analyzable VHDL; Phase 0 item 7 already
   put `scripts/embedded_core/templates/**` on the P7/VSG hard-exclusion list, which covers them).
2. Move the **multi-line VHDL bodies** out of `emitter.py` into fragments; keep ≤2-line connective
   splices (`IRQ_PORT`, `IO_IRQ_DECL`, `IO_IRQ_CONN`, `BUS_CTRL_DECL`, `CPU_IRQ_REQ`) as inline
   literals — the goal is readable VHDL, not zero Python strings. Suggested set:
   `irq_signals.vhd.frag` (the `INT_SIGNAL` block), `irq_read.vhd.frag` (`INT_READ`),
   `irq_logic.vhd.frag` (the interrupt-controller process + `irq <=` line),
   `irq_vec.vhd.frag` (the IM 2 vector encoder addition).
3. Loader helper in `emitter.py`:
   `def _frag(name: str, *, prefix: str = "\n") -> str: return prefix + (_TEMPLATES / "fragments" / name).read_text().rstrip("\n")`.
   Whitespace fidelity is the whole game: today's `INT_SIGNAL`/`INT_READ` strings begin with one
   `"\n"`; `irq_logic` begins with `"\n\n"` (pass `prefix="\n\n"`). Iterate until goldens report
   zero diff — the goldens are the arbiter, not visual inspection.
4. Keep the existing `_fill`/token mechanism and the final `"@@" in result` guard unchanged.
5. Docs: one paragraph in guide §13 (or a short "generator internals" note near §10) describing the
   template + fragment layout, so extenders know where VHDL lives. CLAUDE.md: extend the
   `scripts/embedded_core/` row with `templates/fragments/`.

**Verification:** the strongest in the plan — full suite green with `git status --porcelain hdl/`
**empty** (not one byte of any committed design changes); `regen --check` all `OK`; ruff + mypy
green.

**Expected diff shape:** `emitter.py` shrinks by ~70 string-literal lines; 4 new `.vhd.frag` files;
zero `hdl/` changes.

---

### Phase 5 — Newcomer on-ramp: hello design + front-door docs

**Goal:** a newcomer can (a) discover the embedded-core feature from the README, (b) open a
~20-line firmware as their first artifact, and (c) run the whole edit→assemble→regenerate→run loop
from one accurate page.

**Rationale (F21–F24):** the feature is invisible from the README today, and the smallest committed
firmware is ~270 lines. Guide §7 already *tells* people to start with "the smallest thing that
proves the IO path" — this phase makes that thing exist. Docs land here, after Phases 1–4, so they
describe the final tooling (short-form CLI, regen script, fragments) exactly once.

**Items:**

1. **(F21) `firmware/mx65_hello_7seg.s`** — the guide-§7 program, in the walking firmware's
   comment style. Reference listing (adjust only if `ld65` demands it):

   ```asm
   ; mx65_hello_7seg.s - the smallest program that proves the IO path (guide §7):
   ; light LED0, show "0" on digit 0, then hold forever.  Start your own firmware
   ; by copying this file, systems/mx65_hello_7seg.toml, and the assemble command
   ; in firmware/README.md.
   .setcpu "6502"

   LED_LO   = $E020                ; LED bits 7..0
   SEG_BASE = $E030                ; digit 0 segment register

   .segment "CODE"
   reset:
           sei                     ; no interrupts: we never leave the spin
           cld
           ldx     #$ff
           txs                     ; stack at $01FF (unused, but defined)
           lda     #$01
           sta     LED_LO          ; LED0 on
           lda     GLYPH0
           sta     SEG_BASE        ; digit 0 shows "0"
   spin:   jmp     spin            ; hold the display

   irq_handler:
           rti                     ; valid handler for stray IRQ/NMI/BRK

   .segment "RODATA"
   GLYPH0: .byte   $3F             ; active-high dp,g,f,e,d,c,b,a for "0"

   .segment "VECTORS"
           .addr   irq_handler     ; $FFFA NMI
           .addr   reset           ; $FFFC RESET
           .addr   irq_handler     ; $FFFE IRQ / BRK
   ```

   Check `firmware/mx65.cfg` first and mirror its required segments (the listing already provides
   CODE/RODATA/VECTORS). Assemble with the exact commands from the README and commit the `.bin`
   (a new `.bin` — invariant 1 intact).
2. **`systems/mx65_hello_7seg.toml`** — same memory map and generics as the walking spec;
   `description` tells the §7 story (smallest IO-path proof; copy-this-to-start). Generate
   `hdl/mx65_hello_7seg.vhd` with the short-form CLI; commit.
3. **Tests:** golden reproduce test (clone the `test_generator_reproduces_*` pattern); extend the
   ca65 reassembly parametrization with the hello stem; new `sim/test_cpu_hello.py` — after reset
   settles (~50 µs), assert `led == 0x01` and segment digit 0 == `0x3F` with all other digits
   `0x00`, then sample again ~20 µs later and assert unchanged (it is static). One NVC + one GHDL
   integration wrapper cloned from `test_mx65_walking_runs_nvc`/`_ghdl` with a **short**
   `--stop-time` (static design; keep CI cheap).
4. **(F22) README.md:**
   - Designs sentence (grep `ready-to-run designs`): add the embedded-core family — six generated
     CPU systems (6502 + Z80) plus `mx65_hello_7seg.vhd`.
   - New `### Embedded CPU systems` subsection under "Writing VHDL for the Simulator" (after the
     7-seg section): what they are (CPU + ROM + RAM + IO in one generated file; firmware produces
     the behavior), same board contract as above, one existing GIF
     (`docs/assets/cpu_walk_6digit.gif` — no new capture needed), the one-command regeneration, and
     links to the guide + this plan. Mirror CLAUDE.md's wording where possible — don't invent a
     second phrasing.
   - Project Structure block (grep `walking_counter_7seg.vhd`): add a summarizing row for
     `mx65_*.vhd` / `t80_*.vhd` (generated embedded-core systems — see guide), and rows for
     `scripts/gen_embedded_core.py`, `scripts/regen_embedded_cores.py`,
     `scripts/embedded_core/`, and top-level `systems/` and `firmware/` (all currently missing).
5. **(F23) Rewrite `firmware/README.md`:** table of **all** firmware files (both cores + hello);
   two toolchain sections with exact, tested commands — ca65/ld65 (as today) and the pinned z80asm
   command from Phase 1, with the version/flavor note (z88dk's assembler; Fedora `z88dk` package,
   2.7.1o here; the unrelated z80pack `z80asm` will not work); the workflow section becomes *edit
   source → assemble → `regen_embedded_cores.py --write` → `pytest`* (delete the manual
   paste-the-aggregate flow; `rom_to_vhdl.py` is an internal helper the generator calls); keep and
   restate the `.bin`-is-source-of-truth policy and point at the reassembly/golden tests as the
   drift guards.
6. **(F24) Guide:** add a short "Quickstart — your first change" box right after §1 (five steps:
   run an existing design; open `firmware/mx65_hello_7seg.s`; change the glyph/LED; assemble +
   `regen --write`; rerun and watch it change). Add a **toolflow** ASCII diagram (in §3 or §10)
   complementing the existing hardware diagram:

   ```text
   firmware/<name>.s|.asm ──(ca65+ld65 / z80asm, dev-time)──► firmware/<name>.bin ─┐
   scripts/embedded_core/cores/<core>/  (vendored VHDL, verbatim) ─────────────────┼─► gen_embedded_core.py ─► hdl/<name>.vhd ─► simulator
   systems/<name>.toml  (memory map + irq_mode/io_transport axes) ─────────────────┘        (validate-then-write)
   ```

   Point §7's "smallest thing" paragraph at the now-committed hello files.
7. **CLAUDE.md:** hello rows (firmware + design already covered by the existing family row —
   extend wording to mention hello as the on-ramp).

**Verification:** full suite green (new hello tests included); `regen --check` all seven `OK`;
`--assemble` reproduces the new `.bin`; README renders sanely (`grep -c mx65 README.md` > 0).

**Expected diff shape:** 1 new `.s`, 1 new `.bin`, 1 new `.toml`, 1 new generated `.vhd`, 1 new sim
test + integration wrappers, README/firmware-README/guide/CLAUDE.md edits. No changes to existing
firmware or designs.

---

### Phase 6 — Peripheral extension: LFSR + dice design

**Goal:** prove guide §13's "extend the IO subsystem" promise end-to-end with a committed worked
example — a new spec axis (`peripherals`), an LFSR random-number register realized as fragments,
a 6502 dice-roller firmware, and (deliberately) an **unequal ROM/RAM memory map** as the runtime
proof of Phase 2's size decoupling.

**Rationale (F25 + F11 runtime proof):** extension is the feature's whole pitch, and today nobody
has ever exercised the path; it is also the first real consumer of Phase 4's fragment mechanism —
each validates the other. Making this design's RAM 1 KB against a 2 KB ROM turns the user's
size-independence requirement into a permanently-tested, committed artifact.

**Items:**

1. **Spec axis:** `SystemSpec.peripherals: tuple[str, ...] = ()`; parse from an optional TOML
   `peripherals = ["lfsr"]` list; validate against a `PERIPHERALS = ("lfsr",)` set (unknown value →
   clear error); add `peripherals` to the Phase-2 allowed-key set. **Terminology note (say this in
   the guide §13 example too):** system-spec `peripherals` are CPU-side IO subsystems inside the
   generated design — unrelated to the board-JSON `peripherals` blocks (physical on-board devices,
   roadmap P5's domain).
2. **Template anchors** in `cpu_io.vhd.tmpl`: `@@PERIPH_SIGNALS@@` (after the `tick` declaration),
   `@@PERIPH_SENS@@` (in the read-mux sensitivity list, beside `@@INT_SENS@@`), `@@PERIPH_READ@@`
   (a `when` arm before `others`), `@@PERIPH_LOGIC@@` (end of architecture, beside
   `@@IRQ_LOGIC@@`). All render empty when `peripherals` is empty → **all existing designs stay
   byte-identical** (goldens prove it).
3. **LFSR fragments** (`templates/fragments/lfsr_*.vhd.frag`), spliced when `"lfsr"` is listed:
   - signals: `signal lfsr_reg : std_logic_vector(7 downto 0) := x"A5";  -- nonzero seed`
   - read arm: `when x"08"  => rdata <= lfsr_reg;`
   - logic (own clocked process; free-running, maximal-length x^8+x^6+x^5+x^4+1):

     ```vhdl
     lfsr : process (clk) begin
       if rising_edge(clk) then
         lfsr_reg <= lfsr_reg(6 downto 0) &
                     (lfsr_reg(7) xor lfsr_reg(5) xor lfsr_reg(4) xor lfsr_reg(3));
       end if;
     end process;
     ```

   - sens token renders `, lfsr_reg`.
4. **Guide:** §6 register table gains `$E008 | R | LFSR random byte (only when the spec lists the
   "lfsr" peripheral)`. Rewrite §13's "new subsystems" bullet into a short **worked example**
   subsection: fragment triple → spec list → firmware → tests, citing the dice files.
5. **`firmware/mx65_dice_7seg.s`** — behavior contract (the sim test asserts exactly this):
   - Cold start: standard init; read `CFG_SEGS`; blank digits `1..N_SEGS-1` (write `$00`); show
     glyph "0" on digit 0; LEDs `= 0`.
   - Per tick (poll + write-to-clear `$E010`): edge-detect `btn(0)` (walking firmware's
     `PREVBTN` idiom); on a rising edge read `$E008`, reduce mod 6 (subtract-6 loop), add 1 →
     value 1..6; write `DECLUT[value]` to digit 0 and the raw value to `LED_LO` (binary readout).
   - Reuse the walking source's structure/labels wherever possible — it is the reader's reference.
   Assemble with the standard commands; commit `.s` + `.bin`.
6. **`systems/mx65_dice_7seg.toml`:** `peripherals = ["lfsr"]`, `irq_mode = "none"`,
   `io_transport = "memory"`, and the **unequal map**: ROM `0xF800/0x0800` (2 KB, vectors at top ✓),
   **RAM `0x0000/0x0400` (1 KB)** — zero page + stack fit in 1 KB, and `RAM_ADDR_HIGH (9)` ≠
   `ROM_ADDR_HIGH (10)` exercises Phase 2's per-region slices **at runtime under both simulators**.
   Say so in the spec's description banner.
7. **Tests:** spec-axis tests (unknown peripheral rejected; `peripherals` default empty); golden
   reproduce test; ca65 reassembly parametrization + dice; `sim/test_cpu_dice.py` — boot state
   (digit 0 = `0x3F`, others `0x00`, `led == 0`); then 6 presses of `btn(0)` (hold ≥ 2 ticks,
   release ≥ 2 ticks, varied spacing): after each, digit 0 ∈ glyphs 1–6
   (`{0x06,0x5B,0x4F,0x66,0x6D,0x7D}`) and `led == decoded value`; assert ≥ 2 distinct values
   across the 6 rolls (the sim is deterministic — if a chosen spacing happens to repeat, change the
   spacing constants, don't loosen the assert). NVC + GHDL integration wrappers.
8. **Docs/bookkeeping:** README designs list + firmware README table + CLAUDE.md rows; `regen`
   picks the new system up automatically (glob).

**Verification:** full suite green; goldens for the six pre-existing designs show **zero diffs**
(empty-token proof); `regen --check` all eight `OK`; dice runs under both simulators.

**Expected diff shape:** spec/emitter/template additions + 3 fragments + 1 `.s` + 1 `.bin` +
1 `.toml` + 1 generated `.vhd` + tests + docs. **No changes to the six existing generated designs.**

---

### Phase 7 — Stopwatch RTL showcase + parking

**Goal:** add the interactive hand-written RTL showcase the review called for, and formally park
the remaining low-priority items per the repo's backlog model (parked → roadmap Icebox).

**Rationale (F26):** the repo's strongest teaching theme is "same behavior, hardware vs software"
(the walking counter exists as both RTL and firmware). A stopwatch extends the theme with the most
demo-able cause-and-effect interaction (start/stop/reset under user control), and its future
firmware port is a natural guide exercise. Last because nothing depends on it.

**Items:**

1. **`hdl/stopwatch_7seg.vhd`** — hand-written, in `counter_7seg.vhd`'s commented teaching style
   (~150 lines). Behavior contract:
   - `btn(0)` rising edge toggles `running`; `btn(1)` rising edge zeroes the digits (does not
     change `running`); both sampled synchronously with a previous-value register (inputs are
     clean in this simulator — say so in a comment).
   - Time base: a free-running divider sized from `COUNTER_BITS` (a legitimate use of the contract
     generic — note that the simulator overrides it at runtime); each active switch doubles the
     count rate (reuse `walking_counter_7seg.vhd`'s `idx := base - n` idiom).
   - While `running`: BCD ripple-increment across `NUM_SEGS` digits per divider tick, wrapping at
     all-9s (mirror the walking counter's RTL ripple).
   - `led(0) = running`; other LEDs `'0'`. Glyphs from the same `SEG_LUT` bytes.
2. **`sim/test_stopwatch.py`:** initially all digits show "0" and stay static; press `btn(0)` →
   value advances; press `btn(0)` again → two samples apart are equal (frozen); press `btn(1)` →
   digits return to all-"0". Reuse `test_cpu_walking.py`'s `_segs`/`_number` decode helpers
   (copy locally — sim modules are standalone).
3. **Integration wrappers:** grep `counter_7seg` under `tests/` and clone however the hand-written
   7-seg designs are wired for GHDL + NVC.
4. **Docs:** README designs list + Project Structure row; guide §13 one-liner — porting the
   stopwatch to 6502/Z80 firmware is left as the reader's exercise (the walking counter shows the
   full recipe); CLAUDE.md row.
5. **(Parking — see next section)** Add the parked items to `docs/improvement_roadmap.md`'s Icebox
   with fresh P-IDs (grep the current highest P-ID first), each with its trigger, per the repo's
   backlog model. Mark this plan's ledger complete.
6. **Optional:** a `capture_demo.py` GIF of the stopwatch for the README (nice-to-have; skip if
   time-boxed).

**Verification:** full suite green; stopwatch behavioral tests pass under both simulators;
`regen --check` unaffected (`stopwatch_7seg.vhd` is hand-written, not a system).

**Expected diff shape:** 1 new hand-written `.vhd`, 1 sim test + wrappers, docs, roadmap Icebox
entries. No generator changes.

---

### Parked (recorded in the roadmap Icebox by Phase 7; not scheduled)

| Item | Why parked | Trigger to revive |
|---|---|---|
| Firmware `N_LEDS ≥ 2` clamp (F5) | Requires modifying all six existing `.bin`s (invariant 1); documented instead in Phase 0 | First real report of someone running a CPU design on a 1-LED board, or the next planned firmware reassembly wave |
| Committed T80 IM 1 (`irq_mode="simple"`) design (F6) | Generator path already exercised by `mx65_irq`; a 7th ~150 KB design + new firmware buys little pedagogy | A third core lands (then completing the matrix has demonstration value), or a user asks for an IM 1 reference |
| Traffic-light FSM teaching design (F27) | Lower teaching value than the stopwatch (which already demonstrates FSM-ish control + interaction); avoid example sprawl | Curriculum/course use surfaces a need for a labeled-states FSM example |
| Hex-counter firmware variant (F28) | Deliberately kept as the guide §13 reader exercise — converting BCD to hex display is ideal first-firmware homework | Never (by design), unless the guide gains a solutions appendix |
| Single-file relief valve in `sim_bridge` | Recorded as a P8 decision point (Phase 0 item 7), not standalone work | P8 (NEORV32) starts and the ~11k-line inlining cost becomes concrete |

---

### Final acceptance (after Phase 7)

- `uv run pytest` fully green; `uv run ruff check`, `ruff format --check`, `mypy .` clean.
- `uv run python scripts/regen_embedded_cores.py` → all systems `OK` (six original + hello + dice).
- `uv run python scripts/regen_embedded_cores.py --assemble` → every `.bin` reproduces from source
  with the documented commands (both toolchains).
- Grep-audits: no `mx65_walking_counter_7seg.asm`, no `assembled by ca65` inside any `t80_*.vhd`,
  no `reading $E010`, no `Stage 5 remains`.
- A newcomer path exists end-to-end: README → guide quickstart → `mx65_hello_7seg.s` → edit →
  assemble → `regen --write` → run; and the extension path README → guide §13 → dice example.
- Status ledger above fully filled in; parked items live in the roadmap Icebox.
