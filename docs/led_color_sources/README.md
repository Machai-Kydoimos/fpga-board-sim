# LED color source registry

Cited LED colors for boards whose LED color is **not** encoded in the resource
name (so the sync parsers' name heuristic, `scripts/led_metadata.color_from_name`,
leaves them unset). Each entry names a fetched, authoritative source for the
color, so a bare `led` bank that is physically red or green renders in that
color instead of the theme default (U36).

This mirrors the port-convention registry (`docs/port_convention_sources/`): a
machine-parseable (`tomllib`) family of TOML files, applied to board JSONs by a
sync step. Colors flow into `boards/*/*.json` as the optional per-component
`color` field (see `boards/schema/board.schema.json`).

## Why a registry (and not the port name)

`LEDR`→red / `LEDG`→green is a **Terasic idiom**, not a cross-vendor rule, and
port-naming conventions vary by maker and drift over time. So the color is never
inferred from the name; it is quoted from the board's own documentation, with the
port name (and schematic, when available) as corroboration.

## Schema

```toml
[[board]]
name  = "DE0-CV"                        # human label (not a key)
files = ["amaranth-boards/de0_cv.json"] # board JSON(s) this row colors
maker = "Terasic"

  [[board.bank]]
  match  = "led"      # colors every leds[] entry whose `name` == this
  color  = "red"      # a board.schema.json component color (named or #RRGGBB)
  source = "..."      # REQUIRED: a quote from a fetched authoritative source
```

`match` selects an LED bank by resource name (a consecutive same-`name` run in
`leds[]`); a two-color board (e.g. DE2-115's 18 `led` + 9 `led_g`) lists one
`[[board.bank]]` per bank. `color` wins over the name heuristic — a cited datum
outranks an inferred one.

## Rules

- **Verify or omit.** Only commit a `color` you have quoted from a fetched
  vendor source (user/reference manual or schematic). Do not invent citations;
  an uncited board simply keeps the theme fallback, which is always safe.
- **Corroborate.** Prefer an explicit color statement in prose; note the
  canonical port name and schematic net as corroboration in `source`.
- **Never hand-edit generated board JSONs** to add colors — change this registry
  and re-run the applier (`scripts/sync_led_colors.py`). `boards/custom/*` are
  hand-maintained but are still driven from this registry so the citation is
  recorded in one place.

## Applying

`uv run python scripts/sync_led_colors.py` stamps every board JSON named here
with its registry colors (no network needed). The same application also runs
inside `sync_common.write_outputs`, so a board re-sync (amaranth/litex/digilent)
re-applies colors rather than dropping them.
