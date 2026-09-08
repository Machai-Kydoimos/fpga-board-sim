# Reading `manifest.json`

Every `--screenshots DIR` run writes a `manifest.json` beside the PNGs
([#388](https://github.com/Machai-Kydoimos/fpga-board-sim/issues/388)). This page is the reference
for it: what each field means, and — the part you cannot guess — what each **array index** is, on
the board and in your own VHDL.

## Why it exists

A PNG is named by *simulated* time, which makes it a waveform marker. But **a still is an interval,
not a sample.** The duty engine measures each channel's on-time over the window between two state
messages from the simulation child, and the host then eases that over ~100 ms so a fast PWM channel
reads as a steady glow rather than a strobe.

Measured over 72 (frame, LED) samples of `blinky` on an Arty, pixel brightness correlates
**r = +0.02** with the instantaneous `led` bit at the named time, and **r = +0.70** with the duty
over the preceding window. So a signal that is stable across a window reads back exactly, and one
toggling faster than the window does not — and from the picture alone you cannot tell which case
you are in. The manifest states it.

## Top level

| Field | What it is |
|---|---|
| `board` · `design` | The board's display name and the design's filename |
| `run` | How the design was matched — **this decides what `channels.led[].vhdl` means** (see below) |
| `how_to_read` | One paragraph, so the file explains itself; its wording changes when a run measured no duty |
| `waveform` | `dump`, `gtkw` and `timescale_fs` — **absent when the run captured no waveform** |
| `channels` | The legend: what every array index means |
| `shots` | One entry per PNG |

There is deliberately **no schema version field**. The legend makes the file self-describing, which
serves a reader better than an integer nothing validates.

## `run.mode` — and what `vhdl` means in each

| `mode` | `source` | `channels.led[].vhdl` is… |
|---|---|---|
| `generic` | — | `led(i)` in your file, directly |
| `board-native` | the convention slug (`terasic`, `digilent`, `sipeed`, …) | the board-native port your design declares (`LEDR(0)`, `led0_r`) |
| `pin map` | the constraint file (`test_entity.qsf`) | the port bit your file declares, bound by pin (`led_r(3)`) |

> **The polarity trap.** `active_low` is per channel and it matters. On a board wired active-low —
> Tang Nano 9K, for instance — the wrapper inverts, so the manifest can report `duty = 1.0` while
> your own signal sits at `'0'` in the trace. **Both are correct**; they are opposite sides of an
> inverter. The manifest reports *lit-ness*, not the level on the pin.

A channel with `"vhdl": null` is a board LED your design never reaches — the wrapper drives it dark.
That happens when a convention bank is narrower than the board, or a constraint file binds only some
of the LEDs.

## `channels.led` — one row per **channel**, not per LED

This is the distinction that bites. `NUM_LEDS` counts *channels*: mono LEDs occupy the low indices
in board order, then three channels — red, green, blue — per RGB site. An **Arty A7-35 has 16
channels for 8 visible components**:

```json
{ "i": 4, "label": "RGB0.r", "name": "rgb_led", "number": 0,
  "role": "r", "pins": ["G6"], "vhdl": "led0_r", "active_low": false }
```

So `led.duty[7]` is not "the eighth LED" — it is the **red channel of RGB site 1, on pin G3**.

| Field | Meaning |
|---|---|
| `i` | The index into every shot's `led.duty` / `led.level` |
| `label` | The text drawn under the widget — use it to tie a number to the picture by eye |
| `role` | `mono`, or `r` / `g` / `b` for one channel of an RGB site |
| `pins` | The pin(s) behind this channel; for an RGB channel, just that color's pin |
| `color` | The LED's cited color, when known — why two channels at equal duty look different |
| `vhdl` · `active_low` | See the table above |

A board's secondary green bank (`LEDG` on some Terasic boards) drives **no** boundary channel: the
native wrapper gives it a driver so the design elaborates, but nothing routes it to the display, so
no still can show it and it has no row here.

## `channels.seg` — a rule, not 8 × N rows

```json
{ "index": "8 * digit + segment",
  "segments": ["a", "b", "c", "d", "e", "f", "g", "dp"],
  "digits": 6,
  "digit_0": "the rightmost digit as drawn (HEX0 on Terasic boards)",
  "has_dp": true,
  "boundary_polarity": "active-high: 1.0 means the segment is lit",
  "board_note": "this board's display is wired active-low; the wrapper inverts it, …" }
```

Two facts you cannot guess, both stated outright:

- **digit 0 is the rightmost digit on screen**, matching HEX0-is-least-significant. Array index 0 is
  *not* the leftmost thing you see.
- the values are **lit-ness at the simulator boundary**, which on an active-low display is the
  inverse of the pin.

Worked decode, from a real capture of `counter_7seg.vhd` with LED PWM off (so the levels are exactly
0 or 1):

```text
digit 0 = level[0:8]   = [0, 1, 1, 0, 0, 1, 1, 0]  -> b c f g      -> "4"
digit 2 = level[16:24] = [1, 0, 0, 1, 1, 1, 1, 0]  -> a d e f g    -> "E"
```

## `shots[]`

| Field | Meaning |
|---|---|
| `file` | The PNG's filename |
| `sim_ns` | Simulated time of the state this frame was drawn from — also in the filename |
| `window_ns` | `[from, to]` the duties average over. **`null` when the run measured no duty** |
| `marker` | `sim_ns` in both viewer dialects |
| `window` | `window_ns` in both viewer dialects; absent when there is no window |
| `led` · `seg` | `duty` (measured over the window) and `level` (displayed, after easing), indexed by the legend above |

**Compare a trace over `window_ns` against `duty`.** `level` is only there to explain the pixel — it
is the same duty after the persistence-of-vision ease, which is why the two differ. On one real
frame, LED 5 measured a full 100% duty and was drawn at 92%, still easing up, while LED 6 measured
**0% and was still lit at 8%**, easing down from the window before.

### The two dialects

The viewers disagree about units, so both are written:

```json
"marker": { "time": "7292960 ns", "ticks": 7292960000000 },
"window": { "time": ["6909120 ns", "7292960 ns"], "ticks": [6909120000000, 7292960000000] }
```

`time` is what GTKWave parses, and what Surfer's own command prompt accepts. `ticks` is for Surfer's
`-C`, which parses commands *before* the waveform loads and therefore rejects units. The multiplier
comes from the dump's own `$timescale`, read rather than assumed — both backends write `1 fs` today,
but they also **gzip-wrap their FSTs**, so the header block is at offset 0 of the *decompressed*
stream. When the scale cannot be read, `ticks` is omitted rather than guessed.

### Jumping to a window

GTKWave, via a Tcl script:

```bash
jq -r --arg f shot_0005_sim7292960ns.png '.shots[] | select(.file == $f) |
  "gtkwave::setZoomRangeTimes \(.window.time[0]) \(.window.time[1])
   gtkwave::setMarker \(.marker.time)"' manifest.json > /tmp/win.tcl

gtkwave "$(jq -r .waveform.dump manifest.json)" \
        "$(jq -r .waveform.gtkw manifest.json)" -S /tmp/win.tcl
```

**Verified against GTKWave v3.3.125** (2026-09-08), by setting a marker from Tcl and reading it
back with `gtkwave::getMarker`:

| Tcl argument | `getMarker` returns (dump ticks, 1 fs each) | |
|---|---|---|
| `"1000 ns"` | `1000000000` | units parsed |
| `"1000 us"` | `1000000000000` | exactly 1000× the `ns` value — the unit is genuinely honored, not ignored |
| `"1000 ps"` | `1000000` | |
| `1000` | `1000` | **a bare number is dump ticks, not nanoseconds** |
| `"banana"` | `0` | unparseable input **silently zeroes the marker** — no error |

So `.marker.time` and `.window.time` work as written, and `.marker.ticks` / `.window.ticks` work
equally well as bare arguments. Two things to know: a bare number is *ticks*, so never pass
`.sim_ns` directly (it would land a million times too early at a 1 fs scale); and a malformed time
is not reported, it just moves the marker to 0.

`setZoomRangeTimes` accepts both dialects too, but the resulting viewport is **approximate** — it
snaps to pixel boundaries. Asking for `[6909120 ns, 7292960 ns]` gave `[6909100 ns, 7295482 ns]`.
The marker is exact; the zoom is a view.

Surfer takes SUCL commands via `-C`, separated by `;`. The dependable route is to open the dump and
type the time at Surfer's own prompt:

```bash
surfer "$(jq -r .waveform.dump manifest.json)"   # then type: 7292960 ns
```

### Useful queries

```bash
# every shot's window, as a table
jq -r '.shots[] | "\(.file)  \(.window_ns // "unmeasured")"' manifest.json

# what was LED 3 doing, measured vs displayed?
jq -r '.channels.led[3].label as $n | .shots[] |
       select(.led) | "\(.sim_ns)  \($n)  duty=\(.led.duty[3])  level=\(.led.level[3])"' manifest.json

# which channels does the design actually drive?
jq -r '.channels.led[] | select(.vhdl) | "\(.i)  \(.label)  <- \(.vhdl)"' manifest.json
```

## When LED PWM is off

Turning off **Settings → LED PWM** is not only a display preference: it drops the duty integrator
from the generated wrapper entirely, which is worth ~4.8× throughput on a six-digit board. The
manifest then reports honestly:

- `window_ns` is `null` and the `window` block is absent,
- `duty` is `[]`,
- `level` is exactly `0.0` or `1.0`, with no easing,
- `how_to_read` says so instead of describing an average that never happened.

In that mode a PNG really **is** an instantaneous sample of `sim_ns`, and the caveat this whole file
exists for does not apply.

---

See also: [CONTRIBUTING](../CONTRIBUTING.md#smoke-testing-a-board) for how to produce
captures, and the user guide's waveform-capture section for enabling a dump alongside them.
