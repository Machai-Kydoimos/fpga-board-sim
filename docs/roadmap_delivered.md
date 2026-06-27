# Virtual FPGA Boards — Delivered Roadmap Items

*Companion to [improvement_roadmap.md](improvement_roadmap.md) (the forward plan) and CHANGELOG.md. This is the historical record of completed roadmap cards — their shipped detail, PRs, and the cross-cutting "carried-forward" notes. The forward plan keeps a one-line stub for each item and links here.*

Per-PR detail also lives in `CHANGELOG.md` and the linked PRs; the pre-condense card text is recoverable via `git show <merge-commit>:docs/improvement_roadmap.md`. Completed Tier-3 quick wins (U11, U12, U13) remain inline in the forward plan's Tier-3 table.

---

## User-facing

### U0. Board selector — faceted filtering and sort ✅

- ✅ **2026-05-27 (PR #75).** Filter chips (4 component + data-driven vendor chips with an "Other" group), a 7-mode sort dropdown (Name, Vendor, LEDs, Switches, Buttons, 7-seg, Total), an active-filter counter, and session persistence of all filter/sort state; 42 new tests. Touched `ui/board_selector.py`.

### U1. Help / About overlay (clickable `(?)` button · F1 · `?`) ✅

- ✅ **2026-06-01 (PR #88).** New `ui/help_dialog.py` — a blocking `HelpDialog` (4-step workflow, keyboard-shortcut legend, VHDL contract summary) opened by F1, `?`, or a circular `(?)` button on all three launcher screens; the legend renders from a single `SHORTCUTS` / `WORKFLOW` / `CONTRACT` source so it can't drift from the real handlers; 36 new tests. Carried-forward gotchas now noted on **U5** / **U7** / **U14** (and the [Delivery log](#delivery-log)).

### U2. Inline analysis spinner during VHDL load ✅

- ✅ **2026-06-25 (PR #117).** New `ui/spinner.py` — `run_with_spinner()` runs `analyze_vhdl()` on a worker thread (a `ThreadPoolExecutor` future) and animates a `SpinnerOverlay` (dimmed snapshot → centered info-panel → a 12-dot comet ring, with "Analyzing &lt;file&gt;…" + "Running &lt;SIM&gt; analysis & elaboration…") on the main thread at ~30 fps until the future resolves, then returns its `(ok, detail)`. pygame rendering stays single-threaded — the worker only spawns subprocesses + reads files (approach (a) from the original card). Wired into **both** `__main__.py` analyze call sites (the Load-VHDL picker path and the re-analyze-before-simulate path) via `functools.partial`, whose eager arg-binding sidesteps the loop-variable-closure lint (B023) and preserves mypy's narrowing of the `str | None` path. A window-close (`QUIT`) during the wait is remembered and re-posted after the analysis finishes (the work can't be interrupted mid-flight). Two new `Theme` roles (`spinner_arc` / `spinner_track`); 20 new tests. **Closes Sprint 1b.** Carried-forward rule noted in the [Delivery log](#delivery-log).

### U26. Visual README — interactive demo + selector GIFs (docs / marketing) ✅

- ✅ **2026-06-25 (PR #110).** Two reproducible animated GIFs open the README: an *interactive* `snake_7seg` demo on the DE10-Lite (a faux cursor taps BTN0 / BTN1 / SW0 with cause→effect captions over a "live VHDL simulation · board (source) · file" strip) and the board selector filtering 278 → 9 by component + vendor. New maintainer tooling — `scripts/capture_demo.py` / `capture_selector.py` / `capture_common.py` + `sim/capture_frames.py` (Pillow in the `dev` group; GIFs assembled with `disposal=1` for size). Bundled selector UX wins: always-visible scrollbar, a per-row source tag, and the filter box no longer overlapping the count. Soft: the headless renderer can later feed **U8** (splash screen).

---

## Developer-facing

### D1. Generate the VHDL wrapper from one source ✅

- ✅ **2026-05-28.** Merged `sim_wrapper_template.vhd` + `sim_wrapper_7seg_template.vhd` into one template with conditional seg placeholders spliced by `_generate_wrapper()`; deleted the 7-seg template and `_choose_wrapper_template()`. Unblocks **U21** / **U22**.

### D2. Backend base class with override-only differences ✅

- ✅ **2026-06-25 (PR #115).** Converted `_SimBackend` from a `Protocol` to an **ABC** and hoisted the four discovery helpers (`find` / `available` / `lib_dir` / `sim_bin_lib`) onto it as `@classmethod`s keyed on each backend's `NAME`; `_GHDLBackend` / `_NVCBackend` now override only `NAME` + the four per-simulator command builders (`plugin_lib_name` / `analyze_cmd` / `elaborate_cmd` / `run_cmd`), which stay `@staticmethod`. `_backend()` now returns `type[_SimBackend]`. ~19 LOC of duplication removed from `sim_bridge.py`. As predicted, `test_backend_has_all_protocol_methods` had to be relaxed (static- *or* classmethod); two guard tests were added so the shared helpers must stay inherited (absent from each subclass `__dict__`), locking in the dedup. Unblocks **U20** (a third backend now overrides only `NAME` + the command builders, no copy-paste).

### D4. Shared button-drawing helper ✅

- ✅ **2026-05-31 (PR #83).** Added `ui/widgets/button.py` (`ButtonStyle` + `draw_button`) and routed all four sites through it (board_display footer, error_dialog, sim_panel clock steppers, the sim Stop/Pause overlay — across *both* processes); deleted `sim_panel._draw_btn`; the clock steppers gained hover feedback. 7 new tests. Consumed by **U1 ✅**; **U5 / U7** should reuse it.

### D15. Consolidate scattered colors into the single source of truth ✅

- ✅ **2026-06-24 (PR #109).** New `ui/theme.py` — a frozen `Theme` dataclass (~80 semantic color roles + the vendor-color map, defaults = today's pcb-green) and a single swappable `THEME` instance; `constants.py` keeps only base neutrals + `get_font` / `_ui_scale`; ~112 inline RGB literals across 9 files now read `THEME.<role>`. Shipped **pixel-identical** (all 278 board SVGs byte-for-byte unchanged), import graph kept acyclic (`constants ← widgets.button ← theme`); 12 new tests. Front-loads **U6**'s container shape (see U6's ⚠ carried-forward note).

### D9. `Literal` types for stringly-typed identifiers ✅

- ✅ Defined `Simulator = Literal["ghdl", "nvc"]` (in `sim_bridge.py`) and threaded it through `analyze_vhdl` / `launch_simulation` / `_backend` / `detect_simulators` / session config. Extend with `"iverilog"` when **U20** lands.

### D10. Pin pre-commit hooks consistently; add `.editorconfig` ✅

- ✅ Added `.editorconfig` (Python 4-space / 100-col, matching ruff). **Superseded (2026-06-22, #102):** hooks are no longer `rev:`-pinned — ruff / ruff-format / mypy / rumdl run as *local* hooks tracking `uv.lock` as the single source of truth.

### D11. Module + mock-class docstrings ✅

- ✅ Added the module docstring explaining the exec-in-mock-namespace strategy, plus one-line docstrings on the eight mock classes, the resource helpers, and `_make_namespace()`. *(The mock-exec parser later moved out to `scripts/amaranth_parser.py` in #104.)*

---

## Delivery log

Cross-cutting notes carried forward from completed work (forward-relevant gotchas also appear as ⚠ notes on the open cards they affect in [improvement_roadmap.md](improvement_roadmap.md)):

- **Selector key handling (from U1 ✅).** Any new *printable* keyboard shortcut on the board selector must be intercepted in `BoardSelector._handle_keydown()` *above* the `filter_text += ev.unicode` branch (match on `ev.unicode`), or the keystroke leaks into the text filter — this is how `?` and type-to-filter coexist.
- **Off-main-thread work (from U2 ✅).** `run_with_spinner()` is the pattern for any future long-running launcher operation (simulator install probe, board re-sync, large-file load): the worker callable runs on a `ThreadPoolExecutor` thread and **must not touch pygame** — only the main thread draws. Pass arguments with `functools.partial` (not a `lambda`) when the call site is inside a loop, so loop variables are bound eagerly (avoids B023 and the closure-widening that would otherwise re-introduce `str | None`).
