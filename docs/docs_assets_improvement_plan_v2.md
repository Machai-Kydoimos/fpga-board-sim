# Docs & Assets Improvement Plan — Round 2

> **Status:** **DECISIONS RESOLVED 2026-08-05 (Rick), all as recommended — A2 (single-renderer
> P20 refactor) · B (RGB mixing + scan display + PWM brightness → README; themes + debug duty
> bars → user-guide stills) · C (re-capture the same hero storyboard).** Drafted 2026-07-28.
> Not started. **Split execution adopted 2026-08-05:** PRs 1–2 run early (small, independent —
> may interleave with the U44 arc); PRs 3–6 run **after** the U39–U41 peripherals arc, so one
> asset refresh captures both new feature sets. See `improvement_roadmap.md` → Current focus.
> **Base commit:** every fact and `file:line` locator below was verified against `main` @
> `0d034ee` (v0.20.0, 2026-07-28). If `main` has advanced, re-verify by grepping the quoted
> content before trusting any line number.
> **Executor:** a future Claude session — read this document top to bottom, then execute the PRs
> in order (PRs 3–6 touch overlapping files and stay strictly sequential; per the 2026-08-05
> split above, PRs 3–6 wait until the peripherals arc ships). The §4 decisions are **settled —
> do not relitigate them.** If reality contradicts a stated fact, stop and surface it rather
> than improvising.
> **Closeout:** when the last PR merges, complete [§9](#9-closeout).

## 1. Ledger

| PR | Scope | Size | Status |
|---|---|---|---|
| PR 1 | Doc accuracy sweep + a count-drift guard test | S | ✅ **done 2026-08-25** |
| PR 2 | `--screenshots` on the benchmark path (issue [#129](https://github.com/Machai-Kydoimos/fpga-board-sim/issues/129)) | S | not started |
| PR 3 | Capture pipeline renders true brightness (§4 decision A) | M–L | not started |
| PR 4 | Re-capture the existing asset set | M | not started |
| PR 5 | New visuals for the unillustrated features (§4 decision B) | M | not started |
| PR 6 | Asset-regeneration procedure + docs wiring | S | not started |

No roadmap card needed — this is a maintenance arc, like round 1. Open one umbrella issue and
link each PR to it.

> **Scripted input for capture (added 2026-08-25):** U44 ✅ left the tap point in place — input is
> now **one coalesced full-state message per frame** carrying a monotonic `seq`, echoed back by the
> child as `input_seq` in every `state` payload. Icebox **P31** (input record/replay over
> `sim_link`) is the card for turning that into a recorder/player, and PR 2 here is its named
> trigger.

## 2. Context — why this exists

Rick asked for this on 2026-07-23: *"at the appropriate time we will do a new Docs/Assets
Improvement Plan. We want to shine with the latest."* The v0.10.0 assets predate most of the
current feature set. But exploration on 2026-07-28 turned up something sharper than staleness:

**The committed assets cannot show the product's headline features, because the capture pipeline
renders a different LED model than the product does.**

`sim/capture_frames.py:85` drives the board with the **binary** API:

```python
for i, on in enumerate(lit):
    board.set_led(i, on)
```

while the product's own renderer (`ui/simulation_screen.py:399-419`) drives the **continuous**
one:

```python
self.board.set_led_level(comp, level)  # :399
self.board.set_led_channel(comp, role, level)  # :401
self.board.set_seg_levels(i, levels[...])  # :416
```

Both APIs exist on `FPGABoard` (`ui/board_display.py:268` `set_led` vs `:272` `set_led_level`,
`:277` `set_led_channel`, `:312` `set_seg` vs `:318` `set_seg_levels`). The capture path never
moved to the second set. So **every GIF in `docs/assets/` renders the pre-v0.17 binary on/off LED
model** — no PWM dimming, no RGB color mixing, no honest 1/N scan brightness.

That is exactly the feature list the README leads with:

> **True LED brightness** — …rendered as perceptual brightness: PWM dimming, RGB color mixing,
> and scan-display multiplexing all look like the real hardware (`README.md:169-172`)

The prose and the pictures disagree, and the pictures are the first thing a visitor sees.

**The asset set is also simply old.** `docs/assets/` was last touched **2026-07-03** (PR #163);
`board_selector.gif` dates to **2026-06-25**. Everything shipped since is invisible: U34
single-window (v0.15), U35 simulator picker (v0.16), U9 duty/brightness + U36 LED colors (v0.17),
U37/U38 RGB + debug duty bars (v0.18), U22 board-native scan displays (v0.19).

**And the counts have drifted** (see §3).

### 2.1 The find that reshapes the work

`fpga-sim --benchmark N` (without `--no-ui`) already **renders through the real
`SimulationScreen`, headless** — `__main__.py:199` `_benchmark_full_system`, whose docstring at
`:209` reads *"Benchmark the whole app headless: the real SimulationScreen + a free-running
child."*

So issue **#129** (`--screenshots <dir>` on that path) is not a supporting tool for this arc — it
is **the enabler**. Screenshots taken there come out of the product's own renderer, which means
brightness, RGB pucks, scan multiplexing, themes, the sim panel and the `D` debug duty-bar view
are all correct **for free**, with no second implementation to keep in sync. That is why PR 2
comes before any capture work.

It does not cover everything: the benchmark path free-runs, so it has **no scripted input
injection**. The interactive GIF storyboards (cursor taps BTN0, holds BTN1, toggles SW0) still
need `capture_demo.py`'s machinery. That gap is decision A (§4).

## 3. Verified current state (evidence map)

| Claim | Evidence |
|---|---|
| Capture path uses the binary LED API | `sim/capture_frames.py:85`, `:89` |
| Product path uses the continuous (duty) API | `ui/simulation_screen.py:399`, `:401`, `:416` |
| Both API sets exist on `FPGABoard` | `ui/board_display.py:268`, `:272`, `:277`, `:312`, `:318` |
| `capture_frames.py` has no duty/level handling at all | grep for `duty`/`level` in that file → only an RGB channel-folding comment at `:72-73` |
| `--benchmark` renders via the real `SimulationScreen` | `__main__.py:199`, docstring `:209`; `--no-ui` is the opt-out (`:190`) |
| `--screenshots` does not exist | `fpga-sim --help` lists `--sim`, `--benchmark`, `--board`, `--vhdl`, `--no-ui`, `--list-sims`, `--add-sim` |
| The pre-U34 hand-rolled screenshot recipe has drifted | it builds `FPGABoard` inside the cocotb child and calls `_generate_wrapper` without `duty=`; that signature now takes `match` / `duty` / `design_has_rgb` (`sim_bridge.py:2092-2100`), so a recipe capture has no brightness |
| Assets last regenerated 2026-07-03 (PR #163); selector GIF 2026-06-25 | `git log -1 -- docs/assets`; file mtimes |
| The legacy capture path is a known parked item | Icebox **P20**, `improvement_roadmap.md:547` — "refactor them to drive the sim over `sim_link` and render via `SimulationScreen` for a single rendering path, or leave them as the standalone capture tool they are" |
| 285 boards load | `discover_boards(get_default_boards_path())` → 285 |
| 2127 tests pass | `uv run pytest -q`, 69–71 s |
| `board_images/` is gitignored (generated locally) | `.gitignore:8`; `git ls-files board_images` → 0 |

### 3.1 Count drift (PR 1's worklist)

> **✅ Delivered 2026-08-25.** All eight user-facing counts corrected to **285 boards /
> 266 with conventions** (both re-derived from `discover_boards()`, not carried forward),
> and `tests/test_docs_board_counts.py` added so the next board addition fails the suite.
> Two rows resolved differently from the table below, both deliberately:
> `README.md:30`'s **GIF alt-text** had its count *removed* rather than set to 285 — alt
> text describes the image, and the GIF still shows 278 until PR 4 re-captures it, so a
> number there would be a new lie rather than a fixed one; and the
> `improvement_roadmap.md` stats line was re-verified as planned and found stale *again*
> (U44 moved tests 2127 → 2308), so it was refreshed along with LOC and module counts.
> `scripts/capture_selector.py`'s "all 278 boards" comment was made count-free for the
> same reason as the alt text.

| Location | Says | Should say |
|---|---|---|
| `README.md:16` | 284 boards | 285 |
| `README.md:26` | "one of **284 boards**" | 285 |
| `README.md:28` | "**284 real FPGA boards**" | 285 |
| `README.md:30` | GIF alt-text "the **278**-board list" | 285 (and the GIF itself is re-captured in PR 4) |
| `README.md:95` | "the 284-board list" | 285 |
| `README.md:164` | "**265 of the 284** boards" | re-derive both numbers |
| `docs/user_guide.md:20` | "A list of 284 FPGA boards" | 285 |
| `docs/writing_designs.md:201` | "**265 of the 284** boards" | re-derive both |
| `docs/improvement_roadmap.md:16` | "43 test files (1445 tests)… 278 board definitions… **v0.14.0 released**" | 2127 tests, 285 boards, v0.20.0 |

The board count is now wrong in **eight** places after a single board addition (DE4, #345). Fix
the numbers **and** add the guard — see PR 1. *(2026-08-05: the `improvement_roadmap.md:16`
row was already refreshed by the roadmap reconciliation — PR 1 re-verifies it rather than
re-fixing it.)*

## 4. Decisions to make (open — settle these first)

> **✅ RESOLVED 2026-08-05 (Rick), all as recommended: A2 · B (RGB mixing + scan display + PWM
> brightness for the README; themes + debug duty bars as user-guide stills) · C (re-capture the
> same hero storyboard).** The analyses below are retained as the decision record.

### Decision A — how do interactive GIFs get true brightness?

The stills problem is solved by PR 2. The **GIF storyboards** still run through
`capture_frames.py`'s binary path. Two routes:

| | A1 — patch duty into `capture_frames.py` | A2 — do the P20 refactor |
|---|---|---|
| What | Add a `_duty_ports`-style probe (mirroring `sim_testbench.py:104`) and switch to `set_led_level` / `set_led_channel` / `set_seg_levels` | Rebuild the capture path to drive the child over `sim_link` and render via `SimulationScreen`, adding scripted input injection to that path |
| Size | M | L |
| Result | Two renderers, kept in sync by hand | **One** renderer; every future feature reaches the assets automatically |
| Risk | The sync burden is exactly what just failed | Bigger change; storyboard timing must be re-tuned against a different loop |

**Recommendation: A2.** The maintenance argument is not hypothetical — three releases of visual
work (v0.17/v0.18/v0.19) never reached the assets *precisely because* a second renderer existed
and nobody remembered it. A1 buys a cheaper PR and keeps the trap. A2 also retires Icebox **P20**
and makes PR 5's new visuals nearly free. If the L is unwelcome now, A1 is a legitimate stopgap —
but then say so explicitly in P20 rather than silently re-parking it.

### Decision B — which new visuals ship?

Candidates, each currently unillustrated. Recommend **3–4**, not all of them — round 1's lesson
was that a small set of well-directed captures beats a gallery.

| Candidate | Shows | Why it might earn its place |
|---|---|---|
| **PWM brightness** | a design fading LEDs; graded, not binary | the README's #1 listed feature, with no picture today |
| **RGB color mixing** | `hdl/rgb_rainbow.vhd` cycling the RGB pucks | the most visually striking thing the simulator does |
| **Scan display** | `nexys4ddr_scan.vhd` / `basys3_scan.vhd` at honest 1/N brightness | the v0.19 headline; also proves the "real hardware" claim |
| **Simulator picker** | the `[SIM:…]` toggle cycling GHDL/LLVM/JIT/NVC | v0.16 headline, invisible today |
| **Themes** | one board in PCB Green / Dark / High Contrast | cheap (three stills), sells polish |
| **Debug duty bars** | the `D` view with per-channel duty | strong for the docs, probably too niche for the README |
| **Board-native** | the same board running a design in its own port names + the INFO badge | the v0.14 headline; hard to make *visually* legible |

**Recommendation:** RGB color mixing + scan display + PWM brightness for the README; themes and
debug duty bars as stills in `docs/user_guide.md`. Board-native and the simulator picker read
better as prose than as pictures — leave them.

### Decision C — does the hero GIF change?

`demo.gif` (DE10-Lite + `snake_7seg.vhd`) is a good storyboard and its loop seam was carefully
fixed in round 1. Options: re-capture the **same** storyboard on the duty-aware pipeline
(cheap, keeps the proven direction), or restage it to feature brightness/RGB.

**Recommendation: re-capture the same storyboard.** Round 1 spent real effort on that loop seam
and the interaction beat; re-shooting it with correct brightness is a strict upgrade. Put the new
capabilities in *additional* clips (decision B) rather than rebuilding the hero.

## 5. The PRs

Global conventions in §6 apply to all of them. Each PR: branch off freshly-pulled `main`, one PR,
CHANGELOG entry, merge before starting the next.

### PR 1 — Doc accuracy sweep + count-drift guard (S)

**✅ Done 2026-08-25.** See the §3.1 note for what shipped.

**Do:** fix all nine locations in §3.1. Then add the guard: a test that asserts the
documented board count matches `len(discover_boards(...))` wherever it appears, so the next board
addition fails loudly instead of silently ageing eight strings.

**Verify:** `uv run pytest` green; deliberately bump the loader count in a scratch edit and
confirm the guard fails.

**Quality gates:** this is the "pair a hook with a repo-wide test" lesson from #348 — a guard that
only runs in pre-commit is bypassable, so it belongs in the **test suite**. Keep the assertion
about *counts*, not prose: do not build a general docs linter.

### PR 2 — `--screenshots` on the benchmark path (S) — issue #129

**Do:** add `--screenshots <dir>` to the benchmark path. It saves `SimulationScreen`'s rendered
frames as PNGs, gated on visual change plus a few milestone frames (issue #129 describes the
heuristic). Reuse `FPGABoard.visual_signature()` (`board_display.py:762-784`) as the change gate —
U23 already computes exactly this, so the flag is nearly free and cannot drift from what the
renderer considers a change.

**Verify:** the issue's own done-when —
`fpga-sim --benchmark 5 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd --screenshots /tmp/out`
writes PNGs with evolving LED state; repeat on a 7-seg board + design. Confirm a PWM design's
PNGs show **graded** brightness (this is the proof that the product renderer is in play).

**Quality gates:** `--screenshots` without `--benchmark` must error clearly, like `--no-ui`
(`__main__.py:80`). Update the stale pre-U34 screenshot recipe wherever it is referenced —
CONTRIBUTING's "Smoke-testing a board" is the right home for the replacement.

> **Also serves the peripherals arc.** `u39_peripherals_plan.md` Phase 5 requires headless PNGs
> for Rick's visual-review merge gate. Building this here means that arc gets it for free.

### PR 3 — Capture pipeline renders true brightness (M–L) — decision A

**Do:** whichever of A1 / A2 §4 settles on.

**Verify:** capture a PWM design and a scan design; LEDs are graded and a 1/N scan digit renders
at 1/N brightness. Cross-check one frame against the same design captured via PR 2's
`--screenshots` — **the two paths must agree** (under A2 they are the same code, which is the
point).

**Quality gates:** under A2, do not regress the offline/no-launcher property — these tools are
invoked outside the app and must stay that way. Keep GIF assembly (`capture_common.assemble_gif`)
untouched; only the *rendering* source changes.

### PR 4 — Re-capture the existing asset set (M)

**Do:** regenerate every committed asset on the PR 3 pipeline: `demo.gif` (same storyboard, per
decision C), `board_selector.gif` (oldest asset; its alt-text count is fixed in PR 1),
`mx65_walking_counter_{2,4,6}digit.gif`, `mx65_walking_counter_demo.gif`, `mx65_dice_7seg.gif`,
`mx65_hello_7seg.png`. Re-check every caption against what the new frames actually show.

**Verify:** each GIF loops seamlessly (round 1's rule: restore **all** persistent inputs — SW0
off *and* BTN0 re-tapped); step rates readable, not temporally aliased.

**Quality gates:** **Rick's visual review before merge** — the UI/render carve-out from
merge-on-green. Never post-process a committed GIF; if it is wrong, re-capture it.
`mx65_hello_waveform.png` and `mx65_hello_7seg.gtkw` come from `capture_waveform.py`, a separate
path — leave them unless they are demonstrably stale.

### PR 5 — New visuals (M) — decision B

**Do:** capture the chosen set; embed with descriptive alt-text (round 1's alt-text is long and
explains cause-and-effect — match that register); wire into README and/or `docs/user_guide.md`.

**Verify:** every new asset renders correctly in both GitHub light and dark, and each has alt-text
that stands alone if the image fails to load.

**Quality gates:** Rick's visual review before merge. Watch total README weight — the existing
assets already run to ~3.3 MB; prefer stills over GIFs where a still tells the story.

### PR 6 — Asset-regeneration procedure + docs wiring (S)

**Do:** document how to regenerate every asset (which script, which flags, which board/design) so
the next refresh is a checklist rather than an excavation. Round 1 put this in CONTRIBUTING —
extend it rather than starting a new home. Record the §2 finding explicitly: *assets must be
captured through the product renderer, or they will silently drift from it again.*

**Verify:** a reader can regenerate any committed asset from the doc alone.

## 6. Global conventions

- One feature branch per PR, off freshly-pulled `main`; never commit to `main`. PRs are
  sequential — they touch overlapping files.
- Every PR adds a `CHANGELOG.md` entry under `## [Unreleased]`, Keep-a-Changelog style: bold
  lead-in, prose, `(#PR)`.
- Before every commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy . &&
  uv run rumdl check . && uv run pytest`. Use `set -o pipefail` when piping to `tail`.
- `mypy .` covers `scripts/` and `sim/` — new code must be fully typed, with docstrings (ruff
  `ANN`/`D`).
- US spelling everywhere; VHDL stays plain ASCII.
- `gh` for all GitHub operations. Never predict PR numbers in committed text.
- **Asset PRs (4 and 5) require Rick's visual review of the rendered GIFs/PNGs before merge.**

## 7. Risks

| Risk | Mitigation |
|---|---|
| A2's refactor changes storyboard timing and the loop seams break | PR 4 is a separate PR from PR 3, so re-tuning is isolated; round 1's seam rule (restore *all* persistent inputs) is the acceptance test |
| The two capture paths silently diverge again | PR 3's verify step cross-checks a frame against PR 2's `--screenshots`; A2 removes the possibility structurally |
| README weight grows past comfort | prefer stills; decision B caps the new set at 3–4 |
| Count guard becomes a nuisance that blocks unrelated PRs | assert only the count, in one place, with the fix being a one-line doc edit |
| Assets re-shot now, then the peripherals arc adds a board section | the peripherals section only renders when a device attaches, so existing captures stay valid — confirm this holds when `u39_peripherals_plan.md` Phase 5 lands |
| Scope creep into a general docs overhaul | the README *text* was refreshed in #327 and is in good shape; this arc is pictures + counts, not prose |

## 8. Verification (end-to-end, after PR 6)

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run rumdl check .
uv run pytest                                    # incl. the PR 1 count guard

# the enabler, on the product renderer
uv run fpga-sim --benchmark 5 --board DE10_Lite --vhdl hdl/counter_7seg.vhd \
    --screenshots /tmp/shots                     # graded brightness, not binary

# regenerate an asset from the documented procedure alone
uv run python scripts/capture_demo.py            # hero GIF
```

**Done when:** the assets show what the product actually renders (brightness, RGB, scan), the
counts are right and guarded, `--screenshots` exists and is documented as the smoke-test capture
route, and a maintainer can regenerate any asset from the procedure in CONTRIBUTING.

## 9. Closeout

- [ ] Close umbrella issue + [#129](https://github.com/Machai-Kydoimos/fpga-board-sim/issues/129)
- [ ] Set this document's Status to DONE with the per-PR ledger filled in
- [ ] Resolve Icebox **P20** (`improvement_roadmap.md:547`) — closed by A2, or re-parked with a
      note recording that A1 was chosen and the two-renderer trap remains
- [ ] Refresh `improvement_roadmap.md:16`'s Context paragraph (counts, test total, latest release)
- [ ] Update `docs/docs_assets_improvement_plan.md`'s round-1 closeout to point here
- [ ] CHANGELOG entries reconciled for the release
- [ ] Project memory updated (`project_docs_assets_plan.md` + MEMORY.md pointer)
