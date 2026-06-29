# Embedded Core Systems — Build Notes

> Working log captured while implementing [`embedded_core_system_plan.md`](embedded_core_system_plan.md).
> Purpose: record concrete facts, gotchas, and working commands as each stage lands, so the
> [development guide](embedded_core_system_guide.md) can be finalized against reality at Stage 4.
> Not user-facing — fold the durable parts into the guide, then trim.

## Stage 0 — Vendor mx65 + smoke-test (DONE 2026-06-29)

**Upstream.** `github.com/Steve-Teal/mx65`, file `mx65.vhd`, pinned commit
`d65d81d4f8031e194bd8410133b9036db7e58794`. License **MIT** (Copyright (c) 2022 Steve Teal) — full
text in the repo's `LICENSE`; the core's own inline header carries only the copyright line, so the
vendored copy prepends the full MIT permission notice for compliance.

**Vendored to** `scripts/embedded_core/cores/mx65.vhd` = ASCII provenance+MIT header (32 lines) +
the upstream file byte-for-byte (995 lines) = **1027 lines**.

**Facts confirmed (corrected the plan + guide where they differed):**

- Size is **~995 lines**, not the "~650" the plan/guide originally claimed. *(Fixed in both docs.)*
- Libraries: `ieee.std_logic_1164` + `ieee.numeric_std` **only** — no Synopsys packages, no vendor
  primitives. Single `entity mx65` + one `architecture rtl`, **zero sub-component instantiations**
  (truly self-contained → nothing else to inline under the single-file rule).
- Ports exactly as the plan stated: `clock, reset, ce, data_in(7:0), data_out(7:0),
  address(15:0), rw, sync, nmi, irq`. No generics.
- The upstream repo also ships `ram.vhd`, `rom.vhd`, `uart.vhd`, `apple1.vhd` (an Apple-1 example
  system) — **not** vendored; we write our own `cpu_ram`/`cpu_rom` with the combinational-read
  timing the plan specifies.

**Analyzes clean under both simulators** (toolchain here: GHDL 7.0.0-dev on a 6.0.0 base;
NVC 1.22-devel):

```bash
ghdl -a --std=08   --workdir=<wd>      scripts/embedded_core/cores/mx65.vhd   # exit 0, no warnings
nvc  --work=work:<wd> --std=2008 -a    scripts/embedded_core/cores/mx65.vhd   # exit 0
```

- Benign NVC message: `directory <wd> already exists and is not an NVC library` appears when `<wd>`
  is pre-created (e.g. by `mkdtemp`); NVC then creates its library inside. Harmless (exit 0); the
  existing suite tolerates the same.

**Guide-worthy:**

- **Vendoring recipe:** prepend an ASCII comment block (provenance: repo URL + pinned commit; full
  MIT notice) and keep the core bytes verbatim. Verify the result is ASCII / no-BOM (the
  simulator's encoding gate, `check_vhdl_encoding`) *before* trusting it — non-ASCII bytes in a core
  would fail file selection in the UI.
- A bare core is analyzed with the backend's `analyze_cmd` **directly**, not via `analyze_vhdl()`
  (which also generates + elaborates the `sim_wrapper` and assumes the `clk/sw/btn/led` top contract
  the core doesn't have).

**Tests:** `tests/test_embedded_core.py` — file integrity (present, ASCII, MIT notice, pinned
commit, standard-IEEE-only) + `@pytest.mark.slow` analyze-under-GHDL/NVC. 6 tests, green.

**Still open for Stage 1** (the bus-timing unknowns from the plan's mx65 box — read out of the
architecture and confirm via waveform):

- which clock edge/phase mx65 samples `data_in` (decides combinational vs registered read);
- when `data_out`/`rw` are valid for writes;
- minimum reset pulse width before the reset-vector fetch;
- whether `ce='1'` tied permanently is fine.
