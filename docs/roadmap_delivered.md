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

### D6. Extract a `ScreenController` from `__main__.py` ✅

- ✅ **D6a — screen-result enums, 2026-06-26 (PR #121).** Replaced the stringly-typed screen results (`"back"`, `"load_vhdl"`, `"simulate"`, `"quit"`, `"retry"`) with **two** enums in a new leaf module `ui/results.py`: `ScreenResult` (BACK / LOAD_VHDL / SIMULATE / QUIT) for `FPGABoard.run()`, and `DialogResult` (RETRY / BACK) for `ErrorDialog.run()`, both re-exported from `ui/__init__.py`. Kept as two enums (not one shared) so mypy rejects passing a dialog result where a screen result is expected — both have a `BACK`, but the types are disjoint. `FPGABoard.run()` delegates its exit-flag mapping to a unit-tested `_result()` seam. 7 new tests; `mypy .` confirmed to flag the three misuse shapes (wrong return, wrong assignment, wrong arg).
- ✅ **D6b — ScreenController extraction, 2026-07-05 (PR #168, issue #123).** New `src/fpga_sim/controller.py`: a `SessionState` dataclass (the current VHDL / work-dir / `work_dir_simulator` tuple plus the persisted selector preferences, with `clear_analysis()` / `clear_vhdl()` invariant helpers) and a `ScreenController` that owns the pygame `screen`/`clock` and the loop — each screen has a private `_run_*` method, a `match` on `ScreenResult` dispatches, and the public transition methods (`on_board_selected` / `on_vhdl_loaded` / `on_simulate` / `on_back`) are the unit-testable state-machine edges. `main()` is now a thin ~35-line driver (arg parsing, pygame/window setup, board discovery, hand-off); `_build_generics` moved to `controller.build_generics` (the benchmark path imports it back). Behavior-preserving by design — preselection prefs update only on launch, cancel-keeps-VHDL, retry-reopens-at-`hdl/`, the stale-session contract re-check, and the pygame quit→init cycle around the sim subprocess all carried over verbatim — pinned by 33 new tests (fakes monkeypatched on the controller module namespace; the `on_simulate` tests drive the real quit→init cycle under the session-scoped `headless_pygame` fixture) plus a headless real-screen drive (selector → preview → back → quit) during review. `on_vhdl_loaded()` is the designed landing spot for **U5**'s save-on-pick.

### D9. `Literal` types for stringly-typed identifiers ✅

- ✅ Defined `Simulator = Literal["ghdl", "nvc"]` (in `sim_bridge.py`) and threaded it through `analyze_vhdl` / `launch_simulation` / `_backend` / `detect_simulators` / session config. Extend with `"iverilog"` when **U20** lands.

### D10. Pin pre-commit hooks consistently; add `.editorconfig` ✅

- ✅ Added `.editorconfig` (Python 4-space / 100-col, matching ruff). **Superseded (2026-06-22, #102):** hooks are no longer `rev:`-pinned — ruff / ruff-format / mypy / rumdl run as *local* hooks tracking `uv.lock` as the single source of truth.

### D11. Module + mock-class docstrings ✅

- ✅ Added the module docstring explaining the exec-in-mock-namespace strategy, plus one-line docstrings on the eight mock classes, the resource helpers, and `_make_namespace()`. *(The mock-exec parser later moved out to `scripts/amaranth_parser.py` in #104.)*

### D8. mypy strict mode ✅

- ✅ **First slice, 2026-06-26 (PR #119, issue #116).** Enabled `check_untyped_defs = true` and fixed the 26 errors it surfaced — all in `tests/` (wrong-typed `ComponentInfo` positional args, unguarded `… | None` access, a benign `draw_button` return-value assert kept behind a targeted `# type: ignore[func-returns-value]`).
- ✅ **Full flip, 2026-07-03 (PR #166, issue #125).** `[tool.mypy]` now carries a single `strict = true`, superseding the five flags it used to list explicitly (`warn_return_any`, `warn_unused_ignores`, `disallow_incomplete_defs`, `disallow_untyped_defs`, `check_untyped_defs`) plus enabling the ~8 it didn't (`disallow_any_generics`, `disallow_subclassing_any`, `disallow_untyped_calls`, `disallow_untyped_decorators`, `warn_redundant_casts`, `no_implicit_reexport`, `strict_equality`, `extra_checks`). Fixed all 212 newly-surfaced errors: 10 in `src/` (bare `list`/`dict` generics on `BoardDef` fields; a new `_Positionable` `Protocol` + `Sequence` for `board_display.py`'s heterogeneous LED/Button/Switch/FPGAChip layout lists, replacing invariant bare `list`; a redundant `Surface` cast; an untyped `SimpleQueue` element type), 44 in `scripts/` (bare `dict`/`list`/`tuple` generics across the three board-file parsers + `analyze_metrics.py` — `Any` element types throughout, since the content is genuinely dynamic mock-exec/regex output), and 158 in `tests/` + `sim/` — 151 `no-untyped-call`, cleared by annotating ~20 small test-local helpers (cocotb `dut` readers, synthetic pygame-event builders, sample `BoardDef`/dict factories; the per-module `disallow_untyped_defs` exemption for test bodies was untouched), plus 7 one-off catches: 3 bare-generic `type-arg` (`test_sync_common.py`, `test_board_schema.py`), 2 genuine `no_implicit_reexport` hits (`test_sync_amaranth_boards.py` imported `sanitize_filename`/`unique_name` via `sync_amaranth_boards`'s incidental re-export instead of from `sync_common.py` where they're defined — fixed by importing from the real source), and 2 `comparison-overlap` in `test_screen_results.py` on two intentionally-tautological enum comparisons (proving `ScreenResult`/`DialogResult` are disjoint) — `strict_equality` now proves statically the exact thing those tests assert at runtime, so each got a targeted `# type: ignore[comparison-overlap]`. No CHANGELOG entry (types/tooling only, no runtime/user-facing change, same as the first slice).

---

## Delivery log

Cross-cutting notes carried forward from completed work (forward-relevant gotchas also appear as ⚠ notes on the open cards they affect in [improvement_roadmap.md](improvement_roadmap.md)):

- **Selector key handling (from U1 ✅).** Any new *printable* keyboard shortcut on the board selector must be intercepted in `BoardSelector._handle_keydown()` *above* the `filter_text += ev.unicode` branch (match on `ev.unicode`), or the keystroke leaks into the text filter — this is how `?` and type-to-filter coexist.
- **Off-main-thread work (from U2 ✅).** `run_with_spinner()` is the pattern for any future long-running launcher operation (simulator install probe, board re-sync, large-file load): the worker callable runs on a `ThreadPoolExecutor` thread and **must not touch pygame** — only the main thread draws. Pass arguments with `functools.partial` (not a `lambda`) when the call site is inside a loop, so loop variables are bound eagerly (avoids B023 and the closure-widening that would otherwise re-introduce `str | None`).
