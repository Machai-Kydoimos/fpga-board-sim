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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import pygame

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.ui.components import LED, Button, FPGAChip, SevenSeg, Switch, UIComponent
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
            self.leds: list[LED] = [LED(i, info=c) for i, c in enumerate(board_def.leds)]
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
                HelpDialog(self.screen).run(self.clock)
                self._sync_to_surface()
            if self._settings_requested:
                self._settings_requested = False
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
        label_h = max(12, round(18 * s))
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
            content_h = sec_h - title_h - label_h
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
                    placed.append((label, widgets, 0.0, row, full))
                    row += math.ceil(n / full)
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
        for cand in range(round(42 * scale), 9, -1):
            if flow(cand)[1] * (cand + label_h + led_label_h + gap) <= avail_h:
                size = cand
                break
        pitch = size + gap
        block_h = size + label_h + led_label_h + gap
        placed, _ = flow(size)
        for label, widgets, bank_x, row, wrap in placed:
            self._led_label_pos.append((label, int(x0 + bank_x), int(y0 + row * block_h)))
            for i, led in enumerate(widgets):
                r, c = divmod(i, wrap)
                cx = x0 + bank_x + c * pitch + size / 2
                cy = y0 + (row + r) * block_h + label_h + size / 2
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

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                for sw in self.switches:
                    if sw.state:
                        sw.state = False
                        if sw.callback:
                            sw.callback(sw.index, False, sw.info)
                for btn in self.buttons:
                    btn.handle_release()

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                if self.vhdl_path is not None:
                    self._simulate = True
                    self.running = False

            elif event.type == pygame.WINDOWRESIZED:
                self._resize(event.x, event.y)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Help (?) button
                if self._help_btn_rect and self._help_btn_rect.collidepoint(event.pos):
                    self._help_requested = True
                    return

                # Settings (gear) button
                if self._settings_btn_rect and self._settings_btn_rect.collidepoint(event.pos):
                    self._settings_requested = True
                    return

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
                    return

                # [Select Board] button
                if self._select_board_btn_rect and self._select_board_btn_rect.collidepoint(
                    event.pos
                ):
                    self._go_back = True
                    self.running = False
                    return

                # [Load VHDL File] button
                if self._load_vhdl_btn_rect and self._load_vhdl_btn_rect.collidepoint(event.pos):
                    self._load_vhdl = True
                    self.running = False
                    return

                # [Start Simulation] button (only active when VHDL is loaded)
                if (
                    self._sim_btn_rect
                    and self._sim_btn_rect.collidepoint(event.pos)
                    and self.vhdl_path is not None
                ):
                    self._simulate = True
                    self.running = False
                    return

                for sw in self.switches:
                    sw.handle_click(event.pos)
                for btn in self.buttons:
                    btn.handle_press(event.pos)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
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
                _parts.append(f"{len(self.leds)} LED{'s' if len(self.leds) != 1 else ''}")
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
