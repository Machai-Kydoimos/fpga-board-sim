# Vendored T80 (Z80-compatible CPU core)

Source: <https://github.com/mist-devel/T80> — "an attempt to collect and track
all fixes in one place" (the maintained T80 line: Daniel Wallner → MikeJ /
fpgaarcade → Sorgelig).

- **Pinned commit:** `f7f776b54d67dcd6b19d3b97027dfbc6db6f14f4`
- **License:** BSD-3-Clause (Copyright (c) 2001-2002 Daniel Wallner and later
  contributors). The full notice is retained in each `.vhd` header and travels
  into any generated design, satisfying the "reproduce in synthesized form"
  clause.

## Files (analyze / inline leaf-first, in this order)

1. `T80_Pack.vhd` — shared package
2. `T80_ALU.vhd`
3. `T80_MCode.vhd`
4. `T80_Reg.vhd`
5. `T80.vhd` — the core
6. `T80s.vhd` — synchronous wrapper (the entity we instantiate; `Mode => 0` = Z80)

Only these six are vendored; the upstream 8080/Game-Boy variants and alternate
wrappers (`T80a`, `T80pa`, `T8080se`, `GBse`, …) are not used.

## Standardization patch (the only change to the vendored bytes)

Upstream `T80.vhd` and `T80s.vhd` `use IEEE.STD_LOGIC_UNSIGNED` — a Synopsys
package this project's flow rejects (`ghdl -a --std=08` / `nvc --std=2008 -a`
**without** `-fsynopsys`). They are the only two files that do, and T80 uses no
`std_logic_arith`-only helpers (`conv_integer`, …), so the fix is a
one-line-per-file swap to the VHDL-2008 *standard* package:

```vhdl
use IEEE.STD_LOGIC_UNSIGNED.all;   ->   use IEEE.NUMERIC_STD_UNSIGNED.all;
```

Verified: all six files then analyze clean under GHDL (`--std=08`) and NVC
(`--std=2008`) with no `-fsynopsys`. To re-vendor: copy the six files from a new
pinned commit and re-apply this swap.
