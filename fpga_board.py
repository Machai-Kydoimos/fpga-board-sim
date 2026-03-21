"""
FPGA Board Simulator - Pygame-based graphical interface.

Provides interactive switches, buttons, and LEDs that auto-arrange
to fit the window.  When amaranth-boards definitions are available
(git submodule), a board selector lets you pick a real board whose
resources (names, pins, connectors) are reflected in the UI.
"""

import math
import pygame
import sys
from pathlib import Path

from board_loader import (
    discover_boards, get_default_boards_path, BoardDef, ComponentInfo,
)
from session_config import load_session, save_session

# ── Colours ──────────────────────────────────────────────────────────
BG_GREEN = (34, 139, 34)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED_ON = (255, 30, 30)
RED_OFF = (80, 0, 0)
GRAY = (180, 180, 180)
DARK_GRAY = (80, 80, 80)
YELLOW = (255, 230, 50)
BLUE_ON = (80, 140, 255)
BLUE_OFF = (40, 50, 80)
SEL_BG = (30, 30, 40)
SEL_ROW_A = (40, 40, 50)
SEL_ROW_B = (35, 35, 45)
SEL_HOVER = (50, 70, 50)

# ── UI scaling ────────────────────────────────────────────────────────
_BASE_W, _BASE_H = 1024, 700

def _ui_scale(w: int, h: int) -> float:
    """Linear scale factor relative to the 1024×700 reference (= 1.0).
    Uses the smaller axis ratio so no dimension overflows the window."""
    return min(w / _BASE_W, h / _BASE_H)


# ── Component classes ────────────────────────────────────────────────

class FPGAChip:
    """Visual representation of the FPGA IC package on the board."""

    _VENDOR_COLORS = {
        "Xilinx":     (20,  60, 140),
        "Intel":      (0,   90,  50),
        "Lattice":    (90,  20,  90),
        "QuickLogic": (130, 60,   0),
        "Gowin":      (70,  70,   0),
    }

    def __init__(self, vendor: str = "", device: str = "", package: str = ""):
        self.vendor  = vendor
        self.device  = device
        self.package = package
        self.rect = pygame.Rect(0, 0, 0, 0)

    def draw(self, surface, font):
        if self.rect.width < 20:
            return
        r = self.rect
        color = self._VENDOR_COLORS.get(self.vendor, (40, 40, 40))

        pygame.draw.rect(surface, color, r, border_radius=6)
        pygame.draw.rect(surface, (180, 180, 180), r, 2, border_radius=6)
        self._draw_pin_marks(surface, r)

        cx, cy = r.centerx, r.centery
        line_h = font.get_linesize()
        for text, colour, dy in [
            (self.vendor,          WHITE,           -line_h),
            (self.device.upper(),  (200, 200, 200),  0),
            (self.package.upper(), (150, 150, 150),  line_h),
        ]:
            if text:
                s = font.render(text, True, colour)
                surface.blit(s, s.get_rect(centerx=cx, centery=cy + dy))

    def _draw_pin_marks(self, surface, r):
        color = (120, 120, 120)
        length = 5
        h_count = max(4, min(20, r.width  // 14))
        v_count = max(4, min(14, r.height // 14))

        for i in range(h_count):
            x = r.left + (i + 1) * r.width // (h_count + 1)
            pygame.draw.line(surface, color, (x, r.top),    (x, r.top    - length))
            pygame.draw.line(surface, color, (x, r.bottom), (x, r.bottom + length))

        for i in range(v_count):
            y = r.top + (i + 1) * r.height // (v_count + 1)
            pygame.draw.line(surface, color, (r.left,  y), (r.left  - length, y))
            pygame.draw.line(surface, color, (r.right, y), (r.right + length, y))


class LED:
    """A read-only indicator controlled via FPGABoard.set_led()."""

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)

    @property
    def label(self):
        return self.info.display_name if self.info else f"LED{self.index}"

    def draw(self, surface, font):
        cx, cy = self.rect.center
        r = max(4, min(self.rect.width, self.rect.height) // 2 - 2)

        if self.state:
            glow = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (255, 40, 40, 50), (r * 2, r * 2), r * 2)
            surface.blit(glow, (cx - r * 2, cy - r * 2))
            pygame.draw.circle(surface, RED_ON, (cx, cy), r)
        else:
            pygame.draw.circle(surface, RED_OFF, (cx, cy), r)

        pygame.draw.circle(surface, WHITE, (cx, cy), r, 1)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=cx, top=self.rect.bottom + 1))


class Switch:
    """A toggle switch – clicks flip the state."""

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.state = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    @property
    def label(self):
        return self.info.display_name if self.info else f"SW{self.index}"

    def draw(self, surface, font):
        colour = BLUE_ON if self.state else BLUE_OFF
        pygame.draw.rect(surface, colour, self.rect, border_radius=4)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=4)

        knob_h = self.rect.height // 2
        knob_y = self.rect.y + 2 if self.state else self.rect.bottom - knob_h - 2
        knob = pygame.Rect(self.rect.x + 3, knob_y, self.rect.width - 6, knob_h)
        pygame.draw.rect(surface, WHITE if self.state else GRAY, knob, border_radius=3)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_click(self, pos):
        if self.rect.collidepoint(pos):
            self.state = not self.state
            if self.callback:
                self.callback(self.index, self.state, self.info)
            return True
        return False


