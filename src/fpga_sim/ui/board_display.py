"""FPGABoard: the main interactive board display screen.

Renders the FPGA chip, LEDs, buttons, and switches in a resizable pygame
window.  run() returns a ``ScreenResult`` (BACK / LOAD_VHDL / SIMULATE / QUIT).

Footer buttons
--------------
* [Select Board]     — always enabled; ESC also triggers this action.
* [Load VHDL File]   — always enabled; opens the VHDL file picker.
* [Start Simulation] — greyed out until a VHDL file has been validated and
                       loaded via the [Load VHDL File] button.
* [SIM: …]          — simulator toggle: cycles the installed simulators
                       (each shown by its short label, e.g. ``SIM: GHDL-JIT``);
                       greyed when only one is installed.

The VHDL filename is shown above the buttons once a file is loaded.

The active simulator can be toggled via [SIM:…].  Read ``board.sim`` (a
:class:`~fpga_sim.sim_bridge.SimulatorInfo`) after run() returns to discover
the user's choice.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pygame

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.ui import keymap
from fpga_sim.ui.components import LED, RGBLED, Button, FPGAChip, SevenSeg, Switch, UIComponent
from fpga_sim.ui.constants import WHITE, _ui_scale, get_font
from fpga_sim.ui.help_dialog import HelpDialog, draw_help_button
from fpga_sim.ui.results import ScreenResult
from fpga_sim.ui.settings_dialog import SettingsDialog, draw_settings_button
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.tooltip import Tooltip
from fpga_sim.ui.widgets import draw_button

if TYPE_CHECKING:
    from fpga_sim.sim_bridge import SimulatorInfo

# Cursor dwell (ms) over a component before its hover tooltip appears.
HOVER_TOOLTIP_MS = 400


def _mouse_source(button: int) -> str:
    """Hold-source token for a mouse button (U44), e.g. ``"mouse:1"``."""
    return f"mouse:{button}"


def _key_source(token: str) -> str:
    """Hold-source token for a bound key (U44), e.g. ``"key:s30"``.

    Per-key tokens are load-bearing: ``KSCAN_1`` and ``KSCAN_KP_1`` both press
    button 0, so a user can hold one button with two keys, and releasing one
    must not release the button.
    """
    return f"key:{token}"


@dataclass(frozen=True)
class BoardInputs:
    """A board's user-set input state, carried between boards for one board choice (U45).

    The preview screen and the simulation build **separate** ``FPGABoard``
    objects, and the preview's is rebuilt on every re-entry, so without this a
    switch flipped or a button latched before pressing Start is silently
    discarded.  U44 made that markedly more surprising: latching is now a
    deliberate, visible, sticky act, so "I latched reset, hit Start, and
    nothing was latched" reads as a bug rather than as a screen boundary.

    Live **mouse and key holds are deliberately absent**.  They belong to a
    gesture that is over by the time this is carried anywhere — the hand is off
    the mouse — and only the latch is state the user meant to leave behind.

    In-memory for the session's screen flow only: this is never persisted, so
    a relaunched app opens with the board as the design left it, not as the
    last session did.
    """

    switches: tuple[bool, ...] = ()
    latched: AbstractSet[int] = frozenset()

    def __post_init__(self) -> None:
        """Normalize *latched* to a frozenset, so the value stays hashable.

        Callers name the latched indices however is natural at the call site
        (``{0, 2}`` reads better than ``frozenset({0, 2})``); the stored value
        is always immutable, which is what ``frozen=True`` promises.
        """
        if not isinstance(self.latched, frozenset):
            object.__setattr__(self, "latched", frozenset(self.latched))

    def __bool__(self) -> bool:
        """Report whether anything is set — an all-off board carries nothing."""
        return any(self.switches) or bool(self.latched)


class _Positionable(Protocol):
    """Structural type for board widgets `_place_items` can lay out (assigns `.rect`)."""

    rect: pygame.Rect


class FPGABoard:
    """Pygame window that renders an FPGA-style board.

    Parameters
    ----------
    board_def    : BoardDef or None
        If given, components are built from the board's resource list.
    num_switches, num_buttons, num_leds : int
        Fallback counts when no BoardDef is provided.
    width, height: int
        Initial window size (resizable).
    sim : SimulatorInfo or None
        Currently selected simulator install (engine + backend + label).
    available_sims : list[SimulatorInfo] or None
        Simulators that are installed.  If the list has more than one entry the
        footer shows a toggle button that cycles them by label.
    vhdl_path : str or Path or None
        Currently loaded VHDL file.  When set the filename is shown in the
        footer and [Start Simulation] is enabled.

    """

    def __init__(  # noqa: PLR0913
        self,
        board_def: BoardDef | None = None,
        *,
        screen: pygame.Surface | None = None,
        num_switches: int = 8,
        num_buttons: int = 4,
        num_leds: int = 16,
        width: int = 0,
        height: int = 0,
        sim: SimulatorInfo | None = None,
        available_sims: list[SimulatorInfo] | None = None,
        height_offset: int = 0,
        vhdl_path: str | Path | None = None,
        show_footer: bool = True,
        reserve_footer_space: bool | None = None,
    ) -> None:
        """Initialize the board display with components laid out from board_def.

        Parameters
        ----------
        board_def:
            Parsed board definition supplying LED, button, and switch counts.
            When ``None`` the *num_leds*, *num_buttons*, and *num_switches*
            fallback counts are used instead.
        screen:
            Existing pygame surface to draw on.  When ``None`` a new resizable
            window is created using *width* × *height*.
        num_switches:
            Switch count used when *board_def* is ``None``.
        num_buttons:
            Button count used when *board_def* is ``None``.
        num_leds:
            LED count used when *board_def* is ``None``.
        width, height:
            Initial window size.  When ``0`` (the default) and *screen* is
            provided the surface dimensions are used; without a screen the
            fallback 1024 × 700 is used.
        sim:
            The active simulator install (a ``SimulatorInfo``), or ``None`` when
            the toggle is not surfaced.
        available_sims:
            Installed simulators.  If the list has more than one entry the footer
            shows a toggle button that cycles them by label.
        height_offset:
            Pixels to subtract from the effective height when computing
            layout and handling resize events.  Reserve space for a panel
            drawn below the board (e.g. SimPanel).
        vhdl_path:
            Currently validated VHDL file path.  Shown in the footer;
            enables [Start Simulation] when not ``None``.
        show_footer:
            When ``False`` the footer (buttons + VHDL status line) is not
            drawn.  Set to ``False`` in the simulation screen where the footer
            controls are irrelevant and the SimPanel provides all the
            necessary controls.
        reserve_footer_space:
            Whether the layout reserves the bottom footer strip.  Defaults to
            *show_footer*; pass ``True`` together with ``show_footer=False`` to
            keep the board laid out exactly as it is with the footer shown, so
            components do not jump when the preview's footer is swapped for the
            simulation overlays (which occupy the same strip).  Size-independent:
            the reserve scales with the window like every other metric.

        """
        self.board_def = board_def
        self._height_offset = height_offset
        self.vhdl_path: Path | None = Path(vhdl_path) if vhdl_path else None
        self._show_footer: bool = show_footer
        # The footer strip is reserved whenever it is drawn; the simulation
        # screen hides the footer but still fills that strip with its overlays,
        # so it reserves the space too (keeps the board from jumping — U34).
        self._reserve_footer_space: bool = (
            show_footer if reserve_footer_space is None else reserve_footer_space
        )
        if screen is not None:
            self.screen = screen
            scr_w, scr_h = screen.get_size()
            self.width = width if width > 0 else scr_w
            self.height = (height if height > 0 else scr_h) - height_offset
        else:
            w = width or 1024
            h = height or 700
            self.screen = pygame.display.set_mode((w, h), pygame.RESIZABLE)
            self.width, self.height = w, h - height_offset
        self.clock = pygame.time.Clock()
        self.running = False
        # Loop-exit flags consumed by _result(); run() resets them each entry.
        self._go_back = False
        self._simulate = False
        self._load_vhdl = False

        # The selected simulator + the installed set the [SIM:…] toggle cycles
        # (U35).  ``None`` when the caller does not surface the toggle (the
        # simulation screen's embedded board, the no-boards fallback preview).
        self.sim = sim
        self.available_sims: list[SimulatorInfo] = available_sims or ([sim] if sim else [])

        if board_def:
            _vhdl_sfx = f" \u2013 {self.vhdl_path.name}" if self.vhdl_path else ""
            title = f"FPGA Simulator \u2013 {board_def.name}{_vhdl_sfx}"
        else:
            title = "FPGA Simulator"
        pygame.display.set_caption(title)

        if board_def:
            self.fpga_chip = FPGAChip(
                vendor=board_def.vendor,
                device=board_def.device,
                package=board_def.package,
                clock_hz=board_def.default_clock_hz,
            )
            # A 3-pin rgb_led renders as a tri-color puck (U37); everything else
            # is a plain LED (incl. the 1-pin serial impostors is_rgb rejects).
            self.leds: list[LED] = [
                RGBLED(i, info=c) if c.is_rgb else LED(i, info=c)
                for i, c in enumerate(board_def.leds)
            ]
            self.buttons: list[Button] = [
                Button(i, info=c) for i, c in enumerate(board_def.buttons)
            ]
            self.switches: list[Switch] = [
                Switch(i, info=c) for i, c in enumerate(board_def.switches)
            ]
        else:
            self.fpga_chip = FPGAChip()
            self.leds = [LED(i) for i in range(num_leds)]
            self.buttons = [Button(i) for i in range(num_buttons)]
            self.switches = [Switch(i) for i in range(num_switches)]

        # LED bank clusters (U36): (label, widgets) per consecutive same-name run,
        # so the renderer groups and labels them (LEDR / LEDG / RGB / ...).
        self._led_banks: list[tuple[str, list[LED]]] = []
        if board_def and board_def.leds:
            idx = 0
            for name, comps in board_def.led_banks:
                self._led_banks.append(
                    (board_def.led_bank_label(name), self.leds[idx : idx + len(comps)])
                )
                idx += len(comps)
        elif self.leds:
            self._led_banks = [("LEDs", self.leds)]
        # Bank label anchors (label, x, y), filled by _place_led_banks (U36).
        self._led_label_pos: list[tuple[str, int, int]] = []

        if board_def and board_def.seven_seg:
            ssd = board_def.seven_seg
            self._seven_segs: list[SevenSeg] = [
                SevenSeg(i, has_dp=ssd.has_dp) for i in range(ssd.num_digits)
            ]
        else:
            self._seven_segs = []
        self._prev_seg_bits: list[int] = [0] * len(self._seven_segs)
        self._seg_panel_x: int = 0

        # Unified hover hit-test list (LEDs + switches + buttons) for U3 tooltips.
        self.components: list[UIComponent] = [*self.leds, *self.switches, *self.buttons]
        self._tooltip = Tooltip()
        self._hover_target: UIComponent | None = None
        self._hover_since_ms = 0

        # Which widget each held mouse button is holding (U44).  Keyed by the
        # pygame mouse-button number and storing the *widget index* — never a
        # rect or a position, because _layout() reassigns every rect on resize.
        self._mouse_holds: dict[int, int] = {}

        # Drag-paint state (U44 phase 5), armed only by a mouse-down that
        # actually hit a switch, and cleared on mouse-up.  ``_paint_value`` is
        # the value every switch the drag crosses is *set to* -- painting, not
        # toggling -- and ``_painted`` is the set of widget INDICES already
        # driven this drag, so re-entering one mid-sweep does not flip it back.
        self._paint_value: bool | None = None
        self._painted: set[int] = set()

        # Which button each held KEY is holding, keyed by keymap.event_token.
        # The target is resolved once at key-down and *looked up* at key-up,
        # never recomputed: SDL reports modifiers at event time, so a chord
        # released modifier-first would otherwise resolve to a different button
        # and leak the real hold forever (U44 §3.2).
        self._key_holds: dict[str, int] = {}

        # Default callbacks – print name + connector info
        def _sw_cb(idx: int, state: bool, info: ComponentInfo | None) -> None:
            label = info.display_name if info else f"Switch {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'ON' if state else 'OFF'}{conn}")

        def _btn_cb(idx: int, pressed: bool, info: ComponentInfo | None) -> None:
            label = info.display_name if info else f"Button {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

        for sw in self.switches:
            sw.callback = _sw_cb
        for btn in self.buttons:
            btn.callback = _btn_cb

        self._sim_btn_rect: pygame.Rect | None = None
        self._load_vhdl_btn_rect: pygame.Rect | None = None
        self._select_board_btn_rect: pygame.Rect | None = None
        self._sim_toggle_rect: pygame.Rect | None = None
        self._help_btn_rect: pygame.Rect | None = None
        # Set by the (?) button / F1 / ?; consumed by run() to open the overlay.
        self._help_requested = False
        self._settings_btn_rect: pygame.Rect | None = None
        # Set by the gear button; consumed by run() to open the settings overlay.
        self._settings_requested = False
        self._layout()

    # ── public API ───────────────────────────────────────────────────

    def set_led(self, index: int, state: bool) -> None:
        """Turn an LED fully on or off by index (the binary view of set_led_level)."""
        self.set_led_level(index, 1.0 if state else 0.0)

    def set_led_level(self, index: int, level: float) -> None:
        """Set an LED's brightness by index, as a duty cycle in [0, 1] (U9)."""
        if 0 <= index < len(self.leds):
            self.leds[index].level = max(0.0, min(1.0, level))

    def set_led_channel(self, index: int, channel: str, level: float) -> None:
        """Set one channel of an RGB LED by index (``channel`` = "r"/"g"/"b", U37).

        On a plain LED the channel collapses to :meth:`set_led_level` — callers
        route via ``BoardDef.led_channels``, so that only happens when a board's
        data and widgets disagree, and dropping the distinction is the safe read.
        """
        if 0 <= index < len(self.leds):
            widget = self.leds[index]
            clamped = max(0.0, min(1.0, level))
            if isinstance(widget, RGBLED):
                widget.set_channel(channel, clamped)
            else:
                widget.level = clamped

    def set_switch_callback(
        self, callback: Callable[[int, bool, ComponentInfo | None], None]
    ) -> None:
        """Set callback for *all* switches.  Signature: callback(index, state, info)."""
        for sw in self.switches:
            sw.callback = callback

    def set_button_callback(
        self, callback: Callable[[int, bool, ComponentInfo | None], None]
    ) -> None:
        """Set callback for *all* buttons.  Signature: callback(index, pressed, info)."""
        for btn in self.buttons:
            btn.callback = callback

    def get_switch_state(self, index: int) -> bool:
        """Read the current state of a switch."""
        if 0 <= index < len(self.switches):
            return bool(self.switches[index].state)
        return False

    def set_seg(self, index: int, bits8: int) -> None:
        """Update the bit pattern for digit *index* of the 7-segment display."""
        if 0 <= index < len(self._seven_segs) and self._prev_seg_bits[index] != bits8:
            self._prev_seg_bits[index] = bits8
            self._seven_segs[index].set_bits(bits8)

    def set_seg_levels(self, index: int, levels: Sequence[float]) -> None:
        """Set per-segment brightness for digit *index*, as duty cycles in [0, 1] (U9).

        Bypasses ``set_seg``'s bit-pattern change gate: two different brightness
        vectors can share the same on/off pattern, so the gate would swallow a
        genuine change (a digit fading is exactly that case).
        """
        if 0 <= index < len(self._seven_segs):
            self._seven_segs[index].set_levels(levels)
            self._prev_seg_bits[index] = self._seven_segs[index].bits

    def set_height_offset(self, offset: int) -> None:
        """Change the panel height reservation and reflow the board layout.

        Parameters
        ----------
        offset:
            New pixel height to subtract from the window for the external
            panel below the board.  Pass ``0`` to give the board the full
            window height.

        """
        self._height_offset = offset
        scr_w, scr_h = self.screen.get_size()
        self.height = scr_h - offset
        self._layout()

    def run(self) -> ScreenResult:
        """Enter the main loop and return the user's chosen :class:`ScreenResult`.

        Returns
        -------
        ScreenResult.BACK
            ESC or [Select Board] clicked — return to board selector.
        ScreenResult.LOAD_VHDL
            [Load VHDL File] clicked — caller should open file picker then
            re-enter run() with an updated *vhdl_path*.
        ScreenResult.SIMULATE
            [Start Simulation] clicked or Enter pressed (only fires when
            *vhdl_path* is not ``None``).
        ScreenResult.QUIT
            Window closed.

        """
        self.running = True
        self._go_back = False
        self._simulate = False
        self._load_vhdl = False
        while self.running:
            self._handle_events()
            if self._help_requested:
                self._help_requested = False
                # A modal runs its own event.get() loop and handles only
                # QUIT/RESIZE/KEYDOWN/MOUSEBUTTONDOWN, so every KEYUP and
                # MOUSEBUTTONUP during it is discarded.  Without this, F1 while
                # holding `1` strands BTN1 down for the rest of the session.
                self.release_transient_holds()
                HelpDialog(self.screen).run(self.clock)
                self._sync_to_surface()
            if self._settings_requested:
                self._settings_requested = False
                self.release_transient_holds()  # same KEYUP-swallowing modal
                SettingsDialog(self.screen).run(self.clock)
                self._sync_to_surface()
            self._draw()
            self.clock.tick(60)
        return self._result()

    def _result(self) -> ScreenResult:
        """Map the loop-exit flags (set by _handle_events) to a ScreenResult."""
        if self._simulate:
            return ScreenResult.SIMULATE
        if self._load_vhdl:
            return ScreenResult.LOAD_VHDL
        return ScreenResult.BACK if self._go_back else ScreenResult.QUIT

    def _resize(self, win_w: int, win_h: int) -> None:
        """Apply a new *window* size: update dimensions and reflow the layout."""
        self.width = win_w
        self.height = win_h - self._height_offset
        self._layout()

    def _sync_to_surface(self) -> None:
        """Reflow to the live surface size after a blocking overlay closes.

        A resize that happens while HelpDialog owns the event loop never
        reaches this screen, so its cached size and component layout go stale
        even though the display surface has already auto-resized.  Reconcile
        from the surface so the board re-scales the moment help is dismissed.
        """
        scr_w, scr_h = self.screen.get_size()
        if (scr_w, scr_h) != (self.width, self.height + self._height_offset):
            self._resize(scr_w, scr_h)

    # ── layout engine ────────────────────────────────────────────────

    def _layout(self) -> None:
        """Recompute component positions to fit the current window size."""
        w, h = self.width, self.height
        s = _ui_scale(self.width, self.height)
        margin = max(10, round(20 * s))
        title_h = max(14, round(22 * s))
        section_pad = max(6, round(10 * s))
        # Reserve the bottom strip (footer buttons + VHDL status, or the sim
        # overlays that replace them); minimal when neither is present.
        bottom_reserve = (
            max(65, round(90 * s)) if self._reserve_footer_space else max(8, round(10 * s))
        )

        # Buttons/switches claim height by their wrapped row count plus a little
        # headroom, so a board with many switches (DE2-115's 18 -> two rows) is
        # not cramped and the controls stay comfortable click targets (U36).
        avail_w_full = w - 2 * margin
        sections: list[tuple[str, Sequence[_Positionable], int]] = [("fpga", [self.fpga_chip], 3)]
        if self.leds:
            sections.append(("leds", self.leds, 4))
        if self.buttons:
            btn_w = 1 + self._grid_rows(len(self.buttons), avail_w_full, s)
            sections.append(("buttons", self.buttons, btn_w))
        if self.switches:
            sw_w = 1 + self._grid_rows(len(self.switches), avail_w_full, s)
            sections.append(("switches", self.switches, sw_w))

        if not sections:
            return

        total_weight = sum(sec[2] for sec in sections)
        usable_h = h - 2 * margin - section_pad * (len(sections) - 1) - bottom_reserve

        self._seg_panel_x = 0
        y: float = margin
        for name, items, weight in sections:
            sec_h = usable_h * weight / total_weight
            content_h = sec_h - title_h  # per-item labels are budgeted inside the placers
            avail_w = w - 2 * margin

            if name == "fpga" and self._seven_segs:
                chip_w = int(avail_w * 0.55)
                seg_w = avail_w - chip_w - section_pad
                self._place_items(
                    [self.fpga_chip], margin, y + title_h, chip_w, content_h, "fpga", scale=s
                )
                self._seg_panel_x = int(margin + chip_w + section_pad)
                self._place_items(
                    self._seven_segs,
                    self._seg_panel_x,
                    y + title_h,
                    seg_w,
                    content_h,
                    "seven_segs",
                    scale=s,
                )
            elif name == "leds":
                # Clear the section top (where the chip's summary line can spill)
                # but reclaim the redundant label strip via the wider content_h.
                self._place_led_banks(margin, y + title_h, avail_w, content_h, scale=s)
            else:
                self._place_items(items, margin, y + title_h, avail_w, content_h, name, scale=s)

            y += sec_h + section_pad

    @staticmethod
    def _grid_rows(n: int, avail_w: float, scale: float) -> int:
        """Rows a grid of ``n`` items needs at the current width (U36).

        Shared by the layout (to size the section) and the placement (to balance
        the columns), so a bank that wraps to two rows reserves the height for
        two rows instead of cramping them.
        """
        cols_fit = min(n, max(1, int(avail_w / max(1, round(65 * scale)))))
        return math.ceil(n / cols_fit)

    def _place_items(  # noqa: PLR0913
        self,
        items: Sequence[_Positionable],
        x0: float,
        y0: float,
        avail_w: float,
        avail_h: float,
        kind: str,
        scale: float = 1.0,
    ) -> None:
        n = len(items)
        if n == 0:
            return

        if kind == "fpga":
            # Chip scales with the window.  Width is mildly capped relative to
            # height (≤1.6×) since real FPGA packages are roughly square.
            size_h = min(avail_h * 0.88, round(300 * scale))
            size_w = min(avail_w * 0.70, round(420 * scale), round(size_h * 1.6))
            cx = x0 + avail_w / 2
            cy = y0 + avail_h / 2
            items[0].rect = pygame.Rect(cx - size_w / 2, cy - size_h / 2, size_w, size_h)
            return

        if kind == "seven_segs":
            min_dw = 24
            cols = n
            while cols > 1 and (avail_w / cols) * 0.85 < min_dw:
                cols = math.ceil(cols / 2)
            rows = math.ceil(n / cols)
            cell_w = avail_w / cols
            cell_h = avail_h / max(1, rows)
            dw = min(cell_w * 0.85, cell_h * 8 / 13)
            dh = dw * 13 / 8
            for i, item in enumerate(items):
                r = i // cols
                c = (cols - 1) - (i % cols)
                cx = x0 + c * cell_w + cell_w / 2
                cy = y0 + r * cell_h + cell_h / 2
                item.rect = pygame.Rect(int(cx - dw / 2), int(cy - dh / 2), int(dw), int(dh))
            return

        rows = self._grid_rows(n, avail_w, scale)
        cols = math.ceil(n / rows)  # balance columns evenly across those rows

        cell_w = avail_w / cols
        cell_h = avail_h / max(1, rows)
        # Reserve the item's label (drawn beneath it) so a row never overlaps the
        # next, and let the control fill the rest so it stays an easy click target.
        item_label_h = max(12, round(13 * scale)) + 3
        item_h = max(round(16 * scale), cell_h - item_label_h - round(4 * scale))
        if kind == "buttons":
            size_w = min(cell_w * 0.82, round(120 * scale))
            size_h = min(item_h, round(64 * scale))
        else:
            size_w = min(cell_w * 0.62, round(64 * scale))
            size_h = min(item_h, round(72 * scale))

        for i, item in enumerate(items):
            r = i // cols
            c = i % cols
            cx = x0 + c * cell_w + cell_w / 2
            # Center the control + its label block within the cell.
            cy = y0 + r * cell_h + (cell_h - (size_h + item_label_h)) / 2 + size_h / 2
            item.rect = pygame.Rect(cx - size_w / 2, cy - size_h / 2, size_w, size_h)

    def _place_led_banks(
        self, x0: float, y0: float, avail_w: float, avail_h: float, scale: float
    ) -> None:
        """Flow-pack LED banks at a uniform, space-filling size (U36).

        LEDs within a bank sit at one tight pitch; banks are separated by a small
        consistent gap (widened only when a bank's label needs it, so labels
        never collide) and flow onto the next row when they no longer fit. A bank
        wider than a row wraps its LEDs internally. The LED size is the largest
        that keeps every row -- the label strip above, the LEDs, and the per-LED
        label below -- on screen (capped), and the whole thing reflows with the
        window.
        """
        self._led_label_pos = []
        banks = [(label, widgets) for label, widgets in self._led_banks if widgets]
        if not banks:
            return
        title_font = get_font(max(10, round(13 * scale)) + 5, bold=True)
        label_px = {label: float(title_font.size(label)[0]) for label, _ in banks}
        gap = max(6, round(14 * scale))  # between LEDs within a bank
        bank_gap = max(gap, round(28 * scale))  # a little extra between banks
        label_h = max(14, round(18 * scale))  # bank-label strip above a row
        led_label_h = max(12, round(13 * scale)) + 3  # the LEDn label under each LED

        # Pixel-flow placement: (label, widgets, x_offset, row, wrap_cols).
        def flow(size: int) -> tuple[list[tuple[str, list[LED], float, int, int]], int]:
            pitch = size + gap
            full = max(1, int(avail_w // pitch))
            placed: list[tuple[str, list[LED], float, int, int]] = []
            row, x, rows_used = 0, 0.0, 1
            for label, widgets in banks:
                n = len(widgets)
                if n > full:  # wider than a row -> own block, wraps internally
                    if x > 0:
                        row, x = row + 1, 0.0
                    # Balance the wrap rows (18 LEDs at 16/row -> 9+9, not
                    # 16+2), matching the _place_items grids' column balance.
                    rows_needed = math.ceil(n / full)
                    placed.append((label, widgets, 0.0, row, math.ceil(n / rows_needed)))
                    row += rows_needed
                    rows_used, x = row, 0.0
                    continue
                bank_w = max(n * pitch, label_px[label])
                # A big bank (a full LED row like DE2-115's LEDR) takes its own
                # line so two-color rows stack; small banks pack together.
                large = n * pitch > avail_w * 0.5
                if (large or x + bank_w > avail_w) and x > 0:
                    row, x = row + 1, 0.0
                placed.append((label, widgets, x, row, n))
                rows_used = max(rows_used, row + 1)
                if large:
                    row, x = row + 1, 0.0
                else:
                    x += bank_w + bank_gap
            return placed, rows_used

        # Largest LED size whose rows all fit vertically (falls back to the min).
        size = 10
        for cand in range(round(46 * scale), 9, -1):
            if flow(cand)[1] * (cand + label_h + led_label_h + gap) <= avail_h:
                size = cand
                break
        pitch = size + gap
        block_h = size + label_h + led_label_h + gap
        placed, _ = flow(size)

        # Center each row horizontally so its LEDs are balanced left-to-right.
        row_right: dict[int, float] = {}
        for _lbl, widgets, bank_x, base_row, wrap in placed:
            n = len(widgets)
            for rr in range(math.ceil(n / wrap)):
                in_row = min(wrap, n - rr * wrap)
                key = base_row + rr
                row_right[key] = max(row_right.get(key, 0.0), bank_x + in_row * pitch)
        row_off = {r: max(0.0, (avail_w - ext) / 2) for r, ext in row_right.items()}

        for label, widgets, bank_x, base_row, wrap in placed:
            lx = int(x0 + row_off.get(base_row, 0.0) + bank_x)
            self._led_label_pos.append((label, lx, int(y0 + base_row * block_h)))
            for i, led in enumerate(widgets):
                r, c = divmod(i, wrap)
                cx = x0 + row_off.get(base_row + r, 0.0) + bank_x + c * pitch + size / 2
                cy = y0 + (base_row + r) * block_h + label_h + size / 2
                led.rect = pygame.Rect(int(cx - size / 2), int(cy - size / 2), int(size), int(size))

    # ── events ───────────────────────────────────────────────────────

    def _handle_events(self, events: list[pygame.event.Event] | None = None) -> None:
        for event in events if events is not None else pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._go_back = True
                self.running = False

            elif event.type == pygame.KEYDOWN and (
                event.key == pygame.K_F1 or getattr(event, "unicode", "") == "?"
            ):
                self._help_requested = True

            elif event.type == pygame.KEYUP:
                self._release_key_hold(event)

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                for sw in self.switches:
                    if sw.state:
                        sw.state = False
                        if sw.callback:
                            sw.callback(sw.index, False, sw.info)
                self.release_all_holds()

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                if self.vhdl_path is not None:
                    self._simulate = True
                    self.running = False

            elif event.type == pygame.KEYDOWN:
                # Last in the KEYDOWN chain on purpose: a named shortcut always
                # outranks a board binding, so adding a letter shortcut later
                # can never be silently swallowed by the keymap.  An unbound key
                # falls through here and does nothing.
                self._bind_key(event)

            elif event.type == pygame.WINDOWRESIZED:
                self._resize(event.x, event.y)

            elif event.type == pygame.WINDOWFOCUSLOST:
                # Alt-Tab away mid-hold and the KEYUP is delivered to whatever
                # has focus instead, stranding the button down.  Compared by
                # SYMBOL, never by its integer: pygame-ce renumbered every
                # WINDOW* constant one lower, so the old literal 32786 now means
                # WINDOWCLOSE.  (Not key.get_focused() — its value under the
                # test video driver depends on the pygame flavor.)
                self.release_transient_holds()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Help (?) button
                if self._help_btn_rect and self._help_btn_rect.collidepoint(event.pos):
                    self._help_requested = True
                    continue

                # Settings (gear) button
                if self._settings_btn_rect and self._settings_btn_rect.collidepoint(event.pos):
                    self._settings_requested = True
                    continue

                # Simulator toggle (cycle to next installed simulator)
                if (
                    self._sim_toggle_rect
                    and self._sim_toggle_rect.collidepoint(event.pos)
                    and len(self.available_sims) > 1
                ):
                    idx = (
                        self.available_sims.index(self.sim)
                        if self.sim in self.available_sims
                        else 0
                    )
                    self.sim = self.available_sims[(idx + 1) % len(self.available_sims)]
                    continue

                # [Select Board] button
                if self._select_board_btn_rect and self._select_board_btn_rect.collidepoint(
                    event.pos
                ):
                    self._go_back = True
                    self.running = False
                    continue

                # [Load VHDL File] button
                if self._load_vhdl_btn_rect and self._load_vhdl_btn_rect.collidepoint(event.pos):
                    self._load_vhdl = True
                    self.running = False
                    continue

                # [Start Simulation] button (only active when VHDL is loaded)
                if (
                    self._sim_btn_rect
                    and self._sim_btn_rect.collidepoint(event.pos)
                    and self.vhdl_path is not None
                ):
                    self._simulate = True
                    self.running = False
                    continue

                for sw in self.switches:
                    if sw.handle_click(event.pos):
                        # Arm the sweep with the value this first switch just
                        # took, so dragging on from an off switch drives the
                        # bank on and from an on switch drives it off.
                        self._paint_value = sw.state
                        self._painted = {sw.index}
                        break
                source = _mouse_source(event.button)
                for btn in self.buttons:
                    if btn.handle_press(event.pos, source):
                        self._mouse_holds[event.button] = btn.index
                        break

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                # Right-click toggles a latch (U44).  Modeless by design: there
                # is no sticky mode to render, remember, or explain, and it does
                # not fight the keyboard for a modifier.  Button 3 was entirely
                # unhandled before this, so it costs nothing elsewhere.
                for btn in self.buttons:
                    if btn.rect.collidepoint(event.pos):
                        btn.toggle_latch()
                        break

            elif event.type == pygame.MOUSEMOTION:
                self._paint_switches(event)

            elif event.type == pygame.MOUSEBUTTONUP:
                # Any mouse button, not just 1: a release must always be able to
                # end the hold its press took, or the button stays down forever.
                self._release_mouse_hold(event.button)
                self._paint_value = None
                self._painted.clear()

    # ── hold-source bookkeeping (U44) ────────────────────────────────

    def _release_mouse_hold(self, button: int) -> None:
        """Release only the widget that mouse *button* is holding.

        The pre-U44 handler released *every* button on any mouse-up, so a
        second hold taken by the keyboard (or another mouse button) died with
        it.  The registry makes the release identity-scoped.
        """
        index = self._mouse_holds.pop(button, None)
        if index is not None:
            self.buttons[index].handle_release(_mouse_source(button))

    def _bind_key(self, event: pygame.event.Event) -> None:
        """Take a key hold for *event* if it binds to a button on this board.

        A key with no binding, or one whose index the board does not reach
        (``5`` on a two-button board), is an explicit no-op rather than an error.
        """
        index = keymap.resolve(event)
        if index is None or index >= len(self.buttons):
            return
        token = keymap.event_token(event)
        if token in self._key_holds:
            return  # already down; ignore a repeat rather than double-holding
        self._key_holds[token] = index
        self.buttons[index].hold(_key_source(token))

    def _release_key_hold(self, event: pygame.event.Event) -> None:
        """Release whatever button this key took at key-down, if anything."""
        token = keymap.event_token(event)
        index = self._key_holds.pop(token, None)
        if index is not None:
            self.buttons[index].handle_release(_key_source(token))

    def _paint_switches(self, event: pygame.event.Event) -> None:
        """Drive every switch this motion crossed to the armed paint value.

        Only runs while a sweep is armed — a press that began on a button, on
        the board background, or on chrome paints nothing.

        **The motion segment is tested, not the cursor point.** Switches sit on
        a pitch far wider than they are (measured on a 1024x700 Nexys 4 DDR:
        64 px wide on a 123 px pitch, a 59 px gap), so any single MOUSEMOTION
        delta wider than the pitch would skip a switch outright on a fast
        flick — intermittent, invisible, and blamed on the feature.
        ``rect.clipline`` tests the whole segment; ``event.rel`` gives the
        previous position for free.
        """
        if self._paint_value is None:
            return
        prev = (event.pos[0] - event.rel[0], event.pos[1] - event.rel[1])
        for sw in self.switches:
            if sw.index in self._painted:
                continue
            if not sw.rect.clipline(prev, event.pos):
                continue
            self._painted.add(sw.index)
            if sw.state != self._paint_value:
                sw.state = self._paint_value
                if sw.callback:
                    sw.callback(sw.index, sw.state, sw.info)

    def input_snapshot(self) -> BoardInputs:
        """Capture the user-set input state, for carrying onto another board (U45)."""
        return BoardInputs(
            switches=tuple(sw.state for sw in self.switches),
            latched=frozenset(btn.index for btn in self.buttons if btn.latched),
        )

    def restore_inputs(self, snap: BoardInputs) -> bool:
        """Apply *snap* silently; report whether it left anything set.

        Silent (no widget callbacks) because the caller owns the consequences:
        the preview has nobody to notify, and the simulation screen sets its
        own dirty flag so the restored state ships as one ``input`` message
        rather than one per widget — with a per-widget notification the console
        would also narrate a dozen phantom ``SW3: ON`` lines the user did not
        just do.

        Extra entries are ignored rather than an error: a snapshot only ever
        meets a board of a different size through a bug, and dropping the tail
        is a better outcome than an ``IndexError`` in the launcher.
        """
        for sw, state in zip(self.switches, snap.switches, strict=False):
            sw.state = state
        for btn in self.buttons:
            btn.set_latched(btn.index in snap.latched)
        return bool(snap)

    def release_transient_holds(self) -> None:
        """Drop every live hold (mouse, keyboard) while keeping latches.

        For the moments the event stream itself goes away — window focus loss,
        a blocking modal running its own ``event.get()`` loop — where the
        MOUSEBUTTONUP / KEYUP that would end a hold is never delivered and the
        button would otherwise stay down forever.  Fires one release callback
        per button that actually goes up.
        """
        self._mouse_holds.clear()
        self._key_holds.clear()
        for btn in self.buttons:
            btn.release_transient()

    def release_all_holds(self) -> None:
        """Drop *every* hold source on every button, latches included (the ``R`` reset).

        Fires at most one release callback per button, whatever it was held by.
        """
        self._mouse_holds.clear()
        self._key_holds.clear()
        for btn in self.buttons:
            btn.handle_release()

    # ── hover tooltips (U3) ──────────────────────────────────────────

    def _component_at(self, pos: tuple[int, int]) -> UIComponent | None:
        """Return the LED / switch / button whose rect contains *pos*, or None."""
        for comp in self.components:
            if comp.rect.collidepoint(pos):
                return comp
        return None

    def _update_hover(self, pos: tuple[int, int], now_ms: int) -> UIComponent | None:
        """Track cursor dwell; return the component whose tooltip is due, else None.

        The dwell timer resets whenever the cursor moves to a different component
        (or off all of them); a tooltip becomes due once the same component has
        been hovered for ``HOVER_TOOLTIP_MS``.
        """
        target = self._component_at(pos)
        if target is not self._hover_target:
            self._hover_target = target
            self._hover_since_ms = now_ms
        if target is not None and now_ms - self._hover_since_ms >= HOVER_TOOLTIP_MS:
            return target
        return None

    def _draw_hover_tooltip(self) -> None:
        """Draw the hover tooltip when the cursor has dwelt on a component.

        Called at the end of ``_draw`` so it renders on top of the board (and,
        in preview mode, the footer).  Works in the simulation subprocess too,
        which drives this same ``_draw`` each frame.
        """
        pos = pygame.mouse.get_pos()
        hovered = self._update_hover(pos, pygame.time.get_ticks())
        if hovered is not None:
            self._tooltip.draw(self.screen, pos, hovered.label, hovered.info, hovered.tooltip_extra)

    # ── redraw gating (U23) ──────────────────────────────────────────

    def visual_signature(self, *, quantize: int = 1000) -> tuple[object, ...]:
        """Return a hashable fingerprint of everything ``_draw`` renders that can vary.

        The simulation screen compares this frame-to-frame to skip an identical
        redraw (U23): LED / 7-seg brightness (quantized well past the display's
        resolution, so the persistence-of-vision easing settles to a stable
        "clean" value), switch / button state, and the layout size (a resize
        must force a redraw). Hover tooltips and the overlay/panel are handled
        by the caller (see :meth:`hover_active`).

        *quantize* sets the brightness resolution. The 1000-step default is the
        redraw gate's; the ``--screenshots`` recorder asks for a much coarser
        one, because at 1000 steps every frame of a fade reads as a change
        (see :mod:`fpga_sim.ui.screenshots`).
        """
        q = quantize
        leds = tuple(
            tuple(round(lv * q) for lv in led.levels)
            if isinstance(led, RGBLED)
            else round(led.level * q)
            for led in self.leds
        )
        segs = tuple(tuple(round(lv * q) for lv in seg.levels) for seg in self._seven_segs)
        switches = tuple(sw.state for sw in self.switches)
        # Latch state is part of the fingerprint, not just `pressed`: mouse-hold
        # a button, right-click to latch it, then release the mouse and
        # `pressed` never changes -- so without this the redraw-skip would hold
        # the held style on screen over a latched button forever.
        buttons = tuple((btn.pressed, btn.latched) for btn in self.buttons)
        return (self.width, self.height, self._height_offset, leds, segs, switches, buttons)

    def hover_active(self) -> bool:
        """Return True when the cursor is over a hover-target component (LED/switch/button).

        The dwell-timed tooltip (U3) can appear and update while the board is
        otherwise static, so the simulation screen keeps redrawing whenever this
        holds — the redraw-skip (U23) only kicks in with the cursor off every
        component, which is exactly when no tooltip is in play.
        """
        return self._component_at(pygame.mouse.get_pos()) is not None

    # ── drawing ──────────────────────────────────────────────────────

    def _draw(self, *, flip: bool = True) -> None:
        self.screen.fill(THEME.pcb_bg)

        s = _ui_scale(self.width, self.height)
        font_size = max(10, round(13 * s))
        font = get_font(font_size)
        title_font = get_font(font_size + 5, bold=True)

        chip_font = get_font(max(13, font_size + 3), bold=True)
        if self.fpga_chip.rect.width >= 20:
            t = title_font.render("FPGA", True, WHITE)
            self.screen.blit(t, (20, self.fpga_chip.rect.top - font_size - 10))
        self.fpga_chip.draw(self.screen, chip_font)

        if self._seven_segs and self.fpga_chip.rect.width >= 20:
            t = title_font.render("7-Seg", True, WHITE)
            self.screen.blit(t, (self._seg_panel_x, self._seven_segs[0].rect.top - font_size - 14))

        # Component count summary below the chip.
        # Offset by chip_font.get_linesize() so the count clears the chip's
        # bottom text line (clock freq) even when the chip rect is small.
        if self.board_def and self.fpga_chip.rect.width >= 20:
            _parts = []
            if self.leds:
                # Bank-aware LED counts (U37): "16 LEDs + 2 RGB" / "18+9 LEDs",
                # matching the selector's summary, instead of a flat widget count.
                _parts.append(self.board_def.led_summary())
            if self.buttons:
                _parts.append(f"{len(self.buttons)} Button{'s' if len(self.buttons) != 1 else ''}")
            if self.switches:
                _sw_s = "es" if len(self.switches) != 1 else ""
                _parts.append(f"{len(self.switches)} Switch{_sw_s}")
            if self._seven_segs:
                _parts.append(f"{len(self._seven_segs)}-digit 7-seg")
            if _parts:
                count_f = get_font(max(11, round(13 * s)))
                count_surf = count_f.render("  \u00b7  ".join(_parts), True, THEME.info_green)
                _chip_r = self.fpga_chip.rect
                count_x = _chip_r.centerx - count_surf.get_width() // 2
                # Start below the chip rect plus a gap equal to one chip-font line
                # so the count never overlaps the clock-frequency text inside the chip.
                count_y = _chip_r.bottom + chip_font.get_linesize() + max(2, round(3 * s))
                self.screen.blit(count_surf, (count_x, count_y))

        for _bank_label, _lx, _ly in self._led_label_pos:
            t = title_font.render(_bank_label, True, WHITE)
            self.screen.blit(t, (_lx, _ly))
        if self.buttons:
            t = title_font.render("Buttons", True, WHITE)
            self.screen.blit(t, (20, self.buttons[0].rect.top - font_size - 14))
        if self.switches:
            t = title_font.render("Switches", True, WHITE)
            self.screen.blit(t, (20, self.switches[0].rect.top - font_size - 14))

        for led in self.leds:
            led.draw(self.screen, font)
        for btn in self.buttons:
            btn.draw(self.screen, font)
        for sw in self.switches:
            sw.draw(self.screen, font)

        for seg_widget in self._seven_segs:
            seg_widget.draw(self.screen)

        # ── Footer buttons (preview mode only) ───────────────────────
        if not self._show_footer:
            self._draw_hover_tooltip()
            if flip:
                pygame.display.flip()
            return

        btn_font = get_font(max(12, round(16 * s)), bold=True)
        btn_margin_x = max(15, round(20 * s))
        btn_margin_y = max(15, round(20 * s))
        mouse_pos = pygame.mouse.get_pos()
        gap = max(8, round(10 * s))

        # Help (?) button — top-right corner — with the settings gear to its left.
        help_margin = max(12, round(16 * s))
        self._help_btn_rect = draw_help_button(
            self.screen,
            right=self.width - help_margin,
            top=help_margin,
            size=max(24, round(30 * s)),
            mouse=mouse_pos,
        )
        self._settings_btn_rect = draw_settings_button(
            self.screen,
            right=self._help_btn_rect.left - gap,
            top=help_margin,
            size=max(24, round(30 * s)),
            mouse=mouse_pos,
        )

        # Shared button height from font metrics; button row pinned to the bottom.
        btn_h = btn_font.get_height() + 14
        btn_y = self.height - btn_h - btn_margin_y

        # ── Left side: [Select Board]  [Load VHDL File] ───────────────────────
        sel_w = btn_font.size("Select Board")[0] + 30
        self._select_board_btn_rect = pygame.Rect(btn_margin_x, btn_y, sel_w, btn_h)
        draw_button(
            self.screen,
            self._select_board_btn_rect,
            "Select Board",
            btn_font,
            THEME.btn_select_board,
            hovered=self._select_board_btn_rect.collidepoint(mouse_pos),
        )

        load_w = btn_font.size("Load VHDL File")[0] + 30
        load_x = self._select_board_btn_rect.right + gap
        self._load_vhdl_btn_rect = pygame.Rect(load_x, btn_y, load_w, btn_h)
        draw_button(
            self.screen,
            self._load_vhdl_btn_rect,
            "Load VHDL File",
            btn_font,
            THEME.btn_load_vhdl,
            hovered=self._load_vhdl_btn_rect.collidepoint(mouse_pos),
        )

        # ── Right side: [SIM: …]  [Start Simulation] ──────────────────────────
        can_simulate = self.vhdl_path is not None
        start_w = btn_font.size("Start Simulation")[0] + 30
        start_x = self.width - start_w - btn_margin_x
        self._sim_btn_rect = pygame.Rect(start_x, btn_y, start_w, btn_h)
        draw_button(
            self.screen,
            self._sim_btn_rect,
            "Start Simulation",
            btn_font,
            THEME.btn_start_sim,
            hovered=self._sim_btn_rect.collidepoint(mouse_pos),
            enabled=can_simulate,
        )

        # [SIM:…] toggle — drawn only when a simulator is surfaced (U35).  The
        # embedded board of the simulation screen and the no-boards fallback
        # pass no ``sim``, so they show no toggle.
        if self.sim is not None:
            toggle_label = f"SIM: {self.sim.label}"
            toggle_w = btn_font.size(toggle_label)[0] + 24
            toggle_x = start_x - toggle_w - gap
            self._sim_toggle_rect = pygame.Rect(toggle_x, btn_y, toggle_w, btn_h)
            can_toggle = len(self.available_sims) > 1
            toggle_style = (
                THEME.btn_sim_toggle_nvc if self.sim.engine == "nvc" else THEME.btn_sim_toggle_ghdl
            )
            draw_button(
                self.screen,
                self._sim_toggle_rect,
                toggle_label,
                btn_font,
                toggle_style,
                hovered=self._sim_toggle_rect.collidepoint(mouse_pos),
                enabled=can_toggle,
            )
        else:
            self._sim_toggle_rect = None

        # ── VHDL status line (above button row) ───────────────────────────────
        status_f = get_font(max(10, round(13 * s)))
        status_y = btn_y - status_f.get_linesize() - max(4, round(5 * s))
        if self.vhdl_path is not None:
            status_txt = status_f.render(f"VHDL: {self.vhdl_path.name}", True, THEME.vhdl_ok)
        else:
            status_txt = status_f.render(
                "No VHDL file loaded  \u2013  use [Load VHDL File] to select one",
                True,
                THEME.warning,
            )
        self.screen.blit(status_txt, (btn_margin_x, status_y))

        self._draw_hover_tooltip()
        if flip:
            pygame.display.flip()
