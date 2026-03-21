"""
FPGABoard: the main interactive board display screen.

Renders the FPGA chip, LEDs, buttons, and switches in a resizable pygame
window.  run() returns 'back', 'simulate', or 'quit'.
"""

import math
import pygame

from ui.constants import BG_GREEN, WHITE, _ui_scale
from ui.components import FPGAChip, LED, Switch, Button


class FPGABoard:
    """
    Pygame window that renders an FPGA-style board.

    Parameters
    ----------
    board_def    : BoardDef or None
        If given, components are built from the board's resource list.
    num_switches, num_buttons, num_leds : int
        Fallback counts when no BoardDef is provided.
    width, height: int
        Initial window size (resizable).
    """

    def __init__(self, board_def=None, *,
                 screen=None,
                 num_switches=8, num_buttons=4, num_leds=16,
                 width=1024, height=700):
        self.board_def = board_def
        if screen is not None:
            self.screen = screen
            self.width, self.height = screen.get_size()
        else:
            self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
            self.width, self.height = width, height
        self.clock = pygame.time.Clock()
        self.running = False

        title = f"FPGA Simulator \u2013 {board_def.name}" if board_def else "FPGA Simulator"
        pygame.display.set_caption(title)

        if board_def:
            self.fpga_chip = FPGAChip(
                vendor=board_def.vendor,
                device=board_def.device,
                package=board_def.package,
                clock_hz=board_def.default_clock_hz,
            )
            self.leds = [LED(i, info=c) for i, c in enumerate(board_def.leds)]
            self.buttons = [Button(i, info=c) for i, c in enumerate(board_def.buttons)]
            self.switches = [Switch(i, info=c) for i, c in enumerate(board_def.switches)]
        else:
            self.fpga_chip = FPGAChip()
            self.leds = [LED(i) for i in range(num_leds)]
            self.buttons = [Button(i) for i in range(num_buttons)]
            self.switches = [Switch(i) for i in range(num_switches)]

        # Default callbacks – print name + connector info
        def _sw_cb(idx, state, info):
            label = info.display_name if info else f"Switch {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'ON' if state else 'OFF'}{conn}")

        def _btn_cb(idx, pressed, info):
            label = info.display_name if info else f"Button {idx}"
            conn = f"  [{info.connector_str}]" if info else ""
            print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

        for sw in self.switches:
            sw.callback = _sw_cb
        for btn in self.buttons:
            btn.callback = _btn_cb

        self._sim_btn_rect = None
        self._layout()

    # ── public API ───────────────────────────────────────────────────

    def set_led(self, index: int, state: bool):
        """Turn an LED on or off by index."""
        if 0 <= index < len(self.leds):
            self.leds[index].state = bool(state)

    def set_switch_callback(self, callback):
        """Set callback for *all* switches.  Signature: callback(index, state, info)."""
        for sw in self.switches:
            sw.callback = callback

    def set_button_callback(self, callback):
        """Set callback for *all* buttons.  Signature: callback(index, pressed, info)."""
        for btn in self.buttons:
            btn.callback = callback

    def get_switch_state(self, index: int) -> bool:
        """Read the current state of a switch."""
        if 0 <= index < len(self.switches):
            return self.switches[index].state
        return False

    def run(self):
        """Enter the main loop.  Returns 'back' (ESC), 'simulate' (Enter), or 'quit'."""
        self.running = True
        self._go_back = False
        self._simulate = False
        while self.running:
            self._handle_events()
            self._draw()
            self.clock.tick(60)
        if self._simulate:
            return "simulate"
        return "back" if self._go_back else "quit"

    # ── layout engine ────────────────────────────────────────────────

    def _layout(self):
        """Recompute component positions to fit the current window size."""
        w, h = self.width, self.height
        s              = _ui_scale(self.width, self.height)
        margin         = max(10, round(20 * s))
        title_h        = max(14, round(22 * s))
        label_h        = max(12, round(18 * s))
        section_pad    = max( 6, round(10 * s))
        bottom_reserve = max(50, round(70 * s))   # space for button + ESC hint

        sections = [("fpga", [self.fpga_chip], 2)]
        if self.leds:
            sections.append(("leds", self.leds, 3))
        if self.buttons:
            sections.append(("buttons", self.buttons, 1))
        if self.switches:
            sections.append(("switches", self.switches, 1))

        if not sections:
            return

        total_weight = sum(sec[2] for sec in sections)
        usable_h = h - 2 * margin - section_pad * (len(sections) - 1) - bottom_reserve

        y = margin
        for name, items, weight in sections:
            sec_h = usable_h * weight / total_weight
            content_h = sec_h - title_h - label_h
            self._place_items(items, margin, y + title_h, w - 2 * margin, content_h, name, scale=s)
            y += sec_h + section_pad

    def _place_items(self, items, x0, y0, avail_w, avail_h, kind, scale=1.0):
        n = len(items)
        if n == 0:
            return

        if kind == "fpga":
            size_w = min(avail_w * 0.50, round(260 * scale))
            size_h = min(avail_h * 0.70, round(160 * scale))
            cx = x0 + avail_w / 2
            cy = y0 + avail_h / 2
            items[0].rect = pygame.Rect(
                cx - size_w / 2, cy - size_h / 2, size_w, size_h)
            return

        if kind == "leds":
            if n <= 16:
                cols = n
            else:
                aspect = avail_w / max(1, avail_h)
                cols = max(1, round(math.sqrt(n * aspect)))
                cols = min(cols, n)
        else:
            cols = min(n, max(1, int(avail_w / 65)))
        rows = math.ceil(n / cols)

        cell_w = avail_w / cols
        cell_h = avail_h / max(1, rows)

        if kind == "leds":
            size = min(cell_w, cell_h) * 0.75
            size = max(10, min(size, round(44 * scale)))
        elif kind == "buttons":
            size_w = min(cell_w * 0.70, round(90 * scale))
            size_h = min(cell_h * 0.60, round(50 * scale))
        else:
            size_w = min(cell_w * 0.50, round(44 * scale))
            size_h = min(cell_h * 0.65, round(60 * scale))

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

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._go_back = True
                self.running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                self._simulate = True
                self.running = False

            elif event.type == pygame.WINDOWRESIZED:
                self.width, self.height = event.x, event.y
                self._layout()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Check "Start Simulation" button first
                if self._sim_btn_rect and self._sim_btn_rect.collidepoint(event.pos):
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

    def _draw(self):
        self.screen.fill(BG_GREEN)

        s = _ui_scale(self.width, self.height)
        font_size = max(9, round(12 * s))
        font = pygame.font.SysFont("consolas", font_size)
        title_font = pygame.font.SysFont("consolas", font_size + 4, bold=True)

        chip_font = pygame.font.SysFont("consolas", max(11, font_size + 1), bold=True)
        if self.fpga_chip.rect.width >= 20:
            t = title_font.render("FPGA", True, WHITE)
            self.screen.blit(t, (20, self.fpga_chip.rect.top - font_size - 10))
        self.fpga_chip.draw(self.screen, chip_font)

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

        # "Start Simulation" button
        btn_font = pygame.font.SysFont("consolas", max(12, round(16 * s)), bold=True)
        btn_text = btn_font.render("Start Simulation", True, WHITE)
        btn_w = btn_text.get_width() + 30
        btn_h = btn_text.get_height() + 14
        btn_margin_x = max(15, round(20 * s))
        btn_margin_y = max(15, round(20 * s))
        btn_x = self.width  - btn_w - btn_margin_x
        btn_y = self.height - btn_h - btn_margin_y
        self._sim_btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

        mouse_pos = pygame.mouse.get_pos()
        hovered = self._sim_btn_rect.collidepoint(mouse_pos)
        btn_bg = (30, 120, 60) if hovered else (20, 90, 40)
        pygame.draw.rect(self.screen, btn_bg, self._sim_btn_rect, border_radius=6)
        pygame.draw.rect(self.screen, WHITE, self._sim_btn_rect, 2, border_radius=6)
        self.screen.blit(btn_text, (btn_x + 15, btn_y + 7))

        # ESC hint — positioned using actual font height so it's never clipped
        hint_f = pygame.font.SysFont("consolas", max(9, round(12 * s)))
        hint = hint_f.render("ESC: back to board list", True, (160, 160, 160))
        hint_margin = max(8, round(10 * s))
        self.screen.blit(hint, (15, self.height - hint_f.get_height() - hint_margin))

        pygame.display.flip()