class Button:
    """A momentary push-button – pressed while the mouse is held down."""

    def __init__(self, index, info=None):
        self.index = index
        self.info = info
        self.pressed = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.callback = None

    @property
    def label(self):
        return self.info.display_name if self.info else f"BTN{self.index}"

    def draw(self, surface, font):
        if self.pressed:
            inner = self.rect.inflate(-4, -4)
            pygame.draw.rect(surface, YELLOW, inner, border_radius=6)
        else:
            pygame.draw.rect(surface, GRAY, self.rect, border_radius=6)
        pygame.draw.rect(surface, WHITE, self.rect, 2, border_radius=6)

        lbl = font.render(self.label, True, WHITE)
        surface.blit(lbl, lbl.get_rect(centerx=self.rect.centerx, top=self.rect.bottom + 2))

    def handle_press(self, pos):
        if self.rect.collidepoint(pos):
            self.pressed = True
            if self.callback:
                self.callback(self.index, True, self.info)
            return True
        return False

    def handle_release(self):
        if self.pressed:
            self.pressed = False
            if self.callback:
                self.callback(self.index, False, self.info)


# ── Board selector ───────────────────────────────────────────────────

class BoardSelector:
    """Full-screen picker.  Returns the chosen BoardDef, or None on quit."""

    def __init__(self, boards, screen, preselect_class: str = ""):
        self.boards = boards
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.filter_text = ""

        if preselect_class:
            idx = next((i for i, b in enumerate(boards)
                        if b.class_name == preselect_class), -1)
            if idx >= 0:
                self.hovered = idx
                viewport_h = self.height - self._hdr
                self.scroll = max(
                    0, idx * self.row_h - viewport_h // 2 + self.row_h // 2
                )

    @property
    def row_h(self) -> int:
        return max(32, round(48 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        return max(56, round(80 * _ui_scale(self.width, self.height)))

    def _filtered(self):
        if not self.filter_text:
            return self.boards
        ft = self.filter_text.lower()
        return [b for b in self.boards
                if ft in b.name.lower() or ft in b.class_name.lower()]

    def run(self, clock):
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.WINDOWRESIZED:
                    self.width, self.height = ev.x, ev.y
                    self.scroll = 0
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        step = max(20, round(self.row_h * 3))
                        self.scroll = max(0, self.scroll - step)
                    elif ev.button == 5:
                        step = max(20, round(self.row_h * 3))
                        self.scroll += step
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
                    elif ev.key == pygame.K_BACKSPACE:
                        self.filter_text = self.filter_text[:-1]
                        self.scroll = 0
                    elif ev.unicode and ev.unicode.isprintable():
                        self.filter_text += ev.unicode
                        self.scroll = 0

            self._draw()
            clock.tick(30)

    def _hover(self, pos):
        hdr = self._hdr
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        f = self._filtered()
        self.hovered = idx if 0 <= idx < len(f) else -1

    def _click(self, pos):
        self._hover(pos)
        f = self._filtered()
        if 0 <= self.hovered < len(f):
            return f[self.hovered]
        return None

    def _draw(self):
        self.screen.fill(SEL_BG)
        s = _ui_scale(self.width, self.height)
        title_f  = pygame.font.SysFont("consolas", max(14, round(22 * s)), bold=True)
        item_f   = pygame.font.SysFont("consolas", max(11, round(15 * s)))
        detail_f = pygame.font.SysFont("consolas", max( 9, round(11 * s)))

        hdr = self._hdr
        filtered = self._filtered()

        for i, b in enumerate(filtered):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = SEL_HOVER if i == self.hovered else (
                SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            pygame.draw.rect(self.screen, bg,
                             (10, y, self.width - 20, self.row_h - 2))
            nm = item_f.render(b.name, True, (220, 220, 255))
            self.screen.blit(nm, (20, y + 4))
            sm = detail_f.render(b.summary, True, (150, 150, 150))
            self.screen.blit(sm, (20, y + 26))

        # Header overlay (hides items that scrolled behind header)
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render("FPGA Simulator \u2014 Select Board", True, WHITE)
        self.screen.blit(title, (20, 12))

        stxt = (f"Filter: {self.filter_text}_"
                if self.filter_text else "Type to filter boards...")
        srch = item_f.render(stxt, True, (180, 180, 180))
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (20, 48, self.width - 140, 24), border_radius=3)
        self.screen.blit(srch, (26, 50))
        cnt = detail_f.render(f"{len(filtered)} boards", True, (120, 120, 120))
        self.screen.blit(cnt, (self.width - 100, 52))

        pygame.display.flip()


# ── Main board ───────────────────────────────────────────────────────

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

        total_weight = sum(s[2] for s in sections)
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


# ── VHDL file picker ─────────────────────────────────────────────────

class VHDLFilePicker:
    """Simple file picker for .vhd/.vhdl files.  Returns path or None."""

    def __init__(self, screen, start_dir=None, preselect_name: str = ""):
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.current_dir = Path(start_dir or Path.cwd())
        self._scan()

        if preselect_name:
            for i, (name, _path, is_dir) in enumerate(self.entries):
                if not is_dir and name == preselect_name:
                    self.hovered = i
                    viewport_h = self.height - self._hdr
                    self.scroll = max(
                        0, i * self.row_h - viewport_h // 2 + self.row_h // 2
                    )
                    break

    @property
    def row_h(self) -> int:
        return max(24, round(36 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        return max(48, round(70 * _ui_scale(self.width, self.height)))

    def _scan(self):
        """Refresh the file list for current_dir."""
        self.entries = []
        if self.current_dir.parent != self.current_dir:
            self.entries.append(("..", self.current_dir.parent, True))
        try:
            for p in sorted(self.current_dir.iterdir()):
                if p.name.startswith("."):
                    continue
                if p.is_dir():
                    self.entries.append((p.name + "/", p, True))
            for p in sorted(self.current_dir.iterdir()):
                if p.suffix.lower() in (".vhd", ".vhdl"):
                    self.entries.append((p.name, p, False))
        except PermissionError:
            pass

    def run(self, clock):
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.WINDOWRESIZED:
                    self.width, self.height = ev.x, ev.y
                    self.scroll = 0
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click()
                        if result == "rescan":
                            self.scroll = 0
                            self.hovered = -1
                            continue
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        step = max(20, round(self.row_h * 3))
                        self.scroll = max(0, self.scroll - step)
                    elif ev.button == 5:
                        step = max(20, round(self.row_h * 3))
                        self.scroll += step
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
            self._draw()
            clock.tick(30)

    def _hover(self, pos):
        hdr = self._hdr
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        self.hovered = idx if 0 <= idx < len(self.entries) else -1

    def _click(self):
        if 0 <= self.hovered < len(self.entries):
            name, path, is_dir = self.entries[self.hovered]
            if is_dir:
                self.current_dir = path
                self._scan()
                return "rescan"
            return str(path)
        return None

    def _draw(self):
        self.screen.fill(SEL_BG)
        s       = _ui_scale(self.width, self.height)
        title_f = pygame.font.SysFont("consolas", max(13, round(20 * s)), bold=True)
        path_f  = pygame.font.SysFont("consolas", max( 9, round(12 * s)))
        item_f  = pygame.font.SysFont("consolas", max(10, round(14 * s)))

        hdr = self._hdr

        for i, (name, path, is_dir) in enumerate(self.entries):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = SEL_HOVER if i == self.hovered else (
                SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            pygame.draw.rect(self.screen, bg,
                             (10, y, self.width - 20, self.row_h - 2))
            colour = (180, 180, 255) if is_dir else (220, 255, 220)
            nm = item_f.render(name, True, colour)
            self.screen.blit(nm, (24, y + 8))

        # Header
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render("Select VHDL File", True, WHITE)
        self.screen.blit(title, (20, 10))
        pd = path_f.render(str(self.current_dir), True, (150, 150, 150))
        self.screen.blit(pd, (20, 40))

        pygame.display.flip()


# ── Error dialog ─────────────────────────────────────────────────────

class ErrorDialog:
    """
    Modal error dialog drawn over a dimmed snapshot of the current screen.

    Sized to ~1/3 of the main window area (2/3 wide, 1/2 tall).
    run() returns 'retry' (Try Another File) or 'back' (Back to Boards).
    """

    def __init__(self, screen, title: str, message: str):
        self.screen   = screen
        self.title    = title
        self.message  = message
        self._bg      = screen.copy()
        self._scroll  = 0
        self._retry_rect = None
        self._back_rect  = None

    def run(self, clock):
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return "back"
                elif ev.type == pygame.WINDOWRESIZED:
                    # Rebuild background at new size so the dim overlay fills correctly
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(SEL_BG)
                    self._scroll = 0
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return "back"
                    elif ev.key == pygame.K_RETURN:
                        return "retry"
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result:
                            return result
                    elif ev.button == 4:
                        self._scroll = max(0, self._scroll - 60)
                    elif ev.button == 5:
                        self._scroll += 60

            self._draw()
            clock.tick(30)

    def _click(self, pos):
        if self._retry_rect and self._retry_rect.collidepoint(pos):
            return "retry"
        if self._back_rect and self._back_rect.collidepoint(pos):
            return "back"
        return None

    def _draw(self):
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)

        # Dimmed background
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Scale everything to the window — panel is ~2/3 wide, content area ~1/3 tall
        pad     = max(20, round(28 * s))
        panel_w = round(sw * 2 / 3)
        btn_h   = max(38, round(50 * s))
        btn_gap = max(12, round(16 * s))
        btns_h  = btn_h + btn_gap * 2

        title_f = pygame.font.SysFont("consolas", max(20, round(26 * s)), bold=True)
        body_f  = pygame.font.SysFont("consolas", max(16, round(20 * s)))
        btn_f   = pygame.font.SysFont("consolas", max(16, round(20 * s)), bold=True)
        line_h  = body_f.get_linesize() + 2

        # Word-wrap message lines to fit panel width
        max_text_w = panel_w - pad * 2
        wrapped = []
        for raw_line in self.message.split("\n"):
            words = raw_line.split(" ") if raw_line else [""]
            current = ""
            for word in words:
                test = (current + " " + word).strip()
                if body_f.size(test)[0] <= max_text_w:
                    current = test
                else:
                    if current:
                        wrapped.append(current)
                    current = word
            wrapped.append(current)

        body_h     = len(wrapped) * line_h
        viewport_h = min(body_h, round(sh / 3))
        panel_h    = pad + title_f.get_linesize() + pad + viewport_h + btns_h + pad

        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        # Panel background
        panel_rect = pygame.Rect(px, py, panel_w, panel_h)
        pygame.draw.rect(self.screen, (30, 30, 40), panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, (200, 60, 60), panel_rect, 2, border_radius=10)

        # Title
        t = title_f.render(self.title, True, (255, 100, 100))
        self.screen.blit(t, (px + pad, py + pad))

        # Scrollable body text
        body_top   = py + pad + title_f.get_linesize() + pad
        max_scroll = max(0, body_h - viewport_h)
        self._scroll = min(self._scroll, max_scroll)

        clip = pygame.Rect(px + pad, body_top, max_text_w, viewport_h)
        self.screen.set_clip(clip)
        for i, line in enumerate(wrapped):
            ly = body_top + i * line_h - self._scroll
            if ly + line_h < body_top or ly > body_top + viewport_h:
                continue
            surf = body_f.render(line, True, (220, 220, 220))
            self.screen.blit(surf, (px + pad, ly))
        self.screen.set_clip(None)

        # Scroll indicator
        if body_h > viewport_h:
            sb_x    = px + panel_w - 8
            thumb_h = max(20, viewport_h * viewport_h // body_h)
            thumb_y = body_top + (self._scroll * (viewport_h - thumb_h) // max(1, max_scroll))
            pygame.draw.rect(self.screen, (80, 80, 100),
                             pygame.Rect(sb_x, body_top, 5, viewport_h), border_radius=2)
            pygame.draw.rect(self.screen, (160, 160, 200),
                             pygame.Rect(sb_x, thumb_y, 5, thumb_h), border_radius=2)

        # Buttons
        btn_y       = py + panel_h - btns_h + btn_gap
        retry_w     = btn_f.size("Try Another File")[0] + pad
        back_w      = btn_f.size("Back to Boards")[0]   + pad
        total_btn_w = retry_w + btn_gap + back_w
        btn_start_x = px + (panel_w - total_btn_w) // 2

        mouse = pygame.mouse.get_pos()

        self._retry_rect = pygame.Rect(btn_start_x, btn_y, retry_w, btn_h)
        retry_hov = self._retry_rect.collidepoint(mouse)
        pygame.draw.rect(self.screen, (40, 110, 40) if retry_hov else (25, 70, 25),
                         self._retry_rect, border_radius=6)
        pygame.draw.rect(self.screen, WHITE, self._retry_rect, 2, border_radius=6)
        rt = btn_f.render("Try Another File", True, WHITE)
        self.screen.blit(rt, rt.get_rect(center=self._retry_rect.center))

        self._back_rect = pygame.Rect(btn_start_x + retry_w + btn_gap, btn_y, back_w, btn_h)
        back_hov = self._back_rect.collidepoint(mouse)
        pygame.draw.rect(self.screen, (90, 40, 40) if back_hov else (55, 25, 25),
                         self._back_rect, border_radius=6)
        pygame.draw.rect(self.screen, (200, 100, 100), self._back_rect, 2, border_radius=6)
        bt = btn_f.render("Back to Boards", True, WHITE)
        self.screen.blit(bt, bt.get_rect(center=self._back_rect.center))

        # Keyboard shortcut hint below the panel
        hint_f = pygame.font.SysFont("consolas", max(12, round(14 * s)))
        hint = hint_f.render("Enter: Try Another File    Esc: Back to Boards",
                             True, (140, 140, 140))
        self.screen.blit(hint, hint.get_rect(centerx=px + panel_w // 2,
                                             top=py + panel_h + 8))

        pygame.display.flip()


# ── Entry point ──────────────────────────────────────────────────────

def main():
    pygame.init()
    # get_desktop_sizes() is reliable in pygame 2.x before any set_mode() call
    sizes = pygame.display.get_desktop_sizes()
    sw, sh = sizes[0] if sizes else (1920, 1080)
    width  = max(1024, min(round(sw * 0.80), 1600))
    height = max(700,  min(round(sh * 0.80), 1000))

    boards = discover_boards(get_default_boards_path())

    if not boards:
        print("No amaranth-boards found; using generic board.")
        print("Run  git submodule update --init  to load board definitions.")
        FPGABoard(width=width, height=height).run()
        pygame.quit()
        return

    screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
    pygame.display.set_caption("FPGA Simulator")
    clock = pygame.time.Clock()

    session = load_session()
    last_board_class = session.get("board_class", "")
    last_vhdl_path   = session.get("vhdl_path", "")

    while True:
        # ── Step 1: pick a board ─────────────────────────────────
        chosen = BoardSelector(boards, screen,
                               preselect_class=last_board_class).run(clock)
        if chosen is None:
            break

        # ── Step 2: preview board ────────────────────────────────
        # ESC → back to selector, Enter → pick VHDL, close → quit
        # Pass the existing screen — no set_mode(), preserves window state.
        preview = FPGABoard(board_def=chosen, screen=screen)
        result = preview.run()
        if result == "quit":
            break
        if result == "back":
            continue

        # result == "simulate" → proceed to VHDL file picker
        # ── Steps 3-4: pick + validate VHDL (inner loop for retry) ───
        from sim_bridge import (analyze_vhdl, check_vhdl_encoding,
                                check_vhdl_contract)
        hdl_dir = Path(__file__).parent / "hdl"
        vhdl_path = None
        _back_to_boards = False
        analyzed_work_dir = None

        # Derive file-picker start dir and pre-selection from session (first pick only)
        _last_p = Path(last_vhdl_path) if last_vhdl_path else None
        _fp_dir  = _last_p.parent if (_last_p and _last_p.exists()) else hdl_dir
        _fp_pre  = _last_p.name   if (_last_p and _last_p.exists()) else ""
        _first_pick = True

        while True:
            pygame.display.set_caption("FPGA Simulator – Select VHDL")
            if _first_pick:
                vhdl_path = VHDLFilePicker(
                    screen, start_dir=_fp_dir, preselect_name=_fp_pre).run(clock)
                _first_pick = False
            else:
                vhdl_path = VHDLFilePicker(screen, start_dir=hdl_dir).run(clock)
            if vhdl_path is None:
                # ESC in file picker → back to board selector
                _back_to_boards = True
                break

            # Stage 1 + 2: encoding and contract checks
            toplevel_name = Path(vhdl_path).stem
            intent = "retry"
            for check_fn in [check_vhdl_encoding, check_vhdl_contract]:
                ok, detail = check_fn(vhdl_path)
                if not ok:
                    intent = ErrorDialog(screen, "VHDL Error", detail).run(clock)
                    break
            else:
                # Stage 3: GHDL analysis + elaboration
                ok, detail = analyze_vhdl(vhdl_path, toplevel=toplevel_name)
                if ok:
                    analyzed_work_dir = detail  # reuse in launch_simulation
                else:
                    intent = ErrorDialog(screen, "GHDL Error", detail).run(clock)

            if ok:
                break  # valid file — proceed to simulation
            if intent == "back":
                _back_to_boards = True
                break
            # intent == "retry" → loop back to file picker

        if _back_to_boards:
            pygame.display.set_caption("FPGA Simulator")
            continue  # back to BoardSelector

        # ── Step 5: launch simulation ────────────────────────────
        save_session(chosen.class_name, vhdl_path)
        last_board_class = chosen.class_name  # update in-memory session for this run
        last_vhdl_path   = vhdl_path

        # Capture final window size before quitting pygame so the
        # simulation subprocess and the post-sim restart both use it.
        width, height = screen.get_size()
        pygame.quit()  # cocotb subprocess will start its own pygame

        from sim_bridge import launch_simulation

        board_json = chosen.to_json()
        toplevel = toplevel_name

        # Size generics to match board
        generics = {
            "NUM_SWITCHES": str(max(1, len(chosen.switches))),
            "NUM_BUTTONS": str(max(1, len(chosen.buttons))),
            "NUM_LEDS": str(max(1, len(chosen.leds))),
            "COUNTER_BITS": "10",  # short for fast visible blinking
        }

        try:
            launch_simulation(board_json, vhdl_path, toplevel, generics,
                              sim_width=width, sim_height=height,
                              work_dir=analyzed_work_dir)
        except Exception as e:
            print(f"Simulation error: {e}")

        # After simulation ends, re-init pygame and loop back at the same size.
        pygame.init()
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        clock = pygame.time.Clock()
        continue

    pygame.quit()


if __name__ == "__main__":
    main()
