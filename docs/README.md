# Documentation map

Two kinds of document live here, and the split is the point of this directory's layout.

**`docs/*.md` is what you read to *use* or *extend* the simulator** — it describes the tool as it
is today. If you are here for the first time with a design of your own, read
[first_design.md](first_design.md) and ignore the rest until something breaks.

**[`docs/plans/`](plans/) is how it got that way**: one execution plan per arc, kept as
the project's engineering history rather than deleted at merge. A plan is never the answer to "how
does this work?"; when the two disagree, the reference below is right and the plan is a record of
what was intended at the time.

## Start here

| If you want to… | Read |
|---|---|
| **run your own lab design for the first time** | **[first_design.md](first_design.md)** |
| fix whatever just went wrong | [troubleshooting.md](troubleshooting.md) |
| install it, on any of the three OSes | [install.md](install.md) |
| drive it — the four screens, the in-sim controls, sessions and settings | [user_guide.md](user_guide.md) |
| write a design it can run | [writing_designs.md](writing_designs.md) |
| understand how it is built, before changing it | [architecture.md](architecture.md) |
| write a design around an embedded 6502 or Z80 | [embedded_core_system_guide.md](embedded_core_system_guide.md) |

## Reference and record

| Document | What it is |
|---|---|
| [improvement_roadmap.md](improvement_roadmap.md) | **The strategy source of truth** — every open card, the dependency table, the live queue in *Current focus*, and the Icebox with each parked item's trigger |
| [roadmap_delivered.md](roadmap_delivered.md) | The shipped detail behind every ✅ card, so the roadmap above can stay short |
| [u25_ghdl_perf_profile.md](u25_ghdl_perf_profile.md) | A measurement report: where GHDL's time actually goes (U25). Numbers, not a plan |
| [embedded_core_build_notes.md](embedded_core_build_notes.md) | The working log kept while the embedded-core generator was built |

## Cited data registries

Two directories hold **evidence**, not prose: each entry quotes a fetched vendor source, and an
entry that cannot be verified is omitted rather than guessed.

| Directory | What it pins down |
|---|---|
| [port_convention_sources/](port_convention_sources/) | Where each board's canonical port names and polarities come from — the input to board-native VHDL mode |
| [led_color_sources/](led_color_sources/) | Per board and per LED bank, the cited color a name heuristic cannot supply (Terasic `LEDR` = red, and so on) |

`assets/` holds the GIFs and stills the README and guides embed; `experiments/` holds one-off
write-ups kept for their measurements.

## Plans — [`docs/plans/`](plans/)

Each file carries its own status header; this table is the index. **Live** plans are being executed
or are approved and queued; **executed** plans shipped in the release named.

| Plan | Status |
|---|---|
| [u48_classroom_arc_plan_v2.md](plans/u48_classroom_arc_plan_v2.md) | **LIVE — executing** → v0.23.0. The pre-semester classroom arc: U48–U54 + D17 |
| [u39_peripherals_plan.md](plans/u39_peripherals_plan.md) | **LIVE — approved**, unstarted → v0.24.0. Character LCD + SPI OLED on a peripheral framework |
| [docs_assets_improvement_plan_v2.md](plans/docs_assets_improvement_plan_v2.md) | **LIVE — split execution**; PRs 1–2 shipped, PRs 3–6 ride the peripherals arc |
| [u44_multi_input_plan_v1.md](plans/u44_multi_input_plan_v1.md) | executed → v0.21.0 — simultaneous holds, latched buttons, keyboard mapping |
| [u22_7seg_scan_plan.md](plans/u22_7seg_scan_plan.md) | executed → v0.19.0 — the physical scan display interface |
| [u9_led_complete_plan.md](plans/u9_led_complete_plan.md) | executed → v0.17.0 + v0.18.0 — duty-measured brightness, LED banks and colors, RGB |
| [u35_simulator_picker_plan.md](plans/u35_simulator_picker_plan.md) | executed → v0.16.0 — four selectable simulator backends |
| [u34_single_window_plan.md](plans/u34_single_window_plan.md) | executed → v0.15.0 — one window for the whole session, headless sim child |
| [u21_board_native_vhdl_plan.md](plans/u21_board_native_vhdl_plan.md) | executed → v0.14.0 — a design written to a board's own port names |
| [board_native_release_plan.md](plans/board_native_release_plan.md) | executed → v0.14.0 — that arc's release plan |
| [embedded_core_improvement_plan.md](plans/embedded_core_improvement_plan.md) | executed → v0.9.0 — the generator's follow-up arc |
| [embedded_core_system_plan.md](plans/embedded_core_system_plan.md) | executed → v0.9.0 — soft CPU cores as single-file designs |
| [docs_assets_improvement_plan.md](plans/docs_assets_improvement_plan.md) | executed (round 1) → v0.10.0 — the visual README |
| [7seg_display_plan_v2.md](plans/7seg_display_plan_v2.md) | executed (7-segment v1); its deferred physical-scan half shipped as U22 |
| [u48_classroom_arc_plan.md](plans/u48_classroom_arc_plan.md) | superseded by v2 the same day — kept as the record of how that arc was first framed |
