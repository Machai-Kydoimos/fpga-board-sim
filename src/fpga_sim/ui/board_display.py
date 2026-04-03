"""FPGABoard: the main interactive board display screen.

Renders the FPGA chip, LEDs, buttons, and switches in a resizable pygame
window.  run() returns 'back', 'load_vhdl', 'simulate', or 'quit'.

Footer buttons
--------------
* [Select Board]     — always enabled; ESC also triggers this action.
* [Load VHDL File]   — always enabled; opens the VHDL file picker.
* [Start Simulation] — greyed out until a VHDL file has been validated and
                       loaded via the [Load VHDL File] button.
* [SIM: GHDL/NVC]   — simulator toggle (greyed when only one simulator is
                       installed).

The VHDL filename is shown above the buttons once a file is loaded.

The active simulator can be toggled via [SIM:…].  Read ``board.simulator``
after run() returns to discover the user's choice.
"""

import math
from collections.abc import Callable
from pathlib import Path

import pygame

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.ui.components import LED, Button, FPGAChip, Switch
from fpga_sim.ui.constants import BG_GREEN, WHITE, _ui_scale, get_font


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
    simulator : str
        Currently selected simulator ('ghdl' or 'nvc').
    available_simulators : list[str]
        Simulators that are installed.  If the list has more than one
        entry the footer shows a toggle button.
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
        simulator: str = "ghdl",
        available_simulators: list[str] | None = None,
        height_offset: int = 0,
        vhdl_path: str | Path | None = None,
        show_footer: bool = True,
    ) -> None:
        """Initialise the board display with components laid out from board_def.

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
        simulator:
            Name of the active simulator backend (``"ghdl"`` or ``"nvc"``).
        available_simulators:
            Simulators that are installed.  If the list has more than one
            entry the footer shows a toggle button.
        height_offset:
            Pixels to subtract from the effective height when computing
            layout and handling resize events.  Reserve space for a panel
            drawn below the board (e.g. SimPanel).
        vhdl_path:
            Currently validated VHDL file path.  Shown in the footer;
            enables [Start Simulation] when not ``None``.
        show_footer:
            When ``False`` the footer (buttons + VHDL status line) is not
            drawn.  Set to ``False`` in the simulation subprocess where the
            footer controls are irrelevant and the SimPanel provides all
            the necessary controls.

        """
        self.board_def = board_def
        self._height_offset = height_offset
        self.vhdl_path: Path | None = Path(vhdl_path) if vhdl_path else None
        self._show_footer: bool = show_footer
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

        self.simulator = simulator
        self.available_simulators = available_simulators or ["ghdl"]

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
        self._layout()

    # ── public API ───────────────────────────────────────────────────

    def set_led(self, index: int, state: bool) -> None:
        """Turn an LED on or off by index."""
        if 0 <= index < len(self.leds):
            self.leds[index].state = bool(state)

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

    def run(self) -> str:
        """Enter the main loop.

        Returns
        -------
        'back'
            ESC or [Select Board] clicked — return to board selector.
        'load_vhdl'
            [Load VHDL File] clicked — caller should open file picker then
            re-enter run() with an updated *vhdl_path*.
        'simulate'
            [Start Simulation] clicked or Enter pressed (only fires when
            *vhdl_path* is not ``None``).
        'quit'
            Window closed.

        """
        self.running = True
        self._go_back = False
        self._simulate = False
        self._load_vhdl = False
        while self.running:
            self._handle_events()
            self._draw()
            self.clock.tick(60)
        if self._simulate:
            return "simulate"
        if self._load_vhdl:
            return "load_vhdl"
        return "back" if self._go_back else "quit"

    # ── layout engine ────────────────────────────────────────────────

    def _layout(self) -> None:
        """Recompute component positions to fit the current window size."""
        w, h = self.width, self.height
        s = _ui_scale(self.width, self.height)
        margin = max(10, round(20 * s))
        title_h = max(14, round(22 * s))
        label_h = max(12, round(18 * s))
        section_pad = max(6, round(10 * s))
        # Reserve space for footer buttons + VHDL status; none needed when footer hidden
        bottom_reserve = max(65, round(90 * s)) if self._show_footer else max(8, round(10 * s))

        sections: list[tuple[str, list, int]] = [("fpga", [self.fpga_chip], 3)]
        if self.leds:
            sections.append(("leds", self.leds, 4))
        if self.buttons:
            sections.append(("buttons", self.buttons, 1))
        if self.switches:
            sections.append(("switches", self.switches, 1))

        if not sections:
            return

        total_weight = sum(sec[2] for sec in sections)
        usable_h = h - 2 * margin - section_pad * (len(sections) - 1) - bottom_reserve

        y: float = margin
        for name, items, weight in sections:
            sec_h = usable_h * weight / total_weight
            content_h = sec_h - title_h - label_h
            self._place_items(items, margin, y + title_h, w - 2 * margin, content_h, name, scale=s)
            y += sec_h + section_pad

    def _place_items(  # noqa: PLR0913
        self,
        items: list,
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

        if kind == "leds":
            if n <= 16:
                cols = n
            else:
                aspect = avail_w / max(1, avail_h)
                cols = max(1, round(math.sqrt(n * aspect)))
                cols = min(cols, n)
        else:
            cols = min(n, max(1, int(avail_w / max(1, round(65 * scale)))))
        rows = math.ceil(n / cols)

        cell_w = avail_w / cols
        cell_h = avail_h / max(1, rows)

        if kind == "leds":
            size = min(cell_w, cell_h) * 0.80
            size = max(10, min(size, round(64 * scale)))
        elif kind == "buttons":
            size_w = min(cell_w * 0.75, round(110 * scale))
            size_h = min(cell_h * 0.65, round(60 * scale))
        else:
            size_w = min(cell_w * 0.55, round(56 * scale))
            size_h = min(cell_h * 0.70, round(80 * scale))

        for i, item in enumerate(items):
            r = i // cols
            c = i % cols
            cx = x0 + c * cell_w + cell_w / 2
            cy = y0 + r * cell_h + cell_h / 2
            if kind == "leds":
                item.rect = pygame.Rect(cx - size / 2, cy - size / 2, size, size)
            else:
                item.rect = pygame.Rect(cx - size_w / 2, cy - size_h / 2, size_w, size_h)

    # ── events ───────────────────────────────────────────────────────

    def _handle_events(self, events: list | None = None) -> None:
        for event in events if events is not None else pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._go_back = True
                self.running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                if self.vhdl_path is not None:
                    self._simulate = True
                    self.running = False

            elif event.type == pygame.WINDOWRESIZED:
                self.width, self.height = event.x, event.y - self._height_offset
                self._layout()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Simulator toggle (cycle to next available simulator)
                if (
                    self._sim_toggle_rect
                    and self._sim_toggle_rect.collidepoint(event.pos)
                    and len(self.available_simulators) > 1
                ):
                    idx = (
                        self.available_simulators.index(self.simulator)
                        if self.simulator in self.available_simulators
                        else 0
                    )
                    self.simulator = self.available_simulators[
                        (idx + 1) % len(self.available_simulators)
                    ]
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

    # ── drawing ──────────────────────────────────────────────────────

    def _draw(self, *, flip: bool = True) -> None:
        self.screen.fill(BG_GREEN)

        s = _ui_scale(self.width, self.height)
        font_size = max(10, round(13 * s))
        font = get_font(font_size)
        title_font = get_font(font_size + 5, bold=True)

        chip_font = get_font(max(13, font_size + 3), bold=True)
        if self.fpga_chip.rect.width >= 20:
            t = title_font.render("FPGA", True, WHITE)
            self.screen.blit(t, (20, self.fpga_chip.rect.top - font_size - 10))
        self.fpga_chip.draw(self.screen, chip_font)

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
            if _parts:
                count_f = get_font(max(11, round(13 * s)))
                count_surf = count_f.render("  \u00b7  ".join(_parts), True, (180, 220, 180))
                _chip_r = self.fpga_chip.rect
                count_x = _chip_r.centerx - count_surf.get_width() // 2
                # Start below the chip rect plus a gap equal to one chip-font line
                # so the count never overlaps the clock-frequency text inside the chip.
                count_y = _chip_r.bottom + chip_font.get_linesize() + max(2, round(3 * s))
                self.screen.blit(count_surf, (count_x, count_y))

        if self.leds:
            t = title_font.render("LEDs", True, WHITE)
            self.screen.blit(t, (20, self.leds[0].rect.top - font_size - 10))
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

        # ── Footer buttons (preview mode only) ───────────────────────
        if not self._show_footer:
            if flip:
                pygame.display.flip()
            return

        btn_font = get_font(max(12, round(16 * s)), bold=True)
        btn_margin_x = max(15, round(20 * s))
        btn_margin_y = max(15, round(20 * s))
        mouse_pos = pygame.mouse.get_pos()
        gap = max(8, round(10 * s))

        # Compute shared button height from font metrics
        _sample = btn_font.render("X", True, WHITE)
        btn_h = _sample.get_height() + 14

        # Button row Y
        btn_y = self.height - btn_h - btn_margin_y

        # ── Left side: [Select Board]  [Load VHDL File] ───────────────────────

        # [Select Board] — leftmost; uses teal/slate to distinguish from blue actions
        sel_surf = btn_font.render("Select Board", True, WHITE)
        sel_w = sel_surf.get_width() + 30
        sel_x = btn_margin_x
        self._select_board_btn_rect = pygame.Rect(sel_x, btn_y, sel_w, btn_h)
        sb_hov = self._select_board_btn_rect.collidepoint(mouse_pos)
        sel_bg = (20, 100, 115) if sb_hov else (15, 75, 90)
        pygame.draw.rect(self.screen, sel_bg, self._select_board_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, WHITE, self._select_board_btn_rect, 2, border_radius=6)
        self.screen.blit(sel_surf, (sel_x + 15, btn_y + 7))

        # [Load VHDL File] — right of Select Board
        load_surf = btn_font.render("Load VHDL File", True, WHITE)
        load_w = load_surf.get_width() + 30
        load_x = sel_x + sel_w + gap
        self._load_vhdl_btn_rect = pygame.Rect(load_x, btn_y, load_w, btn_h)
        l_hov = self._load_vhdl_btn_rect.collidepoint(mouse_pos)
        load_bg = (30, 80, 140) if l_hov else (20, 60, 110)
        pygame.draw.rect(self.screen, load_bg, self._load_vhdl_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, WHITE, self._load_vhdl_btn_rect, 2, border_radius=6)
        self.screen.blit(load_surf, (load_x + 15, btn_y + 7))

        # ── Right side: [SIM: GHDL]  [Start Simulation] ───────────────────────

        can_simulate = self.vhdl_path is not None

        # [Start Simulation] — rightmost, greyed when no VHDL loaded
        start_w = btn_font.render("Start Simulation", True, WHITE).get_width() + 30
        start_x = self.width - start_w - btn_margin_x
        self._sim_btn_rect = pygame.Rect(start_x, btn_y, start_w, btn_h)
        s_hov = can_simulate and self._sim_btn_rect.collidepoint(mouse_pos)
        if can_simulate:
            sim_bg = (30, 120, 60) if s_hov else (20, 90, 40)
            sim_border, sim_fg = WHITE, WHITE
        else:
            sim_bg = (30, 55, 35)
            sim_border = (70, 100, 75)
            sim_fg = (100, 140, 105)
        pygame.draw.rect(self.screen, sim_bg, self._sim_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, sim_border, self._sim_btn_rect, 2, border_radius=6)
        self.screen.blit(
            btn_font.render("Start Simulation", True, sim_fg), (start_x + 15, btn_y + 7)
        )

        # [SIM: GHDL/NVC] toggle — left of Start Simulation
        toggle_label = f"SIM: {self.simulator.upper()}"
        toggle_w = btn_font.render(toggle_label, True, WHITE).get_width() + 24
        toggle_x = start_x - toggle_w - gap
        self._sim_toggle_rect = pygame.Rect(toggle_x, btn_y, toggle_w, btn_h)
        can_toggle = len(self.available_simulators) > 1
        t_hov = can_toggle and self._sim_toggle_rect.collidepoint(mouse_pos)
        if self.simulator == "nvc":
            toggle_bg = (100, 40, 130) if t_hov else (80, 30, 100)
        elif can_toggle:
            toggle_bg = (30, 80, 140) if t_hov else (20, 60, 110)
        else:
            toggle_bg = (50, 50, 60)
        pygame.draw.rect(self.screen, toggle_bg, self._sim_toggle_rect, border_radius=6)
        t_border = WHITE if can_toggle else (100, 100, 110)
        pygame.draw.rect(self.screen, t_border, self._sim_toggle_rect, 2, border_radius=6)
        t_fg = WHITE if can_toggle else (140, 140, 150)
        self.screen.blit(btn_font.render(toggle_label, True, t_fg), (toggle_x + 12, btn_y + 7))

        # ── VHDL status line (above button row) ───────────────────────────────
        status_f = get_font(max(10, round(13 * s)))
        status_y = btn_y - status_f.get_linesize() - max(4, round(5 * s))
        if self.vhdl_path is not None:
            status_txt = status_f.render(f"VHDL: {self.vhdl_path.name}", True, (140, 220, 140))
        else:
            status_txt = status_f.render(
                "No VHDL file loaded  \u2013  use [Load VHDL File] to select one",
                True,
                (210, 170, 70),
            )
        self.screen.blit(status_txt, (btn_margin_x, status_y))

        if flip:
            pygame.display.flip()
