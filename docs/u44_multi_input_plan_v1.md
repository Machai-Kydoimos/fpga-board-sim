# U44 — Multi-input: simultaneous holds, latched buttons, keyboard mapping (arc plan v1)

> **Status:** **APPROVED FOR EXECUTION — the active arc.** Drafted 2026-07-29; the five
> decisions in [§5](#5-decisions-to-make-open--settle-these-first) were **resolved 2026-08-05
> (Rick), all as recommended: A1 · B1 · C1 · D1 · E confirmed** (Phase 0b ✅), so the phase
> scopes below apply exactly as written. Roadmap card filed 2026-08-05
> (`improvement_roadmap.md` → Current focus + Part 1 / Tier 2); target release **v0.21.0**.
> Execution not yet started — the milestone and phase issues are opened just-in-time when
> Phase 1 begins.
>
> **Base commit:** every fact and `file:line` locator below was verified against `main` @ `c759258`
> (post-v0.20.0, 2026-07-29). If `main` has advanced, re-verify by grepping the quoted content
> before trusting any line number.
>
> **Card IDs:** **U44** (this arc) and **P31+** (follow-ons) are the next free numbers — verified
> 2026-07-29. `improvement_roadmap.md` allocates through U38 / D16 / P24; `docs/u39_peripherals_plan.md`
> reserves U39–U41 + P25–P30 and names follow-ons U42/U43. Re-verify before opening issues if this
> sits unstarted through another arc. **2026-08-05: the U44 card is now filed and the roadmap's
> new ID-allocation note records every reservation (next free: U46 · D17 · P34) — the roadmap is
> again the allocation source of truth.**
>
> **Audience contract:** written to be executed phase-by-phase by a capable model without additional
> context. Every phase has **Do**, **Verify**, **Quality gates**. Do not start a phase until the
> previous phase's Verify passes. One PR per phase; branch each phase off post-merge `main`; never
> commit to `main`. If reality contradicts a stated fact, stop and surface it rather than improvising.
>
> **Provenance:** the multi-press UX catalog evaluated in [§3.5](#35-why-not-the-alternatives-do-not-relitigate)
> was supplied by Rick from a Gemini query; every pattern in it is given an explicit verdict there so
> the rejected ones are not relitigated later.

---

## 1. Context — why this work exists

On a real board you press three buttons with three fingers, hold them, and let go in whatever order
you like. You wedge a switch bank into a pattern and leave it. You hold `BTNC` while flipping `SW0`.

The simulator can do none of that. It has exactly one hold, because it has exactly one cursor — and
worse, it throws that hold away indiscriminately:

```python
# src/fpga_sim/ui/board_display.py:722-724
elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
    for btn in self.buttons:
        btn.handle_release()          # ← releases EVERY button, regardless of which was pressed
```

`Button.handle_release()` (`components.py:551`) takes no position and no identity. Any mouse-up
clears every held button. There is no keyboard path at all — **no `KEYUP` handler exists anywhere
in `src/`** — so N-key rollover, the one input device a user already owns that can express
simultaneity, is unused.

The good news: **the wire protocol is already correct.** `_send_input()` transmits a full-state
bitmask of every switch and button in one message:

```python
# src/fpga_sim/ui/simulation_screen.py:201-212
sw_val = sum(1 << s.index for s in self.board.switches if s.state)
btn_val = sum(1 << b.index for b in self.board.buttons if b.pressed)
send(self.child.link.conn, "input", {"sw": sw_val, "btn": btn_val, "seq": self._input_seq})
```

Arbitrary simultaneous input is already expressible end-to-end. **Nothing in the VHDL contract, the
wrapper, `sim_link`, or the testbench needs to change to support it.** The entire gap is in the UI's
input model. That makes this a contained, high-leverage arc.

Requested capabilities (Rick, 2026-07-29): hold multiple buttons at once; **sticky/latched** buttons
that stay down until released; both together; **keyboard mapping** where holding `1` holds `BTN1` and
releasing `1` releases it; and a decision on boards with more than 10 buttons.

### 1.1 What research turned up that changes the shape of the work

Two findings that were not part of the original ask:

1. **A latent bug in the sim child swallows fast taps entirely** (see [§4](#4-the-swallowed-tap-bug-decision-d)).
   Keyboard taps are faster than mouse clicks, so this arc makes an existing bug more visible unless
   it is fixed. Decision D.
2. **Key badges on the widgets are not polish — they are mandatory.** On 5 of 285 boards the rendered
   button labels are *duplicated* (Sword shows `BTN0` three times), so no label-driven mapping can
   exist and the on-screen label cannot tell the user which key drives which button. Verified:
   Sword (11 buttons, 5 distinct labels), Lattice CertusPro-NX Versa / VVML, CrossLink-NX Evn / VIP.

---

## 2. Verified current state (evidence map)

| Fact | Locator |
|---|---|
| `Button` is momentary; `pressed: bool`; `handle_release()` takes **no identity** | `src/fpga_sim/ui/components.py:519-556` |
| `Switch` is a toggle; `handle_click(pos)` flips `state` | `src/fpga_sim/ui/components.py:484-516` |
| Mouse-down hit-tests every switch then every button; mouse-up releases **all** buttons | `src/fpga_sim/ui/board_display.py:717-724` |
| Chrome-button hits `return` out of the whole event loop, dropping the rest of the frame's events | `board_display.py:672,677,691,699,705,715` |
| `R` resets switches off + releases all buttons | `board_display.py:651-658` |
| `_send_input()` sends a **full-state** message; fired once per callback | `simulation_screen.py:201-224` |
| `visual_signature()` (drives the U23 redraw-skip) hashes `btn.pressed`, `sw.state`, sizes | `board_display.py:764-784`; consumed at `simulation_screen.py:502-509` |
| Child drains **all** pending messages with no `await` between them | `sim/sim_testbench.py:300-307` |
| `await Timer(...)` is at the **top** of the loop, *before* the drain | `sim/sim_testbench.py:281` |
| Help modal runs its own `event.get()` loop handling only QUIT/RESIZE/KEYDOWN/MOUSEBUTTONDOWN — **KEYUP and MOUSEBUTTONUP are discarded** | `src/fpga_sim/ui/help_dialog.py:104-126`; same shape in `settings_dialog.py:197-213` |
| `SHORTCUTS` is the single source of truth for the help legend ("Add new keys here") | `src/fpga_sim/ui/help_dialog.py:42-54` |
| `sim/capture_frames.py` **assigns** `board.buttons[idx].pressed = True/False` | `sim/capture_frames.py:222,228` |
| Tests assign `.pressed` directly too | `tests/test_board_display_events.py:127,136,170`; `tests/test_simulation_screen.py:374` |
| Chrome rects stay `None` in sim mode (`_draw` early-returns when `_show_footer` is False) | `board_display.py:863-867` |
| Preview and sim build **two separate** `FPGABoard`s; preview input state is discarded | `controller.py:349` vs `simulation_screen.py:138` |
| Keys taken in-sim: `Esc` `F1`/`?` `R` `S` `D`; **`P` reserved** by roadmap card U14 | `simulation_screen.py:434,440,444`; `board_display.py:642,646,651`; `improvement_roadmap.md:128` |

### 2.1 pygame facts, measured on this machine (pygame 2.6.1, SDL 2.28.4, upstream not -ce)

| Probe | Result | Consequence |
|---|---|---|
| `pygame.key.set_repeat` called anywhere? | **Never** | No auto-repeat. A held key yields exactly one KEYDOWN — which is what a held button needs. Do not enable it. |
| `KSCAN_1..KSCAN_0`, `KSCAN_KP_1..KSCAN_KP_0` | 30–39, 89–98 | Layout-independent physical positions exist and are usable. |
| `type(get_pressed()).__getitem__ is tuple.__getitem__` | **False** | `get_pressed()` re-maps every index through `SDL_GetScancodeFromKey`. `ks[KSCAN_1]` silently returns `False` forever. **Polling cannot back up event tracking.** |
| `pygame.key.get_focused()` under `SDL_VIDEODRIVER=dummy` | **False** | Unusable — the whole `headless_pygame` suite (`tests/conftest.py:48-71`) runs under dummy. Never gate a hold on it. Use the `WINDOWFOCUSLOST` event (32786), which tests can post. |
| `Event(KEYUP, {"key":…, "mod":0})` has `.scancode`? | **False** | Synthetic test events are sparse. Read `getattr(ev, "scancode", None)` and fall back — exactly the trap the repo already records for `.unicode` at `improvement_roadmap.md:142`. |
| `KMOD_CTRL` = 192, `KMOD_SHIFT` = 3, `KMOD_MODE` = 16384 | — | AltGr synthesizes `LCTRL+RALT` on Windows/X11 — see Decision C. |

### 2.2 The fleet (measured over all 285 boards via `discover_boards('boards')`)

| Measure | Value |
|---|---|
| Max buttons | **13** — four ULX3S variants |
| Max switches | **18** — DE2-115, VEEK-MT2 |
| Worst combined | **27** — Sword (11 btn + 16 sw); then Nexys4 DDR and DE2-115 at 22 |
| Boards with >10 buttons | **6** of 285 |
| Boards with >10 switches | **14** of 285 |
| Boards with **duplicate** button labels | **5** — Sword, Lattice CertusPro-NX Versa/VVML, CrossLink-NX Evn/VIP |

The ceiling is low and fixed by upstream board data. A 10-key map covers 279 of 285 boards; a
13-key map covers all 285.

---

## 3. Architecture — the hold-source model

### 3.1 The one idea

A button is not "pressed or not." A button is **held by a set of sources**, and it is down whenever
that set is non-empty.

```python
class Button(UIComponent):
    _holds: set[str]  # e.g. {"mouse:1", "key:30", "latch"}

    @property
    def pressed(self) -> bool:
        return bool(self._holds)

    @pressed.setter  # back-compat ONLY; state-only, fires nothing
    def pressed(self, value: bool) -> None:
        if value:
            self._holds.add("direct")
        else:
            self._holds.clear()
```

Every requested capability falls out of this and nothing else:

- **Multi-hold** — independent sets per button.
- **Arbitrary release order** — removing one source never touches another.
- **Sticky** — `"latch"` is a source nothing but an explicit release (or `R`) removes.
- **Sticky + live together** — a latched `BTN0` and a mouse-held `BTN1` are unrelated state.
- **Keyboard hold** — `"key:<scancode>"` added on KEYDOWN, removed on KEYUP.
- **Mouse and keyboard on the same button** — hold `1`, also click it, release the mouse: still
  down, because `"key:30"` remains. This is the case a `pressed` boolean gets wrong.

Per-source tokens are load-bearing, not fussiness: **`KSCAN_1` and `KSCAN_KP_1` both map to button 1**,
so a user can hold one button with two keys, and releasing one must not release the button.

Three invariants the implementation must hold:

1. **The setter is silent.** It mutates state and fires nothing. `tests/test_simulation_screen.py:374`
   assigns `.pressed` on a screen whose callbacks are already wired (`simulation_screen.py:196-197`);
   a firing setter would emit a stray `input` message mid-assertion. `sim/capture_frames.py:222,228`
   drives `dut.btn` itself and would double-drive. `handle_press`/`handle_release` own the callback,
   exactly as today.
2. **Callbacks fire on `pressed` edges, not on set mutation.** Clearing a button that holds
   `{"mouse:1", "latch"}` must fire **one** callback. Otherwise
   `tests/test_board_display_events.py:133-143` (`assert fired == [(1, False)]`) breaks and
   `_send_input` duplicates messages. Pattern: mutate, compare `bool(before)` vs `bool(after)`, fire
   once on change.
3. **Everything is keyed by widget index, never by rect or position.** `_resize()`
   (`board_display.py:388-392`) and `set_height_offset()` (`:329-343`) both call `_layout()`, which
   reassigns every `rect`. Index-keyed holds survive a mid-gesture resize; anything positional does not.

`FPGABoard` owns two registries: `_mouse_holds: dict[int, int]` (mouse button number → widget index)
and `_key_holds: dict[int, tuple[str, int]]` (scancode → (kind, index)).

### 3.2 Why the key-hold registry must record its target

The KEYUP binding is **not** recomputed — it is looked up. SDL reports modifier state *at event time*,
and releasing a modifier before the key is the normal way people let go of a chord. If `Shift+5`
means "button 15" and the user releases Shift first, the KEYUP for `5` arrives with `mod == 0`,
resolves to "button 5", clears a hold that was never taken, and **leaks the button-15 hold forever.**

Rule: KEYDOWN resolves a target once and records it under the scancode; KEYUP pops the recorded
target and acts on that. This makes any modifier tier safe — and it is why the modifier tiers in
Decisions B and C are *implementable*, though [§5](#5-decisions-to-make-open--settle-these-first)
argues they may still not be *desirable*.

### 3.3 Input atomicity — one message per frame

Replace per-callback `send()` with a dirty flag flushed once per frame, after `_pump_events()`.

The precise reason matters, because it is **not** the obvious one. Within a single child drain,
per-callback sends are already equivalent to one coalesced send: `sim/sim_testbench.py:300-307` has
no `await` inside the drain loop, so N assignments to `dut.btn` produce exactly one simulator write
of the last value — the intermediate values never exist. Coalescing changes nothing *there*.

It matters at the **drain boundary**. If two of a frame's sends straddle a drain, the DUT holds a
spurious intermediate for a whole sim step — up to `_MAX_CYCLES_PER_STEP = 9_596` clock cycles
(`sim_testbench.py:73,271`), ample for any edge detector to latch a transition that never happened.
Rare, nondeterministic, and miserable to debug in a teaching tool.

**This already bites today.** `R` on a DE2-115 fires one callback per changed widget
(`board_display.py:651-658`), and each callback sends: **18 full-state messages in one frame**. A
straddle exposes a half-reset switch vector.

So coalescing is a latent-bug fix and a simplification — one flush at a known point replaces a send
per callback, and message volume drops ~18× on reset. It is *less* code, not more. Keep the
per-callback console `print` as-is (per-edge logging is useful).

### 3.4 Where each capability comes from

| Capability | Delivered by | Simultaneity on the wire |
|---|---|---|
| Hold several buttons, release in any order | keyboard holds **or** latching | — |
| Press two buttons at the *same instant* | keyboard chord (both KEYDOWNs in one frame batch → one coalesced message) | **exact** |
| Hold a button indefinitely, hands free | latch | — |
| Latched + live hold together | independent hold sources | — |
| Set a 16-switch pattern fast | drag-paint (Decision C) | one message per motion frame |
| Latch two buttons | two gestures → two messages, one frame apart | overlapping, staggered ~16 ms |

The last row is the only staggered case, and it is faithful: on real hardware two fingers never land
in the same clock cycle either, which is why designs debounce/synchronize. A user who needs a truly
atomic multi-press uses the keyboard chord. This is why arm-and-fire staging is **cut** — see §3.5.

### 3.5 Why not the alternatives (do not relitigate)

Rick supplied a Gemini-generated catalog of multi-press UX patterns. Each was evaluated; verdicts:

| Pattern (from the catalog) | Verdict |
|---|---|
| **Keyboard chording / N-key rollover** | **Adopted.** The only input device that expresses true simultaneity. Core of Phase 4. |
| **Software latches (staging)** | **Adopted in part** — latching yes, *staging* no. See next row. |
| **Arm-and-Trigger (two-phase execute)** | **Cut.** Latching already yields "several buttons down at once," and frame-coalescing already makes each change atomic. Staging would add a third visual state, a third `visual_signature` entry, and a mode — for a capability we already have. Parked as **P33** with a trigger. |
| **Modifier-key multi-select (Shift/Ctrl+click)** | **Cut as a *selection* model.** Selecting-then-acting is a document metaphor, not a hardware one; a board has no selection. Shift+click survives only as a candidate *latch gesture* (Decision A option 3). |
| **Paint / drag selection (lasso)** | **Adopted for switches** (Decision C). Sweeping a pen across a DIP bank is a real hardware gesture, and setting a 16-bit pattern is the actual pain point. |
| **Marquee / bounding-box selection** | **Cut.** Same selection-model objection, plus board widgets are laid out in adaptive grids, so a rectangle rarely means anything. |
| **Mouse button chording (L+R together)** | **Cut as a chord**; right-click is used as a *distinct gesture* instead (Decision A). Simultaneous L+R is undiscoverable and conflicts with OS-level gestures. |
| **Hover + key combination** | **Cut, superseded.** "Point at A, press key for B" is strictly worse than "press key for A and key for B," which the keymap gives directly. |
| **Multi-finger touchpad gestures** | **Cut.** A touchpad reports fingers, not positions-over-widgets; there is no sensible mapping. |
| **Spatial multi-tap (touchscreen)** | **Deferred to P32**, trigger: a user runs on a touchscreen. `FINGERDOWN`/`FINGERUP` would be the truest analog to fingers on a board, but it cannot be tested without hardware. |
| **Master / gang switches, Link mode** | **Cut.** Real boards have no gang switch; inventing one teaches the wrong mental model. |
| **Preset / macro buttons** | **Cut from this arc**, but see **P31** (input record/replay), which is the principled version and has an independent driver. |
| **Time-window grouping (<150 ms)** | **Cut as a heuristic, adopted as a frame boundary.** A guessed threshold silently merges unrelated actions. Coalescing per *frame* is the same benefit with a defined, honest boundary (§3.3). |

Two more, not in the catalog:

- **A global "sticky mode" toggle** — see Decision A; the objection is that the Settings dialog is
  unreachable from a running sim (`board_display.py:675-677` is preview-only chrome).
- **`pygame.key.get_pressed()` polling instead of event tracking** — impossible, see §2.1.

---

## 4. The swallowed-tap bug (Decision D)

Discovered while verifying §3.3. Independent of this feature, but this feature makes it worse.

Per iteration, `sim/sim_testbench.py` does: `await Timer(sim_step_ns)` → read outputs → **drain and
apply all pending input** → send state → pace. Every drained `input` message assigns `dut.btn.value`
with **no `await` between them**, so cocotb collapses them to the last value — the intermediates
never reach the simulator.

Iteration wall time is `target_s = (sim_step_ns / 1e9) / speed` where
`sim_step_ns = min(round(16_666_667 × speed), cap)` (`sim_testbench.py:70-73, 393-404`). Uncapped,
`speed` cancels: **16.667 ms, at every speed setting** — fine. But when the step hits the cycle cap
(`at_max`, `:279`) the loop is CPU-limited and one iteration can take *hundreds* of milliseconds.
That is exactly the embedded-core designs (`hdl/mx65_*.vhd`, `hdl/t80_*.vhd`) and the multi-digit
scan designs.

Then a press in frame *k* and its release in frame *k+2* land in the **same** drain, collapse to
`btn = 0`, and **the design never sees the press.** The user taps `btn(0)` to roll the dice in
`mx65_dice_7seg` and nothing happens. Sometimes.

Host-side mitigation cannot fix this: holding the press one extra 16.7 ms frame does nothing when
the drain window is 300 ms, and it would desynchronize the rendered board from what the DUT sees —
breaking the invariant `sim/capture_frames.py` and the demo assets rely on.

**The fix belongs in the child:** buffer drained `input` messages and apply **at most one per loop
iteration**, so every distinct input value gets at least one `await Timer` of exposure. Other message
kinds (`speed`/`clk`/`pause`/`stop`) keep applying immediately. Drop consecutive duplicates on push
(the host sends full state, so an unchanged state carries no edge) and hard-cap the backlog so a
burst cannot lag the design behind reality.

This turns the input stream from a *sampled level* into a *sequence of edges*, which is what a button
actually is. `input_seq` is already echoed in every `state` payload (`sim_testbench.py:382`) and the
host stores but never reads it (`simulation_screen.py:320`) — a free acknowledgement channel for
asserting "the child applied edge N".

Follow the `sim_duty.py` precedent: the queue is pure logic, so it lives in `src/fpga_sim/` as a
cocotb-free, pygame-free helper unit-tested with **no simulator installed** — exactly as
`src/fpga_sim/sim_duty.py` + `tests/test_duty.py` do.

---

## 5. Decisions to make (open — settle these first)

Each decision names its options, the evidence, and a recommendation. Phase numbering assumes the
recommendations; if a decision flips, the affected phase's scope changes but the ordering does not.

> **✅ RESOLVED 2026-08-05 (Rick): all five as recommended — A1 · B1 · C1 · D1 · E confirmed.**
> The analyses below are retained as the decision record; do not relitigate them.

---

### Decision A — how does a button latch?

All three options deliver the sticky requirement. They differ in whether there is a **mode** to track,
render, and test.

| | **A1 — right-click, modeless** | **A2 — right-click + global Sticky mode** | **A3 — Shift+click** |
|---|---|---|---|
| Gesture | Right-click toggles latch; left-click stays momentary | A1, plus an `L` hotkey + Settings row making every left-click latch | Shift+left-click toggles latch |
| Discoverability | Hover tooltip + help legend + distinct latched look | Same, plus a visible mode indicator | Same as A1 |
| Cost | 1 gesture, 1 visual state | + a mode flag, a mode indicator, a Settings row, an `L` binding, a persisted preference | 1 gesture, 1 visual state |
| Risk | Right-click is not guessable without the tooltip | A mode the user must remember they are in; **the Settings dialog is unreachable from a running sim** (`board_display.py:675-677` is preview-only chrome), so the pref could only be changed by leaving the sim | Burns the modifier that keyboard chording wants; unusable one-handed while keys are held |

**Recommendation: A1.** `event.button == 3` is entirely unhandled today (`board_display.py:668,722`
both gate on `button == 1`), so right-click is free real estate that costs nothing elsewhere. Modeless
means there is no state to render or explain, and it composes with keyboard holds without fighting
for a modifier.

The discoverability objection is real but already solved by machinery this repo has:
`Button.tooltip_extra` currently returns `[]` (`components.py:124`), and the dwell-timed hover
tooltip fires on buttons today. Adding `("Right-click", "latch / unlatch")` and a live
`("Latched", "yes")` row puts the answer exactly where a confused user is already looking, for ~5
lines. That, plus a `SHORTCUTS` row and a visibly different latched button, is a complete story.

**Pick A2 only if** accessibility for one-button / touch / limited-mobility input is a stated goal —
that is the one case a mode genuinely beats a gesture, and it would also justify wiring a gear button
into the sim screen (currently absent), which is a real scope increase.

---

### Decision B — how far does the keyboard map reach, given boards go to 13 buttons?

Rick's explicit open question. Fleet reality: max **13** buttons; only **6** of 285 boards exceed 10.

| | **B1 — hex: `0`-`9` then `A` `B` `C`** | **B2 — digits `0`-`9` only** | **B3 — `Shift`+digit for 10-19** |
|---|---|---|---|
| Coverage | **285/285 boards** (index 12 = `C`) | 279/285 | 285/285, scales to 20 |
| Idiom | Hex numbering — native to a digital-logic tool | Plain | Arbitrary |
| Key conflicts | None. `D` (duty bars) is index 13, which no board has | None | None |
| Release-order risk | None (no modifiers) | None | **Yes** — re-opens the §3.2 leak class; mitigated by the recorded-target registry, but it is one more thing to get right |
| Layout risk | `A`/`B`/`C` are relabeled on AZERTY (physical `A` is labeled `Q`), so a scancode binding's badge would mislead those users; the digit row is labeled identically on every Latin layout | None | `Shift+0` = button 10 is not memorable |
| Failure mode | A future 14-button board would want `D`, which is taken | 6 boards keep mouse+latch only | — |

**Recommendation: B1**, with the letter tier bound by **character** (`ev.unicode`) rather than
scancode so the badge always matches the user's physical keycap, while the digit tier stays
scancode-bound. Hex is the right idiom here and it covers the fleet exactly.

**B2 is a perfectly defensible smaller answer** — it drops one binding tier and one layout caveat,
and it costs coverage on 6 niche boards (Sword, 4× ULX3S, 2× Lattice EVN) that are not the teaching
boards this tool is aimed at. If the `A`/`B`/`C` layout asymmetry feels like a wart, take B2 and say
so in the help legend.

Reject **B3**: it buys headroom no board needs, at the cost of re-opening the modifier-release bug class.

---

### Decision C — how do users set many switches?

Switches already latch — they are toggles. The gap is not *holding* them, it is **setting 16 of them
quickly**. This reframing is why drag-paint leads and a keymap does not.

| | **C1 — drag-paint only** | **C2 — drag-paint + `Shift`+digit toggles** | **C3 — drag-paint + `Ctrl`+digit tiers** |
|---|---|---|---|
| Gesture | Press and sweep across a switch row; each switch the cursor *enters* toggles once | C1 + `Shift`+`0`-`9` toggle switches 0-9 | C1 + `Ctrl`+digit (0-9) and `Ctrl+Shift`+digit (10-17) |
| Coverage | All 18, in one gesture | All 18 by mouse; 10 by key | All 18 by key |
| Release-order risk | None | **None** — a toggle acts on key-*down* only, so there is no hold to leak | None, same reason |
| Modifier risk | None | Interacts with Decision B: on AZERTY, `Shift`+physical-`1` *produces* the character `1`, so a unicode fallback for buttons and a Shift tier for switches become ambiguous. Resolve by preferring the modifier-qualified reading | **AltGr synthesizes `LCTRL+RALT`** on Windows/X11, so AltGr+digit trips switch bindings for German/French/Polish/Czech users. Requires guarding `KMOD_ALT` *and* `KMOD_MODE` (16384) |
| Cost | One MOUSEMOTION branch (there is none today) | + one binding tier | + two binding tiers + three modifier guards |

**Recommendation: C1.** A sweep sets a 16-bit pattern in one gesture with zero modifier surface and
nothing to memorize, and it mirrors running a pen across a real DIP bank. The keyboard's unique value
is *simultaneity*, which toggles do not need.

**C2 is a reasonable add** if "the keyboard can drive the whole board" is worth a tier — it is genuinely
safe (no hold to leak) and cheap once the digit machinery exists. Note it leaves switches 10-17
keyless anyway, so it does not complete the story it promises.

Reject **C3**: the AltGr collision is a real bug for real users, and the repo already ships Czech
documentation (`docs/virtual-fpga-boards-cs.adoc`), so non-US layouts are not hypothetical here.

---

### Decision D — fix the swallowed-tap bug in this arc?

Full analysis in [§4](#4-the-swallowed-tap-bug-decision-d). Pre-existing, independent of this feature,
made more prominent by it.

| | **D1 — fix it in this arc** | **D2 — file it separately** |
|---|---|---|
| Scope | One extra phase: a bounded input queue in `src/fpga_sim/`, applied one-per-iteration in `sim/sim_testbench.py` | Arc stays UI-only |
| Size | M — pure-Python core, unit-testable with no simulator (model: `sim_duty.py` + `tests/test_duty.py`), plus one cocotb assertion | — |
| Argument for | Keyboard taps are faster than mouse clicks, so this arc increases the bug's exposure. Shipping "your button presses now work" alongside "…except sometimes on embedded-core designs" is a bad release note | Keeps the arc tight; the bug is rare on fast designs |
| Risk of deferring | The symptom ("sometimes my button does nothing") will be reported *against this feature*, since it is the feature that invited fast tapping | — |

**Recommendation: D1.** It is a genuine correctness fix in the layer this arc is already reasoning
about, it is independently testable without a simulator, and deferring it means the arc's headline
capability has a known intermittent failure on the designs most likely to showcase it.

If deferred: file it as its own issue immediately (not an Icebox card — it is a confirmed bug, not a
speculative improvement) and add a known-issues line to the user guide.

---

### Decision E — confirmations (settled by Rick's framing; flag only if wrong)

These follow directly from the original request and are recorded so review can veto them explicitly.

1. **Digit `d` presses the button at *index* `d`.** Key `1` → `BTN1`, exactly as written in the
   request. Consequence: key `0` is the **first** button. This is consistent with the 0-based labels
   the board already draws, with `ComponentInfo.number`, and with the `btn(0)` VHDL contract used
   throughout `hdl/` and the docs. The alternative (positional: `1` → first button) would bake a
   permanent off-by-one against documented designs like `hdl/stopwatch_7seg.vhd` (`btn(0)` start/stop,
   `btn(1)` reset).
2. **Keys bind by physical position (scancode), with a `unicode` fallback**, and the resolved target
   is recorded at key-down and popped at key-up (§3.2). Without scancodes, AZERTY and Czech layouts —
   where the digit row is *shifted* — lose the binding entirely. The numpad comes free
   (`KSCAN_KP_1..KP_0` are NumLock-independent), and a numpad is the closest thing a user has to a
   physical button pad.
3. **Left-click behavior is unchanged.** Press-and-hold is still momentary. Everything here is additive.
4. **Latches survive modals and pauses; `R` clears everything** (mouse, key, and latch holds). `R` is
   the documented escape hatch (`help_dialog.py:51`); leaving latches set would make the only way out
   not work.
5. **Keyboard and latching work in the preview screen too**, for free — both screens share
   `FPGABoard._handle_events`. Preview already fires print-only callbacks. (Note the pre-existing wart
   in §8: preview input state is discarded when the sim starts.)

---

## 6. Phases

Five phases assuming the recommendations (A1 / B1 / C1 / D1). One PR each, branched off post-merge
`main`, with a CHANGELOG entry.

### Phase 1 — hold-source model + mouse identity (M) — invisible refactor

**Do:**

1. `Button._holds: set[str]`; `pressed` becomes a property with a **silent** setter (§3.1 invariant 1);
   `handle_release(source: str | None = None)` (None = clear all sources). Callbacks fire on `pressed`
   edges only (invariant 2).
2. `FPGABoard._mouse_holds: dict[int, int]` (mouse button → widget index). Rewrite
   `board_display.py:722-724` to release only the hold registered for *that* mouse button.
3. Convert the six chrome `return`s (`board_display.py:672,677,691,699,705,715`) to `continue` so a
   chrome click stops dropping the rest of the frame's events. Preview-only today, but it becomes a
   stuck-hold path once KEYUPs matter.
4. `R` (`:651-658`) clears all sources with exactly one callback per changed button.
5. `FPGABoard.release_transient_holds()` — clears mouse + key holds, keeps latches, fires per edge.
   Not yet called; Phase 4 wires it up.

**Verify:** the entire existing suite passes untouched — especially
`tests/test_board_display_events.py:124-174`, `tests/test_simulation_screen.py:358-376`,
`tests/test_ui_component_base.py:62-65`. Run the frame-capture path to confirm
`sim/capture_frames.py:222,228` still renders.

**Quality gates:** zero user-visible behavior change **except** drag-off-then-release (mouse-down on
BTN0, drag onto BTN1, release → BTN0 releases, BTN1 was never pressed) — document it; it is both the
standard UI convention and what real hardware does. `pressed` keeps its `bool` annotation; `mypy` clean.

### Phase 2 — input atomicity (M with D1, S with D2)

**Do:**

1. Host: replace per-callback `_send_input()` (`simulation_screen.py:214-224`) with an `_input_dirty`
   flag flushed once per frame in `run()`, after `_pump_events()`. Keep the per-edge console prints.
2. *(Decision D1 only)* New `src/fpga_sim/sim_input.py` — a bounded, cocotb-free, pygame-free input
   queue: push drops consecutive duplicate states, pop returns at most one per call, a hard cap
   collapses the oldest entries. Model the module shape and test style on `src/fpga_sim/sim_duty.py`.
3. *(D1 only)* `sim/sim_testbench.py:300-307` — `input` messages push onto the queue; **one** is
   applied per loop iteration; all other kinds apply immediately as today.

**Verify:** unit-test the queue with **no simulator installed**. Assert `R` on an 18-switch board emits
exactly **one** `input` message (today: 18). One cocotb test proving a press+release arriving in the
same drain is still observed by the DUT.

**Quality gates:** `uv run fpga-sim --benchmark` shows no sim-rate regression outside noise (baselines:
`docs/u25_ghdl_perf_profile.md` — never compare against debug-era tables). New `sim/` files, if any,
added to `[tool.ruff.lint.per-file-ignores]` per `pyproject.toml:96-113`.

### Phase 3 — latching (M)

**Do:**

1. Right-click (`event.button == 3`, currently unhandled) toggles a `"latch"` hold on the button
   under the cursor. Ensure the button-1 mouse-up path clears only button-1 mouse holds — a left
   release must never wipe latches.
2. **Chrome z-order fix:** `simulation_screen._pump_events()` calls `board._handle_events(events)` at
   `:437` *before* its own chrome hit-testing at `:439-460`, so a click on `[Stop]` / `[PAUSE]` /
   toolbar also hits any board widget underneath. Harmless today; with right-click latching it would
   latch a hidden button. Filter chrome-rect hits out of the event list before passing it down.
3. Latched buttons draw distinctly — held **and** locked. Add a `push_latched` theme role to
   `ui/theme.py` (`:66-69`) **and** its high-contrast override (`:320-323`).
4. **Add the latch state to `visual_signature()`** (`board_display.py:764-784`). Without this:
   mouse-hold BTN0 → right-click to latch → release the mouse; `pressed` stays `True` throughout, the
   signature never changes, the U23 redraw-skip fires, and the board shows the wrong style forever.
5. `Button.tooltip_extra` / `Switch.tooltip_extra` (currently `[]`, `components.py:124`) gain live
   rows — the latch gesture hint and current latch state. This is the discoverability mechanism.
6. `SHORTCUTS` row (`help_dialog.py:42-54`) + `docs/user_guide.md` preview and in-sim control lists.

**Verify:** latch + live hold coexist; latch survives mouse-up, modal open, and pause; `R` clears it;
the mouse-held → latched transition repaints (a test that fails without step 4).

**Quality gates:** UI/render PR → PNGs for Rick's visual review before merge (per
`feedback_ui_pr_visual_review`). Latched, held, and idle must be distinguishable in **both** themes.

### Phase 4 — keyboard holds (L)

**Do:**

1. Scancode map: `KSCAN_1..KSCAN_9, KSCAN_0` and `KSCAN_KP_1..KSCAN_KP_0` → button indices 0-9;
   *(B1)* `A`/`B`/`C` by `ev.unicode` → indices 10/11/12. Resolve at KEYDOWN, record under
   `getattr(ev, "scancode", None) or ev.key`, pop at KEYUP (§3.2).
2. Wire `release_transient_holds()` (built in Phase 1) to `pygame.WINDOWFOCUSLOST` **and** to every
   blocking-modal entry — `simulation_screen.py:471` (`_run_help_modal`) and the preview's dialog
   launches in `board_display.run()`. The help modal's own loop discards KEYUP entirely
   (`help_dialog.py:104-126`), so without this, F1 while holding `1` strands `BTN1` down — and
   `_run_help_modal` then *unpauses* the child, so the design runs on with a phantom button.
3. Key badges rendered on bound buttons — **mandatory**, not polish (§1.1): on 5 boards the labels are
   duplicated, so the badge is the only thing that identifies which key drives which button. Skip the
   badge when the rect is too small to render it legibly.
4. `SHORTCUTS` rows + `docs/user_guide.md`. State the >10-button rule explicitly.

**Verify:** two keys held → both bits set in **one** message; release in reverse order → correct
intermediate states; KEYUP after the modifier was already released still releases the right button;
`WINDOWFOCUSLOST` clears key holds but not latches; F1 mid-hold then release inside the modal leaves
nothing held; a KEYUP with no `.scancode` attribute (synthetic test events) still works.

**Quality gates:** no `pygame.key.get_focused()` and no `pygame.key.get_pressed()` anywhere — both are
unusable here (§2.1). No `set_repeat`. PNGs showing badges on a small-rect board (13-button ULX3S) and
a duplicate-label board (Sword).

### Phase 5 — drag-paint switches (S)

**Do:** a MOUSEMOTION branch in `board_display._handle_events` (there is none today) with a per-drag
`set[int]` of already-toggled **indices**, cleared on mouse-up. *(Decision C2 only: `Shift`+digit
switch toggles.)*

**Verify:** sweeping across 4 switches toggles each exactly once; re-entering a switch mid-drag does
not re-toggle; a `WINDOWRESIZED` mid-drag does not corrupt the set (§3.1 invariant 3); one coalesced
message per motion frame.

**Quality gates:** single-click switch behavior byte-identical. PNGs of a 16-switch board mid-sweep.

---

## 7. Test strategy

Three classes, all following existing repo patterns. `headless_pygame` (`tests/conftest.py:48-71`) is
session-scoped under `SDL_VIDEODRIVER=dummy`; **no test may depend on `get_focused()` or
`get_pressed()`** — post `WINDOWFOCUSLOST` explicitly instead.

**Widget unit tests** — extend `tests/test_ui_component_base.py` (defaults block at `:62-65`):
`test_button_pressed_setter_is_state_only`, `test_button_multiple_hold_sources`,
`test_button_callback_fires_once_per_edge`, `test_button_release_unknown_source_is_noop`.

**Event-injection tests** — extend `tests/test_board_display_events.py` (direct
`board._handle_events([ev])` pattern): two buttons held with reverse-order release; mouse-up releases
only the pressed button; drag-off-then-release; digit KEYDOWN/KEYUP; numpad scancode;
**KEYUP after the modifier was released** (the §3.2 regression); missing-`scancode` fallback (mirrors
the existing `test_r_key_without_unicode_does_not_crash` at `:197-203`); `WINDOWFOCUSLOST` clears key
holds; `release_transient_holds` keeps latches; right-click latches and left mouse-up does not clear
it; `R` clears latches with one callback each; **chrome click does not drop later events in the same
batch**; drag-paint toggles each switch once; resize mid-drag preserves holds; badges only on bound
indices (13-button ULX3S fixture); index mapping survives duplicate labels (Sword-shaped fixture).

**Screen/IPC tests** — extend `tests/test_simulation_screen.py` (`pygame.event.post` + `_pump_events`,
`_collect(client, n)` at `:85-92`): two KEYDOWNs in one frame send **one** message carrying both bits;
`R` on a many-switch board sends exactly one message (not 18); help modal mid-hold leaves nothing
pressed; **redraw happens on a latch toggle while held** (the §Phase-3-step-4 regression, sits beside
`test_render_redraws_on_switch_and_button_change` at `:358-376`).

**Queue tests** *(D1 only)* — new `tests/test_sim_input.py`, modeled on `tests/test_duty.py` (pure, no
simulator): one input applied per step; a press/release edge pair survives; consecutive duplicates
collapse; backlog cap bounds lag; non-input kinds bypass the queue.

**Legend anti-drift** — `tests/test_help_dialog.py` already enforces `SHORTCUTS` well-formedness
(`:114`); add coverage that the digit keys and the latch gesture are listed.

---

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Held key stranded when a modifier is released first | Record the resolved target at KEYDOWN; pop it at KEYUP. Never re-resolve modifiers (§3.2). Regression test. |
| Held key stranded by a blocking modal (which discards KEYUP) | `release_transient_holds()` on every modal entry (Phase 4 step 2). |
| Held key stranded by focus loss / Alt-Tab | Handle `pygame.WINDOWFOCUSLOST` (32786). **Not** `get_focused()` — it is `False` under the test driver. |
| Held key stranded by the chrome `return` dropping a KEYUP | Convert to `continue` (Phase 1 step 3). |
| Latched button not repainted (U23 redraw-skip) | Latch state enters `visual_signature()`; a test that fails without it. |
| `pressed` setter breaks `capture_frames.py` / existing tests | Setter is silent and state-only; run the frame-capture path in Phase 1 Verify. |
| Keymap dead on non-US layouts | Bind by scancode with a `unicode` fallback; digit-row positions are labeled identically on every Latin layout. |
| Synthetic test events lack `.scancode` | `getattr(ev, "scancode", None)` fallback — the repo already records this trap class for `.unicode` (`improvement_roadmap.md:142`). |
| Right-click latches a button hidden under sim chrome | Filter chrome-rect hits before `board._handle_events` (Phase 3 step 2). |
| Input queue lags the design behind the user | Drop consecutive duplicates on push; hard-cap the backlog. |
| Latch gesture undiscoverable | Hover tooltip rows + `SHORTCUTS` + a visibly distinct latched style. Revisit if Decision A picks A1 and review still finds it opaque. |
| Help legend drifts from the real handlers | All keys registered in the single `SHORTCUTS` table (`help_dialog.py:42-54`); `tests/test_help_dialog.py` enforces it. |

---

## 9. Sizing, ledger, and follow-on cards

| Phase | Scope | Size | PR | Status |
|---|---|---|---|---|
| 0 | Commit this plan as `docs/u44_multi_input_plan_v1.md` (docs-only) | XS | — | ✅ done |
| 0b | **Resolve the five decisions in §5**; revise this doc accordingly | XS | — | ✅ done 2026-08-05 (A1 · B1 · C1 · D1 · E confirmed) |
| 1 | Hold-source model + mouse identity + chrome `continue` | M | — | not started |
| 2 | Input atomicity (+ child input queue if D1) | M | — | not started |
| 3 | Latching + visual + tooltip discoverability | M | — | not started |
| 4 | Keyboard holds + badges + hold-clearing | L | — | not started |
| 5 | Drag-paint switches | S | — | not started |

Never predict PR numbers in docs (house rule); fill the column in as each merges.

| ID | Scope | Trigger |
|---|---|---|
| **U45** | Carry preview switch/latch state into the sim run. Preview and sim build two separate `FPGABoard`s (`controller.py:349` vs `simulation_screen.py:138`), so preview input is silently discarded at sim start. A pre-existing wart that latching makes markedly more surprising ("I latched reset, hit Start, nothing was latched"). | Ships with this arc or immediately after; alternatively document the behavior in the user guide. |
| **P31** | Input record/replay over `sim_link`. The frame-coalesced flush plus the existing monotonic `seq` is exactly the tap point. | `docs/docs_assets_improvement_plan_v2.md` PR 2 / issue #129 needs scripted input for GIF capture — same machinery. |
| **P32** | Multi-touch (`FINGERDOWN`/`FINGERUP`) — the truest analog to fingers on a board. | A user runs the simulator on a touchscreen. Cannot be tested without hardware. |
| **P33** | Arm-and-fire staging (arm several buttons, commit atomically). | A user hits the transient-combination hazard: a combo where pressing A alone before A+B triggers unwanted behavior, and the keyboard chord is not available to them. |

---

## 10. Cross-cutting quality gates (every phase PR)

`uv run ruff check` + `uv run ruff format --check` + `uv run mypy .` + `uv run pytest` locally before
every commit (use `set -o pipefail` when piping to `tail` — a `pytest | tail && commit` gates on
`tail`'s exit, not pytest's). CHANGELOG entry per PR. Never predict PR numbers in docs. Before each PR
explicitly consider doc updates and test additions. US spelling everywhere. Feature branch per phase;
never commit to `main`. **UI/render PRs: PNGs for Rick's visual review before merge.** Every new key
registered in `SHORTCUTS` (`help_dialog.py:42-54`), never only in the handler.

---

## 11. Closeout checklist

- [ ] File the U44 roadmap card in `improvement_roadmap.md`; condense to a ✅ one-line stub with full
      detail moved to `roadmap_delivered.md` when complete
- [ ] File **U45** and **P31–P33** (§9) with their triggers; P31 cross-referenced from
      `docs/docs_assets_improvement_plan_v2.md`
- [ ] `CLAUDE.md`: note the hold-source model and the keymap in the UI section of the file table
- [ ] `docs/user_guide.md`: preview + in-sim control lists updated with the keymap, the latch gesture,
      and drag-paint; the >10-button rule stated
- [ ] `docs/architecture.md:129-157`: the "Board components and hover overlays" paragraph amended for
      the hold-source model
- [ ] Project memory: `project_multi_input_arc.md` + a `MEMORY.md` pointer, recording the durable
      traps (scancode/`get_pressed` lie, modal KEYUP swallowing, the drain-collapse bug)
- [ ] CHANGELOG entries per phase reconciled for the release
- [ ] Decision D2 only: the swallowed-tap bug filed as its own issue with a known-issues line in the
      user guide

---

## 12. Verification (end-to-end, after Phase 5)

```bash
uv run ruff check && uv run ruff format --check && uv run mypy . && uv run pytest

uv run fpga-sim   # NOTE: --board is benchmark-mode only (__main__.py:64-68,134-141) and
                  # matches class_name / name EXACTLY.  For interactive acceptance, launch
                  # the app and type-to-filter the board selector with the names below.
```

Interactive acceptance — the capabilities this arc exists to deliver:

**Board `Nexys4 DDR`** (class `Nexys4DDRPlatform`; 6 buttons, 16 switches) — load `hdl/blinky.vhd`:

1. Hold keys `0` and `1` together → BTN0 + BTN1 both down, delivered in **one** input message
2. Release `1`, then `0` → correct intermediate state at each release
3. Right-click BTN2 → latches; stays down hands-free
4. Hold key `3` while BTN2 is latched → both down; releasing `3` leaves BTN2 latched
5. F1 mid-hold, release the key inside the modal → on close, nothing stranded; latch survives
6. Alt-Tab away mid-hold and back → key holds cleared, latch survives
7. Sweep the mouse across SW0–SW7 → each toggles exactly once
8. Press `R` → everything clears, switches off

**Board `Sword`** (class `SwordPlatform`; 11 buttons, **three** buttons all labeled `BTN0`):

9. Badges disambiguate the duplicate-labeled buttons; keys `0`/`1`/`2` hit distinct ones
10. *(Decision B1)* keys `A`/`B`/`C` drive buttons 10/11/12

**Board `ULX3 S-85 F-`** (class `ULX3S_85F_Platform`; 13 buttons — the fleet maximum):

11. Badges stay legible at the smallest button rects the layout produces

**Decision D1 only** — the swallowed-tap fix, on a CPU-limited design. Any board works; use
`DE10-Standard` (class `DE10StandardPlatform`) and load `hdl/mx65_dice_7seg.vhd`:

12. Rapid taps of key `0` roll the die **every** time (before: intermittently ignored)

```bash
uv run fpga-sim --benchmark   # no sim-rate regression vs docs/u25_ghdl_perf_profile.md
```

**Done when:** a user can hold several buttons at once from the keyboard and release them in any
order; latch any button down hands-free and combine latched with live holds; set a 16-switch pattern
in one sweep; every simultaneous change reaches the DUT in a single atomic message; no gesture,
modal, focus change, or resize can strand a button down; the keymap is legible on every board in the
fleet including the five with duplicated labels; and — under Decision D1 — a fast tap is never
silently swallowed on a CPU-limited design.
